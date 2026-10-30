"""The flow shared by team games: every game (the adventure's AdventureCore and turtle soup's SoupCore under story/games/) is a subclass.

A game is a team of one to MAX_PLAYERS players. Each player's action is sent with send_as(name, text), recorded in the order sent;
once everyone still in play has acted, the subclass advances a turn (_play_round). With one player, send(text) is their action.
Input that belongs to no player (time's up, dialog answers, /state) uses send(). view(name) gets one player's view of the screen.

This class handles: the player list, asking whether to continue a found save, collecting everyone's actions (all taken back if the turn fails), confirming a restart, playing again,
view(), waiting(), failure replies, and building replies. Subclasses handle: what to ask for a new game (the setup phase), how a turn advances,
the ending, the status bar, /help, plus the game's name (title) and the save format (state_class). A save must have names, premise, turn, game_over.
"""

import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from google.genai import errors
from pydantic import BaseModel

from story.core.ai import is_key_error
from story.core.reply import MAX_PLAYERS, UI, Phase, Reply, pick_choice
from story.core.saves import load, save

CONTINUE_CHOICES = [UI["choice_continue"], UI["choice_new_game"]]
CONFIRM_CHOICES = [UI["choice_confirm"], UI["choice_cancel"]]
PLAY_AGAIN_CHOICES = [UI["choice_play_again"]]
FAILURES = (errors.APIError, RuntimeError)  # Calling the AI failed: stay in the same phase and let players retry
log = logging.getLogger(__name__)


class WrongUsage(ValueError):
    """The shells called the core the wrong way (a bug in the calling code): raised as is, not turned into a reply."""


