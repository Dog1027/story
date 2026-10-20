"""Textual 外殼的對話框：API key、名字、新故事、確認、結局、說明。"""

import asyncio
from collections.abc import Awaitable, Callable

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Static, TextArea

from story.core import MAX_PLAYERS
from story.shells.apikey import KEY_PATH
from story.shells.players import MAX_NAME_LEN, InvalidName, check_name


class Dialog(ModalScreen):
    """所有對話框共用的外框樣式。"""

    DEFAULT_CSS = """
    Dialog { align: center middle; background: $background 30%; }
    Dialog > Vertical {
        width: 64; max-width: 90%; height: auto; max-height: 90%;
        padding: 1 3; background: $surface;
    }
    Dialog .title { text-style: bold; color: $primary; margin-bottom: 1; }
    Dialog .hint { color: $text-muted; margin-bottom: 1; }
    Dialog Input { border: round $panel-lighten-2; background: $surface; margin-bottom: 1; }
    Dialog Input:focus { border: round $primary; background-tint: $foreground 0%; }
    Dialog Checkbox { border: none; background: $surface; padding: 0; margin-bottom: 1; }
    Dialog Horizontal { height: auto; align-horizontal: right; margin-top: 1; }
    Dialog.-narrow > Vertical { width: 100%; max-width: 100%; padding: 1 1; }
    /* 只有焦點所在的按鈕有底色；其他按鈕是純文字，主要按鈕用文字顏色區分。
       內建按鈕樣式的選擇器比較具體，所以要用 !important；規則順序決定優先權，焦點放最後。 */
    Dialog Button {
        margin-left: 2; min-width: 0; padding: 0 2; text-style: none;
        background: transparent !important; color: $text-muted !important;
    }
    Dialog Button.-primary { color: $primary !important; }
    Dialog Button:hover { background: $panel !important; }
    Dialog Button:focus {
        background: $primary !important; color: $background !important;
        text-style: bold !important; background-tint: $foreground 0%;
    }
    """
    BINDINGS = [
        Binding("escape", "cancel", "取消"),
        # 在輸入框裡時，輸入框會先處理 ← →，照常移動游標
        Binding("left", "move_in_row(-1)", show=False),
        Binding("right", "move_in_row(1)", show=False),
        Binding("up", "move_between_rows(-1)", show=False),
        Binding("down", "move_between_rows(1)", show=False),
    ]

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_move_in_row(self, step: int) -> None:
        """← →：只在同一排的按鈕之間移動，到兩端就停住。"""
        focused = self.focused
        if not isinstance(focused, Button):
            return
        buttons = list(focused.parent.query_children(Button))
        i = buttons.index(focused) + step
        if 0 <= i < len(buttons):
            buttons[i].focus()

    def action_move_between_rows(self, step: int) -> None:
        """↑↓：在輸入框、核取方塊、按鈕列之間移動，到頂端或底端就停住。進入按鈕列時停在主要按鈕。"""
        rows: list[list] = []
        for widget in self.focus_chain:
            if isinstance(widget, Button) and rows and isinstance(rows[-1][0], Button):
                rows[-1].append(widget)  # 同一排的按鈕算同一列
            else:
                rows.append([widget])
        current = next((i for i, row in enumerate(rows) if self.focused in row), None)
        if current is None or not 0 <= current + step < len(rows):
            return
        target = rows[current + step]
        primary = [b for b in target if isinstance(b, Button) and b.variant == "primary"]
        (primary or target)[0].focus()


