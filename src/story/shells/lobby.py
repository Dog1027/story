"""The web lobby: the whole server has one lobby holding several rooms (room.py), each playing its own game.

Each browser tab's shared-layer Client connects with connect() and gets one end of a Connection. First it enters a name (unique on the whole server),
then sees the room list in the lobby: open a new room or join one that's waiting for players. Playing alone means opening a room with just you.
Inside a room, messages go to that room; leaving (/leave, or choosing "Leave room" on the waiting screen) goes back to the lobby.
Someone who disconnected mid-game goes straight back to their room when they return with the same name.
When the same browser connects again with the same name and token (a reload, or a phone coming back before the old connection dropped), the new connection replaces the old one
and takes the same seat without waiting for the old one to drop; anyone with a different token is still refused that name. A room closes when no one in it is online (the save stays, so the same people can continue in a new room).

Every room shares the host's API key, and AI calls are under one shared limit (RateLimit); calls over it queue.

Messages are dicts that can be converted to JSON.
Player → lobby
  {"type": "join", "name": "Ming", "token": "..."}   The first message; token is an ID the browser remembers (may be empty)
  {"type": "send", "text": "1"}           In the lobby: pick a room; in a room: passed to the room (see room.py)
  Other messages go to the room while in one
Lobby → player
  {"type": "joined"} or {"type": "rejected", "reason": "..."}
  {"type": "replaced"}                    The same browser (same name, same token) came in from another tab or reconnected: this connection is replaced and will close
  {"type": "lobby", "view": "lobby", "title": "Lobby", "you": "Ming", "choices": [...], "hint": "...", "clear": true,
   "rooms": [{"title": "Hua's room", "host": "Hua", "members": [...], "state": "open", "game": "", "choice": "2"}, ...],
   "people": [{"name": "Ming", "room": "", "playing": false}, ...], "max_rooms": 10, "seats": 4}
      The lobby screen: every room (state is open: waiting for players, full, or playing; game is the name of the game being played;
      choice is the option to send to join it, empty if it can't be joined),
      everyone online and where they are (room is the host's name, empty in the lobby), the options, and the input box hint; with clear, wipe the screen first (just arrived or just left a room)
      A room's waiting screen is also "type": "lobby", with "view": "room"; see room.py
  {"type": "notice", "text": "..."}
  Other messages: see room.py
"""

import asyncio
from collections.abc import Callable

from story.core import MAX_PLAYERS, Game, RateLimit, new_client, pick_choice
from story.games import GAMES
from story.shells.text import ui_text
from story.shells.players import SAVES_DIR, InvalidName, check_name
from story.shells.connection import Connection
from story.shells.room import Room

UI = ui_text("shells")  # story/shells/ui/<lang>/shells.md
MAX_ROOMS = 10  # Most rooms at once: everyone shares one key, and too many rooms means constant queuing
AI_PER_MINUTE = 15  # Most AI calls per minute across all rooms (the free tier's flash-lite limit; raise it on a paid plan)


def team_save(players: list[str], game: str):
    """A team's save and log: the same people (in any order) can continue when they open a room again. One per game, with the game's code at the end of the file name.
    Names only have letters, digits, underscores and hyphens, so they work as file names directly."""
    team = "+".join(sorted(players)) + f".{game}"
    return SAVES_DIR / f"team-{team}.json", SAVES_DIR / f"team-{team}.log.jsonl"


