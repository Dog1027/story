"""A web room: one room is one game (playing alone is a room with just you).

The lobby (lobby.py) creates and closes rooms and manages players' connections and names: it hands people entering this room to add(),
calls remove() when they leave or disconnect, and passes messages inside the room to handle().
The room holds one core (a game from story.games): it passes each player's input to the core, then sends the reply to every player (each sees their own choices).

The flow: waiting for players (the host picks a game) → the host answers "continue the save / what a new game asks" → playing (everyone acts on their own; the turn advances when all have)
→ the ending → back to the waiting screen. The host's /restart also goes back to the waiting screen (asking first if a game is under way). The host is the first person in; when the host leaves, the next person online takes over.

Messages are dicts that can be converted to JSON, sent over a Connection (connection.py); their types are in shells/messages.py.
Player → room
  {"type": "send", "text": "1"}           A player's input: an action, a command, or the host answering a dialog
  {"type": "send", "text": "/suggest", "form": true, "answer": 3}
                                          Actions in the new game dialog (e.g. the adventure's suggest one, change genre) go only to the core,
                                          not pushed to anyone; with "answer" (a request id), the result goes back to the host with that id
  {"type": "ready"}                       New narration finished showing (the timed countdown starts once everyone's has)
Room → player
  {"type": "lobby", "view": "room", "title": "Ming's room", "host": "Ming", "you": "Hua", "members": [...], "seats": 4,
   "choices": [...], "games": [{"code": "adventure", "title": "...", "description": "...", "choice": "1"}, ...], "hint": "...", "clear": true}
                                          The waiting screen: who's in the room (members, in the order they came in), the number of seats, the options, the input box hint;
                                          games is the host's game picker (empty for everyone else), each with the option that starts it
  {"type": "reply", "reply": {...}}       The core's reply (Reply.to_dict(), with this player's choices)
  {"type": "premise", "id": 3, "reply": {...}}
                                          The result of a command while starting a new game, sent only to the host who asked with answer
  {"type": "new_story", "premise": "..."}  A new game starts: wipe the screen and show the premise first (answers to options aren't shown)
  {"type": "busy", "on": true, "progress": "planning the story outline", "label": "Writing the story"}
                                          Waiting for the AI (sent again when progress changes); label is the game's busy_label
  {"type": "draft", "text": "..."}        The narration the AI is writing (the full text streamed so far, sent again when more arrives)
  {"type": "waiting", "names": [...]}     Who hasn't acted this turn
  {"type": "timer", "seconds": 12}        Start the timed countdown (the room sends /timeout when it runs out)
  {"type": "notice", "text": "..."}
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from story.core import AWAY, HOST_PHASES, MAX_PLAYERS, RESTART, TIMEOUT, Reply, TeamGame, pick_choice
from story.shells.connection import BackgroundTasks, ServerEnd
from story.shells.messages import GameCard, LobbyScreen, PlayerMessage, SendMessage, ServerMessage
from story.shells.rooms.countdown import Countdown
from story.shells.rooms.runner import CoreRunner
from story.shells.text import UI

log = logging.getLogger(__name__)
LEAVE = UI["leave_room"]


# make_core(players, on_queue, game) builds a game's core: game is the code of one of the room's GameChoices;
# on_queue(queued) lets the screen show "queued" while an AI call waits in line
MakeCore = Callable[[list[str], Callable[[bool], None], str], TeamGame]


@dataclass(frozen=True)
class GameChoice:
    """A game the host can pick on the waiting screen. The room only needs to show it and pass code to make_core."""

    code: str  # Passed to make_core; also used in save file names
    title: str
    description: str  # A line about it, under its name in the host's game picker


class Member:
    def __init__(self, name: str, conn: ServerEnd):
        self.name, self.conn = name, conn
        self.online = True
        self.behind = False  # Came back while the core was busy: shown the current screen once it's done


class Room:
    def __init__(
        self,
        games: list[GameChoice],
        make_core: MakeCore,
        on_change: Callable[[], Awaitable[None]] | None = None,
    ):
        """games are the games the host can pick, and make_core builds the one picked (see MakeCore).
        on_change() is awaited after input that may change what the lobby shows (a game started, back to waiting)."""
        self.games = {g.code: g for g in games}
        self.starts = {UI["start_game"].format(game=g.title): g.code for g in games}  # The options that start each game
        self.make_core = make_core
        self.on_change = on_change
        self.tasks = BackgroundTasks()  # Input that uses the core, handled in the background (see handle())
        self.game_title = ""  # The name of the game being played (shown on the lobby's room card)
        self.members: dict[str, Member] = {}  # In the order they came in; people who disconnect mid-game are kept so they can reconnect
        self.host = ""
        self.core: TeamGame | None = None
        self.host_reply: Reply | None = None  # The screen waiting for the host's answer (save, premise, confirm restart), resent when the host changes
        self.lock = asyncio.Lock()  # Held while using the core (see _using_core); messages that don't need the core never wait for it
        self.runner = CoreRunner(self._broadcast)  # Calls the core in a background thread and tells everyone how it's going
        self.countdown = Countdown(  # Timed mode: starts once everyone has read the narration; /timeout when it runs out
            announce=lambda seconds: self._broadcast({"type": "timer", "seconds": seconds}), time_up=self._time_up)

    # ---------- For the lobby ----------

    @property
    def online(self) -> list[str]:
        return [m.name for m in self._online_members()]

    @property
    def playing(self) -> bool:
        return self.core is not None

    @property
    def active_core(self) -> TeamGame:
        """The core, for code that only runs during a game (the caller has already checked self.core)."""
        if self.core is None:
            raise RuntimeError("no game in progress")
        return self.core

    def is_host(self, name: str) -> bool:
        return name == self.host

    def entry_error(self, name: str) -> str:
        """Whether this person may come in; the reason if not. The lobby makes sure names are unique."""
        if self.core is not None:
            if name not in self.core.players:
                return UI["room_members_only"].format(players=UI["list_sep"].join(self.core.players))
        elif len(self.online) >= MAX_PLAYERS:
            return UI["room_full"].format(max=MAX_PLAYERS)
        return ""

    def is_leaving(self, name: str, text: str) -> bool:
        """Whether this input leaves the room: /leave, or "Leave room" chosen on the waiting screen."""
        return text == "/leave" or (self.core is None and pick_choice(text, self._lobby_choices(name)) == LEAVE)

    async def handle(self, name: str, message: PlayerMessage) -> None:
        """Input that uses the core is handled in the background: the AI can take tens of seconds, and meanwhile this player's
        connection keeps being read (so leaving is noticed at once). The core's lock takes them one at a time, in the order they came."""
        if message["type"] == "send":
            self.tasks.spawn(self._on_send_message(name, message))
        elif message["type"] == "ready":
            self.countdown.finished_reading(name, self.online)

    async def close(self) -> None:
        self.countdown.stop()
        self.tasks.cancel()
        self.runner.close()

    @asynccontextmanager
    async def _using_core(self):
        """Use the core, one at a time: it isn't thread-safe, and a call can take tens of seconds while the AI writes.
        Only code that touches the core goes through here, so leaving, disconnecting and "finished reading" never wait for the AI.
        On the way out, show people who came back meanwhile the current screen, and stand in for offline players if only they are left."""
        async with self.lock:
            yield
            await self._fill_offline()  # May call the AI again: catch people up only after it, or anyone coming back meanwhile is missed
            while behind := [m for m in self._online_members() if m.behind]:
                await self._catch_up(behind[0].name)

    # ---------- Coming and going ----------

    async def add(self, name: str, conn: ServerEnd) -> None:
        self.members[name] = Member(name, conn)
        if not self.host or not self.members[self.host].online:
            self.host = name
        if self.core is None:
            await self._broadcast_lobby(clear_for=name)
            return
        await self._broadcast_notice(UI["room_back"].format(name=name), skip=name)
        if self.lock.locked():  # The core is busy (e.g. the AI is writing): don't wait here; they're caught up once it's done
            self.members[name].behind = True
            if self.runner.busy:
                await self._safe_write(self.members[name], self.runner.busy_message())
            return
        async with self._using_core():
            await self._catch_up(name)

    async def _catch_up(self, name: str) -> None:
        """Show someone who (re)joined a game in progress where things stand now."""
        member = self.members.get(name)
        if member is None or not member.online:
            return
        member.behind = False
        if self.core is None:
            return  # The game ended meanwhile: they already got the waiting screen with everyone else
        if self.core.phase == "playing":
            await self._send_reply(name, self.core.view(name))
            await self._broadcast_waiting()
            if left := self.countdown.remaining():
                await self._safe_write(member, {"type": "timer", "seconds": left})
        elif self.is_host(name) and self.host_reply:
            await self._send_reply(name, self.host_reply)
        else:
            await self._send_notice(name, UI["host_setting_up"])

    async def remove(self, name: str) -> None:
        if name not in self.members:
            return
        if self.core is None:
            del self.members[name]
        else:
            self.members[name].online = False
        online = self.online
        was_host = self.is_host(name)
        if was_host:
            self.host = online[0] if online else ""
        if not online:
            return
        if self.core is None:
            await self._broadcast_lobby()
            return
        await self._broadcast_notice(UI["room_left"].format(name=name))
        if self.host_reply and was_host:
            await self._send_reply(self.host, self.host_reply)  # The old host left, so the new host answers
        self.countdown.left_room(name, online)  # They might have been the last one still reading
        # Stand in for them in the background: that may call the AI, and leaving must not wait for it (the lobby frees their name only
        # once this returns). If the core is busy, whoever is using it stands in for them on the way out anyway
        self.tasks.spawn(self._stand_in())

    async def _stand_in(self) -> None:
        async with self._using_core():
            pass  # Leaving _using_core stands in for offline players if only they are left

    # ---------- Input ----------

    async def _on_send_message(self, name: str, message: SendMessage) -> None:
        text = str(message.get("text", "")).strip()
        async with self._using_core():
            try:
                await self._on_send(name, text, form=bool(message.get("form")), answer=message.get("answer"))
            except Exception:
                await self._recover(name, message)
        if self.on_change:
            await self.on_change()

    async def _on_send(self, name: str, text: str, form: bool = False, answer: int | None = None) -> None:
        """answer: the id of a new game dialog request waiting for this command's result (see the messages above)."""
        if self.core is None:
            await self._on_lobby(name, text)
            return
        core = self.core
        if text == RESTART and core.phase != "playing":  # Nothing to give up yet (setup, continuing a save, the ending): straight back to picking a game
            if self.is_host(name):
                await self._back_to_waiting()
            else:
                await self._send_notice(name, UI["host_only_restart"])
        elif core.phase == "playing":
            await self._on_playing(name, text)
        elif not self.is_host(name) and core.phase != "ending":  # Anyone may retry an ending that failed to wrap up
            await self._send_notice(name, UI["wait_host_story"].format(host=self.host))
        elif form and core.phase == "setup":  # Actions in the new game dialog, not pushed to anyone else
            reply = await self.runner.call(lambda: core.send(text))
            if answer is not None:
                await self._safe_write(self.members[name], {"type": "premise", "id": answer, "reply": reply.to_dict()})
        else:
            starting = core.phase == "setup"  # Starting a game: calls the AI
            if starting:  # What the host wrote in a setup form is shown to everyone first; answers to choices (turtle soup's puzzle source) aren't
                premise = "" if self.host_reply and self.host_reply.form is None else text
                await self._broadcast({"type": "new_story", "premise": premise})
            restarting = core.phase == "confirm_restart"
            reply = await self.runner.call(lambda: core.send(text), busy=starting)
            if restarting and reply.phase == "setup":  # The host confirmed giving up this game: back to picking one, not the same game's setup
                await self._back_to_waiting()
                return
            await self._route(reply)

    async def _on_lobby(self, name: str, text: str) -> None:
        if not self.is_host(name):
            await self._send_notice(name, UI["wait_host_start"].format(host=self.host))
            return
        game = self.starts.get(pick_choice(text, self._lobby_choices(name)) or "")
        if game is None:
            return
        core = self.make_core(self.online, self.runner.set_queued, game)
        self.game_title, self.core = self.games[game].title, core
        self.runner.attach(core)
        await self._route(await self.runner.call(core.start))  # May read a save or call the AI: not on the event loop

    async def _on_playing(self, name: str, text: str) -> None:
        core = self.active_core
        if text == TIMEOUT:
            return  # The room runs the countdown; players can't call time for everyone
        if text == RESTART and not self.is_host(name):
            await self._send_notice(name, UI["host_only_restart"])
            return
        if text.startswith("/") and core.action_for(text, name=name) is None:  # /state, /restart, or an unknown command: reply only to the sender
            # (some games' actions start with a slash too, like turtle soup's /ask: those are actions, so the last one shows everyone the wait)
            reply = await self.runner.call(lambda: core.send_as(name, text))
            await self._route(reply, only=name)
            return
        await self._take_turn(name, text)

    async def _take_turn(self, name: str, text: str) -> None:
        core = self.active_core
        resolving = core.waiting() == [name]
        await self._route(await self.runner.call(lambda: core.send_as(name, text), busy=resolving), only=name)

    async def _fill_offline(self) -> None:
        """Everyone online has acted and only offline people are left: send "away" for them, one at a time, so the turn can advance.
        Runs whenever someone is done with the core (see _using_core)."""
        while self.core is not None and self.core.phase == "playing" and self.online:
            waiting = self.core.waiting()
            if not waiting or any(self.members[n].online for n in waiting if n in self.members):
                return
            await self._take_turn(waiting[0], AWAY)  # The core decides the text for the AI

    # ---------- Replies ----------

    async def _route(self, reply: Reply, only: str = "") -> None:
        """Send the core's reply to whoever should get it: everyone when there's new narration, otherwise only `only` (the sender)."""
        phase = reply.phase
        if phase in HOST_PHASES:
            self.host_reply = reply
            self.countdown.stop()
            await self._send_reply(self.host, reply)
            if phase != "confirm_restart":
                await self._broadcast_notice(UI["host_setting_up"], skip=self.host)
            return
        self.host_reply = None
        if phase == "playing" and reply.error:  # The turn didn't advance: the core took back everyone's actions, and everyone chooses again
            self.countdown.stop()
            await self._send_to_all(reply)
            if reply.time_limit:
                self.countdown.start_now(reply.time_limit)
            return
        if phase == "playing" and not reply.narration:
            if only:
                await self._send_reply(only, reply)
            await self._broadcast_waiting()
            return
        self.countdown.stop()
        await self._send_to_all(reply)
        if phase == "playing":
            if reply.time_limit:
                self.countdown.after_reading(reply.time_limit)
        elif phase == "ending" and not reply.error:
            # Go on to write the epilogue. If wrapping up the ending failed, don't go round again on our own: the same error would repeat
            # endlessly (and an epilogue that fails calls the AI every time); anyone can send something to try again
            core = self.active_core
            await self._route(await self.runner.call(lambda: core.send(""), busy=True))
        elif phase == "ended":
            await self._back_to_waiting()

    async def _back_to_waiting(self) -> None:
        """The game is over (or the host restarted): drop the core and anyone offline, and show the waiting screen; the same people can play again."""
        self.countdown.stop()
        self.core, self.host_reply = None, None
        self.runner.attach(None)
        for name in [m.name for m in self.members.values() if not m.online]:
            del self.members[name]
        await self._broadcast_lobby()

    async def _send_to_all(self, reply: Reply) -> None:
        """Everyone online gets the reply (each with their own choices), then, during play, who hasn't acted yet."""
        for member in self._online_members():
            await self._send_reply(member.name, reply)
        await self._broadcast_waiting()

    async def _send_reply(self, name: str, reply: Reply) -> None:
        member = self.members.get(name)
        if member and member.online and not member.behind:  # Someone catching up gets the whole current screen instead (_catch_up)
            view = self.core.view(name, reply) if self.core else reply
            await self._safe_write(member, {"type": "reply", "reply": view.to_dict()})

    # ---------- Timed countdown (countdown.py): the room sends /timeout when it runs out ----------

    async def _time_up(self) -> None:
        async with self._using_core():
            self.countdown.detach()  # Only now: while waiting for the core, a turn that advanced still stops (cancels) this countdown
            try:
                core = self.core
                if core and core.phase == "playing" and core.waiting():
                    await self._route(await self.runner.call(lambda: core.send(TIMEOUT), busy=True))
            except Exception:
                await self._recover("", None)

    async def _recover(self, name: str, message: SendMessage | None) -> None:
        """The last line of defence: something nobody expected failed while handling a message, or the countdown's time-up (message None)
        (the core already turns its own errors into replies). Log the details, tell people, and put everyone's current screen back, keeping the room and the connections."""
        message = message or {"type": "send", "text": "/timeout"}
        log.exception("unexpected error in %s's room handling %r from %r", self.host, message, name)
        try:
            for member in self._online_members():
                await self._send_notice(member.name, UI["room_error"])
                if self.core is not None and self.core.phase == "playing":
                    await self._send_reply(member.name, self.core.view(member.name))
            await self._broadcast_waiting()
            if (request := message.get("answer")) is not None and name in self.members:  # The premise dialog is waiting for this answer: give it one, or it waits forever
                failed = Reply(phase=self.core.phase if self.core else "setup", error="api", notice=UI["room_error"])
                await self._safe_write(self.members[name], {"type": "premise", "id": request, "reply": failed.to_dict()})
            elif self.host_reply and not message.get("form") and self.core is not None and self.core.phase == self.host_reply.phase:
                await self._send_reply(self.host, self.host_reply)  # The host's dialog closed when they answered: show it again so they can answer again
        except Exception:
            log.exception("could not restore the screens after the error")

    # ---------- Broadcasting ----------

    def _online_members(self) -> list[Member]:
        return [m for m in self.members.values() if m.online]

    async def _broadcast(self, message: ServerMessage, skip: str = "") -> None:
        for member in self._online_members():
            if member.name != skip:
                await self._safe_write(member, message)

    def _lobby_choices(self, name: str) -> list[str]:
        return [*self.starts, LEAVE] if self.is_host(name) else [LEAVE]

    def _game_menu(self) -> list[GameCard]:
        """The host's game picker: every game with its name and a line about it; choice is the option that starts it."""
        return [
            {"code": g.code, "title": g.title, "description": g.description, "choice": str(i)}
            for i, g in enumerate(self.games.values(), 1)
        ]

    async def _broadcast_lobby(self, clear_for: str = "") -> None:
        """The waiting screen: who's in the room; the host can start and everyone can leave. clear_for is someone who just came in, whose screen is wiped first."""
        for member in self._online_members():
            host = self.is_host(member.name)
            screen: LobbyScreen = {
                "type": "lobby",
                "view": "room",
                "title": UI["room_title"].format(host=self.host),
                "host": self.host,
                "you": member.name,
                "members": self.online,
                "seats": MAX_PLAYERS,
                "choices": self._lobby_choices(member.name),
                "games": self._game_menu() if host else [],
                "hint": UI["room_hint_host"] if host else UI["lobby_waiting_host"].format(host=self.host),
                "clear": member.name == clear_for,
            }
            await self._safe_write(member, screen)

    async def _broadcast_waiting(self) -> None:
        if self.core and self.core.phase == "playing":
            await self._broadcast({"type": "waiting", "names": self.core.waiting()})

    async def _broadcast_notice(self, text: str, skip: str = "") -> None:
        await self._broadcast({"type": "notice", "text": text}, skip=skip)

    async def _send_notice(self, name: str, text: str) -> None:
        if member := self.members.get(name):  # Input is handled in the background, so they may have left the room meanwhile
            await self._safe_write(member, {"type": "notice", "text": text})

    @staticmethod
    async def _safe_write(member: Member, message: ServerMessage) -> None:
        await member.conn.send_if_open(message)  # If they already disconnected, the lobby handles their leaving
