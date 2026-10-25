"""Textual 外殼的對話框：API key、新故事、確認、結局、說明。"""

import asyncio
from collections.abc import Callable

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Select, Static, TextArea

from story.core import GENRE_AUTO, GENRE_NONE, Reply, ui_text
from story.shells.client import CONFIG_PATH

UI, TERMINAL = ui_text("dialogs"), ui_text("terminal")  # story/ui/語言/


class Dialog(ModalScreen):
    """所有對話框共用：外框樣式、「離開」按鈕與 Esc、方向鍵怎麼移動。"""

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
        Binding("escape", "cancel", UI["cancel"]),
        # 在輸入框裡時，輸入框會先處理 ← →，照常移動游標
        Binding("left", "move_in_row(-1)", show=False),
        Binding("right", "move_in_row(1)", show=False),
        Binding("up", "move_between_rows(-1)", show=False),
        Binding("down", "move_between_rows(1)", show=False),
    ]

    @on(Button.Pressed, "#cancel")
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
    """請玩家輸入 API key。回傳 (key, 是否儲存) 或 None。"""

    def __init__(self, reason: str):
        super().__init__()
        self.reason = reason

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.reason, classes="title")
            yield Static(UI["key_where"].format(link="https://aistudio.google.com/apikey"), classes="hint")
            yield Input(placeholder=UI["key_placeholder"], password=True, id="key")
            yield Checkbox(UI["key_save"].format(path=CONFIG_PATH), value=True, id="save")
            with Horizontal():
                yield Button(UI["leave"], id="cancel", compact=True)
                yield Button(UI["ok"], variant="primary", id="ok", compact=True)

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    def submit(self) -> None:
        key = self.query_one("#key", Input).value.strip()
        if key:
            self.dismiss((key, self.query_one("#save", Checkbox).value))


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


class GenreSelect(Select, inherit_bindings=False):
    """題材選單。內建的 Select 把上下鍵用來打開選單，焦點到這裡就走不到下面的按鈕；
    這裡改成：上下鍵照常在各列之間移動，Enter 或空白鍵打開選單，左右鍵直接切換題材。"""

    BINDINGS = [
        Binding("enter,space", "show_overlay", TERMINAL["choose_genre"], show=False),
        Binding("up", "screen.move_between_rows(-1)", show=False),
        Binding("down", "screen.move_between_rows(1)", show=False),
        Binding("left", "cycle(-1)", show=False),
        Binding("right", "cycle(1)", show=False),
    ]

    def __init__(self, options: list[tuple[str, str]], **kwargs):
        super().__init__(options, **kwargs)
        self.values = [value for _, value in options]

    def action_cycle(self, step: int) -> None:
        self.value = self.values[(self.values.index(self.value) + step) % len(self.values)]


