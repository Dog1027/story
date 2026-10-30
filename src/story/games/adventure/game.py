"""Adventure: a team adventures through a story the AI writes. Text goes in, a reply comes out.

From outside it looks like calling an LLM: `reply = core.send("climb up")` (with several characters, `core.send_as("Ming", "climb up")`).
Memory, rules and saves are hidden in here; the flow every game shares (the team, continuing saves, collecting actions) is in story/core/team.py.
A reply is the narration plus extra data (choices, the status bar, the countdown…), and shells draw it from those fields.

The API key, player names, the countdown and the typing effect belong to the shells, not here.
"""

import logging
import random
import threading
from pathlib import Path
from typing import Any

from story.core.reply import Ending, Reply, SetupForm, Status, Tone, join, pick_choice
from story.core.team import FAILURES, PLAY_AGAIN_CHOICES, ReplayFields, StatusFields, TeamGame
from story.games.adventure.engine import Engine
from story.games.adventure.models import Character, GameState, word
from story.games.adventure.prompting import AWAY_ACTION, TIMEOUT_ACTION, TURN
from story.games.adventure.records import DEFAULT_PREMISE, change_groups, ending_record, memory_text, snapshot
from story.games.adventure.rules import condition_list, warning_level
from story.games.adventure.text import UI

log = logging.getLogger(__name__)
GENRE_AUTO, GENRE_NONE = "auto", "none"  # The two special genre options: AI picks from the premise, or no genre (shown as genre_label())


def genre_label(choice: str) -> str:
    """The text shown for a genre choice: special options become this language's words; a genre pack shows its name."""
    return {GENRE_AUTO: UI["genre_auto"], GENRE_NONE: UI["genre_none"]}.get(choice, choice)


