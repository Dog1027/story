"""Building prompts: combine the game state with the text in prompts/<lang>/ into the prompt for each kind of AI call. Never calls the AI; just prompts uses it to preview.

Order: what rarely changes first and what changes later, so Gemini's automatic cache (which only matches an identical beginning) hits as much as possible:
premise, mode, genre guide → summary (rarely changes) → story log (append only) → key events, story progress, game state (change with the story) → this turn's instructions.
"""

import json
import random

from story.core import prompts
from story.games.adventure.genres import Genre
from story.games.adventure.models import AdventureState, Character, Condition, StoryArc, Turn, word
from story.games.adventure.rules import (
    ACT_TURNS,
    DAY,
    DEATH_SCORE,
    HOUR,
    MAX_TIME_LIMIT,
    MIN_ACT_TURNS,
    MIN_ENDING_TURN,
    MIN_TIME_LIMIT,
    TARGET_TURNS,
    body_conditions,
    body_level,
    body_score,
    ending_allowed,
    mind_conditions,
    parts_to_compact,
    time_of_day,
)
from story.games.adventure.text import TEXT

# Text for the AI, each in the file of the same name in prompts/<lang>/
SYSTEM_PROMPT = TEXT.load("system")
CONTEXT = TEXT.sections("context")
TURN = TEXT.sections("turn")
PROGRESS = TEXT.sections("progress")
PLAN = TEXT.sections("plan")
PREMISE = TEXT.sections("premise")
MEMORY = TEXT.sections("memory")
STATUS_KEYS = prompts.table(CONTEXT["status_keys"])  # Field names in the game state JSON: {code: name shown to the AI}
STATUS_EMPTY = prompts.table(CONTEXT["status_empty"])  # Text shown when something in the game state is empty
TIMEOUT_ACTION = TURN["timeout_action"]  # Written to the story log in place of a player's action when timed mode runs out
AWAY_ACTION = TURN["away_action"]  # Written to the story log in place of a player who is away (the room sends it when someone disconnects)
TWIST_IDEAS = 3  # How many twist ideas to draw at random from a genre pack's twists.md when planning the outline
# "Suggest one" has the program pick a genre and setting at random, so the AI doesn't keep coming up with similar stories
PREMISE_GENRES = prompts.items(PREMISE["genres"])
PREMISE_SETTINGS = prompts.items(PREMISE["settings"])


# ---------- Small pieces of the game state ----------


def clock_text(minutes: int) -> str:
    """E.g. "day 2, evening (18:30)". Only in prompts for the AI, never shown to players."""
    day, hour, minute = minutes // DAY + 1, minutes % DAY // HOUR, minutes % HOUR
    return CONTEXT["clock"].format(day=day, period=word("time_of_day", time_of_day(minutes)), hour=hour, minute=minute)


def time_text(state: AdventureState) -> str:
    return STATUS_EMPTY["time_unknown"] if state.minutes is None else clock_text(state.minutes)


def history_entry(turn: Turn) -> str:
    """One turn in the story log: the narration then, and what the players did after reading it."""
    return CONTEXT["history_entry"].format(narration=turn.narration, label=CONTEXT["turn_label"], action=turn.action)


def format_actions(actions: dict[str, str]) -> str:
    """Each character's action this turn, one per line. Also the action recorded in the story log."""
    return "\n".join(TURN["action_entry"].format(name=name, action=action) for name, action in actions.items())


def names_text(names: list[str]) -> str:
    return TURN["names_sep"].join(names)


def character_facts(c: Character) -> dict:
    """One character in the game state: body, mind, overall (how far from death), bag."""
    key, empty = STATUS_KEYS, STATUS_EMPTY
    if not c.alive:
        return {key["name"]: c.name, key["state"]: empty["dead"]}

    def listed(conditions: list[Condition], empty_key: str) -> list[str]:
        return [CONTEXT["condition"].format(name=x.name, severity=word("severity", x.severity)) for x in conditions] or [empty[empty_key]]

    overall = CONTEXT["overall"].format(level=word("level", body_level(c)), score=body_score(c), death=DEATH_SCORE)
    return {
        key["name"]: c.name,
        key["body"]: listed(body_conditions(c), "body"),
        key["mind"]: listed(mind_conditions(c), "mind"),
        key["overall"]: overall,
        key["inventory"]: c.inventory or [empty["inventory"]],
    }


