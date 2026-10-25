"""Textual 外殼的主畫面：上方固定狀態列、中間捲動的故事、下方選項與輸入框。

只負責「長什麼樣子」：實作共用層的 View（story.shells.client），把玩家的輸入交給 Client。
開局流程、和核心的對話、什麼時候顯示什麼，都在共用層。
"""

import asyncio
import time

from rich.cells import cell_len
from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Input, OptionList, Static

from story.core import ChangeGroups, Reply, ui_text
from story.shells.client import CharacterLine, LocalClient, StatusLine, View
from story.shells.textual.commands import COMMANDS, help_text
from story.shells.textual.dialogs import ApiKeyDialog, ConfirmDialog, EndingDialog, InfoDialog, PremiseDialog
from story.shells.textual.prose import Marked, Prose
from story import settings
from story.shells.textual.style import CHAR_DELAY, FAST_FACTOR, PAUSE_AFTER, SPINNER, THEME, palette


UI, DIALOGS = ui_text("terminal"), ui_text("dialogs")  # story/ui/語言/
NARROW_WIDTH = 60  # 比這個窄（手機直式）就用窄畫面的樣式


# ---------- 回合間的變化 ----------


def describe_changes(groups: ChangeGroups, colors: dict[str, str]) -> Text | None:
    """把核心回覆的變化轉成彩色文字，例如「新增 右臂撕裂傷（重）　痊癒 左肘擦傷　獲得 油燈」。colors 是 palette() 的結果。"""
    parts: list[tuple[str, str]] = []
    for label, items in groups:
        parts.append((("　" if parts else "") + label + " ", "dim"))
        for i, (text, tone) in enumerate(items):
            parts += [(" · ", "dim")] * bool(i) + [(text, colors[tone])]
    return Text.assemble(*parts) if parts else None


def pack(groups: list[Text], width: int, sep: Text = Text("  ")) -> Text:
    """把幾個不該拆開的小區塊（「⚠ 重傷」「右臂撕裂傷」）用 sep 串起來排進指定寬度：一行放得下就並排，放不下才換行。
    Rich 會在任何空白處換行，直接交給它排會把「⚠」和「重傷」拆到兩行。"""
    lines: list[list[Text]] = [[]]
    used = 0
    for group in (g for g in groups if g.plain):
        size = cell_len(group.plain) + (cell_len(sep.plain) if lines[-1] else 0)
        if lines[-1] and used + size > width:
            lines.append([])
            used, size = 0, cell_len(group.plain)
        lines[-1].append(group)
        used += size
    return Text("\n").join(sep.join(line) for line in lines)


# ---------- 主畫面 ----------


