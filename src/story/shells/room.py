"""線上多人的房間：網頁伺服器裡唯一的一局多人遊戲。

每個瀏覽器分頁都是 textual-serve 啟動的一個獨立遊戲程序，這些程序透過 Unix socket 連到網頁伺服器裡的房間。
房間持有一份 PartyCore：把每位玩家的輸入交給核心，再把回覆送給每位玩家（各自看到自己的選項）。
API key 用伺服器的，玩家不用輸入。

流程：大廳（等人加入，房主按開始）→ 房主回答「繼續存檔／故事前提」→ 遊戲中（每個人各自行動，到齊才推進）
→ 結局 → 回到大廳。房主是第一位加入的人；房主離線時交給下一位在線的玩家。

訊息都是一行一個 JSON。
玩家 → 房間
  {"type": "join", "name": "阿明"}        第一則訊息
  {"type": "send", "text": "1"}           玩家的輸入：行動、指令，或房主回答對話框
                                          房主在前提對話框送的指令可以加 "answer": true，要求回傳結果
  {"type": "ready"}                       新劇情顯示完了（大家都顯示完才開始限時倒數）
房間 → 玩家
  {"type": "joined"} 或 {"type": "rejected", "reason": "..."}
  {"type": "lobby", "members": [...], "host": "阿明"}
  {"type": "reply", "reply": {...}}       核心的回覆（Reply.to_dict()，已換成這位玩家的選項）
  {"type": "premise", "reply": {...}}     前提對話框的指令（幫我想、換一個、換題材）的結果，只回給要求 answer 的房主
  {"type": "new_story", "premise": "..."}  新故事開始：清空畫面，先顯示故事前提
  {"type": "busy", "on": true, "progress": "規劃故事大綱"}   故事生成中（progress 變了會再送一次）
  {"type": "waiting", "names": [...]}     這回合還沒行動的人
  {"type": "timer", "seconds": 12}        開始限時倒數（時間到由房間送出 /timeout）
  {"type": "notice", "text": "..."}
"""

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace

from story.core import MAX_PLAYERS, PartyCore, Reply
from story.shells.players import SAVES_DIR, InvalidName, check_name

START = "開始遊戲"
OFFLINE_ACTION = "（暫時離開了，這回合沒有行動）"
READY_WAIT = 90  # 等大家看完劇情最多幾秒，超過就直接開始倒數
TIMEOUT_GRACE = 1  # 倒數結束後多等一下，抵銷網路延遲
LINE_LIMIT = 2**20
PROGRESS_POLL = 0.3  # 呼叫 AI 時每隔幾秒看一次進度


async def write(writer: asyncio.StreamWriter, message: dict) -> None:
    writer.write(json.dumps(message, ensure_ascii=False).encode() + b"\n")
    await writer.drain()


async def read(reader: asyncio.StreamReader) -> dict | None:
    """讀一則訊息；連線結束時回傳 None。"""
    try:
        line = await reader.readline()
    except (ConnectionError, ValueError):
        return None
    return json.loads(line) if line else None


class Member:
    def __init__(self, name: str, writer: asyncio.StreamWriter):
        self.name, self.writer = name, writer
        self.online = True


