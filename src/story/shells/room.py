"""網頁版的房間：一個房間就是一局遊戲（一個人玩也是一個只有自己的房間）。

房間由大廳（lobby.py）建立與關閉；玩家的連線、名字也由大廳管理，大廳把進到這個房間的人交給 add()，
離開或斷線時呼叫 remove()，房間裡的訊息交給 handle()。
房間持有一份 PartyCore：把每位玩家的輸入交給核心，再把回覆送給每位玩家（各自看到自己的選項）。

流程：等人（房主按開始）→ 房主回答「繼續存檔／故事前提」→ 遊戲中（每個人各自行動，到齊才推進）
→ 結局 → 回到等人的畫面。房主是第一位進來的人；房主離開時交給下一位在線的人。

訊息是可以轉成 JSON 的 dict，經過 Connection 傳送。
玩家 → 房間
  {"type": "send", "text": "1"}           玩家的輸入：行動、指令，或房主回答對話框
                                          房主在前提對話框送的指令可以加 "answer": true，要求回傳結果
  {"type": "ready"}                       新劇情顯示完了（大家都顯示完才開始限時倒數）
房間 → 玩家
  {"type": "lobby", ...}                  等人的畫面：見 lobby.py 的說明（title、members、choices、hint）
  {"type": "reply", "reply": {...}}       核心的回覆（Reply.to_dict()，已換成這位玩家的選項）
  {"type": "premise", "reply": {...}}     前提對話框的指令（幫我想、換一個、換題材）的結果，只回給要求 answer 的房主
  {"type": "new_story", "premise": "..."}  新故事開始：清空畫面，先顯示故事前提
  {"type": "busy", "on": true, "progress": "規劃故事大綱"}   故事生成中（progress 變了會再送一次）
  {"type": "draft", "text": "..."}        AI 正在寫的劇情（串流中目前收到的全文，有新的字就再送一次）
  {"type": "waiting", "names": [...]}     這回合還沒行動的人
  {"type": "timer", "seconds": 12}        開始限時倒數（時間到由房間送出 /timeout）
  {"type": "notice", "text": "..."}
"""

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace

from story.core import MAX_PLAYERS, PartyCore, Reply, pick_choice, ui_text

UI = ui_text("shells")  # story/ui/語言/shells.md
START, LEAVE = UI["start_game"], UI["leave_room"]  # 等人的畫面裡的選項
READY_WAIT = 90  # 等大家看完劇情最多幾秒，超過就直接開始倒數
TIMEOUT_GRACE = 1  # 倒數結束後多等一下，抵銷網路延遲
PROGRESS_POLL = 0.1  # 呼叫 AI 時每隔幾秒看一次進度與 AI 寫到哪裡


class Connection:
    """玩家與伺服器之間連線的一端：send() 的訊息由另一端的 receive() 收到。
    任一端 close() 之後，另一端的 receive() 回傳 None，再 send() 會丟出 ConnectionError。"""

    def __init__(self, inbox: asyncio.Queue, outbox: asyncio.Queue):
        self.inbox, self.outbox = inbox, outbox
        self.peer: Connection | None = None
        self.closed = False

    @staticmethod
    def pair() -> tuple["Connection", "Connection"]:
        a, b = asyncio.Queue(), asyncio.Queue()
        one, other = Connection(a, b), Connection(b, a)
        one.peer, other.peer = other, one
        return one, other

    async def send(self, message: dict) -> None:
        if self.closed or self.peer.closed:
            raise ConnectionError("connection closed")
        # 轉成 JSON 再轉回來：兩端不會共用同一個物件，收到的只有 JSON 的型別（tuple 變成 list），訊息格式才是唯一的約定
        self.outbox.put_nowait(json.loads(json.dumps(message, ensure_ascii=False)))

    async def receive(self) -> dict | None:
        """收下一則訊息；連線結束時回傳 None。"""
        if self.closed:
            return None
        return await self.inbox.get()

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.outbox.put_nowait(None)  # 讓另一端的 receive() 結束
            self.inbox.put_nowait(None)  # 自己這端還在等的 receive() 也結束


class Member:
    def __init__(self, name: str, conn: Connection):
        self.name, self.conn = name, conn
        self.online = True


