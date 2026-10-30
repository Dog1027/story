"""Advancing a game: plan the outline, have the AI write each turn, check and apply the changes it proposes, write the epilogue, compact memory.

Rules are in rules.py, prompts in prompting.py (with text in prompts/<lang>/), and the shared AI-calling code in story/core/ai.py.
"""

from pathlib import Path

from google.genai import types

from story.core.ai import MODEL, AICaller, AIFailed, GeminiClient, StopStream, partial_bool, partial_string
from story.games.adventure.genres import Genre, load_genres
from story.games.adventure.models import Epilogue, GameState, GenrePick, StoryArc, StoryBeat, Turn
from story.games.adventure.prompting import MEMORY, SYSTEM_PROMPT, TURN, PromptBuilder, clock_text, format_actions
from story.games.adventure.rules import (
    ACT_TURNS,
    DEATH_SCORE,
    advance_clock,
    apply_condition_changes,
    apply_items,
    apply_story_progress,
    body_score,
    clamp_time_limit,
    ending_allowed,
    needs_compaction,
    parts_to_compact,
)
from story.games.adventure.text import UI


class EndingTooEarly(StopStream):
    """Found while streaming that the AI declared the ending too early: stop before any narration is shown and have it rewrite."""

    reason = "early_ending"


class Engine(AICaller):
    def __init__(
        self,
        api_key: str | None = None,
        client: GeminiClient | None = None,
        log_path: Path | None = None,
        genres: dict[str, Genre] | None = None,
    ):
        super().__init__(api_key, client, log_path)
        self.genres = load_genres()[0] if genres is None else genres  # Genre packs (see genres.py)
        self.build = PromptBuilder(self.genres)

    # ---------- Public interface ----------

    def start(self, state: GameState) -> None:
        """Plan the hidden story outline first, then write the opening (with the "auto" genre, pick a genre before everything else).
        This calls the AI several times and takes longer than a normal turn, so progress tells the shells how far along it is."""
        try:
            if state.genre_pending and self.genres:
                self.progress = UI["stage_genre"]
                self.pick_genre(state)
            self.progress = UI["stage_arc"]
            self.plan_arc(state)
            self.progress = UI["stage_opening"]
            self._advance(state, None)
        finally:
            self.progress, self.draft = "", ""

    def pick_genre(self, state: GameState) -> None:
        """The players chose "auto": give the AI the genre catalog and have it pick one for the premise. Pick first so the outline can use the genre's guide and twist ideas."""
        response = self.generate(
            "genre",
            model=MODEL,
            contents=self.build.pick_genre(state),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GenrePick,
                thinking_config=types.ThinkingConfig(thinking_level="low"),
            ),
        )
        picked = response.parsed.genre.strip() if isinstance(response.parsed, GenrePick) else ""
        state.genre, state.genre_pending = (picked if picked in self.genres else ""), False  # Not in the catalog (or blank): no genre

    def plan_arc(self, state: GameState) -> None:
        """Have the AI plan the story outline. If its answer can't be used, the game goes on without one and a later turn makes one from the story so far,
        picking which act to continue from by the turn number. Raises AIFailed if the AI can't be reached."""
        response = self.generate(
            "arc",
            model=MODEL,
            contents=self.build.arc(state),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=StoryArc,
                thinking_config=types.ThinkingConfig(thinking_level="low"),
            ),
        )
        if not isinstance(response.parsed, StoryArc) or len(response.parsed.acts) < 4:
            return  # Planning failed: go without an outline for now and retry next turn
        state.arc = response.parsed
        state.arc.acts = state.arc.acts[:4]
        state.act, state.act_turns = min(3, state.turn // ACT_TURNS), 0  # A late outline: estimate the current act from the turn number

    def play_turn(self, state: GameState, actions: dict[str, str]) -> None:
        """Every character has acted ({name: action}): advance a turn."""
        if state.arc is None:
            self.plan_arc(state)
        state.recent.append(Turn(narration=state.current_narration, action=format_actions(actions)))  # Append only
        try:
            self._advance(state, actions)
        finally:
            self.draft = ""

    def suggest_premise(self, avoid: str = "", genre: str = "") -> str:
        """Have the AI come up with a new story opening. The program picks the genre at random (or the one the players chose); the AI fills it in."""
        response = self.generate(
            "suggest",
            model=MODEL,
            contents=self.build.premise(avoid, genre),
            config=types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level="low")),
        )
        text = (response.text or "").strip().strip("「」\"")
        if not text:
            raise AIFailed(UI["no_suggestion"])
        return text

    def write_epilogue(self, state: GameState) -> None:
        """After the story ends, have the AI look back over the whole journey and write the epilogue and the ending's title."""
        response = self.generate(
            "epilogue",
            model=MODEL,
            contents=self.build.epilogue(state),
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, response_mime_type="application/json", response_schema=Epilogue),
        )
        if not isinstance(response.parsed, Epilogue):
            raise AIFailed(UI["no_epilogue"])
        state.ending_title, state.epilogue = response.parsed.title.strip(), response.parsed.text.strip()
        self.write_log({"turn": state.turn, "epilogue": state.ending_title})

    # ---------- A turn ----------

    def _next_beat(self, state: GameState, actions: dict[str, str] | None) -> StoryBeat:
        """Have the AI write this turn. If it writes the ending too early, have it rewrite once; if the rewrite still ends, _apply() ignores the ending."""
        prompt = self.build.turn(state, actions)
        try:
            # game_over is the first field the AI writes: an early ending is caught before any narration appears, so players never see the discarded version
            return self.stream_beat(prompt, stop_on_ending=not ending_allowed(state, state.turn + 1))
        except EndingTooEarly:
            self.draft = ""
            return self.stream_beat(prompt + "\n\n" + TURN["early_ending_retry"], kind="rewrite")

    def _advance(self, state: GameState, actions: dict[str, str] | None) -> None:
        beat = self._next_beat(state, actions)
        newly_dead = self._apply(state, beat)
        self._log_turn(state, actions, beat)
        if newly_dead:
            self._write_deaths(state, newly_dead)

    def _apply(self, state: GameState, beat: StoryBeat) -> list[str]:
        """The AI can only propose changes; the program decides how much to accept, applying the rules to each character. Returns the characters who died of wounds this turn."""
        elapsed, is_opening_turn = advance_clock(state, beat.time_passed, beat.start_time_of_day)
        may_end = ending_allowed(state, state.turn)  # Checked before advancing the act: the turn that enters the last act can't end yet
        updates = {u.name.strip(): u for u in beat.character_updates}  # Names not on the team are simply ignored
        if state.solo and beat.character_updates and state.characters[0].name not in updates:
            updates[state.characters[0].name] = beat.character_updates[0]  # With one character, a wrong name from the AI still counts as theirs
        newly_dead = []
        for c in state.characters:
            if not c.alive:
                continue
            u = updates.get(c.name)
            if u is None:  # The AI left this character out: time still passes, and choices are empty (the player can act freely)
                apply_condition_changes(c, [], [], elapsed)
                c.choices = []
                continue
            apply_condition_changes(c, u.conditions_changed, u.conditions_removed, elapsed)
            apply_items(c, u.items_gained, u.items_lost)
            c.choices = u.choices[:4]
            if body_score(c) >= DEATH_SCORE:
                c.alive, c.choices = False, []
                newly_dead.append(c.name)
        apply_story_progress(state, beat.flags_set, beat.key_event, beat.milestone_reached, is_opening_turn)

        state.current_narration = beat.narration
        state.game_over = (beat.game_over and may_end) or not any(c.alive for c in state.characters)
        state.current_time_limit = clamp_time_limit(state, beat.time_limit)
        return newly_dead

    def _write_deaths(self, state: GameState, names: list[str]) -> None:
        """The program found a character died of their wounds: have the AI write a short scene of them falling, after this turn's narration."""
        prefix = state.current_narration + "\n\n"

        def on_text(text: str) -> None:  # While streaming, follow on from the narration just shown
            self.draft = prefix + text.lstrip()

        text, _ = self.stream(
            "death",
            on_text,
            model=MODEL,
            contents=self.build.death(state, names),
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        )
        if text := text.strip():
            state.current_narration += "\n\n" + text

    def _log_turn(self, state: GameState, actions: dict[str, str] | None, beat: StoryBeat) -> None:
        """Log the changes the AI proposed this turn and what the program applied, to look into "why did that happen" later."""
        self.write_log({
            "turn": state.turn,
            "actions": actions,
            "ai": beat.model_dump(exclude={"narration"}),
            "characters": {c.name: {"conditions": [f"{x.name}({x.severity})" for x in c.conditions], "alive": c.alive} for c in state.characters},
            "time": clock_text(state.minutes),
        })

    def stream_beat(self, prompt: str, kind: str = "turn", stop_on_ending: bool = False) -> StoryBeat:
        """A streaming call returning one turn's structured response (StoryBeat). Updates draft as narration arrives, so shells can show it early.
        With stop_on_ending, stops as soon as the AI declares the ending (EndingTooEarly)."""

        def on_text(text: str) -> None:
            if stop_on_ending and partial_bool(text, "game_over") is True:
                raise EndingTooEarly
            if (narration := partial_string(text, "narration")) is not None:
                self.draft = narration

        text, last = self.stream(
            kind,
            on_text,
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, response_mime_type="application/json", response_schema=StoryBeat),
        )
        try:
            return StoryBeat.model_validate_json(text)
        except ValueError as e:
            reason = last.candidates[0].finish_reason if last is not None and last.candidates else UI["no_content"]
            raise AIFailed(UI["unparsable"].format(reason=reason)) from e

    # ---------- Memory compaction ----------

    def needs_compaction(self, state: GameState) -> bool:
        """Whether compact_memory() has anything to do. Part of the engine's interface to the game, so the game never reaches into rules.py
        and the test engines can stand in for it."""
        return needs_compaction(state)

    def compact_memory(self, state: GameState) -> None:
        """When the story log gets too long, fold the oldest turns (down to half), older key events and facts into the long-term summary.
        The core calls this in the background while players read, only when needs_compaction(). Rare: a 30-turn story is only about 7,000–8,000 characters."""
        turns, old_events, old_flags = parts_to_compact(state)
        response = self.generate(
            "compaction",
            model=MODEL,
            contents=self.build.compaction(state),
            config=types.GenerateContentConfig(system_instruction=MEMORY["system"], thinking_config=types.ThinkingConfig(thinking_level="low")),
        )
        text = (response.text or "").strip()
        if not text:
            return  # On failure keep things as they are and retry next time
        # Remove only what was folded into the summary this time (no new turns arrive during compaction, but counting is safer)
        state.summary = text
        del state.recent[: len(turns)]
        del state.key_events[: len(old_events)]
        del state.flags[: len(old_flags)]
