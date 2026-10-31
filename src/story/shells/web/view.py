"""The web interface's View: turns each call from the shared layer into a JSON message for the browser, and waits for the browser's reply when the player must answer.

The browser side (static/app.js) only draws; the flow is all in the shared layer (story.shells.screen.client).

Server → browser: {"t": kind, ...}. Messages that need a reply carry "id", and the browser answers with {"t": "answer", "id": …, "value": …}.
Browser → server:
  {"t": "answer", "id": 1, "value": …}       Answer a dialog, or report that narration finished showing or Enter was pressed (value unused)
  {"t": "act", "text": "1"}                  An action: a choice number or free text
  {"t": "command", "text": "/state"}         A command
  {"t": "premise_event", "req": 3, "action": "genre", "genre": "Wuxia", "text": "…"}
      An action in the premise dialog: action is genre (change genre), reroll (another one), or suggest (suggest one); text is the text box's current content.
      Reply {"t": "premise_update", "req": 3, "text": "…" or null (leave the text box as is), "error": "…"}
"""

import asyncio
import logging
from dataclasses import asdict
from typing import Any

from aiohttp import web

from story.core import ChangeGroups
from story.shells.connection import BackgroundTasks
from story.shells.screen.client import Client
from story.shells.screen.premise import PremiseFailed, PremiseForm
from story.shells.screen.view import StatusLine, View

log = logging.getLogger(__name__)


class WebView(View):
    def __init__(self, ws: web.WebSocketResponse):
        self.ws = ws
        self.client: Client | None = None
        self.outbox: asyncio.Queue[dict] = asyncio.Queue()  # Sent in order, so concurrent sends never interleave
        self.pending: dict[int, asyncio.Future] = {}
        self.next_id = 0
        self.premise_form: PremiseForm | None = None  # While the premise dialog is open: its rules (shared layer)
        self.tasks = BackgroundTasks()  # Work started by player input (cancelled together when the connection ends)

    # ---------- Sending and receiving ----------

    def post(self, kind: str, **fields) -> None:
        self.outbox.put_nowait({"t": kind, **fields})

    async def write_loop(self) -> None:
        while True:
            message = await self.outbox.get()
            if self.ws.closed:
                return
            await self.ws.send_json(message)

    async def ask(self, kind: str, **fields: Any) -> Any:
        """Send a message that needs a reply and return the browser's answer."""
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
                self.tasks.spawn(self.client.act(text) if kind == "act" else self.client.send(text))  # A command isn't shown in the story area
        elif kind == "premise_event" and self.premise_form:
            self.tasks.spawn(self.answer_premise(self.premise_form, message))

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
        except (PremiseFailed, ConnectionError) as e:  # The AI failing or the room going away only shows a notice; it doesn't interrupt starting a new game
            self.post("premise_update", req=req, text=None, error=str(e)[:200])
            return
        except Exception as e:  # A bug: still just a notice for the player, but logged so it can be found
            log.exception("premise dialog action %r failed", action)
            self.post("premise_update", req=req, text=None, error=str(e)[:200])
            return
        self.post("premise_update", req=req, text=premise, error="")

    def close(self) -> None:
        for future in self.pending.values():
            future.cancel()
        self.tasks.cancel()

    # ---------- View ----------

    def clear_story(self, premise: str) -> None:
        self.post("clear", premise=premise)

    def show_action(self, text: str) -> None:
        self.post("action", text=text)

    def show_note(self, text: str) -> None:
        self.post("note", text=text)

    def start_narration(self) -> None:
        self.post("narration_start")

    def show_past_narration(self, text: str) -> None:
        self.post("past_narration", text=text)

    def extend_narration(self, text: str) -> None:
        self.post("narration_text", text=text)

    async def finish_narration(self, text: str) -> None:
        await self.ask("narration_end", text=text)  # The browser replies once it has shown it all

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

    def mark_choice(self, index: int) -> None:
        self.post("mark_choice", index=index)

    def set_hint(self, placeholder: str) -> None:
        self.post("hint", placeholder=placeholder)

    def set_status(self, status: StatusLine | None) -> None:
        self.post("status", status=asdict(status) if status else None)

    def show_lobby(self, screen: dict) -> None:
        self.post("lobby", screen=screen)

    def set_busy(self, busy: bool) -> None:
        self.post("busy", on=busy)

    def show_busy(self) -> None:
        self.post("busy_line", text=self.client.busy_text())

    def start_timer(self, seconds: int) -> None:
        self.post("timer", seconds=seconds)  # The room keeps time and sends time's up; the browser only displays it

    def stop_timer(self) -> None:
        self.post("stop_timer")

    def notify(self, text: str, error: bool = False, lasting: bool = False) -> None:
        self.post("notify", text=text, error=error, lasting=lasting)

    def show_activity(self, text: str) -> None:
        self.post("activity", text=text)

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
        if not isinstance(answer, list) or len(answer) != 2:
            return None  # Closed (null), or not the [text, timed] pair the page sends
        text, timed = answer  # The text box content and whether it's timed; the genre went to form when it changed
        return form.finish(str(text), bool(timed))

    async def ask_ending(self, title: str, record: str) -> bool:
        return bool(await self.ask("ending", title=title, record=record))

    async def ask_name(self, error: str, max_len: int) -> str | None:
        raw = await self.ask("name", error=error, max_len=max_len)
        return None if raw is None else str(raw)

    def exit(self) -> None:
        self.post("exit")