class Room:
    def __init__(self, make_core: Callable[[list[str], Callable[[bool], None]], PartyCore]):
        """make_core(玩家, on_queue) 建立這一局的核心；on_queue(是否排隊中) 讓 AI 呼叫排隊時畫面顯示「排隊中」。"""
        self.make_core = make_core
        self.members: dict[str, Member] = {}  # 依進來的順序；遊戲中斷線的人會保留，可以重新連線
        self.host = ""
        self.core: PartyCore | None = None
        self.host_reply: Reply | None = None  # 正在等房主回答的畫面（存檔、前提、確認重來），換房主時重送
        self.lock = asyncio.Lock()  # 一次只處理一則輸入，核心不會被同時呼叫
        self.ready: set[str] = set()  # 已經看完這回合劇情的人
        self.countdown: asyncio.Task | None = None
        self.waiting_ready = False  # 倒數還沒開始，在等大家看完劇情
        self.deadline = 0.0  # 倒數結束的時間（loop.time()），給中途連線的人接著倒數
        self.time_limit = 0  # 這回合的限時秒數（從核心的回覆記下來）
        self.queued = False  # AI 呼叫正在排隊（所有房間共用一把 key 的次數上限）

    # ---------- 給大廳用的 ----------

    @property
    def online(self) -> list[str]:
        return [m.name for m in self._online_members()]

    @property
    def playing(self) -> bool:
        return self.core is not None

    def entry_error(self, name: str) -> str:
        """這個人能不能進來；不能時回傳原因。名字不重複由大廳負責。"""
        if self.core is not None:
            if name not in self.core.players:
                return UI["room_members_only"].format(players=UI["list_sep"].join(self.core.players))
        elif len(self.online) >= MAX_PLAYERS:
            return UI["room_full"].format(max=MAX_PLAYERS)
        return ""

    def is_leaving(self, name: str, text: str) -> bool:
        """這句輸入是不是要離開房間：/leave，或在等人的畫面選了「離開房間」。"""
        return text == "/leave" or (self.core is None and pick_choice(text, self._lobby_choices(name)) == LEAVE)

    async def add(self, name: str, conn: Connection) -> None:
        async with self.lock:
            await self._join(name, conn)

    async def remove(self, name: str) -> None:
        async with self.lock:
            await self._leave(name)

    async def handle(self, name: str, message: dict) -> None:
        async with self.lock:
            await self._on_message(name, message)

    async def close(self) -> None:
        self._stop_countdown()

    # ---------- 進出 ----------

    async def _join(self, name: str, conn: Connection) -> None:
        self.members[name] = Member(name, conn)
        if not self.host or not self.members[self.host].online:
            self.host = name
        if self.core is None:
            await self._broadcast_lobby(clear_for=name)
            return
        await self._broadcast_notice(UI["room_back"].format(name=name), skip=name)
        if self.core.phase == "playing":
            await self._send_reply(name, self.core.view(name))
            await self._broadcast_waiting()
            if self.countdown and not self.waiting_ready:
                left = round(self.deadline - asyncio.get_running_loop().time())
                if left > 0:
                    await conn.send({"type": "timer", "seconds": left})
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
            await self._send_notice(name, UI["wait_host_story"].format(host=self.host))
        elif text.startswith(("/suggest", "/random", "/timed", "/genre")):  # 前提對話框裡的操作，不用推給其他人
            reply = await self._call(lambda: self.core.send(text))
            if answer:
                await self._safe_write(self.members[name], {"type": "premise", "reply": reply.to_dict()})
        else:
            starting = self.core.phase == "ask_premise" and not text.startswith("/")
            if starting:
                await self._broadcast({"type": "new_story", "premise": text})
            await self._route(await self._call(lambda: self.core.send(text), busy=starting))

    async def _on_lobby(self, name: str, text: str) -> None:
        if name != self.host:
            await self._send_notice(name, UI["wait_host_start"].format(host=self.host))
            return
        if pick_choice(text, self._lobby_choices(name)) != START:
            return
        self.core = self.make_core(self.online, self._set_queued)
        await self._route(self.core.start())

    def _set_queued(self, queued: bool) -> None:
        self.queued = queued  # 在背景執行緒呼叫：_call() 每隔一下看一次，有變就告訴大家

    async def _on_playing(self, name: str, text: str) -> None:
        if text == "/timeout":
            return  # 倒數由房間負責，玩家不能替大家按下時間到
        if text == "/restart" and name != self.host:
            await self._send_notice(name, UI["host_only_restart"])
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
        if self.core is None or self.core.phase != "playing" or not self.online:
            return
        waiting = self.core.waiting()
        if waiting and not any(self.members[n].online for n in waiting if n in self.members):
            await self._act(waiting[0], "/away")  # 給 AI 的文字由核心決定

    async def _call(self, fn: Callable[[], Reply], busy: bool = False) -> Reply:
        """在背景執行緒呼叫核心（可能會呼叫 AI，要花幾秒）。busy 時讓大家看到「故事生成中」。"""
        if busy:
            await self._broadcast({"type": "busy", "on": True, "progress": ""})
        try:
            task = asyncio.create_task(asyncio.to_thread(fn))
            progress = draft = ""
            while busy and not task.done():  # 進度變了（開新故事要呼叫好幾次 AI）、AI 多寫了幾個字，就告訴大家
                await asyncio.wait({task}, timeout=PROGRESS_POLL)
                if not self.core or task.done():
                    continue
                now = UI["queued"] if self.queued else self.core.progress
                if now != progress:
                    progress = now
                    await self._broadcast({"type": "busy", "on": True, "progress": progress})
                if self.core.draft and self.core.draft != draft:
                    draft = self.core.draft
                    await self._broadcast({"type": "draft", "text": draft})
            reply = await task
        finally:
            if busy:
                await self._broadcast({"type": "busy", "on": False})
        if reply.error == "api_key":  # 玩家沒辦法換伺服器的 key
            reply = replace(reply, error="api", notice=UI["server_key_invalid"])
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
                await self._broadcast_notice(UI["host_setting_up"], skip=self.host)
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
        if self.waiting_ready and self.ready >= set(self.online):
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

    async def _broadcast(self, message: dict, skip: str = "") -> None:
        for member in self._online_members():
            if member.name != skip:
                await self._safe_write(member, message)

    def _lobby_choices(self, name: str) -> list[str]:
        return [START, LEAVE] if name == self.host else [LEAVE]

    async def _broadcast_lobby(self, clear_for: str = "") -> None:
        """等人的畫面：房間裡有誰、房主能開始、大家都能離開。clear_for 是剛進來的人，他的畫面要先清空。"""
        members = [UI["host_mark"].format(name=n) if n == self.host else n for n in self.online]
        for member in self._online_members():
            host = member.name == self.host
            await self._safe_write(member, {
                "type": "lobby",
                "title": UI["room_title"].format(host=self.host),
                "members": members,
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
            pass  # 對方已經斷線，大廳會處理離開
