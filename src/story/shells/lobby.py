"""網頁版的大廳：整台伺服器只有一個大廳，裡面有好幾個房間（room.py），每個房間各自玩一局。

每個瀏覽器分頁的共用層 Client 用 connect() 連進大廳，拿到一端 Connection。先輸入名字（整台伺服器不重複），
接著在大廳看到房間列表：開一個新房間，或加入等人中的房間。一個人玩就是開一個只有自己的房間。
進了房間之後，訊息交給那個房間處理；離開房間（/leave，或在等人的畫面選「離開房間」）回到大廳。
遊戲中斷線的人，用同一個名字回來時直接回到原本的房間。房間裡沒有人在線就關閉（存檔還在，同一組人再開房間可以接著玩）。

所有房間共用架站者的 API key，呼叫 AI 受同一個次數限制（RateLimit），超過的排隊。

訊息是可以轉成 JSON 的 dict。
玩家 → 大廳
  {"type": "join", "name": "阿明"}        第一則訊息
  {"type": "send", "text": "1"}           在大廳：選房間；在房間裡：交給房間（見 room.py）
  其他訊息在房間裡時交給房間
大廳 → 玩家
  {"type": "joined"} 或 {"type": "rejected", "reason": "..."}
  {"type": "lobby", "title": "大廳", "members": [...], "choices": [...], "hint": "...", "clear": true}
      大廳或房間的等人畫面：標題、在這裡的人、可以選的、輸入框的提示；clear 時先清空畫面（剛進來或剛離開房間）
  {"type": "notice", "text": "..."}
  其他訊息見 room.py
"""

import asyncio
from collections.abc import Callable

from story.core import MAX_PLAYERS, StoryCore, RateLimit, new_client, pick_choice, ui_text
from story.shells.players import SAVES_DIR, InvalidName, check_name
from story.shells.connection import Connection
from story.shells.room import Room

UI = ui_text("shells")  # story/ui/語言/shells.md
MAX_ROOMS = 10  # 同時最多幾個房間：大家共用一把 key，房間太多就會一直排隊
AI_PER_MINUTE = 15  # 所有房間加起來，每分鐘最多呼叫幾次 AI（免費方案 flash-lite 的上限；付費方案可以調高）


def team_save(players: list[str]):
    """一組人的存檔與紀錄：同一組人（不管順序）再開房間時可以接著玩。名字只有文字、數字、底線、連字號，可以直接當檔名。"""
    team = "+".join(sorted(players))
    return SAVES_DIR / f"team-{team}.json", SAVES_DIR / f"team-{team}.log.jsonl"