class Lobby:
    def __init__(self, make_core: Callable[[list[str], Callable[[bool], None], str], Game]):
        """make_core(players, on_queue, game) builds a game's core; see Room."""
        self.make_core = make_core
        self.people: dict[str, Connection] = {}  # People online (the lobby's end of each connection)
        self.where: dict[str, Room | None] = {}  # Which room each person is in; None is the lobby
        self.tokens: dict[str, str] = {}  # Each person's browser ID: the same browser connecting again replaces the old connection
        self.rooms: list[Room] = []  # In the order they were opened
        self.options: dict[str, list[Room | None]] = {}  # The options each person sees in the lobby: None is "open a new room"
        self.shown: dict[str, dict] = {}  # The last lobby screen each person got (not resent if unchanged)
        self.lock = asyncio.Lock()  # Handle comings and goings one at a time
        self.links: dict[Connection, asyncio.Task] = {}

    @staticmethod
    def for_server(api_key: str) -> "Lobby":
        """For the web server: every room's core uses the host's key and shares one call limit."""
        SAVES_DIR.mkdir(exist_ok=True)
        limit, client = RateLimit(AI_PER_MINUTE), new_client(api_key)

        def make_core(players: list[str], on_queue: Callable[[bool], None], game: str) -> Game:
            save_path, log_path = team_save(players, game)
            return GAMES[game](api_key, players, save_path=save_path, log_path=log_path, client=limit.wrap(client, on_queue))

        return Lobby(make_core)

    def connect(self) -> Connection:
        """A player connects: returns the player's end; the lobby's end is handled by serve()."""
        player_end, lobby_end = Connection.pair()
        self.links[lobby_end] = asyncio.create_task(self.serve(lobby_end))
        return player_end

    async def stop(self) -> None:
        for room in self.rooms:
            await room.close()
        for conn, task in list(self.links.items()):
            conn.close()
            task.cancel()
        await asyncio.gather(*self.links.values(), return_exceptions=True)

    # ---------- Connections ----------

    async def serve(self, conn: Connection) -> None:
        name = None
        try:
            while name is None:  # If the name can't be used, let the player try another
                message = await conn.receive()
                if not message or message.get("type") != "join":
                    return
                raw, token = message.get("name", ""), str(message.get("token", ""))[:64]
                async with self.lock:
                    old = self._same_browser(raw, token)
                    if old is None and (error := self._name_error(raw)):
                        await conn.send({"type": "rejected", "reason": error})
                        continue
                    name = check_name(raw)
                    if old is not None:  # Replace the old connection: take the same seat without leaving, so the room doesn't close for being empty
                        await self._send_to(old, {"type": "replaced"})
                        old.close()
                    else:
                        self.where[name] = None
                    self.people[name], self.tokens[name] = conn, token
                    await conn.send({"type": "joined"})
                    room = self.where[name]
                    back = room or next((r for r in self.rooms if r.playing and name in r.members), None)
                if room is not None:
                    self.shown.pop(name, None)
                    await room.add(name, conn)
                elif back:  # Someone who disconnected mid-game is back: straight to their room
                    await self._enter(name, back)
                else:
                    await self._show_rooms(clear_for=name)
            while message := await conn.receive():
                await self._on_message(name, message)
        except ConnectionError:
            pass
        finally:
            if name and self.people.get(name) is conn:  # Replaced by a new connection: nothing to clean up, the seat already belongs to it
                await self._leave_room(name, back_to_lobby=False)
                async with self.lock:
                    del self.people[name], self.where[name], self.tokens[name]
                    self.options.pop(name, None)
                    self.shown.pop(name, None)
                await self._show_rooms()
            conn.close()
            self.links.pop(conn, None)

    def _same_browser(self, raw: str, token: str) -> Connection | None:
        """Someone with the same name and token is already online: return their old connection (to be replaced)."""
        try:
            name = check_name(raw)
        except InvalidName:
            return None
        if token and name in self.people and self.tokens.get(name) == token:
            return self.people[name]
        return None

    def _name_error(self, raw: str) -> str:
        try:
            name = check_name(raw)
        except InvalidName as e:
            return str(e)
        return UI["room_name_taken"] if name in self.people else ""

    # ---------- Input ----------

    async def _on_message(self, name: str, message: dict) -> None:
        room = self.where.get(name)
        text = str(message.get("text", "")).strip()
        if room is None:
            if message.get("type") == "send":
                await self._choose(name, text)
        elif message.get("type") == "send" and room.is_leaving(name, text):
            await self._leave_room(name)
        else:
            await room.handle(name, message)
            await self._show_rooms()  # The room's state may have changed (a game started, back to waiting)

    async def _choose(self, name: str, text: str) -> None:
        options = self.options.get(name, [])
        labels = self._labels(options)
        picked = pick_choice(text, labels)
        if picked is None:
            await self._notice(name, UI["rooms_hint"])
            return
        room = options[labels.index(picked)]
        if room is None:
            async with self.lock:
                if len(self.rooms) >= MAX_ROOMS:
                    await self._notice(name, UI["rooms_full"].format(max=MAX_ROOMS))
                    return
                room = Room(self.make_core)
                self.rooms.append(room)
        await self._enter(name, room)

    # ---------- Entering and leaving rooms ----------

    async def _enter(self, name: str, room: Room) -> None:
        if room not in self.rooms:
            await self._notice(name, UI["room_gone"])
            await self._show_rooms()
            return
        if error := room.entry_error(name):
            await self._notice(name, error)
            return
        self.where[name] = room
        self.shown.pop(name, None)  # Must be resent when they come back to the lobby
        await room.add(name, self.people[name])
        await self._show_rooms()

    async def _leave_room(self, name: str, back_to_lobby: bool = True) -> None:
        room = self.where.get(name)
        if room is None:
            return
        self.where[name] = None
        await room.remove(name)
        if not room.online:  # No one online: close it (the save stays, so the same people can continue in a new room)
            await room.close()
            self.rooms.remove(room)
        if back_to_lobby:
            await self._show_rooms(clear_for=name)
        else:
            await self._show_rooms()

    # ---------- The lobby screen ----------

    def _labels(self, options: list[Room | None]) -> list[str]:
        labels = []
        for room in options:
            if room is None:
                labels.append(UI["room_create"])
            else:
                labels.append(UI["room_entry"].format(host=room.host, count=len(room.online), max=MAX_PLAYERS))
        return labels

    def _room_card(self, room: Room, choice: str) -> dict:
        state = "playing" if room.playing else "full" if len(room.online) >= MAX_PLAYERS else "open"
        return {
            "title": UI["room_title"].format(host=room.host), "host": room.host, "members": room.online,
            "state": state, "game": room.game if room.playing else "", "choice": choice,
        }

    async def _show_rooms(self, clear_for: str = "") -> None:
        """Send the lobby screen to everyone in the lobby: every room (only those waiting and not full can be joined) and everyone online. Not resent if unchanged, so the screen doesn't flicker."""
        joinable = [r for r in self.rooms if not r.playing and len(r.online) < MAX_PLAYERS]
        in_lobby = [n for n, room in self.where.items() if room is None]
        options = [None, *joinable]  # Option 1 opens a new room; the rest are rooms that can be joined
        rooms = [self._room_card(r, str(options.index(r) + 1) if r in joinable else "") for r in self.rooms]
        people = [{"name": n, "room": room.host if room else "", "playing": bool(room and room.playing)} for n, room in self.where.items()]
        for name in in_lobby:
            self.options[name] = options
            screen = {
                "type": "lobby", "view": "lobby", "title": UI["lobby_title"], "you": name,
                "choices": self._labels(options), "hint": UI["rooms_hint"],
                "rooms": rooms, "people": people, "max_rooms": MAX_ROOMS, "seats": MAX_PLAYERS,
            }
            if self.shown.get(name) == screen and name != clear_for:
                continue
            self.shown[name] = screen
            await self._send(name, screen | {"clear": name == clear_for})

    async def _notice(self, name: str, text: str) -> None:
        await self._send(name, {"type": "notice", "text": text})

    async def _send(self, name: str, message: dict) -> None:
        if name in self.people:
            await self._send_to(self.people[name], message)

    @staticmethod
    async def _send_to(conn: Connection, message: dict) -> None:
        try:
            await conn.send(message)
        except ConnectionError:
            pass  # They already disconnected; handled when serve() ends
