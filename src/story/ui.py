"""Textual 終端機介面：上方固定狀態列、中間捲動的故事、下方選項與輸入框。"""

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

from google.genai import errors
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Checkbox, Input, OptionList, Static

from story.apikey import KEY_PATH, forget_api_key, get_saved_api_key, is_key_error, save_api_key
from story.commands import COMMANDS, help_text
from story.engine import TIMEOUT_ACTION, Engine
from story.models import GameState

SAVE_PATH = Path("save.json")
DEFAULT_PREMISE = "你是一名失憶的旅人，在暴風雨夜醒來，發現自己躺在一座廢棄燈塔的底層，手裡握著一把不屬於你的鑰匙。"

CHAR_DELAY = 0.03  # 每個字的間隔秒數
FAST_FACTOR = 0.15  # 按一次 Enter 後，間隔縮成原本的幾倍
PAUSE_AFTER = {"。": 0.25, "！": 0.25, "？": 0.25, "，": 0.1, "、": 0.08, "…": 0.15, "\n": 0.1}
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
THEME = "tokyo-night"  # 其他選擇：catppuccin-mocha、rose-pine、nord、dracula……


def save(state: GameState) -> None:
    SAVE_PATH.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def load() -> GameState | None:
    if not SAVE_PATH.exists():
        return None
    return GameState.model_validate_json(SAVE_PATH.read_text(encoding="utf-8"))


def memory_text(state: GameState) -> str:
    events = "\n".join(f"  - {e}" for e in state.key_events) or "  （無）"
    return (
        f"[已確立的事實]\n  {'、'.join(state.flags) or '無'}\n\n"
        f"[重大事件]\n{events}\n\n"
        f"[長期摘要]\n  {state.summary or '（尚無）'}\n\n"
        f"[近期記憶] {len(state.recent)} 回合原文，{len(state.unsummarized)} 回合等待壓縮"
    )


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
    """請玩家輸入 API key。回傳 (key, 是否儲存) 或 None。"""

    def __init__(self, reason: str):
        super().__init__()
        self.reason = reason

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.reason, classes="title")
            yield Static("可以到 https://aistudio.google.com/apikey 免費申請。", classes="hint")
            yield Input(placeholder="貼上 API key", password=True, id="key")
            yield Checkbox(f"儲存到 {KEY_PATH}，下次自動使用", value=True, id="save")
            with Horizontal():
                yield Button("離開", id="cancel", compact=True)
                yield Button("確定", variant="primary", id="ok", compact=True)

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    def submit(self) -> None:
        key = self.query_one("#key", Input).value.strip()
        if key:
            self.dismiss((key, self.query_one("#save", Checkbox).value))

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)


