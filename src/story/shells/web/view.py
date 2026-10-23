"""網頁介面的 View：把共用層的每個呼叫變成一則 JSON 訊息送給瀏覽器，要等玩家回答的再等瀏覽器回覆。

瀏覽器那邊（static/app.js）只負責畫出來；流程都在共用層（story.shells.client）。

伺服器 → 瀏覽器：{"t": 種類, ...}。要等回覆的訊息帶 "id"，瀏覽器用 {"t": "answer", "id": …, "value": …} 回答。
瀏覽器 → 伺服器：
  {"t": "answer", "id": 1, "value": …}       回答對話框，或回報劇情顯示完、按了 Enter（value 不用）
  {"t": "act", "text": "1"}                  行動：選項編號或自由輸入
  {"t": "command", "text": "/state"}         指令
  {"t": "timeout"}                           倒數到了
  {"t": "premise_ask", "req": 3, "commands": ["/genre 武俠", "/random"]}   前提對話框裡的操作（換題材、換一個、幫我想）
"""

import asyncio
from dataclasses import asdict

from aiohttp import web

from story.core import ChangeGroups, Reply
from story.shells.client import MAX_NAME_LEN, Client, StatusLine, View

BUSY_POLL = 0.3  # 等待時每隔幾秒看一次進度文字有沒有變


def premise_fields(reply: Reply) -> dict:
    return {
        "default": reply.premise_default,
        "suggestion": reply.suggestion,
        "timed": reply.timed,
        "genre": reply.genre,
        "genres": [list(g) for g in reply.genres],
        "error": reply.notice if reply.error else "",
    }


