"""Textual 終端機介面：上方固定狀態列、中間捲動的故事、下方選項與輸入框。"""

import asyncio
import time
from collections.abc import Callable

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.events import Key
from textual.message import Message
from textual.widgets import Button, Checkbox, Input, OptionList, Static, TextArea

from story.apikey import KEY_PATH, forget_api_key, get_saved_api_key, save_api_key
from story.commands import COMMANDS, help_text
from story.common import CHAR_DELAY, FAST_FACTOR, LEVEL_COLORS, PAUSE_AFTER, SEVERITY_COLORS, ChangeGroups
from story.core import Reply, Status, StoryCore
from story.engine import TIMEOUT_ACTION
from story.players import MAX_NAME_LEN, InvalidName, Player, check_name

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
THEME = "tokyo-night"  # 其他選擇：catppuccin-mocha、rose-pine、nord、dracula……


# ---------- 回合間的變化 ----------


def describe_changes(groups: ChangeGroups) -> Text | None:
    """把核心回覆的變化轉成彩色文字，例如「新增 右臂撕裂傷（重）　痊癒 左肘擦傷　獲得 油燈」。"""
    parts: list[tuple[str, str]] = []
    for label, items in groups:
        parts.append((("　" if parts else "") + label + " ", "dim"))
        for i, item in enumerate(items):
            parts += [(" · ", "dim")] * bool(i) + [item]
    return Text.assemble(*parts) if parts else None


# ---------- 對話框 ----------


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
    """網頁版：輸入名字。名字決定存檔，同一個名字同時只能有一個連線。回傳佔用成功的 Player 或 None。"""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("你的名字", classes="title")
            yield Static("每個名字有自己的存檔，下次用同一個名字進來就能接著玩。", classes="hint")
            yield Input(placeholder="例如：阿明", id="name", max_length=MAX_NAME_LEN)
            yield Static("", id="error", classes="hint")
            with Horizontal():
                yield Button("離開", id="cancel", compact=True)
                yield Button("進入", variant="primary", id="ok", compact=True)

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    def submit(self) -> None:
        error = self.query_one("#error", Static)
        try:
            player = Player(check_name(self.query_one("#name", Input).value))
        except InvalidName as e:
            error.update(str(e))
            return
        if not player.acquire():
            error.update("這個名字正在遊戲中，請換一個名字，或等對方離開。")
            return
        self.dismiss(player)

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


# ---------- 主畫面 ----------