class ApiKeyDialog(Dialog):
    """請玩家輸入 API key。回傳 (key, 是否儲存) 或 None。網頁版不提供儲存，key 只留在這次連線的記憶體裡。"""

    def __init__(self, reason: str, can_save: bool = True):
        super().__init__()
        self.reason, self.can_save = reason, can_save

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.reason, classes="title")
            yield Static("可以到 https://aistudio.google.com/apikey 免費申請。", classes="hint")
            if not self.can_save:
                yield Static("key 只用於這次連線，不會存到伺服器上；下次進來要重新輸入。", classes="hint")
            yield Input(placeholder="貼上 API key", password=True, id="key")
            yield Checkbox(f"儲存到 {KEY_PATH}，下次自動使用", value=True, id="save", disabled=not self.can_save)
            with Horizontal():
                yield Button("離開", id="cancel", compact=True)
                yield Button("確定", variant="primary", id="ok", compact=True)

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    def submit(self) -> None:
        key = self.query_one("#key", Input).value.strip()
        if key:
            self.dismiss((key, self.can_save and self.query_one("#save", Checkbox).value))

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)


class NameDialog(Dialog):
    """網頁版：輸入名字。claim(名字) 負責佔用這個名字，成功回傳空字串，失敗回傳要顯示的原因。
    回傳佔用成功的名字或 None。"""

    def __init__(self, claim: Callable[[str], Awaitable[str]], hint: str = "每個名字有自己的存檔，下次用同一個名字進來就能接著玩。"):
        super().__init__()
        self.claim, self.hint = claim, hint

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("你的名字", classes="title")
            yield Static(self.hint, classes="hint")
            yield Input(placeholder="例如：阿明", id="name", max_length=MAX_NAME_LEN)
            yield Static("", id="error", classes="hint")
            with Horizontal():
                yield Button("離開", id="cancel", compact=True)
                yield Button("進入", variant="primary", id="ok", compact=True)

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    async def submit(self) -> None:
        error = self.query_one("#error", Static)
        try:
            name = check_name(self.query_one("#name", Input).value)
        except InvalidName as e:
            error.update(str(e))
            return
        if reason := await self.claim(name):
            error.update(reason)
            return
        self.dismiss(name)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)


class PartyNamesDialog(Dialog):
    """多人模式：輸入每位玩家的名字。回傳名字清單或 None。"""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("多人模式", classes="title")
            yield Static(
                f"每位玩家扮演一位角色，大家輪流在這台電腦上輸入行動。\n輸入 2 到 {MAX_PLAYERS} 位玩家的名字，用逗號或空白隔開。",
                classes="hint",
            )
            yield Input(placeholder="例如：阿明，小華", id="names")
            yield Static("", id="error", classes="hint")
            with Horizontal():
                yield Button("離開", id="cancel", compact=True)
                yield Button("開始", variant="primary", id="ok", compact=True)

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    def submit(self) -> None:
        error = self.query_one("#error", Static)
        raw = self.query_one("#names", Input).value.replace("，", " ").replace(",", " ").replace("、", " ")
        try:
            names = [check_name(n) for n in raw.split()]
        except InvalidName as e:
            error.update(str(e))
            return
        if not 2 <= len(names) <= MAX_PLAYERS:
            error.update(f"需要 2 到 {MAX_PLAYERS} 位玩家。")
            return
        if len(set(names)) != len(names):
            error.update("名字不能重複。")
            return
        self.dismiss(names)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)


class PremiseArea(TextArea):
    """會自動換行的多行輸入框，行為比照單行輸入框：Enter 送出；在最上或最下一行按 ↑↓ 會離開輸入框。"""

    class Submitted(Message):
        pass

    async def _on_key(self, event: Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted())
            return
        await super()._on_key(event)

    def action_cursor_up(self, select: bool = False) -> None:
        self._move_or_leave(super().action_cursor_up, select, -1)

    def action_cursor_down(self, select: bool = False) -> None:
        self._move_or_leave(super().action_cursor_down, select, 1)

    def _move_or_leave(self, move, select: bool, step: int) -> None:
        before = self.cursor_location
        move(select)
        if not select and self.cursor_location == before:  # 已經到頂或到底，游標動不了
            self.screen.action_move_between_rows(step)