class Lobby:
    def __init__(self, make_core: Callable[[list[str], Callable[[bool], None]], StoryCore]):
        """make_core(玩家, on_queue) 建立一局的核心，見 Room。"""
        self.make_core = make_core
        self.people: dict[str, Connection] = {}  # 在線的人（大廳這一端的連線）
        self.where: dict[str, Room | None] = {}  # 每個人在哪個房間；None 是在大廳
        self.rooms: list[Room] = []  # 依開房的順序
        self.options: dict[str, list[Room | None]] = {}  # 每個人在大廳看到的選項：None 是「開新房間」
        self.shown: dict[str, dict] = {}  # 每個人最後收到的大廳畫面（沒變就不重送）
        self.lock = asyncio.Lock()  # 大廳的進出一次處理一件
        self.links: dict[Connection, asyncio.Task] = {}

    @staticmethod
    def for_server(api_key: str) -> "Lobby":
        """網頁伺服器用：每個房間的核心都用架站者的 key，共用同一個次數限制。"""
        SAVES_DIR.mkdir(exist_ok=True)
        limit, client = RateLimit(AI_PER_MINUTE), new_client(api_key)

        def make_core(players: list[str], on_queue: Callable[[bool], None]) -> StoryCore:
            save_path, log_path = team_save(players)
            return StoryCore(api_key, players, save_path=save_path, log_path=log_path, client=limit.wrap(client, on_queue))

        return Lobby(make_core)

    def connect(self) -> Connection:
        """一位玩家連進來：回傳玩家那一端，大廳這一端交給 serve() 處理。"""
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

    # ---------- 連線 ----------

    async def serve(self, conn: Connection) -> None:
        name = None
        try:
            while name is None:  # 名字不能用時讓玩家換一個再試
                message = await conn.receive()
                if not message or message.get("type") != "join":
                    return
                async with self.lock:
                    if error := self._name_error(message.get("name", "")):
                        await conn.send({"type": "rejected", "reason": error})
                        continue
                    name = check_name(message["name"])
                    self.people[name], self.where[name] = conn, None
                    await conn.send({"type": "joined"})
                    back = next((r for r in self.rooms if r.playing and name in r.members), None)
                if back:  # 遊戲中斷線的人回來了：直接回到原本的房間
                    await self._enter(name, back)
                else:
                    await self._show_rooms(clear_for=name)
            while message := await conn.receive():
                await self._on_message(name, message)
        except ConnectionError:
            pass
        finally:
            if name:
                await self._leave_room(name, back_to_lobby=False)
                async with self.lock:
                    del self.people[name], self.where[name]
                    self.options.pop(name, None)
                    self.shown.pop(name, None)
                await self._show_rooms()
            conn.close()
            self.links.pop(conn, None)

    def _name_error(self, raw: str) -> str:
        try:
            name = check_name(raw)
        except InvalidName as e:
            return str(e)
        return UI["room_name_taken"] if name in self.people else ""

    # ---------- 輸入 ----------

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
            await self._show_rooms()  # 房間的狀態可能變了（開始遊戲、回到等人）

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

    # ---------- 進出房間 ----------

    async def _enter(self, name: str, room: Room) -> None:
        if room not in self.rooms:
            await self._notice(name, UI["room_gone"])
            await self._show_rooms()
            return
        if error := room.entry_error(name):
            await self._notice(name, error)
            return
        self.where[name] = room
        self.shown.pop(name, None)  # 回到大廳時要重送
        await room.add(name, self.people[name])
        await self._show_rooms()

    async def _leave_room(self, name: str, back_to_lobby: bool = True) -> None:
        room = self.where.get(name)
        if room is None:
            return
        self.where[name] = None
        await room.remove(name)
        if not room.online:  # 沒有人在線了：關閉（存檔還在，同一組人再開房間可以接著玩）
            await room.close()
            self.rooms.remove(room)
        if back_to_lobby:
            await self._show_rooms(clear_for=name)
        else:
            await self._show_rooms()

    # ---------- 大廳的畫面 ----------

    def _labels(self, options: list[Room | None]) -> list[str]:
        labels = []
        for room in options:
            if room is None:
                labels.append(UI["room_create"])
            else:
                labels.append(UI["room_entry"].format(host=room.host, count=len(room.online), max=MAX_PLAYERS))
        return labels

    async def _show_rooms(self, clear_for: str = "") -> None:
        """把房間列表送給在大廳的人：開新房間，以及還在等人、還沒滿的房間。內容沒變就不重送，畫面才不會一直閃。"""
        joinable = [r for r in self.rooms if not r.playing and len(r.online) < MAX_PLAYERS]
        in_lobby = [n for n, room in self.where.items() if room is None]
        busy = len(self.rooms) - len(joinable)
        hint = UI["rooms_hint"] + (UI["rooms_busy"].format(count=busy) if busy else "")
        for name in in_lobby:
            self.options[name] = [None, *joinable]
            screen = {"type": "lobby", "title": UI["lobby_title"], "members": in_lobby, "choices": self._labels(self.options[name]), "hint": hint}
            if self.shown.get(name) == screen and name != clear_for:
                continue
            self.shown[name] = screen
            await self._send(name, screen | {"clear": name == clear_for})

    async def _notice(self, name: str, text: str) -> None:
        await self._send(name, {"type": "notice", "text": text})

    async def _send(self, name: str, message: dict) -> None:
        try:
            await self.people[name].send(message)
        except (ConnectionError, KeyError):
            pass  # 對方已經斷線，serve() 結束時會處理