class PremiseDialog(Dialog):
    """輸入故事前提並選擇模式。回傳 (前提, 是否限時)；前提空白就用預設值。"""

    def __init__(self, default: str, hint: str, timed: bool):
        super().__init__()
        self.default, self.hint, self.timed = default, hint, timed

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("新的故事", classes="title")
            yield Static(f"輸入故事前提，留白則{self.hint}：\n{self.default}", classes="hint")
            yield Input(placeholder="例如：你是一名在末日城市送信的郵差……", id="premise")
            yield Checkbox("限時模式：情勢緊迫時，要在時間內做出決定", value=self.timed, id="timed")
            with Horizontal():
                yield Button("開始", variant="primary", id="ok", compact=True)

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    def submit(self) -> None:
        premise = self.query_one("#premise", Input).value.strip() or self.default
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
    #status {
        dock: top; height: auto; padding: 1 3 0 3;
        border-bottom: hkey $panel-lighten-1; background: $background;
    }
    #log { padding: 1 3; align-horizontal: center; scrollbar-size-vertical: 1; }
    #log > Static { width: 1fr; max-width: 80; }
    #log .narration { color: $foreground; margin-bottom: 1; }
    #log .action {
        color: $accent; text-style: italic;
        border-left: outer $accent; padding: 0 1; margin-bottom: 1;
    }
    #log .ending { color: $text-muted; text-align: center; margin: 1 0; }
    #log .busy { color: $accent; margin-bottom: 1; }
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

    def __init__(self) -> None:
        super().__init__()
        self.engine: Engine | None = None
        self.state: GameState | None = None
        self.busy = False
        self.busy_line: Static | None = None  # 故事區裡的「故事生成中」那一行
        self.frame = 0
        self.time_left = 0.0  # 限時模式的剩餘秒數，0 代表沒有在倒數
        self.last_tick = 0.0
        self.timed_mode = False  # 開新局時的預設模式（沿用上一局的選擇）
        self.typing = False
        self.speed = 1.0
        self.skip = False

    def compose(self) -> ComposeResult:
        yield Static("", id="status")
        yield VerticalScroll(id="log")
        yield Static("", id="timer")
        choices = OptionList(id="choices", classes="-empty")
        choices.border_title = "接下來"
        yield choices
        cmd = Input(placeholder="↑↓ 選擇，或寫下你的行動", id="cmd")
        cmd.border_subtitle = "/ 指令 · F1 說明"
        yield cmd

    def on_mount(self) -> None:
        self.theme = THEME
        self.set_status()
        self.set_interval(0.1, self.tick)
        self.boot()

    # ---------- 啟動流程 ----------

    @work
    async def boot(self) -> None:
        key = get_saved_api_key() or await self.ask_api_key("找不到 Gemini API key。")
        if key is None:
            self.exit()
            return
        self.engine = Engine(api_key=key)

        state = load()
        if state and not state.game_over and await self.push_screen_wait(
            ConfirmDialog("找到存檔，要繼續嗎？", yes="繼續", no="開新遊戲")
        ):
            self.state = state
            self.timed_mode = state.timed_mode
            self.log_message(f"讀取存檔：{state.premise}", "action")
            await self.show_turn()
        else:
            await self.new_game()

    async def ask_api_key(self, reason: str) -> str | None:
        result = await self.push_screen_wait(ApiKeyDialog(reason))
        if result is None:
            return None
        key, keep = result
        if keep:
            save_api_key(key)
        return key

    async def new_game(self, last_premise: str | None = None) -> None:
        default = last_premise or DEFAULT_PREMISE
        hint = "沿用上一局的前提" if last_premise else "使用預設"
        premise, self.timed_mode = await self.push_screen_wait(PremiseDialog(default, hint, self.timed_mode))
        self.stop_timer()
        state = GameState(premise=premise, timed_mode=self.timed_mode)
        self.query_one("#log", VerticalScroll).remove_children()
        self.set_choices([])
        if await self.generate(lambda: self.engine.start(state)):
            self.state = state
            save(state)
            await self.show_turn()
        else:
            self.log_message("開場生成失敗。按 Ctrl+R 再試一次。", "ending")

    # ---------- 呼叫 LLM ----------

    async def generate(self, call: Callable[[], None]) -> bool:
        """在背景執行緒呼叫 LLM，期間顯示等待動畫。key 無效時請玩家重新輸入並重試。"""
        self.set_busy(True)
        try:
            while True:
                try:
                    await asyncio.to_thread(call)
                    return True
                except (errors.APIError, RuntimeError) as e:
                    if not is_key_error(e):
                        self.notify(str(e)[:300], title="出錯了", severity="error", timeout=8)
                        return False
                    forget_api_key()
                    key = await self.ask_api_key("API key 無效或沒有權限，請重新輸入。")
                    if key is None:
                        return False
                    self.engine.set_api_key(key)
        finally:
            self.set_busy(False)

    @work
    async def act(self, action: str) -> None:
        if self.busy or self.typing or self.state is None or self.state.game_over:
            return
        self.stop_timer()
        self.set_choices([])
        self.log_message(f"› {action}", "action")
        if await self.generate(lambda: self.engine.act(self.state, action)):
            save(self.state)
            await self.show_turn()
        else:
            # act() 可能已經改了一半的狀態，從存檔還原
            self.state = load() or self.state
            self.set_choices(self.state.current_choices)

    # ---------- 顯示 ----------

    def set_status(self) -> None:
        s = self.state
        if s is None:
            self.query_one("#status", Static).update(Text("Story", style="dim"))
            return
        muted = "dim"
        condition = (" · ".join(s.conditions), "#e0af68") if s.conditions else ("良好", "#9ece6a")
        bar = Text.assemble(
            ("回合 ", muted), (str(s.turn), "bold"),
            ("     狀態 ", muted), condition,
            ("     背包 ", muted), (" · ".join(s.inventory) or "空", ""),
            ("     限時模式" if s.timed_mode else "", "#f7768e"),
        )
        self.query_one("#status", Static).update(bar)

    def log_message(self, text: str, kind: str) -> Static:
        log = self.query_one("#log", VerticalScroll)
        widget = Static(text, classes=kind, markup=False)
        log.mount(widget)
        log.scroll_end(animate=False)
        return widget

    async def show_turn(self) -> None:
        s = self.state
        self.set_status()
        await self.typewrite(s.current_narration)
        if s.game_over:
            self.log_message("─── 故事結束 ───", "ending")
            if await self.push_screen_wait(ConfirmDialog("故事結束了。要再玩一次嗎？", yes="再玩一次", no="離開")):
                await self.new_game(last_premise=s.premise)
            else:
                self.exit()
            return
        self.set_choices(s.current_choices)
        if s.current_time_limit:
            self.start_timer(s.current_time_limit)

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
        if busy:
            self.busy_line = self.log_message(f"{SPINNER[0]} 故事生成中…", "busy")
        else:
            if self.busy_line is not None:
                self.busy_line.remove()
                self.busy_line = None
            self.query_one("#cmd", Input).focus()

    # ---------- 限時模式 ----------

    def start_timer(self, seconds: int) -> None:
        self.time_limit = self.time_left = float(seconds)
        self.last_tick = time.monotonic()
        self.query_one("#timer", Static).add_class("show")
        self.render_timer()

    def stop_timer(self) -> None:
        self.time_left = 0.0
        self.query_one("#timer", Static).remove_class("show")

    def render_timer(self) -> None:
        width = 24
        filled = round(width * self.time_left / self.time_limit)
        color = "#f7768e" if self.time_left <= 5 else "#e0af68"
        self.query_one("#timer", Static).update(
            Text.assemble(
                ("限時 ", "dim"), ("━" * filled, color), ("─" * (width - filled), "dim"),
                (f" {self.time_left:.0f} 秒", f"bold {color}"),
            )
        )

    def tick(self) -> None:
        now = time.monotonic()
        elapsed, self.last_tick = now - self.last_tick, now
        if self.busy and self.busy_line is not None:
            self.frame = (self.frame + 1) % len(SPINNER)
            self.busy_line.update(f"{SPINNER[self.frame]} 故事生成中…")
        # 開著對話框或指令選單時暫停倒數
        if self.time_left <= 0 or isinstance(self.screen, ModalScreen):
            return
        self.time_left = max(0.0, self.time_left - elapsed)
        self.render_timer()
        if self.time_left == 0:
            self.stop_timer()
            self.act(TIMEOUT_ACTION)

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

        if self.typing:  # 文字顯示中：Enter 用來加速或跳過
            if self.speed < 1.0:
                self.skip = True
            self.speed = FAST_FACTOR
            return
        if not raw:
            # 輸入框是空的：選定用 ↑↓ 移到的選項
            highlighted = self.query_one("#choices", OptionList).highlighted
            if highlighted is not None and self.state:
                self.act(self.state.current_choices[highlighted])
            return
        if raw.startswith("/"):
            action = getattr(self, f"action_{raw[1:]}", None)
            if raw in COMMANDS and action:
                action()
            else:
                self.notify(f"沒有 {raw} 這個指令，按 F1 看指令列表。", severity="warning")
            return

        choices = self.state.current_choices if self.state else []
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            raw = choices[int(raw) - 1]
        self.act(raw)

    def action_move_choice(self, step: int) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        options = self.query_one("#choices", OptionList)
        if options.option_count:
            options.action_cursor_down() if step > 0 else options.action_cursor_up()

    @on(OptionList.OptionSelected, "#choices")
    def choose(self, event: OptionList.OptionSelected) -> None:
        if self.state and not self.typing:
            self.act(self.state.current_choices[event.option_index])

    # ---------- 指令 ----------

    def get_system_commands(self, screen: Screen):
        for name, (key, desc) in COMMANDS.items():
            yield SystemCommand(name, f"{desc}（{key}）", getattr(self, f"action_{name[1:]}"))

    def action_state(self) -> None:
        if self.state:
            self.push_screen(InfoDialog("程式記住的東西", memory_text(self.state)))

    def action_help(self) -> None:
        self.push_screen(InfoDialog("指令", help_text()))

    @work
    async def action_restart(self) -> None:
        if self.busy:
            return
        if self.state is None or await self.push_screen_wait(ConfirmDialog("確定要放棄目前進度、重新開始嗎？")):
            await self.new_game(last_premise=self.state.premise if self.state else None)

    def action_quit(self) -> None:
        self.exit()  # 每回合都已自動存檔