class PremiseDialog(Dialog):
    """輸入故事前提並選擇模式。回傳 (前提, 是否限時)；前提空白就用預設值。"""

    DEFAULT_CSS = """
    PremiseDialog > Vertical { width: 84; }
    PremiseDialog TextArea {
        height: 6; margin-bottom: 1; background: $surface;
        border: round $panel-lighten-2;
    }
    PremiseDialog TextArea:focus { border: round $primary; background-tint: $foreground 0%; }
    """

    def __init__(self, default: str, timed: bool, suggest: Callable[[str], str]):
        super().__init__()
        self.default, self.timed = default, timed
        self.suggest = suggest  # 請 AI 想一個開頭（會在背景執行緒呼叫）

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("新的故事", classes="title")
            yield Static(f"輸入故事前提，留白則使用：\n{self.default}", classes="hint")
            yield PremiseArea(placeholder="例如：你是一名在末日城市送信的郵差……", id="premise", highlight_cursor_line=False)
            yield Checkbox("限時模式：情勢緊迫時，要在時間內做出決定", value=self.timed, id="timed")
            with Horizontal():
                yield Button("幫我想", id="suggest", compact=True)
                yield Button("開始", variant="primary", id="ok", compact=True)

    @on(Button.Pressed, "#suggest")
    @work
    async def ask_ai(self) -> None:
        button, field = self.query_one("#suggest", Button), self.query_one("#premise", PremiseArea)
        button.disabled, button.label = True, "構思中…"
        try:
            field.text = await asyncio.to_thread(self.suggest, field.text.strip() or self.default)
            field.move_cursor(field.document.end)
            field.focus()
        except Exception as e:  # 網路、key、額度等錯誤都只提示，不中斷開新局
            self.notify(str(e)[:200], title="AI 沒有想出開頭", severity="error")
        finally:
            button.disabled, button.label = False, "幫我想"

    @on(PremiseArea.Submitted)
    @on(Button.Pressed, "#ok")
    def submit(self) -> None:
        premise = " ".join(self.query_one("#premise", PremiseArea).text.split()) or self.default
        self.dismiss((premise, self.query_one("#timed", Checkbox).value))

    def action_cancel(self) -> None:
        self.dismiss((self.default, self.query_one("#timed", Checkbox).value))


class ConfirmDialog(Dialog):
    def __init__(self, question: str, yes: str = "確定", no: str = "取消"):
        super().__init__()
        self.question, self.yes, self.no = question, yes, no

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.question, classes="title")
            with Horizontal():
                yield Button(self.no, id="no", compact=True)
                yield Button(self.yes, variant="primary", id="yes", compact=True)

    def on_mount(self) -> None:
        self.query_one("#yes", Button).focus()

    @on(Button.Pressed)
    def answer(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_cancel(self) -> None:
        self.dismiss(False)


class EndingDialog(ConfirmDialog):
    """故事結束：顯示結局名稱與這趟旅程的紀錄，問要不要再玩。"""

    def __init__(self, title: str, record: str):
        super().__init__(f"結局：{title}" if title else "故事結束", yes="再玩一次", no="離開")
        self.record = record

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.question, classes="title")
            yield Static(self.record, classes="hint")
            with Horizontal():
                yield Button(self.no, id="no", compact=True)
                yield Button(self.yes, variant="primary", id="yes", compact=True)


class InfoDialog(Dialog):
    BINDINGS = [Binding("q", "cancel", "關閉")]

    def __init__(self, title: str, body: str):
        super().__init__()
        self.title_text, self.body = title, body

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.title_text, classes="title")
            with VerticalScroll():
                yield Static(self.body, markup=False)
            with Horizontal():
                yield Button("關閉", variant="primary", id="close", compact=True)

    def on_mount(self) -> None:
        self.query_one("#close", Button).focus()

    @on(Button.Pressed)
    def close(self) -> None:
        self.dismiss(None)