class AdventureCore(TeamGame[GameState]):
    """One adventure: a team of one to four characters, each played by one player (one when playing alone).
    The AI writes a turn only once every living character has acted. The shared flow is in TeamGame."""

    title = UI["title"]
    busy_label = UI["busy_label"]
    description = UI["description"]
    state_class = GameState
    timeout_action = TIMEOUT_ACTION
    away_action = AWAY_ACTION

    def __init__(
        self,
        api_key: str,
        players: list[str],
        *,
        save_path: Path,
        log_path: Path | None = None,
        engine: Engine | None = None,
        client: Any = None,
    ):
        """client: a Gemini client to share (e.g. one limited by RateLimit); without one, a client is made from api_key."""
        super().__init__(players, save_path)
        self.engine = engine or Engine(api_key=api_key, client=client, log_path=log_path)
        self.timed = False  # The mode for new games, kept from the last game
        self.genre = GENRE_AUTO  # The genre choice for new games, kept from the last game
        self.last_premise = ""
        self.suggested = ""  # The premise /suggest came up with, used first when the premise is left blank
        self.drawn = ""  # A premise drawn at random from the genre packs' opening ideas; not drawn on play again, which keeps the last premise
        self._compaction: threading.Thread | None = None

    @property
    def progress(self) -> str:
        return self.engine.progress

    @property
    def draft(self) -> str:
        return self.engine.draft

    def watch(self, on_change) -> None:
        self.engine.on_change = on_change

    # ---------- New game: the story premise ----------

    def _new_game(self) -> Reply:
        self._wait_compaction()  # The last game's compaction must not save over the new game
        if self.state is not None:
            self.last_premise = self.state.premise  # Play again keeps the last game's premise
        return self._ask_premise()

    def _on_setup(self, raw: str) -> Reply:
        if raw == "/suggest":
            try:
                chosen = self.genre if self.genre in self.engine.genres else ""
                suggestion = self.engine.suggest_premise(self.last_premise or DEFAULT_PREMISE, genre=chosen)
            except FAILURES as e:
                return self._failed(e, self._ask_premise)
            self.suggested = suggestion
            return self._ask_premise(suggestion=suggestion)
        if raw == "/random":
            self.suggested, self.drawn = "", self._draw_premise(avoid=self._default_premise())
            return self._ask_premise(notice=UI["rerolled"])
        if raw.startswith("/timed"):
            arg = raw.removeprefix("/timed").strip()
            self.timed = {"on": True, "off": False}.get(arg, not self.timed)
            return self._ask_premise(notice=UI["mode_switched_timed" if self.timed else "mode_switched_normal"])
        if raw.startswith("/genre"):
            typed = raw.removeprefix("/genre").strip()
            choice = {UI["genre_auto"]: GENRE_AUTO, UI["genre_none"]: GENRE_NONE}.get(typed, typed)  # Typing the displayed word works too
            if choice not in (GENRE_AUTO, GENRE_NONE, *self.engine.genres):
                options = join(genre_label(g) for g in (GENRE_AUTO, GENRE_NONE, *self.engine.genres))
                return self._ask_premise(notice=UI["genre_unknown"].format(choice=typed, options=options))
            self.genre = choice
            if self.drawn and not self.suggested and self.drawn not in self._premise_pool():
                self.drawn = self._draw_premise()  # The drawn opening switches to the new genre's
            return self._ask_premise(notice=UI["genre_chosen"].format(choice=genre_label(choice)))
        if raw.startswith("/"):
            return self._ask_premise(notice=UI["unknown_command"].format(command=raw))

        premise = " ".join(raw.split()) or self._default_premise()
        state = self._new_state(premise)
        try:
            self.engine.start(state)
        except FAILURES as e:
            return self._failed(e, self._ask_premise)
        self.state, self._phase, self.last_premise, self.suggested, self.drawn = state, "playing", premise, "", ""
        self._save()
        return self._turn_reply(before=None)

    def _ask_premise(self, suggestion: str = "", notice: str = "", error=None) -> Reply:
        self._phase = "setup"
        if not (self.suggested or self.drawn or self.last_premise):  # The first new story: draw an opening at random
            self.drawn = self._draw_premise()
        form = SetupForm(default=self._default_premise(), genre=self.genre, genres=self._genre_menu(), suggestion=suggestion)
        return self._reply(form=form, notice=notice, error=error)

    def _new_state(self, premise: str) -> GameState:
        self.pending = {}
        characters = [Character(name=n) for n in self._players]
        return GameState(premise=premise, characters=characters, timed_mode=self.timed, **self._genre_fields())

    def _genre_fields(self) -> dict:
        """The new game's genre fields: a chosen genre applies directly; with "auto", the AI picks from the catalog when planning the outline."""
        if self.genre in self.engine.genres:
            return {"genre": self.genre}
        return {"genre_pending": self.genre == GENRE_AUTO and bool(self.engine.genres)}

    def _genre_menu(self) -> list[tuple[str, str, str]]:
        """The new story dialog's genre menu: (value, text shown, description), with auto and none first; no menu without genre packs."""
        if not self.engine.genres:
            return []
        return [
            (GENRE_AUTO, UI["genre_auto_option"], UI["genre_auto_hint"]),
            (GENRE_NONE, UI["genre_none_option"], UI["genre_none_hint"]),
        ] + [(g.name, UI["genre_option"].format(name=g.name), g.description) for g in self.engine.genres.values()]

    def _default_premise(self) -> str:
        """The premise used if left blank: the AI's suggestion → the random draw → the last game's (play again) → the default."""
        return self.suggested or self.drawn or self.last_premise or DEFAULT_PREMISE

    def _premise_pool(self) -> list[str]:
        """Openings to draw from: the chosen genre pack's, or every pack's if no genre is chosen, plus the default premise."""
        genres = self.engine.genres
        if self.genre in genres and genres[self.genre].premises:
            return list(genres[self.genre].premises)
        return [p for g in genres.values() for p in g.premises] + [DEFAULT_PREMISE]

    def _draw_premise(self, avoid: str = "") -> str:
        pool = self._premise_pool()
        return random.choice([p for p in pool if p != avoid] or pool)

    # ---------- A turn ----------

    def _action(self, raw: str, actor: str | None) -> str | None:
        if raw.startswith("/"):
            return None
        return pick_choice(raw, self._choices(actor) if actor else []) or raw

    def _play_round(self, actions: dict[str, str]) -> Reply:
        """Have the AI write this turn, save, and return this turn's reply."""
        self._wait_compaction()
        before = {c.name: snapshot(c) for c in self.game.characters}
        self.engine.act(self.game, actions)
        self.pending = {}  # Before building the reply: the new turn's choices go to whoever hasn't acted in it
        self._save()
        if self.game.game_over:
            self._phase = "ending"
        else:
            self._start_compaction()
        return self._turn_reply(before)

    def _on_ending(self, raw: str) -> Reply:
        """The next input after the story ends: write the epilogue. If the epilogue fails, still move on to the end so players can play again."""
        s = self.game
        notice = ""
        if not s.epilogue:
            try:
                self.engine.write_epilogue(s)
                self._save()
            except FAILURES as e:
                notice = UI["epilogue_failed"].format(error=str(e)[:200])
        self._phase = "ended"
        return self._reply(
            choices=PLAY_AGAIN_CHOICES,
            notice=notice,
            ending=Ending(title=s.ending_title, epilogue=s.epilogue, record=ending_record(s)),
        )

    def _turn_reply(self, before) -> Reply:
        s = self.game
        changes = []
        if before is not None:
            for c in s.characters:
                if groups := change_groups(before[c.name], c):
                    changes.append((c.name, groups))
        return self._reply(narration=s.current_narration, changes=changes, **self._screen())

    # ---------- Data for TeamGame ----------

    def _active(self) -> list[str]:
        return [c.name for c in self.game.characters if c.alive]

    def _choices(self, name: str) -> list[str]:
        return next((list(c.choices) for c in self.game.characters if c.name == name), [])

    def _time_limit(self) -> int:
        return self.game.current_time_limit

    def _status(self) -> StatusFields:
        s = self.game
        return {"turn": s.turn, "timed": s.timed_mode, "characters": [status_bar(c) for c in s.characters]}

    def _next_timed(self) -> bool:
        return self.timed

    def _loaded(self) -> None:
        self.timed = self.game.timed_mode

    def _replay(self) -> ReplayFields:
        s = self.game
        return {"narration": s.current_narration, "resumed": True, "history": self._history(), "history_trimmed": bool(s.summary)}

    def _history(self) -> list[tuple[str, str]]:
        """Earlier narration (the story log's original text): (narration, the actions taken after it). With one character, actions have no name in front, as usual."""
        s = self.game
        prefix = TURN["action_entry"].format(name=s.characters[0].name, action="") if s.solo else ""
        return [(t.narration, t.action.removeprefix(prefix)) for t in s.recent]

    def _help(self) -> str:
        return UI["help"]

    def _memory(self) -> str:
        return memory_text(self.game)

    # ---------- Background memory compaction ----------

    def _start_compaction(self) -> None:
        """While players read, compact old memory into the summary in the background. The next LLM call waits for it to finish."""
        if not self.engine.needs_compaction(self.game):
            return
        state = self.game

        def run() -> None:
            try:
                self.engine.compact_memory(state)
            except Exception:  # A failure is fine (it's retried next turn), but log why
                log.exception("memory compaction failed")
                return
            if state is self.state:  # If a new game started meanwhile, don't overwrite the save with the old one
                self._save()

        self._compaction = threading.Thread(target=run, daemon=True)
        self._compaction.start()

    def _wait_compaction(self) -> None:
        if self._compaction is not None:
            self._compaction.join()
            self._compaction = None


def status_bar(c: Character) -> Status:
    """One character's status for the shells to show (one item in Reply.characters)."""
    warning = warning_level(c) if c.alive else ""
    items: list[tuple[str, Tone]] = [*condition_list(c)] or [(word("level", "healthy"), "good")]
    return Status(items=items, warning=warning, name=c.name, alive=c.alive, warning_text=word("level", warning) if warning else "")