class TeamGame:
    title: str  # The game's name (adventure, turtle soup), shown by the shells
    busy_label: str  # What everyone sees while waiting for the AI (e.g. "writing the story", "the judge is thinking")
    description: str  # One line on what the game is like, shown in the room's game picker
    state_class: type[BaseModel]  # The save format
    timeout_action: str  # Stands in for players who haven't acted when timed mode runs out (/timeout)
    away_action: str  # Stands in for a player who is away (the room sends /away when someone disconnects)

    def __init__(self, players: list[str], save_path: Path):
        names = [n.strip() for n in players if n.strip()]
        if not 1 <= len(names) <= MAX_PLAYERS or len(set(names)) != len(names):
            raise ValueError(UI["team_size"].format(min=1, max=MAX_PLAYERS))
        self._players = names
        self.save_path = save_path
        self.state = None  # This game's state (state_class); None before it starts
        self._phase: Phase = "setup"
        self.pending: dict[str, str] = {}  # Actions already sent this turn
        self._as: str | None = None  # The player given to send_as()

    # ---------- Public interface ----------

    @property
    def players(self) -> list[str]:
        """The players' names on the team (read-only), in the order given."""
        return list(self._players)

    @property
    def phase(self) -> Phase:
        """The current phase (read-only), the same as the latest reply's reply.phase. Web rooms use it to decide who gets the input."""
        return self._phase

    @property
    def progress(self) -> str:
        """While send() runs, what it's doing now (e.g. "planning the story outline"); shells may read it from another thread."""
        return ""

    @property
    def draft(self) -> str:
        """While send() runs, the narration the AI is writing (what has streamed in so far); shells may read it from another thread."""
        return ""

    def watch(self, on_change: Callable[[], None]) -> None:
        """Call on_change() whenever progress or draft changes, so shells don't have to keep checking. It's called from the thread
        running send(), so it should only hand the news over to the shell's own thread (e.g. loop.call_soon_threadsafe)."""

    def start(self) -> Reply:
        """The first reply: asks whether to continue if the same players have an unfinished save, otherwise starts a new game."""
        state = load(self.save_path, self.state_class)
        if state and not state.game_over and sorted(state.names) == sorted(self._players):  # The same players in any order
            self.state, self._phase = state, "ask_continue"
            self._loaded()
            return self._reply(choices=CONTINUE_CHOICES, notice=UI["found_save"].format(turn=state.turn, premise=state.premise))
        return self._new_game()

    def action_for(self, text: str) -> str | None:
        """The action this input stands for in the game (e.g. "2" → the second choice), so shells can show it before the reply arrives.
        None when it isn't an action (a command, blank, not in a game)."""
        raw = text.strip()
        if self._phase != "playing" or not raw:
            return None
        if raw == "/timeout":
            return self.timeout_action
        if raw == "/away":
            return self.away_action
        return self._action(raw, self._actor())

    def send(self, text: str) -> Reply:
        """Send one input and get the reply. May call the AI, so it can take a few seconds."""
        raw = text.strip()
        if raw == "/help":
            return self._reply(info=(UI["help_title"], self._help()), **self._screen())
        if raw == "/state":
            if self.state is None:
                return self._reply(notice=UI["no_story_yet"], **self._screen())
            return self._reply(info=(UI["memory_title"], self._memory()), **self._screen())
        handler = {
            "ask_continue": self._on_ask_continue,
            "setup": self._on_setup,
            "playing": self._on_playing,
            "confirm_restart": self._on_confirm_restart,
            "ending": self._on_ending,
            "ended": self._on_ended,
        }[self._phase]
        try:
            return handler(raw)
        except WrongUsage:
            raise
        except Exception:  # A bug, or an error nobody expected: restore and let players retry instead of ending the game
            log.exception("unexpected error in phase %s for input %r", self._phase, raw)
            return self._recover()

    def send_as(self, name: str, text: str) -> Reply:
        """Send input as a given player, in any order. Outside of play (premise, confirmations…), the same as send()."""
        if self._phase == "playing" and self._is_action(text.strip()):  # Only actions need checking
            if name not in self._active():
                return self._reply(notice=UI["character_fallen"], **self._screen())
            if name in self.pending:
                return self._reply(notice=UI["already_acted"], **self._screen())
        self._as = name
        try:
            return self.send(text)
        finally:
            self._as = None

    def view(self, name: str, reply: Reply | None = None) -> Reply:
        """One player's view of the screen: actor and choices become that player's (players who have acted or are out have no choices).
        With reply, its other fields are kept; otherwise it's the current turn's screen (used on reconnect)."""
        if reply is None:
            reply = self._reply(**self._screen())
            if self._phase == "playing":
                reply = replace(reply, **self._replay())
        if self._phase != "playing":
            return replace(reply, actor="", choices=[] if reply.actor else reply.choices)
        return replace(reply, **self._screen_for(name if name in self.waiting() else None))

    def waiting(self) -> list[str]:
        """The names of players who haven't acted this turn, in team order."""
        if self.state is None or self._phase != "playing":
            return []
        return [n for n in self._active() if n not in self.pending]

    # ---------- Phases ----------

    def _on_ask_continue(self, raw: str) -> Reply:
        answer = pick_choice(raw, CONTINUE_CHOICES)
        if answer == CONTINUE_CHOICES[0] or raw == "/continue":
            return self._resume()
        if answer == CONTINUE_CHOICES[1] or raw in ("/new", "/restart"):
            return self._new_game()
        return self._reply(choices=CONTINUE_CHOICES, notice=UI["answer_continue"])

    def _on_playing(self, raw: str) -> Reply:
        if raw == "/restart":
            self._phase = "confirm_restart"
            return self._reply(choices=CONFIRM_CHOICES, notice=UI["confirm_restart"])
        action = self.action_for(raw)
        if action is None:
            notice = UI["unknown_command"].format(command=raw) if raw else UI["enter_action"]
            return self._reply(notice=notice, **self._screen())
        return self._take_action(action, timeout=raw == "/timeout")

    def _take_action(self, action: str, timeout: bool) -> Reply:
        """Record this player's action; advance a turn only once everyone has acted. When time runs out, everyone who hasn't acted hesitates."""
        if timeout:
            for name in self.waiting():
                self.pending[name] = action
        else:
            actor = self._actor()
            if actor is None:
                raise WrongUsage("With several players, actions must be sent with send_as(name, text) so it's clear whose action it is")
            self.pending[actor] = action
            if self.waiting():
                return self._reply(**self._screen())  # Still waiting for others: shells show who hasn't acted using waiting()
        actions = {n: self.pending[n] for n in self._players if n in self.pending}
        try:
            reply = self._play_round(actions)
        except FAILURES as e:
            self.state = load(self.save_path, self.state_class) or self.state  # It may be half changed; restore from the save
            # Take back every action this turn so everyone chooses again. Taking back only the last one isn't enough: if an action filled in
            # on time-out or for an offline player fails, everyone counts as having acted but no one can resend, and the game is stuck
            self.pending = {}
            return self._failed(e, lambda **kw: self._reply(**self._screen(), **kw), hint=UI["failed_turn"])
        self.pending = {}
        return reply

    def _on_confirm_restart(self, raw: str) -> Reply:
        answer = pick_choice(raw, CONFIRM_CHOICES)
        if answer == CONFIRM_CHOICES[0]:
            return self._new_game()
        if answer == CONFIRM_CHOICES[1]:
            self._phase = "playing"
            return self._reply(**self._screen())
        return self._reply(choices=CONFIRM_CHOICES, notice=UI["answer_confirm"])

    def _on_ended(self, raw: str) -> Reply:
        if pick_choice(raw, PLAY_AGAIN_CHOICES) or raw in ("/new", "/restart"):
            return self._new_game()
        return self._reply(choices=PLAY_AGAIN_CHOICES, notice=UI["answer_play_again"])

    # ---------- Shared ----------

    def _resume(self) -> Reply:
        self._phase = "playing"
        self.pending = {}
        return self._reply(notice=UI["resumed"].format(premise=self.state.premise), **self._replay(), **self._screen())

    def _actor(self) -> str | None:
        """Whose input this is: the player given to send_as(), or the only player. None if they've already acted or are out."""
        if self.state is None:
            return None
        name = self._as if self._as is not None else (self._players[0] if len(self._players) == 1 else None)
        return name if name in self.waiting() else None

    def _screen(self) -> dict:
        """The fixed part of the in-game screen: the choices of the player who sent the input (the only player when alone), and the time limit."""
        return self._screen_for(self._actor() if self._phase == "playing" else None)

    def _screen_for(self, actor: str | None) -> dict:
        """A player's choices (while they haven't acted) and the time limit; no choices when actor is None."""
        if self.state is None or self._phase not in ("playing", "ending"):
            return {}
        return {"actor": actor or "", "choices": self._choices(actor) if actor else [], "time_limit": self._time_limit()}

    def _recover(self) -> Reply:
        """An unexpected error: the state may be half changed, so restore it from the save and take back this turn's actions, like a failed AI call."""
        if self.state is not None:
            self.state = load(self.save_path, self.state_class) or self.state
        self.pending = {}
        hint = {"playing": UI["failed_turn"], "ending": UI["failed_ending"]}.get(self._phase, "")
        notice = UI["failed"].format(hint=hint, error=UI["unexpected"])
        return self._reply(error="api", notice=notice, **self._screen())

    def _failed(self, e: Exception, retry_screen, hint: str = "") -> Reply:
        """Calling the AI failed: stay in the same phase so players can retry."""
        notice = UI["key_invalid"] if is_key_error(e) else UI["failed"].format(hint=hint, error=str(e)[:300])
        return retry_screen(error="api", notice=notice)

    def _reply(self, **fields) -> Reply:
        in_game = self.state is not None and self._phase != "setup"  # A game is in progress (not yet while waiting to start one)
        return Reply(phase=self._phase, **(self._status() if in_game else {"timed": self._next_timed()}), **fields)

    def _save(self) -> None:
        save(self.state, self.save_path)

    # ---------- Provided by subclasses ----------

    def _new_game(self) -> Reply:
        """Start a new game (no save, chose a new game, confirmed a restart, play again): reply with the setup phase's screen."""
        raise NotImplementedError

    def _on_setup(self, raw: str) -> Reply:
        """Input during the setup phase."""
        raise NotImplementedError

    def _play_round(self, actions: dict[str, str]) -> Reply:
        """Everyone has acted: advance a turn and save. On failure, raise one of FAILURES; this class restores and takes back every action."""
        raise NotImplementedError

    def _on_ending(self, raw: str) -> Reply:
        """The next input right after the end: wrap up the ending and reply with ended."""
        raise NotImplementedError

    def _active(self) -> list[str]:
        """Players still in play who act each turn (in the adventure, fallen characters don't count)."""
        return list(self._players)

    def _is_action(self, raw: str) -> bool:
        """Whether this input is an in-game action (which must be checked against having acted already)."""
        return not raw.startswith("/") or raw == "/away"

    def _action(self, raw: str, actor: str | None) -> str | None:
        """The action an in-game input stands for; None if it isn't one. /timeout and /away are already handled."""
        raise NotImplementedError

    def _choices(self, name: str) -> list[str]:
        """This player's choices this turn."""
        return []

    def _time_limit(self) -> int:
        return 0

    def _status(self) -> dict:
        """While a game is in progress: turn, timed, characters for the reply."""
        raise NotImplementedError

    def _next_timed(self) -> bool:
        """Before a game starts: the mode a new game will use."""
        return False

    def _replay(self) -> dict:
        """What to show again after loading or reconnecting: narration, resumed, history…"""
        raise NotImplementedError

    def _loaded(self) -> None:
        """When a save that can be continued is found (self.state is already the save)."""

    def _help(self) -> str:
        """What /help shows."""
        raise NotImplementedError

    def _memory(self) -> str:
        """What /state shows."""
        raise NotImplementedError