# ---------- The prompt for each kind of AI call ----------


class PromptBuilder:
    def __init__(self, genres: dict[str, Genre]):
        self.genres = genres  # Genre packs (genres.py)

    def turn(self, state: AdventureState, actions: dict[str, str] | None) -> str:
        """This turn: the story content plus this turn's instructions (the opening when actions is None). Every call is stateless; all memory comes from here."""
        return "\n\n".join(self.context(state, actions is not None) + self.instructions(state, actions))

    def death(self, state: AdventureState, names: list[str]) -> str:
        """The program found a character died of their wounds: have the AI write a short scene of them falling."""
        return "\n\n".join(self.context(state) + [TURN["death"].format(narration=state.current_narration, who=names_text(names))])

    def epilogue(self, state: AdventureState) -> str:
        return "\n\n".join(self.context(state) + [TURN["epilogue"].format(narration=state.current_narration)])

    def pick_genre(self, state: AdventureState) -> str:
        catalog = "\n".join(PLAN["catalog_entry"].format(name=g.name, description=g.description) for g in self.genres.values())
        return PLAN["pick_genre"].format(premise=state.premise, catalog=catalog)

    def arc(self, state: AdventureState) -> str:
        if state.turn == 0:
            situation = PLAN["arc_new"]
        else:  # Planning failed before the opening, so make one now: continue from the story so far
            situation = PLAN["arc_resume"].format(turn=state.turn, summary=state.summary or PLAN["summary_none"], events="\n".join(state.key_events))
        cast = TURN["cast"].format(names=names_text(state.names)) + "\n"
        prompt = PLAN["arc"].format(target_turns=TARGET_TURNS, premise=state.premise, cast=cast, situation=situation)
        if genre := self.genres.get(state.genre):  # The outline must fit the genre
            prompt += "\n\n" + PLAN["genre"].format(name=genre.name, guide=genre.guide)
            if genre.names:
                prompt += "\n\n" + PLAN["names"].format(names=genre.names)
            if genre.twists:  # Draw a few at random each game, so the same genre played many times doesn't always use the same trick
                ideas = "\n".join(f"- {t}" for t in random.sample(genre.twists, min(TWIST_IDEAS, len(genre.twists))))
                prompt += "\n\n" + PLAN["twist_ideas"].format(ideas=ideas)
        return prompt

    def premise(self, avoid: str = "", genre: str = "") -> str:
        """"Suggest one": the program picks a genre at random (or the one the players chose); a genre pack adds its description and a few opening ideas."""
        if genre not in self.genres:
            genre = random.choice([*self.genres, *(g for g in PREMISE_GENRES if g not in self.genres)])
        parts = [PREMISE["intro"].format(genre=genre, setting=random.choice(PREMISE_SETTINGS))]
        if pack := self.genres.get(genre):
            parts.append(PREMISE["pack"].format(description=pack.description))
            if pack.premises:
                ideas = "\n".join(f"- {p}" for p in random.sample(pack.premises, min(3, len(pack.premises))))
                parts.append(PREMISE["pack_ideas"].format(ideas=ideas))
        parts.append(PREMISE["rules"])
        if avoid:
            parts.append(PREMISE["avoid"].format(avoid=avoid))
        return "\n".join(parts)

    def compaction(self, state: AdventureState) -> str:
        """When the story log gets too long: fold the oldest turns, older key events and facts into the long-term summary."""
        turns, old_events, old_flags = parts_to_compact(state)
        old = old_events + old_flags
        parts = [MEMORY["summary"].format(summary=state.summary or MEMORY["summary_none"])]
        if turns:
            parts.append(MEMORY["turns"].format(entries="\n\n".join(history_entry(t) for t in turns)))
        if old:
            parts.append(MEMORY["old_facts"].format(items="\n".join(f"- {x}" for x in old)))
        parts.append(MEMORY["compact"])
        return "\n\n".join(parts)

    # ---------- Building blocks ----------

    def context(self, state: AdventureState, acting: bool = False) -> list[str]:
        """The story content (everything but the instructions). The epilogue and the falling scene use it too, each with its own instructions.
        acting: players acted this turn; the last turn's actions are listed separately in the instructions, so the story log doesn't repeat them."""
        mode = TURN["mode_timed"].format(min=MIN_TIME_LIMIT, max=MAX_TIME_LIMIT) if state.timed_mode else TURN["mode_normal"]
        sections = [CONTEXT["premise"].format(premise=state.premise), CONTEXT["mode"].format(mode=mode)]
        if state.solo:  # The system prompt says so too, but the AI often switches to third person when it sees a name, so remind it here
            sections.append(TURN["second_person"].format(name=state.characters[0].name))
        genre = self.genres.get(state.genre)
        if genre:
            sections.append(CONTEXT["genre_guide"].format(name=genre.name, guide=genre.guide))
        if state.summary:
            sections.append(CONTEXT["summary"].format(summary=state.summary))
        if turns := state.recent:
            entries = [history_entry(t) for t in turns]
            if acting:
                entries[-1] = CONTEXT["history_last"].format(narration=turns[-1].narration)
            sections.append(CONTEXT["history"].format(entries="\n\n".join(entries)))
        if state.key_events:
            sections.append(CONTEXT["key_events"].format(events="\n".join(f"- {e}" for e in state.key_events)))
        if progress := self.progress(state):
            sections.append(progress)
        if genre and genre.names and not acting and state.turn == 0:  # The opening introduces people and places: add the naming material
            sections.append(PLAN["names"].format(names=genre.names))
        sections.append(self.status(state))
        return sections

    def status(self, state: AdventureState) -> str:
        key = STATUS_KEYS
        status = {
            key["turn"]: state.turn,
            key["time"]: time_text(state),
            key["flags"]: state.flags or [STATUS_EMPTY["flags"]],
            key["characters"]: [character_facts(c) for c in state.characters],
        }
        return CONTEXT["status"].format(json=json.dumps(status, ensure_ascii=False, separators=(",", ":")))

    def instructions(self, state: AdventureState, actions: dict[str, str] | None) -> list[str]:
        sections = []
        alive = [c.name for c in state.characters if c.alive]
        if len(alive) > 1:  # The program rotates the focus so the AI doesn't keep making the same person the lead
            sections.append(TURN["focus"].format(name=alive[state.turn % len(alive)]))
        sections.append(TURN["opening"] if actions is None else TURN["action"].format(actions=format_actions(actions)))
        return sections

    def progress(self, state: AdventureState) -> str:
        """The hidden story outline and pacing reminders. For the AI only."""
        arc = state.arc
        if arc is None:
            return ""
        lines = [PROGRESS["goal"].format(goal=arc.goal)]
        for i, act in enumerate(arc.acts):
            mark = PROGRESS["act_current"] if i == state.act else (PROGRESS["act_done"] if i < state.act else "")
            lines.append(PROGRESS["act"].format(number=i + 1, name=act.name, milestone=act.milestone, mark=mark))
        lines.append(PROGRESS["endings"].format(endings=PROGRESS["endings_sep"].join(arc.endings)))
        if arc.twist:
            lines += self.twist_lines(arc, state.act)

        final = state.act == len(arc.acts) - 1
        if not final and state.act_turns + 1 < MIN_ACT_TURNS:
            left = MIN_ACT_TURNS - state.act_turns - 1
            lines.append(PROGRESS["act_just_started"].format(left=left))
        if not ending_allowed(state, state.turn + 1):
            lines.append(PROGRESS["ending_locked"].format(min_ending_turn=MIN_ENDING_TURN))
        if state.turn >= TARGET_TURNS:
            lines.append(PROGRESS["overdue"].format(target_turns=TARGET_TURNS))
        elif final:
            lines.append(PROGRESS["final_act"])
        elif state.act_turns >= ACT_TURNS:
            lines.append(PROGRESS["act_too_long"])
        return PROGRESS["header"].format(lines="\n".join(lines))

    @staticmethod
    def twist_lines(arc: StoryArc, act: int) -> list[str]:
        """The hidden truth: acts one and two only plant clues, act three reveals it, and after that it's known."""
        clues = "\n".join(f"- {c}" for c in arc.clues)
        if act < 2:
            lines = [PROGRESS["twist_hidden"].format(twist=arc.twist)]
            if clues:
                lines.append(PROGRESS["twist_clues"].format(clues=clues))
            return lines
        if act == 2:
            reveal = PROGRESS["twist_reveal"].format(twist=arc.twist)
            return [reveal + ("\n" + PROGRESS["twist_reveal_clues"].format(clues=clues) if clues else "")]
        return [PROGRESS["twist_known"].format(twist=arc.twist)]