class PremiseDialog(Dialog):
    """選擇題材、輸入故事前提、選擇模式。回傳 (前提, 是否限時, 題材)；前提空白就用預設值。
    由上到下：題材、題材介紹、故事前提（一開始就填好預設的開頭，玩家改了才用玩家寫的）、限時模式。"""

    DEFAULT_CSS = """
    PremiseDialog > Vertical { width: 84; }
    PremiseDialog TextArea {
        height: 6; margin-bottom: 1; background: $surface;
        border: round $panel-lighten-2;
    }
    PremiseDialog TextArea:focus { border: round $primary; background-tint: $foreground 0%; }
    PremiseDialog Select { margin-bottom: 0; }
    PremiseDialog #genre-hint { margin: 0 0 1 2; }
    """

    def __init__(self, reply: Reply, ask: Callable[..., Reply]):
        super().__init__()
        self.default, self.timed = reply.premise_default, reply.timed
        self.genre, self.genres = reply.genre, dict(reply.genres)  # 目前的題材選擇；可選的題材（名稱 → 描述）
        # 把指令送給核心並拿回最後一個回覆，例如 ask("/genre 武俠", "/random")；會在背景執行緒呼叫
        self.ask = ask
        self.asking = asyncio.Lock()  # 一次只送一個請求：核心不能同時被兩個執行緒呼叫
        self.latest = 0  # 最新一次操作的編號；被後面的操作取代的舊結果就不用了

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(UI["premise_title"], classes="title")
            if self.genres:
                options = [(UI["genre_auto_option"], GENRE_AUTO), (UI["genre_none_option"], GENRE_NONE)]
                options += [(UI["genre_option"].format(name=name), name) for name in self.genres]
                value = self.genre if self.genre in (GENRE_AUTO, GENRE_NONE, *self.genres) else GENRE_AUTO
                yield GenreSelect(options, value=value, allow_blank=False, compact=True, id="genre")
                yield Static(self.genre_hint(value), id="genre-hint", classes="hint")
            yield Static(UI["premise_hint"], classes="hint")
            yield PremiseArea(self.default, placeholder=UI["premise_placeholder"], id="premise", highlight_cursor_line=False)
            yield Checkbox(UI["timed_option"], value=self.timed, id="timed")
            with Horizontal():
                yield Button(UI["reroll"], id="reroll", compact=True)
                yield Button(UI["suggest"], id="suggest", compact=True)
                yield Button(UI["start"], variant="primary", id="ok", compact=True)

    async def request(self, *commands: str, latest_only: bool = True) -> Reply | None:
        """排隊把指令送給核心。latest_only 時，如果等待期間又有新的操作（例如快速切換題材），回傳 None。"""
        self.latest += 1
        mine = self.latest
        async with self.asking:
            reply = await asyncio.to_thread(self.ask, *commands)
        return reply if not latest_only or mine == self.latest else None

    def on_mount(self) -> None:
        field = self.query_one("#premise", PremiseArea)
        field.focus()
        field.move_cursor(field.document.end)

    def set_default(self, premise: str, replace: bool = False) -> None:
        """換了預設的開頭：玩家還沒改過文字框（或 replace）就換上新的，改過的就保留玩家寫的。"""
        field = self.query_one("#premise", PremiseArea)
        if replace or " ".join(field.text.split()) in ("", " ".join(self.default.split())):
            field.text = premise
            field.move_cursor(field.document.end)
        self.default = premise

    @on(Button.Pressed, "#suggest")
    @work
    async def ask_ai(self) -> None:
        button, field = self.query_one("#suggest", Button), self.query_one("#premise", PremiseArea)
        button.disabled, button.label = True, UI["thinking"]
        try:
            reply = await self.request(f"/genre {self.chosen_genre()}", "/suggest", latest_only=False)
            if reply.error:
                raise RuntimeError(reply.notice)
            self.set_default(reply.suggestion, replace=True)
            field.focus()
        except Exception as e:  # 網路、key、額度等錯誤都只提示，不中斷開新局
            self.notify(str(e)[:200], title=UI["suggest_failed"], severity="error")
        finally:
            button.disabled, button.label = False, UI["suggest"]

    @on(Button.Pressed, "#reroll")
    @work
    async def reroll(self) -> None:
        """換一個：從題材包的開頭靈感裡重抽，不用等 AI。"""
        if reply := await self.request(f"/genre {self.chosen_genre()}", "/random"):
            self.set_default(reply.premise_default, replace=True)  # 玩家按了「換一個」：文字框一定換掉

    @on(Select.Changed, "#genre")
    @work
    async def show_genre(self, event: Select.Changed) -> None:
        """換題材：顯示題材的描述；隨機抽到的開頭也換成新題材的。"""
        self.query_one("#genre-hint", Static).update(self.genre_hint(event.value))
        if reply := await self.request(f"/genre {event.value}"):
            self.set_default(reply.premise_default)

    def genre_hint(self, choice: str) -> str:
        if choice == GENRE_AUTO:
            return UI["genre_auto_hint"]
        if choice == GENRE_NONE:
            return UI["genre_none_hint"]
        return self.genres.get(choice, "")

    def chosen_genre(self) -> str:
        return self.query_one("#genre", Select).value if self.genres else self.genre

    @on(PremiseArea.Submitted)
    @on(Button.Pressed, "#ok")
    def submit(self) -> None:
        premise = " ".join(self.query_one("#premise", PremiseArea).text.split()) or self.default
        self.dismiss((premise, self.query_one("#timed", Checkbox).value, self.chosen_genre()))

    def action_cancel(self) -> None:
        self.dismiss((self.default, self.query_one("#timed", Checkbox).value, self.chosen_genre()))


class ConfirmDialog(Dialog):
    def __init__(self, question: str, yes: str = UI["ok"], no: str = UI["cancel"], detail: str = ""):
        super().__init__()
        self.question, self.yes, self.no, self.detail = question, yes, no, detail

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.question, classes="title")
            if self.detail:
                yield Static(self.detail, classes="hint")
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
        super().__init__(UI["ending_title"].format(title=title) if title else UI["story_over"], yes=UI["play_again"], no=UI["leave"], detail=record)


class InfoDialog(Dialog):
    BINDINGS = [Binding("q", "cancel", UI["close"])]

    def __init__(self, title: str, body: str):
        super().__init__()
        self.title_text, self.body = title, body

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.title_text, classes="title")
            with VerticalScroll():
                yield Static(self.body, markup=False)
            with Horizontal():
                yield Button(UI["close"], variant="primary", id="close", compact=True)

    def on_mount(self) -> None:
        self.query_one("#close", Button).focus()

    @on(Button.Pressed)
    def close(self) -> None:
        self.dismiss(None)