class StoryApp(App, View):
    TITLE = "Story"
    CSS = """
    #status {
        dock: top; height: auto; padding: 1 3 0 3;
        border-bottom: hkey $panel-lighten-1; background: $background;
    }
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
    #log .premise {
        color: $text-muted; text-style: italic;
        border-left: outer $panel-lighten-2; padding: 0 1; margin-bottom: 1;
    }
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

    /* 窄畫面（手機）：縮小邊距，讓故事有更多寬度 */
    Screen.-narrow #status { padding: 0 1; }
    Screen.-narrow #log { padding: 1 1; }
    Screen.-narrow #timer, Screen.-narrow #choices { margin: 0 0; }
    Screen.-narrow #cmd { margin: 0 0; }
    """
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (NARROW_WIDTH, "-wide")]
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
        self.client = LocalClient(self)
        self.choices: list[str] = []
        self.choices_hidden = False  # prepare_choices 放好、還看不見的選項
        self.busy = False
        self.busy_line: Static | None = None  # 故事區裡的「故事生成中」那一行
        self.status_shown: StatusLine | None = None  # 狀態列目前顯示的內容（換主題、改變寬度時重畫）
        self.theme_ready = False
        self.frame = 0
        self.time_limit = self.time_left = 0.0  # 限時模式這回合的秒數與剩下的秒數，0 代表沒有在倒數
        self.last_tick = 0.0
        self.continue_event: asyncio.Event | None = None  # 等玩家按 Enter 繼續
        self.follow = True  # 故事區有新內容時自動捲到最底；玩家往上捲就暫停，捲回最底再恢復
        self.typing = False
        self.speed = 1.0
        self.skip = False
        self.narration: Prose | None = None
        self.narration_text = ""  # 這段劇情目前收到的全文（AI 還在寫時會越來越長）
        self.narration_done = False
        self.narration_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="status")
        yield VerticalScroll(id="log")
        choices = OptionList(id="choices", classes="-empty")
        choices.border_title = UI["choices_title"]
        yield Static("", id="timer")
        yield choices
        cmd = Input(id="cmd")  # 提示由共用層 set_hint() 設定
        cmd.border_subtitle = UI["input_hint"]
        yield cmd

    def on_unmount(self) -> None:
        self.client.close()

    def on_mount(self) -> None:
        saved = settings.get("theme")
        self.theme = saved if saved in self.available_themes else THEME
        self.theme_ready = True  # 之後的主題變更才是玩家選的，要記住
        self.set_status(None)
        self.watch(self.query_one("#log", VerticalScroll), "scroll_y", self.follow_log, init=False)
        self.set_interval(0.1, self.tick)
        self.run_worker(self.client.run(), exclusive=False)

    @property
    def colors(self) -> dict[str, str]:
        """目前主題的狀態顏色。"""
        return palette(self.current_theme)

    def watch_theme(self, theme: str) -> None:
        """換了主題：狀態列跟著換色，並記住選擇。"""
        if not self.theme_ready:
            return
        self.set_status(self.status_shown)
        settings.put("theme", theme)

    def action_theme(self) -> None:
        self.action_change_theme()  # Textual 內建的主題選擇器：上下移動就能預覽

    # ---------- 對話框（View） ----------

    async def ask_confirm(self, question: str, yes: str, no: str) -> bool:
        return await self.push_screen_wait(ConfirmDialog(question, yes=yes, no=no))

    async def ask_premise(self, reply: Reply, ask) -> tuple[str, bool, str] | None:
        return await self.push_screen_wait(PremiseDialog(reply, ask))

    async def ask_ending(self, title: str, record: str) -> bool:
        return await self.push_screen_wait(EndingDialog(title, record))

    async def ask_api_key(self, reason: str) -> tuple[str, bool] | None:
        return await self.push_screen_wait(ApiKeyDialog(reason))

    def show_info(self, title: str, body: str) -> None:
        self.push_screen(InfoDialog(title, body))

    def notify(self, message: str, *, error: bool = False, lasting: bool = False, **kwargs) -> None:  # type: ignore[override]
        """共用層的通知；也保留 Textual 原本 notify 的參數（對話框等元件會直接用）。"""
        if error and not kwargs:
            kwargs = {"severity": "error", "timeout": 30 if lasting else 8}
            if not lasting:
                kwargs["title"] = DIALOGS["error_title"]
        super().notify(message, **kwargs)

    # ---------- 狀態列 ----------

    def on_resize(self, event: events.Resize) -> None:
        self.set_status(self.status_shown)  # 狀態列的換行跟畫面寬度有關，轉向或改變視窗大小時重畫

    def condition_parts(self, line: CharacterLine) -> list[Text]:
        """一位角色的狀態：危險時先警告，再依序列出每個狀態，依程度上色。"""
        parts = [Text(f"⚠ {line.warning_text}", style=f"bold {self.colors[line.warning]}")] if line.warning else []
        return parts + [Text(text, style=self.colors[tone]) for text, tone in line.items]

    def turn_line(self, status: StatusLine) -> Text:
        """「回合 7  限時模式」：模式跟回合放在同一排，狀態列其他地方都留給狀態。"""
        mode = (status.mode, self.colors["bad"] if status.timed else "dim")
        return Text.assemble((UI["turn"] + " ", "dim"), (str(status.turn), "bold"), ("  ", ""), mode)

    def set_status(self, status: StatusLine | None) -> None:
        self.status_shown = status
        bar = self.query_one("#status", Static)
        width = bar.content_region.width or self.size.width - 8
        sep = Text(" · ", style="dim")
        if status is None:
            bar.update(Text("Story", style="dim"))
            return
        parts = self.condition_parts(status.characters[0])
        head = Text.assemble(self.turn_line(status), (f"     {UI['status']} ", "dim"))
        line = pack(parts, width - cell_len(head.plain), sep)
        if "\n" in line.plain:  # 同一排放不下（手機）：狀態整個移到第二排
            head = Text.assemble(self.turn_line(status), (f"\n{UI['status']} ", "dim"))
            line = pack(parts, width - cell_len(UI["status"]) - 1, sep)
        bar.update(head + line)

    # ---------- 故事區 ----------

    def clear_story(self, premise: str) -> None:
        """新故事開始：清空故事區、選項與狀態列，並先顯示故事前提（等 AI 寫開場時可以先讀）。"""
        log = self.query_one("#log", VerticalScroll)
        log.remove_children()
        self.busy_line = None  # 已經跟著被移除了，之後要重新顯示
        self.follow = True
        if premise:
            log.mount(Prose(UI["premise"].format(premise=premise), classes="premise"))
        self.set_choices([])
        self.set_status(None)

    def log_message(self, text: str | Text | Marked, kind: str, follow: bool = False) -> Static:
        widget = Static(text, classes=kind, markup=False)
        self.query_one("#log", VerticalScroll).mount(widget)
        self.scroll_log(follow)
        return widget

    def follow_log(self, scroll_y: float) -> None:
        """故事區捲動了：停在最底就繼續自動跟著新內容，往上捲就不跟，文字還在打的時候也能往回看。
        內容變少時捲軸位置會被夾到新的最底，所以一樣算在最底。"""
        self.follow = scroll_y >= self.query_one("#log", VerticalScroll).max_scroll_y - 1

    def scroll_log(self, force: bool = False) -> None:
        if force:
            self.follow = True
        if self.follow:
            self.query_one("#log", VerticalScroll).scroll_end(animate=False)

    def show_action(self, text: str) -> None:
        self.log_message(Marked("› ", text), "action", follow=True)  # 自己剛行動：一定捲到最底看結果

    def show_note(self, text: str) -> None:
        self.log_message(text, "action")

    def show_changes(self, groups: ChangeGroups, name: str = "") -> None:
        changes = describe_changes(groups, self.colors)
        if changes is not None:
            self.log_message(Text.assemble((f"{name}　", "bold"), changes) if name else changes, "changes")

    def show_ending_title(self, title: str) -> None:
        self.log_message(f"─── {title} ───", "ending", follow=True)

    def start_narration(self) -> None:
        """開始一段劇情：AI 還在寫時就開始打字，打字效果追著目前收到的文字。"""
        if self.busy_line is not None:
            self.busy_line.remove()
            self.busy_line = None
        self.narration = Prose(classes="narration")
        self.query_one("#log", VerticalScroll).mount(self.narration)
        self.narration_text, self.narration_done = "", False
        self.typing, self.speed, self.skip = True, 1.0, False
        self.narration_task = asyncio.create_task(self.type_narration(self.narration))

    def extend_narration(self, text: str) -> None:
        self.narration_text = text

    async def finish_narration(self, text: str) -> None:
        self.narration_text, self.narration_done = text, True
        await self.narration_task

    def discard_narration(self) -> None:
        if self.narration_task is not None:
            self.narration_task.cancel()
            self.narration.remove()
        self.typing = False

    async def type_narration(self, widget: Prose) -> None:
        """一個字一個字顯示到目前收到的地方；還沒收完就等新的字。按 Enter 加速，再按一次直接顯示全部。"""
        shown = 0
        try:
            while True:
                text = self.narration_text
                if self.skip and shown < len(text):
                    shown = len(text)
                    widget.set_text(text)
                    self.scroll_log()
                if shown < len(text):
                    shown += 1
                    widget.set_text(text[:shown])
                    self.scroll_log()
                    await asyncio.sleep((CHAR_DELAY + PAUSE_AFTER.get(text[shown - 1], 0)) * self.speed)
                elif self.narration_done:
                    break
                else:
                    await asyncio.sleep(0.05)  # AI 還在寫
        finally:
            self.typing = False

    async def wait_enter(self, hint: str) -> None:
        """提示也寫在輸入框裡：玩家往上捲在看前面的劇情時，故事區最底的提示看不到。"""
        line = self.log_message(f"（{hint}）", "busy")
        cmd = self.query_one("#cmd", Input)
        placeholder, cmd.placeholder = cmd.placeholder, hint
        self.continue_event = asyncio.Event()
        cmd.focus()
        await self.continue_event.wait()
        self.continue_event = None
        cmd.placeholder = placeholder
        line.remove()

    # ---------- 選項 ----------

    def prepare_choices(self, choices: list[str], timed: bool) -> None:
        """選項框和倒數條在打字前就先佔好位置（看不見），打完字時版面才不會突然往上跳（手機上特別明顯）。"""
        self.typing = True  # 從現在起按 Enter 都算加速打字，不會選到還看不見的選項
        self.set_choices(choices, reveal=False)
        if timed:
            self.reserve_timer()

    def show_choices(self, choices: list[str]) -> None:
        options = self.query_one("#choices", OptionList)
        if not choices and options.option_count:
            # 選完選項：保留原本選項的位置，只是完全看不見，故事區才不會忽高忽低、文字往下掉
            self.choices, self.choices_hidden = [], True
            self.animator.force_stop_animation(options.styles, "opacity")
            options.styles.opacity = 0.0
        elif self.choices_hidden and choices == self.choices:
            self.reveal_choices()  # prepare_choices 放好的選項：淡入
        else:
            self.set_choices(choices)

    def set_choices(self, choices: list[str], reveal: bool = True) -> None:
        """換上新的選項。reveal=False 時先透明地佔好位置，之後用 reveal_choices() 淡入。"""
        self.choices = list(choices)
        options = self.query_one("#choices", OptionList)
        options.clear_options()
        options.add_options([Marked(f"{i}. ", c) for i, c in enumerate(choices, 1)])
        options.set_class(not choices, "-empty")
        self.animator.force_stop_animation(options.styles, "opacity")  # 上一次的淡入還沒播完時，不能讓它把新選項又調回可見
        options.styles.opacity = 0.0
        self.choices_hidden = True
        if reveal:
            self.reveal_choices()
        self.query_one("#cmd", Input).focus()

    def reveal_choices(self) -> None:
        self.choices_hidden = False
        self.query_one("#choices", OptionList).styles.animate("opacity", 1.0, duration=0.4)

    def set_hint(self, placeholder: str) -> None:
        self.query_one("#cmd", Input).placeholder = placeholder

    # ---------- 等待 ----------

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.query_one("#cmd", Input).disabled = busy
        if not busy:
            if self.busy_line is not None:
                self.busy_line.remove()
                self.busy_line = None
            self.query_one("#cmd", Input).focus()

    def show_busy(self) -> None:
        if self.busy_line is None:
            self.busy_line = self.log_message(self.busy_text(), "busy")

    def busy_text(self) -> str:
        """等待那一行的文字，例如「⠋ 故事生成中：規劃故事大綱…」。"""
        return f"{SPINNER[self.frame]} {self.client.busy_text()}"

    # ---------- 限時模式（倒數由介面負責，時間到交給共用層） ----------

    def start_timer(self, seconds: int) -> None:
        self.time_limit = self.time_left = float(seconds)
        self.last_tick = time.monotonic()
        self.query_one("#timer", Static).add_class("show")
        self.render_timer()

    def reserve_timer(self) -> None:
        """先空出倒數條那一行，倒數開始時才不會把版面往上推。"""
        timer = self.query_one("#timer", Static)
        timer.update("")
        timer.add_class("show")

    def stop_timer(self) -> None:
        self.time_left = 0.0
        self.query_one("#timer", Static).remove_class("show")

    def render_timer(self) -> None:
        width = 24
        filled = round(width * self.time_left / self.time_limit)
        color = self.colors["severe"] if self.time_left <= 5 else self.colors["light"]
        self.query_one("#timer", Static).update(
            Text.assemble(
                (UI["timer"] + " ", "dim"), ("━" * filled, color), ("─" * (width - filled), "dim"),
                (" " + UI["seconds"].format(seconds=f"{self.time_left:2.0f}"), f"bold {color}"),
            )
        )

    def tick(self) -> None:
        now = time.monotonic()
        elapsed, self.last_tick = now - self.last_tick, now
        if self.busy_line is not None:
            self.frame = (self.frame + 1) % len(SPINNER)
            self.busy_line.update(self.busy_text())
        if self.time_left <= 0 or self.busy or isinstance(self.screen, ModalScreen):  # 開著對話框或指令選單時暫停倒數
            return
        self.time_left = max(0.0, self.time_left - elapsed)
        self.render_timer()
        if self.time_left == 0:
            self.stop_timer()
            self.run_worker(self.client.timeout())

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

        if self.continue_event is not None:
            self.continue_event.set()
            return
        if self.typing:  # 文字顯示中：Enter 用來加速或跳過
            if self.speed < 1.0:
                self.skip = True
            self.speed = FAST_FACTOR
            return
        if not self.client.ready:
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
                self.run_worker(self.client.command(raw))  # 交給核心，它會回覆「沒有這個指令」
            return
        self.run_worker(self.client.act(raw))

    def choose_index(self, index: int) -> None:
        if not self.choices_hidden:  # 看不見的選項（剛選完、還沒換上新的）不能選
            self.run_worker(self.client.act(str(index + 1)))

    def action_move_choice(self, step: int) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        options = self.query_one("#choices", OptionList)
        if options.option_count and not self.choices_hidden:
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
        if self.client.ready:
            self.run_worker(self.client.command("/state"))

    def action_help(self) -> None:
        self.push_screen(InfoDialog(UI["commands_title"], help_text()))

    def action_restart(self) -> None:
        if self.client.ready and not self.typing:
            self.run_worker(self.client.command("/restart"))

    def action_quit(self) -> None:
        self.exit()  # 每回合都已自動存檔
