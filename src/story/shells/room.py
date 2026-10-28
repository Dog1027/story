"""A web room: one room is one game (playing alone is a room with just you).

The lobby (lobby.py) creates and closes rooms and manages players' connections and names: it hands people entering this room to add(),
calls remove() when they leave or disconnect, and passes messages inside the room to handle().
The room holds one core (a game from story.games): it passes each player's input to the core, then sends the reply to every player (each sees their own choices).

The flow: waiting for players (the host picks a game) → the host answers "continue the save / what a new game asks" → playing (everyone acts on their own; the turn advances when all have)
→ the ending → back to the waiting screen. The host is the first person in; when the host leaves, the next person online takes over.

Messages are dicts that can be converted to JSON, sent over a Connection (connection.py).
Player → room
  {"type": "send", "text": "1"}           A player's input: an action, a command, or the host answering a dialog
  {"type": "send", "text": "/suggest", "form": true, "answer": true}
                                          Actions in the new game dialog (e.g. the adventure's suggest one, change genre) go only to the core,
                                          not pushed to anyone; with "answer": true, the result goes back to the host
  {"type": "ready"}                       New narration finished showing (the timed countdown starts once everyone's has)
Room → player
  {"type": "lobby", "view": "room", "title": "Ming's room", "host": "Ming", "you": "Hua", "members": [...], "seats": 4,
   "choices": [...], "hint": "...", "clear": true}
                                          The waiting screen: who's in the room (members, in the order they came in), the number of seats, the options, the input box hint
  {"type": "reply", "reply": {...}}       The core's reply (Reply.to_dict(), with this player's choices)
  {"type": "premise", "reply": {...}}     The result of a command while starting a new game, sent only to the host who asked with answer
  {"type": "new_story", "premise": "..."}  A new game starts: wipe the screen and show the premise first (answers to options aren't shown)
  {"type": "busy", "on": true, "progress": "planning the story outline"}   Writing the story (sent again when progress changes)
  {"type": "draft", "text": "..."}        The narration the AI is writing (the full text streamed so far, sent again when more arrives)
  {"type": "waiting", "names": [...]}     Who hasn't acted this turn
  {"type": "timer", "seconds": 12}        Start the timed countdown (the room sends /timeout when it runs out)
  {"type": "notice", "text": "..."}
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from story.core import MAX_PLAYERS, Game, Reply, pick_choice
from story.games import GAMES
from story.shells.connection import Connection
from story.shells.text import ui_text

UI = ui_text("shells")  # story/shells/ui/<lang>/shells.md
log = logging.getLogger(__name__)
TITLES = {code: game.title for code, game in GAMES.items()}  # Game code → name
STARTS = {UI["start_game"].format(game=title): code for code, title in TITLES.items()}  # The host picks the game on the waiting screen
LEAVE = UI["leave_room"]
READY_WAIT = 90  # Most seconds to wait for everyone to finish reading; after that the countdown starts anyway
TIMEOUT_GRACE = 1  # Wait a little after the countdown ends to make up for network lag


class Member:
    def __init__(self, name: str, conn: Connection):
        self.name, self.conn = name, conn
        self.online = True
        self.behind = False  # Came back while the core was busy: shown the current screen once it's done


class Room:
    def __init__(self, make_core: Callable[[list[str], Callable[[bool], None], str], Game], on_change: Callable[[], Awaitable[None]] | None = None):
        """make_core(players, on_queue, game) builds this game's core: game is a code from GAMES;
        on_queue(queued) lets the screen show "queued" while an AI call waits in line.
        on_change() is awaited after input that may change what the lobby shows (a game started, back to waiting)."""
        self.make_core = make_core
        self.on_change = on_change
        self.tasks: set[asyncio.Task] = set()  # Work in the background: input that uses the core (see handle()) and progress reports
        self.game = ""  # The name of this game (shown on the lobby's room card)
        self.members: dict[str, Member] = {}  # In the order they came in; people who disconnect mid-game are kept so they can reconnect
        self.host = ""
        self.core: Game | None = None
        self.host_reply: Reply | None = None  # The screen waiting for the host's answer (save, premise, confirm restart), resent when the host changes
        self.lock = asyncio.Lock()  # Held while using the core (see _using_core); messages that don't need the core never wait for it
        self.busy = False  # Everyone sees "writing the story" (a call made with busy=True is running)
        self.reported = ("", "")  # The progress and draft everyone was last told about during this call
        self.loop: asyncio.AbstractEventLoop | None = None  # For news from the thread running the core (see _changed)
        self.ready: set[str] = set()  # People who finished reading this turn's narration
        self.countdown: asyncio.Task | None = None
        self.waiting_ready = False  # The countdown hasn't started; waiting for everyone to finish reading
        self.deadline = 0.0  # When the countdown ends (loop.time()), so people who connect midway can pick it up
        self.time_limit = 0  # This turn's time limit in seconds (taken from the core's reply)
        self.queued = False  # An AI call is queued (all rooms share one key's call limit)

    # ---------- For the lobby ----------

    @property
    def online(self) -> list[str]:
        return [m.name for m in self._online_members()]

    @property
    def playing(self) -> bool:
        return self.core is not None

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

    async def add(self, name: str, conn: Connection) -> None:
        await self._join(name, conn)

    async def remove(self, name: str) -> None:
        await self._leave(name)

    async def handle(self, name: str, message: dict) -> None:
        """Input that uses the core is handled in the background: the AI can take tens of seconds, and meanwhile this player's
        connection keeps being read (so leaving is noticed at once). The core's lock takes them one at a time, in the order they came."""
        if message.get("type") == "send":
            self._spawn(self._on_send_message(name, message))
        else:
            await self._on_message(name, message)

    async def close(self) -> None:
        self._stop_countdown()
        for task in list(self.tasks):
            task.cancel()

    @asynccontextmanager
    async def _using_core(self):
        """Use the core, one at a time: it isn't thread-safe, and a call can take tens of seconds while the AI writes.
        Only code that touches the core goes through here, so leaving, disconnecting and "finished reading" never wait for the AI.
        On the way out, show people who came back meanwhile the current screen, and stand in for offline players if only they are left."""
        async with self.lock:
            yield
            for member in [m for m in self._online_members() if m.behind]:
                await self._catch_up(member.name)
            await self._fill_offline()

    # ---------- Coming and going ----------

    async def _join(self, name: str, conn: Connection) -> None:
        self.members[name] = Member(name, conn)
        if not self.host or not self.members[self.host].online:
            self.host = name
        if self.core is None:
            await self._broadcast_lobby(clear_for=name)
            return
        await self._broadcast_notice(UI["room_back"].format(name=name), skip=name)
        if self.lock.locked():  # The core is busy (e.g. the AI is writing): don't wait here; they're caught up once it's done
            self.members[name].behind = True
            if self.busy:
                await self._safe_write(self.members[name], {"type": "busy", "on": True, "progress": self._progress()})
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
            if self.countdown and not self.waiting_ready:
                left = round(self.deadline - asyncio.get_running_loop().time())
                if left > 0:
                    await member.conn.send({"type": "timer", "seconds": left})
        elif name == self.host and self.host_reply:
            await self._send_reply(name, self.host_reply)
        else:
            await self._send_notice(name, UI["host_setting_up"])

    async def _leave(self, name: str) -> None:
        if name not in self.members:
            return
        if self.core is None:
            del self.members[name]
        else:
            self.members[name].online = False
            self.ready.discard(name)
        online = self.online
        if name == self.host:
            self.host = online[0] if online else ""
        if not online:
            return
        if self.core is None:
            await self._broadcast_lobby()
            return
        await self._broadcast_notice(UI["room_left"].format(name=name))
        if self.host_reply and name != self.host:
            await self._send_reply(self.host, self.host_reply)  # The old host left, so the new host answers
        await self._maybe_start_countdown()  # They might have been the last one still reading
        if not self.lock.locked():  # If the core is busy, whoever is using it stands in for them on the way out
            async with self._using_core():
                pass  # Leaving _using_core stands in for offline players if only they are left

    # ---------- Input ----------

    async def _on_message(self, name: str, message: dict) -> None:
        kind = message.get("type")
        if kind == "ready":
            self.ready.add(name)
            await self._maybe_start_countdown()

    async def _on_send_message(self, name: str, message: dict) -> None:
        text = str(message.get("text", "")).strip()
        async with self._using_core():
            try:
                await self._on_send(name, text, form=bool(message.get("form")), answer=bool(message.get("answer")))
            except Exception:
                await self._recover(name, message)
        if self.on_change:
            await self.on_change()

    async def _on_send(self, name: str, text: str, form: bool = False, answer: bool = False) -> None:
        if self.core is None:
            await self._on_lobby(name, text)
        elif self.core.phase == "playing":
            await self._on_playing(name, text)
        elif name != self.host and self.core.phase != "ending":  # Anyone may retry an ending that failed to wrap up
            await self._send_notice(name, UI["wait_host_story"].format(host=self.host))
        elif form and self.core.phase == "setup":  # Actions in the new game dialog, not pushed to anyone else
            reply = await self._call(lambda: self.core.send(text))
            if answer:
                await self._safe_write(self.members[name], {"type": "premise", "reply": reply.to_dict()})
        else:
            starting = self.core.phase == "setup"  # Starting a game: calls the AI
            if starting:  # A written premise is shown to everyone first; answers to options (turtle soup's puzzle source) aren't, and the scenario waits until the puzzle is drawn
                premise = "" if self.host_reply and self.host_reply.choices else text
                await self._broadcast({"type": "new_story", "premise": premise})
            await self._route(await self._call(lambda: self.core.send(text), busy=starting))

    async def _on_lobby(self, name: str, text: str) -> None:
        if name != self.host:
            await self._send_notice(name, UI["wait_host_start"].format(host=self.host))
            return
        game = STARTS.get(pick_choice(text, self._lobby_choices(name)) or "")
        if game is None:
            return
        self.loop = asyncio.get_running_loop()
        self.game, self.core = TITLES[game], self.make_core(self.online, self._set_queued, game)
        self.core.watch(self._changed)
        await self._route(self.core.start())

    def _progress(self) -> str:
        """What the waiting screen says: queued for the shared call limit, or what the core is doing."""
        return UI["queued"] if self.queued else (self.core.progress if self.core else "")

    def _set_queued(self, queued: bool) -> None:
        self.queued = queued
        self._changed()

    def _changed(self) -> None:
        """Called from the thread running the core when its progress or draft changes, or an AI call starts or stops queuing:
        hand it to the event loop, which tells everyone (_report)."""
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self._spawn, self._report())

    def _spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _report(self) -> None:
        """Tell everyone the progress (a new story calls the AI several times) and the narration so far, if they changed."""
        if not self.busy or self.core is None:
            return  # Only while everyone sees "writing the story"; news arriving after the call ended is dropped
        progress, draft = self._progress(), self.core.draft
        if progress != self.reported[0]:
            await self._broadcast({"type": "busy", "on": True, "progress": progress})
        if draft and draft != self.reported[1]:
            await self._broadcast({"type": "draft", "text": draft})
        self.reported = (progress, draft or self.reported[1])

    async def _on_playing(self, name: str, text: str) -> None:
        if text == "/timeout":
            return  # The room runs the countdown; players can't call time for everyone
        if text == "/restart" and name != self.host:
            await self._send_notice(name, UI["host_only_restart"])
            return
        if text.startswith("/"):  # /state, /restart, or an unknown command: reply only to the sender
            reply = await self._call(lambda: self.core.send_as(name, text))
            await self._route(reply, only=name)
            return
        await self._act(name, text)

    async def _act(self, name: str, text: str) -> None:
        resolving = self.core.waiting() == [name]
        await self._route(await self._call(lambda: self.core.send_as(name, text), busy=resolving), only=name)
        await self._fill_offline()

    async def _fill_offline(self) -> None:
        """Everyone online has acted and only offline people are left: send "away" for them so the turn can advance."""
        if self.core is None or self.core.phase != "playing" or not self.online:
            return
        waiting = self.core.waiting()
        if waiting and not any(self.members[n].online for n in waiting if n in self.members):
            await self._act(waiting[0], "/away")  # The core decides the text for the AI

    async def _call(self, fn: Callable[[], Reply], busy: bool = False) -> Reply:
        """Call the core in a background thread (it may call the AI and take a few seconds). With busy, everyone sees "writing the story"."""
        if busy:
            self.busy, self.reported = True, ("", "")
            await self._broadcast({"type": "busy", "on": True, "progress": ""})
        try:
            reply = await asyncio.to_thread(fn)  # Progress and narration so far arrive through _changed() meanwhile
        finally:
            if busy:
                self.busy = False
                await self._broadcast({"type": "busy", "on": False})
        return reply

    # ---------- Replies ----------

    async def _route(self, reply: Reply, only: str = "") -> None:
        """Send the core's reply to whoever should get it: everyone when there's new narration, otherwise only `only` (the sender)."""
        phase = reply.phase
        if phase in ("ask_continue", "setup", "confirm_restart"):
            self.host_reply = reply
            self._stop_countdown()
            await self._send_reply(self.host, reply)
            if phase != "confirm_restart":
                await self._broadcast_notice(UI["host_setting_up"], skip=self.host)
            return
        self.host_reply = None
        if phase == "playing" and reply.error:  # The turn didn't advance: the core took back everyone's actions, and everyone chooses again
            for member in self._online_members():
                await self._send_reply(member.name, reply)
            await self._broadcast_waiting()
            self._stop_countdown()
            if reply.time_limit:
                self.countdown = asyncio.create_task(self._countdown(reply.time_limit, wait_first=False))
            return
        if phase == "playing" and not reply.narration:
            if only:
                await self._send_reply(only, reply)
            await self._broadcast_waiting()
            return
        self._stop_countdown()
        for member in self._online_members():
            await self._send_reply(member.name, reply)
        if phase == "playing":
            await self._broadcast_waiting()
            if reply.time_limit:
                self.ready, self.waiting_ready, self.time_limit = set(), True, reply.time_limit
                self.countdown = asyncio.create_task(self._countdown(reply.time_limit, wait_first=True))
        elif phase == "ending" and not reply.error:
            # Go on to write the epilogue. If wrapping up the ending failed, don't go round again on our own: the same error would repeat
            # endlessly (and an epilogue that fails calls the AI every time); anyone can send something to try again
            await self._route(await self._call(lambda: self.core.send(""), busy=True))
        elif phase == "ended":
            self.core = None  # Back to the waiting screen; the same people can play again
            for name in [m.name for m in self.members.values() if not m.online]:
                del self.members[name]
            await self._broadcast_lobby()

    async def _send_reply(self, name: str, reply: Reply) -> None:
        member = self.members.get(name)
        if member and member.online and not member.behind:  # Someone catching up gets the whole current screen instead (_catch_up)
            view = self.core.view(name, reply) if self.core else reply
            await self._safe_write(member, {"type": "reply", "reply": view.to_dict()})

    # ---------- Timed countdown: starts once everyone has read the narration; the room sends /timeout when it runs out ----------

    async def _maybe_start_countdown(self) -> None:
        if self.waiting_ready and self.ready >= set(self.online):
            self.countdown.cancel()
            self.countdown = asyncio.create_task(self._countdown(self.time_limit, wait_first=False))

    async def _countdown(self, seconds: int, wait_first: bool) -> None:
        if wait_first:  # Waiting for everyone to finish reading (_maybe_start_countdown switches to the real countdown early)
            await asyncio.sleep(READY_WAIT)
        self.waiting_ready = False
        self.deadline = asyncio.get_running_loop().time() + seconds
        await self._broadcast({"type": "timer", "seconds": seconds})
        await asyncio.sleep(seconds + TIMEOUT_GRACE)
        async with self._using_core():
            self.countdown = None
            try:
                if self.core and self.core.phase == "playing" and self.core.waiting():
                    await self._route(await self._call(lambda: self.core.send("/timeout"), busy=True))
            except Exception:
                await self._recover("", {"type": "timeout"})

    async def _recover(self, name: str, message: dict) -> None:
        """The last line of defence: something nobody expected failed while handling a message (the core already turns its own errors into replies).
        Log the details, tell people, and put everyone's current screen back, keeping the room and the connections."""
        log.exception("unexpected error in %s's room handling %r from %r", self.host, message, name)
        try:
            for member in self._online_members():
                await self._send_notice(member.name, UI["room_error"])
                if self.core is not None and self.core.phase == "playing":
                    await self._send_reply(member.name, self.core.view(member.name))
            await self._broadcast_waiting()
            if message.get("answer") and name in self.members:  # The premise dialog is waiting for this answer: give it one, or it waits forever
                failed = Reply(phase=self.core.phase if self.core else "setup", error="api", notice=UI["room_error"])
                await self._safe_write(self.members[name], {"type": "premise", "reply": failed.to_dict()})
            elif self.host_reply and not message.get("form") and self.core is not None and self.core.phase == self.host_reply.phase:
                await self._send_reply(self.host, self.host_reply)  # The host's dialog closed when they answered: show it again so they can answer again
        except Exception:
            log.exception("could not restore the screens after the error")

    def _stop_countdown(self) -> None:
        if self.countdown and self.countdown is not asyncio.current_task():
            self.countdown.cancel()
        self.countdown, self.waiting_ready = None, False

    # ---------- Broadcasting ----------

    def _online_members(self) -> list[Member]:
        return [m for m in self.members.values() if m.online]

    async def _broadcast(self, message: dict, skip: str = "") -> None:
        for member in self._online_members():
            if member.name != skip:
                await self._safe_write(member, message)

    def _lobby_choices(self, name: str) -> list[str]:
        return [*STARTS, LEAVE] if name == self.host else [LEAVE]

    async def _broadcast_lobby(self, clear_for: str = "") -> None:
        """The waiting screen: who's in the room; the host can start and everyone can leave. clear_for is someone who just came in, whose screen is wiped first."""
        for member in self._online_members():
            host = member.name == self.host
            await self._safe_write(member, {
                "type": "lobby",
                "view": "room",
                "title": UI["room_title"].format(host=self.host),
                "host": self.host,
                "you": member.name,
                "members": self.online,
                "seats": MAX_PLAYERS,
                "choices": self._lobby_choices(member.name),
                "hint": UI["room_hint_host"] if host else UI["lobby_waiting_host"].format(host=self.host),
                "clear": member.name == clear_for,
            })

    async def _broadcast_waiting(self) -> None:
        if self.core and self.core.phase == "playing":
            await self._broadcast({"type": "waiting", "names": self.core.waiting()})

    async def _broadcast_notice(self, text: str, skip: str = "") -> None:
        await self._broadcast({"type": "notice", "text": text}, skip=skip)

    async def _send_notice(self, name: str, text: str) -> None:
        await self._safe_write(self.members[name], {"type": "notice", "text": text})

    @staticmethod
    async def _safe_write(member: Member, message: dict) -> None:
        try:
            await member.conn.send(message)
        except ConnectionError:
            pass  # They already disconnected; the lobby handles their leaving
