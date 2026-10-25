"""網頁介面的 View：把共用層的每個呼叫變成一則 JSON 訊息送給瀏覽器，要等玩家回答的再等瀏覽器回覆。

瀏覽器那邊（static/app.js）只負責畫出來；流程都在共用層（story.shells.client）。

伺服器 → 瀏覽器：{"t": 種類, ...}。要等回覆的訊息帶 "id"，瀏覽器用 {"t": "answer", "id": …, "value": …} 回答。
瀏覽器 → 伺服器：
  {"t": "answer", "id": 1, "value": …}       回答對話框，或回報劇情顯示完、按了 Enter（value 不用）
  {"t": "act", "text": "1"}                  行動：選項編號或自由輸入
  {"t": "command", "text": "/state"}         指令
  {"t": "premise_event", "req": 3, "action": "genre", "genre": "武俠", "text": "…"}
      前提對話框裡的操作：action 是 genre（換題材）、reroll（換一個）、suggest（幫我想），text 是文字框目前的內容。
      回覆 {"t": "premise_update", "req": 3, "text": "…" 或 null（文字框保持原樣）, "error": "…"}
"""

import asyncio
from dataclasses import asdict

from aiohttp import web

from story.core import ChangeGroups
from story.shells.client import MAX_NAME_LEN, Client, PremiseForm, StatusLine, View

BUSY_POLL = 0.3  # 等待時每隔幾秒看一次進度文字有沒有變


class WebView(View):
    def __init__(self, ws: web.WebSocketResponse):
        self.ws = ws
        self.client: Client | None = None
        self.outbox: asyncio.Queue[dict] = asyncio.Queue()  # 依序送出，不會因為同時送而交錯
        self.pending: dict[int, asyncio.Future] = {}
        self.next_id = 0
        self.premise_form: PremiseForm | None = None  # 前提對話框開著時：它的規則（共用層）
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
        elif kind == "premise_event" and self.premise_form:
            self.spawn(self.answer_premise(self.premise_form, message))

    def spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def answer_premise(self, form: PremiseForm, message: dict) -> None:
        action, text, req = message.get("action"), str(message.get("text", "")), message.get("req")
        try:
            if action == "genre":
                premise = await form.change_genre(str(message.get("genre", "")), text)
            elif action == "reroll":
                premise = await form.reroll(text)
            elif action == "suggest":
                premise = await form.suggest(text)
            else:
                return
        except Exception as e:  # 網路、key 等錯誤只提示，不中斷開新局
            self.post("premise_update", req=req, text=None, error=str(e)[:200])
            return
        self.post("premise_update", req=req, text=premise, error="")

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

    def show_lobby(self, screen: dict) -> None:
        self.post("lobby", screen=screen)

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
        self.post("timer", seconds=seconds)  # 房間統一計時，時間到由房間送出，瀏覽器只負責顯示

    def stop_timer(self) -> None:
        self.post("stop_timer")

    def notify(self, text: str, error: bool = False, lasting: bool = False) -> None:
        self.post("notify", text=text, error=error, lasting=lasting)

    def show_info(self, title: str, body: str) -> None:
        self.post("info", title=title, body=body)

    async def ask_confirm(self, question: str, yes: str, no: str) -> bool:
        return bool(await self.ask("confirm", question=question, yes=yes, no=no))

    async def ask_premise(self, form: PremiseForm) -> tuple[str, bool, str] | None:
        options = form.genre_options()
        self.premise_form = form
        try:
            answer = await self.ask(
                "premise", default=form.default, timed=form.timed, genre=form.genre,
                options=options, hints={value: form.genre_hint(value) for _, value in options},
            )
        finally:
            self.premise_form = None
        if not answer:
            return None
        text, timed = answer  # 瀏覽器回傳文字框的內容、要不要限時；題材在換的時候就交給 form 了
        return form.finish(str(text), bool(timed))

    async def ask_ending(self, title: str, record: str) -> bool:
        return bool(await self.ask("ending", title=title, record=record))

    async def ask_name(self, hint: str, error: str) -> str | None:
        raw = await self.ask("name", hint=hint, error=error, max_len=MAX_NAME_LEN)
        return None if raw is None else str(raw)

    def exit(self) -> None:
        self.post("exit")
