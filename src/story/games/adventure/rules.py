"""Game rules: the AI only proposes changes; whether and how much to apply is decided here. Wounds and death, in-game time and healing, items, story pacing, the memory budget.

All pure functions that only read and write the game state (models.py); they never call the AI or build prompts.
"""

from typing import get_args

from story.core import prompts
from story.games.adventure.models import VOCAB, Character, Condition, GameState, Severity, Turn, code

TARGET_TURNS = 30  # The planned story length (turns); past it, the AI is only reminded to wrap up, never forced to end
ACT_TURNS = TARGET_TURNS // 4  # Expected turns per act; staying too long reminds the AI to move on
MIN_ACT_TURNS = 5  # Minimum turns per act; before that, the AI saying the milestone is reached doesn't advance, so the story doesn't rush through
MIN_ENDING_TURN = 20  # The earliest turn an ending the AI declares is accepted (it must also be in the last act); death from wounds isn't limited
MIN_TIME_LIMIT, MAX_TIME_LIMIT = 8, 60  # Reaction time range in timed mode (seconds)
MAX_CONDITION_LEN = 12  # Most characters (words in English) for one condition, so the LLM doesn't write a whole sentence
HISTORY_BUDGET = 20_000  # Most characters (words in English) the story log keeps verbatim; past it, the oldest part is compacted into the summary, down to half at once
KEEP_EVENTS, KEEP_FLAGS = 6, 12  # How many recent key events and established facts to keep verbatim; older ones are folded into the summary when compacting

# Body: the LLM only decides each condition's severity; the program computes the total and life or death
SEVERITY_POINTS = {"light": 1, "moderate": 2, "severe": 4}
DEATH_SCORE = 8  # A wound total reaching this is death
DYING_SCORE = 6  # A total reaching this is dying
HEAVY_SCORE = 4  # No severe wound, but several moderate ones adding up to this also count as badly hurt
SEVERITY_ORDER = list(get_args(Severity))  # From light to severe
WARNING_LEVELS = ("serious", "dying")  # Overall conditions to warn the player about: another wound could kill

# In-game time: the AI only picks a category; the program converts it to minutes
HOUR, DAY = 60, 24 * 60
TIME_SPANS = {"instant": 1, "moment": 10, "while": HOUR, "hours": 4 * HOUR, "night": 8 * HOUR, "days": 3 * DAY}
TIME_OF_DAY_START = {"dawn": 6, "morning": 9, "noon": 12, "afternoon": 15, "dusk": 18, "evening": 20, "late_night": 23}  # Opening hour
TIME_OF_DAY_RANGES = [(5, "dawn"), (7, "morning"), (11, "noon"), (13, "afternoon"), (17, "dusk"), (19, "evening"), (23, "late_night")]

# Natural recovery: how long at one severity before it gets one level better. Severe body wounds don't heal on their own and need treatment in the story; mind conditions all ease with time
HEAL_TIME = {
    "body": {"light": 6 * HOUR, "moderate": 2 * DAY},
    "mind": {"light": 2 * HOUR, "moderate": 12 * HOUR, "severe": 2 * DAY},
}


# ---------- Wounds and death ----------


def body_conditions(who: Character) -> list[Condition]:
    return [c for c in who.conditions if c.kind == "body"]


def mind_conditions(who: Character) -> list[Condition]:
    return [c for c in who.conditions if c.kind == "mind"]


def body_score(who: Character) -> int:
    """The wound total only counts body conditions; mind conditions affect the story but can't kill."""
    return sum(SEVERITY_POINTS[c.severity] for c in body_conditions(who))


def condition_list(who: Character) -> list[tuple[str, str]]:
    """Conditions for the shells to show: (name, severity code), body first, then mind."""
    return [(c.name, c.severity) for c in body_conditions(who) + mind_conditions(who)]


def body_level(who: Character) -> str:
    """The overall condition (a models.Level code) follows the worst item: only a severe wound (or several moderate ones adding up) is badly hurt; only light conditions is minor."""
    score = body_score(who)
    worst = {c.severity for c in body_conditions(who)}
    if score >= DEATH_SCORE:
        return "dead"
    if score >= DYING_SCORE:
        return "dying"
    if "severe" in worst or score >= HEAVY_SCORE:
        return "serious"
    if "moderate" in worst:
        return "injured"
    return "minor" if worst else "healthy"


def warning_level(who: Character) -> str:
    """The overall condition to warn the player about (serious, dying); empty when not in danger."""
    level = body_level(who)
    return level if level in WARNING_LEVELS else ""


# ---------- Time ----------


def time_of_day(minutes: int) -> str:
    """The time-of-day code for the in-game clock, e.g. dusk."""
    hour = minutes % DAY // HOUR
    return next((name for start, name in reversed(TIME_OF_DAY_RANGES) if hour >= start), "late_night")


def advance_clock(state: GameState, time_passed: str, start_time_of_day: str) -> tuple[int, bool]:
    """Advance the turn and the in-game clock (both arguments are words the AI returned). Returns (minutes passed, whether this is the opening)."""
    state.turn += 1
    is_opening_turn = state.turn == 1
    if state.minutes is None:  # The opening: the AI picks the time from the story, and no time passes this turn
        state.minutes, elapsed = TIME_OF_DAY_START[code("time_of_day", start_time_of_day)] * HOUR, 0
    else:
        elapsed = TIME_SPANS[code("time_span", time_passed)]
        state.minutes += elapsed
    return elapsed, is_opening_turn


