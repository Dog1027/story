"""Textual 外殼的主畫面：上方固定狀態列、中間捲動的故事、下方選項與輸入框。

只負責顯示與輸入：把玩家的輸入轉成文字送給核心（StoryCore），再依照回覆（Reply）更新畫面。
線上多人（room）時沒有自己的核心：輸入送到網頁伺服器裡的房間，房間把核心的回覆推回來。
"""

import asyncio
import time

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Input, OptionList, Static

from story.core import ChangeGroups, PartyCore, Reply, Status, StoryCore
from story.shells.apikey import forget_api_key, get_saved_api_key, save_api_key
from story.shells.players import Player
from story.shells.room import START, RoomConnection
from story.shells.textual.commands import COMMANDS, help_text
from story.shells.textual.dialogs import ApiKeyDialog, ConfirmDialog, EndingDialog, InfoDialog, NameDialog, PartyNamesDialog, PremiseDialog
from story.shells.textual.prose import Prose
from story.shells.textual.style import CHAR_DELAY, FAST_FACTOR, LEVEL_COLORS, PAUSE_AFTER, SEVERITY_COLORS, SPINNER, THEME, TONE_STYLES


# ---------- 回合間的變化 ----------


def describe_changes(groups: ChangeGroups) -> Text | None:
    """把核心回覆的變化轉成彩色文字，例如「新增 右臂撕裂傷（重）　痊癒 左肘擦傷　獲得 油燈」。"""
    parts: list[tuple[str, str]] = []
    for label, items in groups:
        parts.append((("　" if parts else "") + label + " ", "dim"))
        for i, (text, tone) in enumerate(items):
            parts += [(" · ", "dim")] * bool(i) + [(text, TONE_STYLES[tone])]
    return Text.assemble(*parts) if parts else None


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

    /* 窄畫面（手機）：縮小邊距，讓故事有更多寬度 */
    Screen.-narrow #statusbar { padding: 0 1; }
    Screen.-narrow #mode { width: 9; }
    Screen.-narrow #log { padding: 1 1; }
    Screen.-narrow #timer, Screen.-narrow #choices { margin: 0 0; }
    Screen.-narrow #cmd { margin: 0 0; }
    """
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (60, "-wide")]  # 60 格以下（手機直式）用窄畫面的樣式
    BINDINGS = [
        Binding(key, name.lstrip("/"), desc, priority=key.startswith("ctrl"))
        for name, (key, desc) in COMMANDS.items()
    ] + [
        # 輸入框有焦點時，↑↓ 直接移動選項，不用先切換焦點
        Binding("up", "move_choice(-1)", show=False),
        Binding("down", "move_choice(1)", show=False),
    ]

    def __init__(self, web: bool = False, party: bool = False, room: str | None = None) -> None:
        super().__init__()
        self.web = web  # 網頁版：先問名字，存檔依名字分開，API key 不存到伺服器
        self.party = party  # 多人模式：大家輪流在這台電腦上輸入行動
        self.room_path = room  # 線上多人：房間的 socket；這時不建立自己的核心
        self.room: RoomConnection | None = None
        self.inbox: asyncio.Queue[dict] = asyncio.Queue()  # 房間推來、要依序處理的訊息
        self.suggestion: asyncio.Future | None = None
        self.waiting: list[str] = []  # 線上多人：這回合還沒行動的人
        self.my_name = ""  # 線上多人：自己的名字
        self.actor = ""  # 多人模式：現在輪到誰（線上多人：輪到自己時是自己的名字）
        self.player: Player | None = None
        self.core: StoryCore | None = None
        self.choices: list[str] = []
        self.busy = False
        self.busy_line: Static | None = None  # 故事區裡的「故事生成中」那一行
        self.progress = ""  # 線上多人：房間推來的進度（單人直接讀核心的 progress）
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
        if self.room:
            self.room.close()

    def on_mount(self) -> None:
        self.theme = THEME
        self.set_status(None)
        self.render_mode(False)
        self.set_interval(0.1, self.tick)
        self.boot()

    def watch_app_focus(self, focus: bool) -> None:
        # 網頁版一開始是失焦狀態，這時跳出的對話框不會自動聚焦；回到焦點時 Textual 只還原舊畫面上的焦點，
        # 對話框裡就沒有元件能打字。這裡補上：沒有元件有焦點時，聚焦第一個。
        if focus and self.screen.focused is None:
            self.screen.focus_next()

    # ---------- 啟動：取得 key，建立核心 ----------

    @work
    async def boot(self) -> None:
        if self.room_path:
            await self.join_room()
            return
        if self.web:
            name = await self.push_screen_wait(NameDialog(self.claim_name))
            if name is None:
                self.exit()
                return
            key = await self.ask_api_key(f"{name}，請輸入你的 Gemini API key")
        else:
            key = get_saved_api_key() or await self.ask_api_key("找不到 Gemini API key。")
        if key is None:
            self.exit()
            return
        if self.party:
            names = await self.push_screen_wait(PartyNamesDialog())
            if names is None:
                self.exit()
                return
            self.core = PartyCore(api_key=key, players=names)
        elif self.player:
            self.core = StoryCore(api_key=key, save_path=self.player.save_path, log_path=self.player.log_path)
        else:
            self.core = StoryCore(api_key=key)
        await self.handle(self.core.start())

    async def claim_name(self, name: str) -> str:
        player = Player(name)
        if not player.acquire():
            return "這個名字正在遊戲中，請換一個名字，或等對方離開。"
        self.player = player
        return ""

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
        if not self.party:  # 多人模式的倒數以整回合為單位，換人輸入時繼續跑
            self.stop_timer()
        if echo:
            self.set_choices([])
            self.log_message(f"› {echo}", "action")
        if self.room:  # 線上多人：回覆會由房間推回來
            await self.room.send({"type": "send", "text": text})
            return
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
        self.render_mode(reply.timed)
        self.actor = reply.actor
        if reply.phase != "playing":
            self.stop_timer()
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
            if reply.phase == "ending" and not self.room:  # 線上多人由房間接著寫尾聲
                await self.send("")  # 讓核心接著寫尾聲
        elif reply.phase == "ended":
            await self.show_ending(reply)

    async def ask_premise(self, reply: Reply) -> None:
        if reply.error == "api":
            return  # 開場生成失敗：錯誤已經提示了，留在原處，玩家可以用 Ctrl+R 再試
        timed = reply.timed
        loop = asyncio.get_running_loop()

        def suggest(_: str) -> str:
            if self.room:  # 對話框在背景執行緒呼叫這裡，請房間代問後等結果
                text, error = asyncio.run_coroutine_threadsafe(self.ask_room_suggestion(), loop).result()
                if error:
                    raise RuntimeError(error)
                return text
            suggestion = self.core.send("/suggest")
            if suggestion.error:
                raise RuntimeError(suggestion.notice)
            return suggestion.suggestion

        premise, want_timed = await self.push_screen_wait(PremiseDialog(reply.premise_default, timed, suggest))
        if want_timed != timed:
            command = f"/timed {'on' if want_timed else 'off'}"
            if self.room:
                await self.room.send({"type": "send", "text": command})
            else:
                await asyncio.to_thread(self.core.send, command)
        self.query_one("#log", VerticalScroll).remove_children()
        self.set_choices([])
        self.set_status(None)
        await self.send(premise)

    # ---------- 線上多人：和房間對話 ----------

    async def join_room(self) -> None:
        try:
            self.room = await RoomConnection.open(self.room_path)
        except OSError:
            self.query_one("#status", Static).update(Text("連不上遊戲房間，請稍後重新整理。", style="bold red"))
            return
        name = await self.push_screen_wait(NameDialog(self.claim_seat, hint="大家在同一局裡，每個名字就是一位角色。中途斷線可以用同一個名字回來。"))
        if name is None:
            self.exit()
            return
        self.my_name = name
        self.run_worker(self.listen(), exclusive=False)
        self.run_worker(self.process_inbox(), exclusive=False)

    async def claim_seat(self, name: str) -> str:
        await self.room.send({"type": "join", "name": name})
        answer = await self.room.receive()
        if answer is None:
            return "和遊戲房間的連線中斷了。"
        return answer.get("reason", "") if answer["type"] == "rejected" else ""

    async def listen(self) -> None:
        """收房間推來的訊息。簡單的直接處理；回覆、大廳等要等前一個顯示完的，排進 inbox 依序處理。"""
        while (message := await self.room.receive()) is not None:
            kind = message["type"]
            if kind == "busy":
                self.progress = message.get("progress", "")
                self.set_busy(message["on"])
                if message["on"]:
                    self.show_busy_line()
            elif kind == "timer":
                self.start_timer(message["seconds"])
            elif kind == "waiting":
                self.update_waiting(message["names"])
            elif kind == "notice":
                self.notify(message["text"])
            elif kind == "suggestion" and self.suggestion:
                self.suggestion.set_result((message["text"], message["error"]))
            else:
                self.inbox.put_nowait(message)
        self.set_busy(False)
        self.notify("和遊戲房間的連線中斷了，請重新整理頁面。", severity="error", timeout=30)

    def update_waiting(self, names: list[str]) -> None:
        """這回合還沒行動的人變了：有人行動時跳出通知，並更新提示（不重建選項，畫面才不會閃）。"""
        if set(names) < set(self.waiting):  # 名單變短：有人剛行動（新回合時名單會變回全部的人）
            acted = [n for n in self.waiting if n not in names and n != self.my_name]
            if acted:
                self.notify(f"{'、'.join(acted)} 已行動")
        self.waiting = names
        self.render_turn_hint()

    async def process_inbox(self) -> None:
        while True:
            message = await self.inbox.get()
            kind = message["type"]
            if kind == "reply":
                await self.handle(Reply.from_dict(message["reply"]))
            elif kind == "lobby":
                self.show_lobby(message["members"], message["host"])
            elif kind == "new_story":
                self.query_one("#log", VerticalScroll).remove_children()
                self.set_choices([])
                self.set_status(None)

    async def ask_room_suggestion(self) -> tuple[str, str]:
        self.suggestion = asyncio.get_running_loop().create_future()
        await self.room.send({"type": "send", "text": "/suggest"})
        try:
            return await self.suggestion
        finally:
            self.suggestion = None

    def show_lobby(self, members: list[str], host: str) -> None:
        names = [f"{n}（房主）" if n == host else n for n in members]
        self.query_one("#status", Static).update(Text.assemble(("大廳  ", "dim"), (" · ".join(names), "bold")))
        self.actor, self.waiting = "", []
        me = self.query_one("#cmd", Input)
        if self.my_name == host:
            self.set_choices([START] if len(members) >= 2 else [])
            me.placeholder = "選「開始遊戲」，大家就會一起進入故事" if len(members) >= 2 else "等其他玩家加入（至少 2 人）…"
        else:
            self.set_choices([])
            me.placeholder = f"等房主 {host} 開始遊戲…"

    # ---------- 顯示 ----------

    def set_status(self, status: Status | None, party: list[Status] | None = None) -> None:
        muted = "dim"

        def listed(conds: list[tuple[str, str]], first_sep: str) -> list[tuple[str, str]]:
            parts: list[tuple[str, str]] = []
            for i, (name, severity) in enumerate(conds):
                parts += [(" · " if i else first_sep, muted), (name, SEVERITY_COLORS[severity])]
            return parts

        if party:
            lines = [Text.assemble(("回合 ", muted), (str(party[0].turn), "bold"))]
            for st in party:
                if not st.alive:
                    lines.append(Text.assemble((st.name, "bold dim"), ("  已倒下", muted)))
                    continue
                lines.append(Text.assemble(
                    (st.name, "bold"), ("  ", ""), (st.level, f"bold {LEVEL_COLORS[st.level]}"), *listed(st.body, "  "),
                    *([("     精神 ", muted)] + listed(st.mind, "") if st.mind else []),
                    ("     背包 ", muted), (" · ".join(st.inventory) or "空", ""),
                ))
            self.query_one("#status", Static).update(Text("\n").join(lines))
            return
        if status is None:
            self.query_one("#status", Static).update(Text("Story", style="dim"))
            return

        bar = Text.assemble(
            ("回合 ", muted), (str(status.turn), "bold"),
            ("     狀態 ", muted), (status.level, f"bold {LEVEL_COLORS[status.level]}"), *listed(status.body, "  "),
            *([("     精神 ", muted)] + listed(status.mind, "") if status.mind else []),
            ("     背包 ", muted), (" · ".join(status.inventory) or "空", ""),
        )
        self.query_one("#status", Static).update(bar)

    def log_message(self, text: str | Text, kind: str) -> Static:
        log = self.query_one("#log", VerticalScroll)
        widget = Static(text, classes=kind, markup=False)
        log.mount(widget)
        log.scroll_end(animate=False)
        return widget

    async def show_turn(self, reply: Reply) -> None:
        """有新劇情時逐字顯示，打完才顯示變化與更新狀態列，避免先劇透。"""
        if reply.narration:
            if reply.resumed:
                self.log_message(reply.notice, "action")
            await self.typewrite(reply.narration)
            if changes := describe_changes(reply.changes):
                self.log_message(changes, "changes")
            for name, groups in reply.party_changes:
                self.log_message(Text.assemble((f"{name}　", "bold"), describe_changes(groups)), "changes")
            self.stop_timer()
        self.set_status(reply.status, reply.party)
        self.set_choices(reply.choices)
        if reply.narration and reply.time_limit:
            if self.room:  # 線上多人：告訴房間看完了，大家都看完房間才開始倒數
                await self.room.send({"type": "ready"})
            else:
                self.start_timer(reply.time_limit)

    async def show_ending(self, reply: Reply) -> None:
        ending = reply.ending
        if ending.epilogue:
            self.log_message(f"─── {ending.title} ───", "ending")
            await self.typewrite(ending.epilogue)
        else:
            self.log_message("─── 故事結束 ───", "ending")
        await self.wait_for_enter("按 Enter 查看結局")
        if not await self.push_screen_wait(EndingDialog(ending.title, ending.record)):
            self.exit()
        elif not self.room:  # 線上多人：房間會自動回到大廳
            await self.send("1")

    async def wait_for_enter(self, hint: str) -> None:
        line = self.log_message(f"（{hint}）", "busy")
        self.continue_event = asyncio.Event()
        self.query_one("#cmd", Input).focus()
        await self.continue_event.wait()
        self.continue_event = None
        line.remove()

    async def typewrite(self, text: str) -> None:
        """一個字一個字顯示。按 Enter 加速，再按一次直接顯示全部。"""
        log = self.query_one("#log", VerticalScroll)
        widget = Prose(classes="narration")  # 懂中文換行規則的文字區塊
        log.mount(widget)
        self.typing, self.speed, self.skip = True, 1.0, False
        try:
            for i, ch in enumerate(text, 1):
                if self.skip:
                    break
                widget.set_text(text[:i])
                log.scroll_end(animate=False)
                await asyncio.sleep((CHAR_DELAY + PAUSE_AFTER.get(ch, 0)) * self.speed)
        finally:
            widget.set_text(text)
            log.scroll_end(animate=False)
            self.typing = False

    def set_choices(self, choices: list[str]) -> None:
        self.choices = list(choices)
        options = self.query_one("#choices", OptionList)
        self.render_turn_hint()
        options.clear_options()
        options.add_options([f"{i}. {c}" for i, c in enumerate(choices, 1)])
        options.set_class(not choices, "-empty")
        if choices:
            options.styles.opacity = 0.0
            options.styles.animate("opacity", 1.0, duration=0.4)
        self.query_one("#cmd", Input).focus()

    def render_turn_hint(self) -> None:
        """選項框的標題與輸入框的提示：輪到誰；線上多人時還在等誰。"""
        self.query_one("#choices", OptionList).border_title = f"輪到 {self.actor}" if self.actor else "接下來"
        cmd = self.query_one("#cmd", Input)
        cmd.placeholder = f"輪到 {self.actor}：↑↓ 選擇，或寫下行動" if self.actor else "↑↓ 選擇，或寫下你的行動"
        if self.room and not self.actor and self.waiting:
            cmd.placeholder = f"等待 {'、'.join(self.waiting)} 行動…"

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
            self.busy_line = self.log_message(self.busy_text(), "busy")

    def busy_text(self) -> str:
        """等待那一行的文字，例如「⠋ 故事生成中：規劃故事大綱…」。"""
        progress = self.progress if self.room else (self.core.progress if self.core else "")
        return f"{SPINNER[self.frame]} 故事生成中{'：' + progress if progress else ''}…"

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
            self.busy_line.update(self.busy_text())
        # 開著對話框或指令選單時暫停倒數（線上多人大家共用一個倒數，不能暫停）
        if self.time_left <= 0 or self.busy or (not self.room and isinstance(self.screen, ModalScreen)):
            return
        self.time_left = max(0.0, self.time_left - elapsed)
        self.render_timer()
        if self.time_left == 0:
            self.stop_timer()
            if self.room:
                return  # 時間到由房間送出
            self.run_worker(self.send("/timeout", echo=self.core.action_for("/timeout") or ""))

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
        if not self.connected or self.busy:
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
        self.run_worker(self.send(raw, echo=self.echo_for(raw)))

    def choose_index(self, index: int) -> None:
        text = str(index + 1)
        self.run_worker(self.send(text, echo=self.echo_for(text)))

    @property
    def connected(self) -> bool:
        return self.core is not None or self.room is not None

    def echo_for(self, text: str) -> str:
        """送出前先顯示的行動；多人模式加上是誰的行動。"""
        if self.room:  # 線上多人沒有自己的核心：輪到自己時，照畫面上的選項對應
            if not self.actor or text.startswith("/"):
                return ""
            index = int(text) - 1 if text.isdigit() else -1
            action = self.choices[index] if 0 <= index < len(self.choices) else text
        else:
            action = self.core.action_for(text) or ""
        return f"{self.actor}：{action}" if action and self.actor else action

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
        if self.connected and not self.busy:
            self.run_worker(self.send("/state"))

    def action_help(self) -> None:
        self.push_screen(InfoDialog("指令", help_text()))

    def action_restart(self) -> None:
        if self.connected and not self.busy and not self.typing:
            self.run_worker(self.send("/restart"))

    def action_quit(self) -> None:
        self.exit()  # 每回合都已自動存檔