class Room:
    def __init__(self, make_core: Callable[[list[str]], PartyCore]):
        self.make_core = make_core
        self.members: dict[str, Member] = {}  # 依加入順序；遊戲中斷線的人會保留，可以重新連線
        self.host = ""
        self.core: PartyCore | None = None
        self.host_reply: Reply | None = None  # 正在等房主回答的畫面（存檔、前提、確認重來），換房主時重送
        self.lock = asyncio.Lock()  # 一次只處理一則輸入，核心不會被同時呼叫
        self.ready: set[str] = set()  # 已經看完這回合劇情的人
        self.countdown: asyncio.Task | None = None
        self.waiting_ready = False  # 倒數還沒開始，在等大家看完劇情
        self.deadline = 0.0  # 倒數結束的時間（loop.time()），給中途連線的人接著倒數
        self.time_limit = 0  # 這回合的限時秒數（從核心的回覆記下來）
        self.server: asyncio.AbstractServer | None = None

    @staticmethod
    def for_server(api_key: str) -> "Room":
        SAVES_DIR.mkdir(exist_ok=True)
        save_path, log_path = SAVES_DIR / "party.json", SAVES_DIR / "party.log.jsonl"
        return Room(lambda players: PartyCore(api_key, players, save_path=save_path, log_path=log_path))

    async def start(self, path: str) -> None:
        self.server = await asyncio.start_unix_server(self.serve, path=path, limit=LINE_LIMIT)

    async def stop(self) -> None:
        self._stop_countdown()
        if self.server:
            self.server.close()
            self.server.close_clients()  # 不然 wait_closed() 會等到每個玩家自己斷線
            await self.server.wait_closed()

    # ---------- 連線 ----------

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        name = None
        try:
            while name is None:  # 名字不能用時讓玩家換一個再試
                message = await read(reader)
                if not message or message.get("type") != "join":
                    return
                async with self.lock:
                    if error := self._join_error(message.get("name", "")):
                        await write(writer, {"type": "rejected", "reason": error})
                        continue
                    name = check_name(message["name"])
                    await self._join(name, writer)
            while message := await read(reader):
                async with self.lock:
                    await self._on_message(name, message)
        except ConnectionError:
            pass
        finally:
            if name:
                async with self.lock:
                    await self._leave(name)
            writer.close()

    def _join_error(self, raw: str) -> str:
        try:
            name = check_name(raw)
        except InvalidName as e:
            return str(e)
        member = self.members.get(name)
        if member and member.online:
            return "這個名字已經在房間裡了，請換一個名字。"
        if self.core is not None:
            if name not in self.core.players:
                return f"遊戲進行中，只有隊伍裡的玩家（{'、'.join(self.core.players)}）能重新加入。"
        elif len(self._online()) >= MAX_PLAYERS:
            return f"房間已滿（最多 {MAX_PLAYERS} 人）。"
        return ""

    async def _join(self, name: str, writer: asyncio.StreamWriter) -> None:
        self.members[name] = Member(name, writer)
        if not self.host or not self.members[self.host].online:
            self.host = name
        await write(writer, {"type": "joined"})
        if self.core is None:
            await self._broadcast_lobby()
            return
        await self._broadcast_notice(f"{name} 回來了。", skip=name)
        if self.core.phase == "playing":
            await self._send_reply(name, self.core.view(name))
            await self._broadcast_waiting()
            if self.countdown and not self.waiting_ready:
                left = round(self.deadline - asyncio.get_running_loop().time())
                if left > 0:
                    await write(writer, {"type": "timer", "seconds": left})
        elif name == self.host and self.host_reply:
            await self._send_reply(name, self.host_reply)
        else:
            await self._send_notice(name, "房主正在設定故事，請稍候。")

    async def _leave(self, name: str) -> None:
        if self.core is None:
            del self.members[name]
        else:
            self.members[name].online = False
            self.ready.discard(name)
        online = self._online()
        if name == self.host:
            self.host = online[0] if online else ""
        if self.core is None:
            await self._broadcast_lobby()
            return
        if not online:
            return
        await self._broadcast_notice(f"{name} 離線了。")
        if self.core.phase == "playing":
            await self._fill_offline()
            await self._maybe_start_countdown()
        elif name != self.host and self.host_reply:
            await self._send_reply(self.host, self.host_reply)  # 原本的房主離開了，交給新房主回答

    # ---------- 輸入 ----------

    async def _on_message(self, name: str, message: dict) -> None:
        kind = message.get("type")
        if kind == "ready":
            self.ready.add(name)
            await self._maybe_start_countdown()
        elif kind == "send":
            await self._on_send(name, str(message.get("text", "")).strip(), bool(message.get("answer")))

    async def _on_send(self, name: str, text: str, answer: bool = False) -> None:
        if self.core is None:
            await self._on_lobby(name, text)
        elif self.core.phase == "playing":
            await self._on_playing(name, text)
        elif name != self.host:
            await self._send_notice(name, f"等房主 {self.host} 設定好故事。")
        elif text.startswith(("/suggest", "/random", "/timed", "/genre")):  # 前提對話框裡的操作，不用推給其他人
            reply = await self._call(lambda: self.core.send(text))
            if answer:
                await write(self.members[name].writer, {"type": "premise", "reply": reply.to_dict()})
        else:
            starting = self.core.phase == "ask_premise" and not text.startswith("/")
            if starting:
                await self._broadcast({"type": "new_story", "premise": text})
            await self._route(await self._call(lambda: self.core.send(text), busy=starting))

    async def _on_lobby(self, name: str, text: str) -> None:
        if name != self.host:
            await self._send_notice(name, f"等房主 {self.host} 開始遊戲。")
            return
        players = self._online()
        if text not in ("1", START) or len(players) < 2:
            await self._send_notice(name, "至少要 2 位玩家才能開始。")
            return
        self.core = self.make_core(players)
        await self._route(self.core.start())

    async def _on_playing(self, name: str, text: str) -> None:
        if text == "/timeout":
            return  # 倒數由房間負責，玩家不能替大家按下時間到
        if text == "/restart" and name != self.host:
            await self._send_notice(name, "只有房主能重新開始。")
            return
        if text.startswith("/"):  # /state、/restart，或沒有這個指令：只回給本人
            reply = await self._call(lambda: self.core.send_as(name, text))
            await self._route(reply, only=name)
            return
        await self._act(name, text)

    async def _act(self, name: str, text: str) -> None:
        resolving = self.core.waiting() == [name]
        await self._route(await self._call(lambda: self.core.send_as(name, text), busy=resolving), only=name)
        await self._fill_offline()

    async def _fill_offline(self) -> None:
        """在線的人都行動了、只剩離線的人：替離線的人送出「暫時離開」，讓這回合可以推進。"""
        if self.core is None or self.core.phase != "playing" or not self._online():
            return
        waiting = self.core.waiting()
        if waiting and not any(self.members[n].online for n in waiting if n in self.members):
            await self._act(waiting[0], OFFLINE_ACTION)

    async def _call(self, fn: Callable[[], Reply], busy: bool = False) -> Reply:
        """在背景執行緒呼叫核心（可能會呼叫 AI，要花幾秒）。busy 時讓大家看到「故事生成中」。"""
        if busy:
            await self._broadcast({"type": "busy", "on": True, "progress": ""})
        try:
            task = asyncio.create_task(asyncio.to_thread(fn))
            progress = ""
            while busy and not task.done():  # 開新故事要呼叫兩次 AI：進度變了就告訴大家
                await asyncio.wait({task}, timeout=PROGRESS_POLL)
                if self.core and self.core.progress != progress and not task.done():
                    progress = self.core.progress
                    await self._broadcast({"type": "busy", "on": True, "progress": progress})
            reply = await task
        finally:
            if busy:
                await self._broadcast({"type": "busy", "on": False})
        if reply.error == "api_key":  # 玩家沒辦法換伺服器的 key
            reply = replace(reply, error="api", notice="伺服器的 Gemini API key 無效或沒有權限，請通知架站的人。")
        return reply

    # ---------- 回覆 ----------

    async def _route(self, reply: Reply, only: str = "") -> None:
        """把核心的回覆送給該收到的人。有新劇情時送給所有人，否則只送給 only（送出輸入的人）。"""
        phase = reply.phase
        if phase in ("ask_continue", "ask_premise", "confirm_restart"):
            self.host_reply = reply
            self._stop_countdown()
            await self._send_reply(self.host, reply)
            if phase != "confirm_restart":
                await self._broadcast_notice("房主正在設定故事，請稍候。", skip=self.host)
            return
        self.host_reply = None
        if phase == "playing" and reply.error:  # 這回合沒推進成功：核心撤回了所有人的行動，大家重新選擇
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
        elif phase == "ending":
            await self._route(await self._call(lambda: self.core.send(""), busy=True))  # 接著寫尾聲
        elif phase == "ended":
            self.core = None  # 回到大廳，同一批人可以再玩一次
            for name in [m.name for m in self.members.values() if not m.online]:
                del self.members[name]
            await self._broadcast_lobby()

    async def _send_reply(self, name: str, reply: Reply) -> None:
        member = self.members.get(name)
        if member and member.online:
            view = self.core.view(name, reply) if self.core else reply
            await self._safe_write(member, {"type": "reply", "reply": view.to_dict()})

    # ---------- 限時倒數：大家都看完劇情才開始，時間到由房間送出 /timeout ----------

    async def _maybe_start_countdown(self) -> None:
        if self.waiting_ready and self.ready >= set(self._online()):
            self.countdown.cancel()
            self.countdown = asyncio.create_task(self._countdown(self.time_limit, wait_first=False))

    async def _countdown(self, seconds: int, wait_first: bool) -> None:
        if wait_first:  # 等大家看完劇情（_maybe_start_countdown 會提早換成正式倒數）
            await asyncio.sleep(READY_WAIT)
        self.waiting_ready = False
        self.deadline = asyncio.get_running_loop().time() + seconds
        await self._broadcast({"type": "timer", "seconds": seconds})
        await asyncio.sleep(seconds + TIMEOUT_GRACE)
        async with self.lock:
            self.countdown = None
            if self.core and self.core.phase == "playing" and self.core.waiting():
                await self._route(await self._call(lambda: self.core.send("/timeout"), busy=True))

    def _stop_countdown(self) -> None:
        if self.countdown and self.countdown is not asyncio.current_task():
            self.countdown.cancel()
        self.countdown, self.waiting_ready = None, False

    # ---------- 廣播 ----------

    def _online_members(self) -> list[Member]:
        return [m for m in self.members.values() if m.online]

    def _online(self) -> list[str]:
        return [m.name for m in self._online_members()]

    async def _broadcast(self, message: dict, skip: str = "") -> None:
        for member in self._online_members():
            if member.name != skip:
                await self._safe_write(member, message)

    async def _broadcast_lobby(self) -> None:
        await self._broadcast({"type": "lobby", "members": self._online(), "host": self.host})

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
            await write(member.writer, message)
        except ConnectionError:
            pass  # 對方已經斷線，serve() 結束時會處理離開


class RoomConnection:
    """遊戲程序這一端：連到房間，收發訊息。"""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer

    @classmethod
    async def open(cls, path: str) -> "RoomConnection":
        return cls(*await asyncio.open_unix_connection(path, limit=LINE_LIMIT))

    async def send(self, message: dict) -> None:
        await write(self.writer, message)

    async def receive(self) -> dict | None:
        return await read(self.reader)

    def close(self) -> None:
        self.writer.close()