# ---------- Applying the changes the AI proposes ----------


def apply_condition_changes(who: Character, changed: list, removed_names: list[str], elapsed: int) -> None:
    # Let existing conditions recover with time first, then apply what the AI reported
    remaining = []
    for c in who.conditions:
        c.minutes += elapsed
        heal = HEAL_TIME[c.kind]
        while c.severity in heal and c.minutes >= heal[c.severity]:
            # Leftover time carries into the next level, e.g. "several days" may heal a moderate wound all the way
            c.minutes -= heal[c.severity]
            if c.severity == "light":
                break
            c.severity = SEVERITY_ORDER[SEVERITY_ORDER.index(c.severity) - 1]
        else:
            remaining.append(c)  # The loop didn't break on a light condition healing, so the condition is still there
    who.conditions = remaining

    # Removal: mind conditions and light body conditions can be removed outright; moderate and severe body ones only drop a level, so the AI can't erase a severe wound in one line
    removed = {name.strip() for name in removed_names}
    remaining = []
    for c in who.conditions:
        if c.name in removed and c.kind == "body" and c.severity != "light":
            c.severity, c.minutes = SEVERITY_ORDER[SEVERITY_ORDER.index(c.severity) - 1], 0
        elif c.name in removed:
            continue
        remaining.append(c)
    who.conditions = remaining  # Names that don't exist are simply ignored

    for change in changed:  # The category and severity the AI reports are this language's words; convert to codes
        name = prompts.clip(change.name.strip(), MAX_CONDITION_LEN)
        if not name or name in VOCAB.table["level"].values():  # Words like "fine" or "badly hurt" judge the overall condition; they aren't wounds
            continue
        kind, severity = code("kind", change.kind), code("severity", change.severity)
        existing = next((c for c in who.conditions if c.name == name), None)
        if existing:
            existing.kind = kind  # The AI may correct the category
            old_level = SEVERITY_ORDER.index(existing.severity)
            new_level = SEVERITY_ORDER.index(severity)
            if new_level == old_level:
                continue
            # Getting worse has no limit; getting better is at most one level a turn, so the AI can't turn a severe wound into healed at once
            existing.severity = SEVERITY_ORDER[max(new_level, old_level - 1)]
            existing.minutes = 0
        else:
            who.conditions.append(Condition(name=name, kind=kind, severity=severity))


def apply_items(who: Character, gained: list[str], lost: list[str]) -> None:
    for item in lost:
        if item in who.inventory:  # Can't lose what you don't have
            who.inventory.remove(item)
    who.inventory.extend(gained)


def apply_story_progress(state: GameState, flags: list[str], key_event: str, milestone_reached: bool, is_opening_turn: bool) -> None:
    for flag in flags:
        if flag not in state.flags:
            state.flags.append(flag)
    if key_event.strip():
        state.key_events.append(key_event.strip())
    if state.arc is not None and not is_opening_turn:
        state.act_turns += 1
        # The program controls the pacing: each act lasts at least MIN_ACT_TURNS turns, and the AI saying it's reached early doesn't advance
        if milestone_reached and state.act_turns >= MIN_ACT_TURNS and state.act < len(state.arc.acts) - 1:
            state.act, state.act_turns = state.act + 1, 0


def ending_allowed(state: GameState, turn: int) -> bool:
    """Whether the story can end on turn `turn`: in the last act and at least MIN_ENDING_TURN; always allowed past the planned length.
    Only covers endings the AI declares; death from wounds is decided separately by the program and isn't limited."""
    if turn >= TARGET_TURNS:
        return True
    final = state.arc is None or state.act == len(state.arc.acts) - 1
    return final and turn >= MIN_ENDING_TURN


def clamp_time_limit(state: GameState, given: int) -> int:
    """The program decides whether there's a time limit: outside timed mode, the LLM's seconds are ignored; in timed mode, they're clamped to a sensible range."""
    limit = given if state.timed_mode and not state.game_over else 0
    return 0 if limit <= 0 else max(MIN_TIME_LIMIT, min(MAX_TIME_LIMIT, limit))


# ---------- The memory budget ----------


def history_size(turns: list[Turn]) -> int:
    return sum(prompts.text_length(t.narration) + prompts.text_length(t.action) for t in turns)


def needs_compaction(state: GameState) -> bool:
    return history_size(state.recent) > HISTORY_BUDGET or len(state.key_events) > KEEP_EVENTS * 2 or len(state.flags) > KEEP_FLAGS * 2


def to_compact(state: GameState) -> tuple[list[Turn], list[str], list[str]]:
    """What this compaction folds into the summary: the oldest turns, older key events, older facts."""
    return oldest_turns_to_compact(state.recent), state.key_events[:-KEEP_EVENTS], state.flags[:-KEEP_FLAGS]


def oldest_turns_to_compact(turns: list[Turn]) -> list[Turn]:
    """The oldest turns to compact when the story log is over budget: down to no more than half the budget. Nothing if it isn't over."""
    if history_size(turns) <= HISTORY_BUDGET:
        return []
    size, cut = history_size(turns), 0
    while cut < len(turns) - 1 and size > HISTORY_BUDGET // 2:
        size -= prompts.text_length(turns[cut].narration) + prompts.text_length(turns[cut].action)
        cut += 1
    return turns[:cut]