class WebView(View):
    def __init__(self, ws: web.WebSocketResponse):
        self.ws = ws
        self.client: Client | None = None
        self.outbox: asyncio.Queue[dict] = asyncio.Queue()  # 依序送出，不會因為同時送而交錯
        self.pending: dict[int, asyncio.Future] = {}
        self.next_id = 0
        self.premise_ask = None  # 前提對話框開著時：把指令送給核心的函式
        self.asking = asyncio.Lock()  # 核心一次只能被一個執行緒呼叫
        self.busy_task: asyncio.Task | None = None
        self.tasks: set[asyncio.Task] = set()  # 玩家輸入觸發的工作（連線結束時一起取消）

    # ---------- 收發 ----------

    def post(self, kind: str, **fields) -> None:
        self.outbox.put_nowait({"t": kind, **fields})

    async def write_loop(self) -> None:
        while True:
            message = await self.outbox.get()
            if self.ws.closed:
                return
            await self.ws.send_json(message)

    async def ask(self, kind: str, **fields):
        """送出要等回覆的訊息，回傳瀏覽器的回答。"""
        self.next_id += 1
        mine = self.next_id
        future = asyncio.get_running_loop().create_future()
        self.pending[mine] = future
        self.post(kind, id=mine, **fields)
        try:
            return await future
        finally:
            self.pending.pop(mine, None)

    def receive(self, message: dict) -> None:
        kind = message.get("t")
        if kind == "answer":
            future = self.pending.get(message.get("id"))
            if future and not future.done():
                future.set_result(message.get("value"))
        elif kind in ("act", "command") and self.client.ready:
            text = str(message.get("text", "")).strip()
            if text:
                self.spawn(self.client.act(text) if kind == "act" else self.client.command(text))
        elif kind == "timeout":
            self.spawn(self.client.timeout())
        elif kind == "premise_ask" and self.premise_ask:
            self.spawn(self.answer_premise(message.get("req"), [str(c) for c in message.get("commands", [])]))

    def spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def answer_premise(self, req, commands: list[str]) -> None:
        ask = self.premise_ask
        async with self.asking:
            try:
                reply = await asyncio.to_thread(ask, *commands)
            except Exception as e:  # 網路、key 等錯誤只提示，不中斷開新局
                self.post("premise_update", req=req, error=str(e)[:200])
                return
        self.post("premise_update", req=req, **premise_fields(reply))

    def close(self) -> None:
        for future in self.pending.values():
            future.cancel()
        for task in list(self.tasks):
            task.cancel()
        if self.busy_task:
            self.busy_task.cancel()

    # ---------- View ----------

    def clear_story(self, premise: str) -> None:
        self.post("clear", premise=premise)

    def show_action(self, text: str) -> None:
        self.post("action", text=text)

    def show_note(self, text: str) -> None:
        self.post("note", text=text)

    def start_narration(self) -> None:
        self.post("narration_start")

    def extend_narration(self, text: str) -> None:
        self.post("narration_text", text=text)

    async def finish_narration(self, text: str) -> None:
        await self.ask("narration_end", text=text)  # 瀏覽器顯示完才回覆

    def discard_narration(self) -> None:
        self.post("narration_discard")

    def show_changes(self, groups: ChangeGroups, name: str = "") -> None:
        self.post("changes", name=name, groups=[[label, [list(i) for i in items]] for label, items in groups])

    def show_ending_title(self, title: str) -> None:
        self.post("ending_title", title=title)

    async def wait_enter(self, hint: str) -> None:
        await self.ask("wait_enter", hint=hint)

    def prepare_choices(self, choices: list[str], timed: bool) -> None:
        self.post("prepare_choices", choices=choices, timed=timed)

    def show_choices(self, choices: list[str]) -> None:
        self.post("choices", choices=choices)

    def set_hint(self, placeholder: str) -> None:
        self.post("hint", placeholder=placeholder)

    def set_status(self, status: StatusLine | None) -> None:
        self.post("status", status=asdict(status) if status else None)

    def show_lobby(self, members: list[str]) -> None:
        self.post("lobby", members=members)

    def set_busy(self, busy: bool) -> None:
        self.post("busy", on=busy)
        if not busy and self.busy_task:
            self.busy_task.cancel()
            self.busy_task = None

    def show_busy(self) -> None:
        if self.busy_task is None:
            self.busy_task = asyncio.create_task(self.follow_progress())

    async def follow_progress(self) -> None:
        """等待時，進度文字（例如「規劃故事大綱」）變了就更新。"""
        shown = None
        while True:
            text = self.client.busy_text()
            if text != shown:
                self.post("busy_line", text=text)
                shown = text
            await asyncio.sleep(BUSY_POLL)

    def start_timer(self, seconds: int) -> None:
        # 線上多人大家共用一個倒數（房間計時），開著對話框也不能暫停
        self.post("timer", seconds=seconds, pausable=self.client.room is None)

    def stop_timer(self) -> None:
        self.post("stop_timer")

    def notify(self, text: str, error: bool = False, lasting: bool = False) -> None:
        self.post("notify", text=text, error=error, lasting=lasting)

    def show_info(self, title: str, body: str) -> None:
        self.post("info", title=title, body=body)

    async def ask_confirm(self, question: str, yes: str = "確定", no: str = "取消") -> bool:
        return bool(await self.ask("confirm", question=question, yes=yes, no=no))

    async def ask_premise(self, reply: Reply, ask) -> tuple[str, bool, str] | None:
        self.premise_ask = ask
        try:
            answer = await self.ask("premise", **premise_fields(reply))
        finally:
            self.premise_ask = None
        if not answer:
            return None
        premise, timed, genre = answer
        return " ".join(str(premise).split()) or reply.premise_default, bool(timed), str(genre)

    async def ask_ending(self, title: str, record: str) -> bool:
        return bool(await self.ask("ending", title=title, record=record))

    async def ask_name(self, hint: str, error: str) -> str | None:
        raw = await self.ask("name", hint=hint, error=error, max_len=MAX_NAME_LEN)
        return None if raw is None else str(raw)

    async def ask_api_key(self, reason: str, can_save: bool) -> tuple[str, bool] | None:
        key = await self.ask("api_key", reason=reason)
        return (str(key).strip(), False) if key and str(key).strip() else None

    def exit(self) -> None:
        self.post("exit")