class StoryApp(App):
    TITLE = "Story"
    CSS = """
    #statusbar {
        dock: top; height: auto; padding: 1 3 0 3;
        border-bottom: hkey $panel-lighten-1; background: $background;
    }
    #status { width: 1fr; }
    #mode { width: 18; text-align: right; }
    #log {
        padding: 1 3; align-horizontal: center;
        scrollbar-size-vertical: 1; scrollbar-gutter: stable;  /* 一開始就預留捲軸位置，捲軸出現時文字才不會跳 */
    }
    #log > Static { width: 1fr; max-width: 80; }
    #log .narration { color: $foreground; margin-bottom: 1; }
    #log .action {
        color: $accent; text-style: italic;
        border-left: outer $accent; padding: 0 1; margin-bottom: 1;
    }
    #log .ending { color: $warning; text-style: bold; text-align: center; margin: 1 0; }
    #log .changes { margin-bottom: 1; }
    #log .busy { color: $text-muted; margin-bottom: 1; }
    #timer { height: 1; margin: 0 3; padding: 0 1; display: none; }
    #timer.show { display: block; }
    #choices {
        height: auto; max-height: 10; margin: 0 3; padding: 0 1;
        background: $background; border: round $panel-lighten-1; border-title-color: $text-muted;
    }
    #choices:focus { border: round $primary; }
    #choices > .option-list--option { padding: 0 1; }
    #choices > .option-list--option-highlighted { background: $primary 25%; color: $text; text-style: bold; }
    #choices > .option-list--option-hover { background: $primary 12%; }
    #choices.-empty { display: none; }
    #cmd {
        margin: 1 3; background: $background;
        border: round $panel-lighten-1; border-subtitle-color: $text-muted;
    }
    #cmd:focus { border: round $primary; background-tint: $foreground 0%; }
    """
    BINDINGS = [
        Binding(key, name.lstrip("/"), desc, priority=key.startswith("ctrl"))
        for name, (key, desc) in COMMANDS.items()
    ] + [
        # 輸入框有焦點時，↑↓ 直接移動選項，不用先切換焦點
        Binding("up", "move_choice(-1)", show=False),
        Binding("down", "move_choice(1)", show=False),
    ]

    def __init__(self, web: bool = False) -> None:
        super().__init__()
        self.web = web  # 網頁版：先問名字，存檔依名字分開，API key 不存到伺服器
        self.player: Player | None = None
        self.core: StoryCore | None = None
        self.choices: list[str] = []
        self.busy = False
        self.busy_line: Static | None = None  # 故事區裡的「故事生成中」那一行
        self.frame = 0
        self.time_left = 0.0  # 限時模式的剩餘秒數，0 代表沒有在倒數
        self.last_tick = 0.0
        self.continue_event: asyncio.Event | None = None  # 等玩家按 Enter 繼續
        self.typing = False
        self.speed = 1.0
        self.skip = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="statusbar"):
            yield Static("", id="status")
            yield Static("", id="mode")  # 狀態列最右邊固定一格：顯示目前的模式
        yield VerticalScroll(id="log")
        choices = OptionList(id="choices", classes="-empty")
        choices.border_title = "接下來"
        yield Static("", id="timer")
        yield choices
        cmd = Input(placeholder="↑↓ 選擇，或寫下你的行動", id="cmd")
        cmd.border_subtitle = "/ 指令 · F1 說明"
        yield cmd

    def on_unmount(self) -> None:
        if self.player:
            self.player.release()  # 連線異常中斷沒跑到這裡也沒關係：下次會發現鎖的程序已不存在而接手

    def on_mount(self) -> None:
        self.theme = THEME
        self.set_status(None)
        self.set_interval(0.1, self.tick)
        self.boot()

    # ---------- 啟動：取得 key，建立核心 ----------

    @work
    async def boot(self) -> None:
        if self.web:
            self.player = await self.push_screen_wait(NameDialog())
            if self.player is None:
                self.exit()
                return
            key = await self.ask_api_key(f"{self.player.name}，請輸入你的 Gemini API key")
        else:
            key = get_saved_api_key() or await self.ask_api_key("找不到 Gemini API key。")
        if key is None:
            self.exit()
            return
        if self.player:
            self.core = StoryCore(api_key=key, save_path=self.player.save_path, log_path=self.player.log_path)
        else:
            self.core = StoryCore(api_key=key)
        await self.handle(self.core.start())

    async def ask_api_key(self, reason: str) -> str | None:
        result = await self.push_screen_wait(ApiKeyDialog(reason, can_save=not self.web))
        if result is None:
            return None
        key, keep = result
        if keep:
            save_api_key(key)
        return key

    # ---------- 和核心對話 ----------

    async def send(self, text: str, echo: str = "") -> None:
        """送一句文字給核心並顯示回覆。echo 是要先顯示在故事區的玩家行動。"""
        if self.busy:
            return
        self.stop_timer()
        if echo:
            self.set_choices([])
            self.log_message(f"› {echo}", "action")
        reply = await self.ask_core(text)
        if reply is not None:
            await self.handle(reply)

    async def ask_core(self, text: str) -> Reply | None:
        """在背景執行緒呼叫核心；超過一下子才顯示等待動畫。key 無效時請玩家換一個再重送。"""
        self.set_busy(True)
        try:
            while True:
                task = asyncio.create_task(asyncio.to_thread(self.core.send, text))
                done, _ = await asyncio.wait({task}, timeout=0.15)
                if not done:
                    self.show_busy_line()
                reply = await task
                if reply.error != "api_key":
                    return reply
                if not self.web:  # 網頁版本來就沒有存 key
                    forget_api_key()
                self.set_busy(False)
                key = await self.ask_api_key("API key 無效或沒有權限，請重新輸入。")
                if key is None:
                    return reply
                self.core.set_api_key(key)
                self.set_busy(True)
        finally:
            self.set_busy(False)

    async def handle(self, reply: Reply) -> None:
        """依照回覆的階段與欄位更新畫面。"""
        if reply.info:
            self.push_screen(InfoDialog(*reply.info))
        if reply.error == "api":
            self.notify(reply.notice, title="出錯了", severity="error", timeout=8)
        elif reply.notice and reply.phase in ("playing", "ending", "ended") and not reply.narration:
            self.notify(reply.notice)

        if reply.phase == "ask_continue":
            keep = await self.push_screen_wait(ConfirmDialog(f"{reply.notice}\n\n要繼續嗎？", yes="繼續", no="開新遊戲"))
            await self.send("1" if keep else "2")
        elif reply.phase == "ask_premise":
            await self.ask_premise(reply)
        elif reply.phase == "confirm_restart":
            sure = await self.push_screen_wait(ConfirmDialog(reply.notice))
            await self.send("1" if sure else "2")
        elif reply.phase in ("playing", "ending"):
            await self.show_turn(reply)
            if reply.phase == "ending":
                await self.send("")  # 讓核心接著寫尾聲
        elif reply.phase == "ended":
            await self.show_ending(reply)

    async def ask_premise(self, reply: Reply) -> None:
        if reply.error == "api":
            return  # 開場生成失敗：錯誤已經提示了，留在原處，玩家可以用 Ctrl+R 再試
        timed = self.core.timed

        def suggest(_: str) -> str:
            suggestion = self.core.send("/suggest")
            if suggestion.error:
                raise RuntimeError(suggestion.notice)
            return suggestion.suggestion

        premise, want_timed = await self.push_screen_wait(PremiseDialog(reply.premise_default, timed, suggest))
        if want_timed != timed:
            await asyncio.to_thread(self.core.send, f"/timed {'on' if want_timed else 'off'}")
        self.query_one("#log", VerticalScroll).remove_children()
        self.set_choices([])
        self.set_status(None)
        await self.send(premise)

    # ---------- 顯示 ----------

    def set_status(self, status: Status | None) -> None:
        if status is None:
            self.query_one("#status", Static).update(Text("Story", style="dim"))
            self.render_mode(self.core.timed if self.core else False)
            return
        muted = "dim"

        def listed(conds: list[tuple[str, str]], first_sep: str) -> list[tuple[str, str]]:
            parts: list[tuple[str, str]] = []
            for i, (name, severity) in enumerate(conds):
                parts += [(" · " if i else first_sep, muted), (name, SEVERITY_COLORS[severity])]
            return parts

        bar = Text.assemble(
            ("回合 ", muted), (str(status.turn), "bold"),
            ("     狀態 ", muted), (status.level, f"bold {LEVEL_COLORS[status.level]}"), *listed(status.body, "  "),
            *([("     精神 ", muted)] + listed(status.mind, "") if status.mind else []),
            ("     背包 ", muted), (" · ".join(status.inventory) or "空", ""),
        )
        self.query_one("#status", Static).update(bar)
        self.render_mode(status.timed)

    def log_message(self, text: str | Text, kind: str) -> Static:
        log = self.query_one("#log", VerticalScroll)
        widget = Static(text, classes=kind, markup=False)
        log.mount(widget)
        log.scroll_end(animate=False)
        return widget

    async def show_turn(self, reply: Reply) -> None:
        """有新劇情時逐字顯示，打完才顯示變化與更新狀態列，避免先劇透。"""
        if reply.narration:
            if reply.notice and reply.notice.startswith("讀取存檔"):
                self.log_message(reply.notice, "action")
            await self.typewrite(reply.narration)
            if changes := describe_changes(reply.changes):
                self.log_message(changes, "changes")
        self.set_status(reply.status)
        self.set_choices(reply.choices)
        if reply.narration and reply.time_limit:
            self.start_timer(reply.time_limit)

    async def show_ending(self, reply: Reply) -> None:
        ending = reply.ending
        if ending.epilogue:
            self.log_message(f"─── {ending.title} ───", "ending")
            await self.typewrite(ending.epilogue)
        else:
            self.log_message("─── 故事結束 ───", "ending")
        await self.wait_for_enter("按 Enter 查看結局")
        if await self.push_screen_wait(EndingDialog(ending.title, ending.record)):
            await self.send("1")
        else:
            self.exit()

    async def wait_for_enter(self, hint: str) -> None:
        line = self.log_message(f"（{hint}）", "busy")
        self.continue_event = asyncio.Event()
        self.query_one("#cmd", Input).focus()
        await self.continue_event.wait()
        self.continue_event = None
        line.remove()

    async def typewrite(self, text: str) -> None:
        """一個字一個字顯示。按 Enter 加速，再按一次直接顯示全部。"""
        widget = self.log_message("", "narration")
        log = self.query_one("#log", VerticalScroll)
        self.typing, self.speed, self.skip = True, 1.0, False
        try:
            for i, ch in enumerate(text, 1):
                if self.skip:
                    break
                widget.update(text[:i])
                log.scroll_end(animate=False)
                await asyncio.sleep((CHAR_DELAY + PAUSE_AFTER.get(ch, 0)) * self.speed)
        finally:
            widget.update(text)
            log.scroll_end(animate=False)
            self.typing = False

    def set_choices(self, choices: list[str]) -> None:
        self.choices = list(choices)
        options = self.query_one("#choices", OptionList)
        options.clear_options()
        options.add_options([f"{i}. {c}" for i, c in enumerate(choices, 1)])
        options.set_class(not choices, "-empty")
        if choices:
            options.styles.opacity = 0.0
            options.styles.animate("opacity", 1.0, duration=0.4)
        self.query_one("#cmd", Input).focus()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.query_one("#cmd", Input).disabled = busy
        if not busy:
            if self.busy_line is not None:
                self.busy_line.remove()
                self.busy_line = None
            self.query_one("#cmd", Input).focus()

    def show_busy_line(self) -> None:
        if self.busy_line is None:
            self.busy_line = self.log_message(f"{SPINNER[0]} 故事生成中…", "busy")

    # ---------- 限時模式（倒數由外殼負責，時間到送 /timeout 給核心） ----------

    def start_timer(self, seconds: int) -> None:
        self.time_limit = self.time_left = float(seconds)
        self.last_tick = time.monotonic()
        self.query_one("#timer", Static).add_class("show")
        self.render_timer()

    def stop_timer(self) -> None:
        self.time_left = 0.0
        self.query_one("#timer", Static).remove_class("show")

    def render_mode(self, timed: bool) -> None:
        """狀態列最右邊固定顯示目前的模式。"""
        label = Text("限時模式", style="#f7768e") if timed else Text("一般模式", style="dim")
        self.query_one("#mode", Static).update(label)

    def render_timer(self) -> None:
        """選項上方的倒數條。"""
        width = 24
        filled = round(width * self.time_left / self.time_limit)
        color = "#f7768e" if self.time_left <= 5 else "#e0af68"
        self.query_one("#timer", Static).update(
            Text.assemble(
                ("限時 ", "dim"), ("━" * filled, color), ("─" * (width - filled), "dim"),
                (f" {self.time_left:2.0f} 秒", f"bold {color}"),
            )
        )

    def tick(self) -> None:
        now = time.monotonic()
        elapsed, self.last_tick = now - self.last_tick, now
        if self.busy_line is not None:
            self.frame = (self.frame + 1) % len(SPINNER)
            self.busy_line.update(f"{SPINNER[self.frame]} 故事生成中…")
        # 開著對話框或指令選單時暫停倒數
        if self.time_left <= 0 or isinstance(self.screen, ModalScreen):
            return
        self.time_left = max(0.0, self.time_left - elapsed)
        self.render_timer()
        if self.time_left == 0:
            self.stop_timer()
            self.run_worker(self.send("/timeout", echo=TIMEOUT_ACTION))

    # ---------- 輸入 ----------

    @on(Input.Changed, "#cmd")
    def maybe_open_palette(self, event: Input.Changed) -> None:
        if event.value == "/":
            event.input.value = ""
            self.action_command_palette()

    @on(Input.Submitted, "#cmd")
    def submit(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        event.input.value = ""

        if self.continue_event is not None:  # 正在等玩家按 Enter 繼續
            self.continue_event.set()
            return
        if self.typing:  # 文字顯示中：Enter 用來加速或跳過
            if self.speed < 1.0:
                self.skip = True
            self.speed = FAST_FACTOR
            return
        if self.core is None or self.busy:
            return
        if not raw:
            # 輸入框是空的：選定用 ↑↓ 移到的選項
            highlighted = self.query_one("#choices", OptionList).highlighted
            if highlighted is not None:
                self.choose_index(highlighted)
            return
        if raw.startswith("/"):
            action = getattr(self, f"action_{raw[1:]}", None)
            if raw in COMMANDS and action:
                action()
            else:
                self.run_worker(self.send(raw))  # 交給核心，它會回覆「沒有這個指令」
            return
        if raw.isdigit() and 1 <= int(raw) <= len(self.choices):
            self.choose_index(int(raw) - 1)
            return
        self.run_worker(self.send(raw, echo=raw))

    def choose_index(self, index: int) -> None:
        self.run_worker(self.send(str(index + 1), echo=self.choices[index]))

    def action_move_choice(self, step: int) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        options = self.query_one("#choices", OptionList)
        if options.option_count:
            options.action_cursor_down() if step > 0 else options.action_cursor_up()

    @on(OptionList.OptionSelected, "#choices")
    def choose(self, event: OptionList.OptionSelected) -> None:
        if not self.typing and not self.busy:
            self.choose_index(event.option_index)

    # ---------- 指令 ----------

    def get_system_commands(self, screen: Screen):
        for name, (key, desc) in COMMANDS.items():
            yield SystemCommand(name, f"{desc}（{key}）", getattr(self, f"action_{name[1:]}"))

    def action_state(self) -> None:
        if self.core and not self.busy:
            self.run_worker(self.send("/state"))

    def action_help(self) -> None:
        self.push_screen(InfoDialog("指令", help_text()))

    def action_restart(self) -> None:
        if self.core and not self.busy and not self.typing:
            self.run_worker(self.send("/restart"))

    def action_quit(self) -> None:
        self.exit()  # 每回合都已自動存檔
