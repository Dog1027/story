"""外殼共用層：跟真人玩家互動的流程，終端機、網頁等介面都用這一層。

分工：
- 核心（story.core）：遊戲規則、AI、存檔。送文字進去、拿 Reply 出來，沒有時間感，也不知道畫面的存在。
- 這一層（Client）：「什麼時候顯示什麼」。依回覆的階段跳出哪個對話框、打完字才顯示選項、
  大家看完才倒數、結局一段一段出現……終端機版用 LocalClient（自己的核心），網頁版用 room_client.py 的
  RoomClient（連進大廳與房間），兩者只差在把輸入交給誰、回覆從哪裡來。
- 介面（View 的實作，例如 Textual 的 StoryApp）：只負責「長什麼樣子」，把 View 的每個方法畫出來，
  再把玩家的輸入交給 Client（act、command、timeout）。

新功能盡量改在這一層；只有新的畫面元素才需要在每個介面各加一點顯示程式。
判斷標準：改變遊戲結果或事實 → 核心；改變真人看到的順序、時機、流程 → 這一層；改變長相 → 介面。
"""

import asyncio
from dataclasses import dataclass, field

from story.core import ChangeGroups, Ending, Reply, Status, StoryCore, ui_text, word
from story import settings
from story.shells.players import MAX_NAME_LEN, InvalidName, check_name

# 介面的對話框也會用到的規則（名字怎樣才能用、key 存在哪裡），一律從這裡取用
CONFIG_PATH = settings.CONFIG_PATH
__all__ = ["CONFIG_PATH", "MAX_NAME_LEN", "CharacterLine", "Client", "LocalClient", "StatusLine", "View", "status_line"]

UI = ui_text("shells")  # 外殼共用的文字（story/ui/語言/shells.md）
BUSY_DELAY = 0.15  # 核心超過這麼久還沒回覆才顯示「故事生成中」，很快的回覆就不閃一下
DRAFT_POLL = 0.1  # 等核心時每隔幾秒看一次 AI 寫到哪裡（串流），有新的字就先顯示


# ---------- 給介面的顯示資料：只說內容與程度，不說顏色與排版 ----------


@dataclass
class CharacterLine:
    """狀態列上一位角色（只有一位角色時不顯示名字，見 StatusLine.named）。"""

    name: str
    alive: bool
    warning: str  # 整體狀態的代號（serious、dying）：要醒目地警告；平常是空字串
    warning_text: str  # 警告顯示的詞，例如「重傷」
    items: list[tuple[str, str]]  # (文字, 語氣)：每個狀態的名稱與程度的代號，不分身體與精神；沒有狀態時是 [("良好", "healthy")]


@dataclass
class StatusLine:
    turn: int
    mode: str  # 「限時模式」或「一般模式」，跟回合寫在同一排
    timed: bool
    characters: list[CharacterLine] = field(default_factory=list)
    named: bool = False  # 好幾位角色：每位角色一列，列出名字


def character_line(status: Status) -> CharacterLine:
    # 哪些程度要警告是遊戲規則，由核心判斷（status.warning）
    warning_text = word("level", status.warning) if status.warning else ""
    items = list(status.conditions) or [(word("level", "healthy"), "healthy")]
    return CharacterLine(status.name, status.alive, status.warning, warning_text, items)


def status_line(turn: int, characters: list[Status], timed: bool) -> StatusLine | None:
    """只有一位角色時不列名字；好幾位時每位角色一列。"""
    if not characters:
        return None
    mode = UI["mode_timed" if timed else "mode_normal"]
    return StatusLine(turn, mode, timed, [character_line(s) for s in characters], named=len(characters) > 1)


# ---------- 介面要實作的方法 ----------


class View:
    """介面要提供的功能。Client 依照遊戲流程呼叫這些方法，介面只負責畫出來。
    async 的方法要等玩家看完或回答完才回傳。"""

    # 故事區
    def clear_story(self, premise: str) -> None:
        """新故事開始：清空故事區、選項與狀態列，先顯示故事前提（可能是空字串）。"""
        raise NotImplementedError

    def show_action(self, text: str) -> None:
        """玩家剛做的行動（自己剛送出時要捲到最底看結果）。"""
        raise NotImplementedError

    def show_note(self, text: str) -> None:
        """故事區裡的一行說明，例如讀取存檔時的「讀取存檔：……」。"""
        raise NotImplementedError

    def start_narration(self) -> None:
        """開始顯示一段劇情（例如打字效果）。文字會陸續由 extend_narration() 給；等待提示要一併收起。"""
        raise NotImplementedError

    def extend_narration(self, text: str) -> None:
        """這段劇情目前收到的全文（AI 還在寫，會越來越長）。"""
        raise NotImplementedError

    async def finish_narration(self, text: str) -> None:
        """這段劇情的完整內容；全部顯示完才回傳。"""
        raise NotImplementedError

    def discard_narration(self) -> None:
        """收回還沒寫完的這段劇情（AI 出錯，這回合沒有推進）。"""
        raise NotImplementedError

    def show_changes(self, groups: ChangeGroups, name: str = "") -> None:
        """回合間的變化（新增、痊癒、獲得……）；好幾位角色時有角色名字，一個人玩是空的。"""
        raise NotImplementedError

    def show_ending_title(self, title: str) -> None:
        raise NotImplementedError

    async def wait_enter(self, hint: str) -> None:
        """停下來，等玩家按 Enter 再繼續。"""
        raise NotImplementedError

    # 選項與輸入
    def prepare_choices(self, choices: list[str], timed: bool) -> None:
        """劇情還在顯示時先放好選項但還看不見（介面可以先佔好版面）；timed 時也會有倒數條。"""
        raise NotImplementedError

    def show_choices(self, choices: list[str]) -> None:
        """顯示選項（prepare_choices 放好的就是讓它出現）。"""
        raise NotImplementedError

    def set_hint(self, placeholder: str) -> None:
        """輸入框的提示，例如網頁版行動完之後的「等待 小華 行動…」。"""
        raise NotImplementedError

    def set_status(self, status: StatusLine | None) -> None:
        raise NotImplementedError

    def show_lobby(self, title: str, members: list[str]) -> None:
        """網頁版的大廳或房間的等人畫面：狀態列顯示標題（「大廳」「阿明 的房間」）與在這裡的人。"""
        raise NotImplementedError

    def set_busy(self, busy: bool) -> None:
        """核心在忙：不接受輸入。"""
        raise NotImplementedError

    def show_busy(self) -> None:
        """顯示等待的提示（文字用 client.busy_text()，會隨進度改變）。"""
        raise NotImplementedError

    # 限時模式：介面負責倒數，時間到呼叫 client.timeout()
    def start_timer(self, seconds: int) -> None:
        raise NotImplementedError

    def stop_timer(self) -> None:
        raise NotImplementedError

    # 通知與對話框
    def notify(self, text: str, error: bool = False, lasting: bool = False) -> None:
        raise NotImplementedError

    def show_info(self, title: str, body: str) -> None:
        raise NotImplementedError

    async def ask_confirm(self, question: str, yes: str, no: str) -> bool:
        raise NotImplementedError

    async def ask_premise(self, reply: Reply, ask) -> tuple[str, bool, str] | None:
        """開新故事：回傳 (前提, 要不要限時, 題材)。ask(*指令) 會在背景執行緒呼叫，送指令給核心並回傳最後一個回覆
        （換題材、換一個、幫我想）。"""
        raise NotImplementedError

    async def ask_ending(self, title: str, record: str) -> bool:
        """顯示結局與旅程紀錄，回傳要不要再玩一次。"""
        raise NotImplementedError

    async def ask_name(self, hint: str, error: str) -> str | None:
        """問名字，回傳玩家輸入的文字（取消時 None）。error 是上一次不能用的原因，第一次是空字串；hint 空白時用介面自己的說明。"""
        raise NotImplementedError

    async def ask_api_key(self, reason: str) -> tuple[str, bool] | None:
        """終端機版：key 無效或沒有時問玩家。回傳 (key, 要不要存起來)。"""
        raise NotImplementedError

    def exit(self) -> None:
        raise NotImplementedError


# ---------- 共用的流程 ----------


class Client:
    """跟真人玩家互動的流程，終端機版（LocalClient）與網頁版（RoomClient，room_client.py）共用：
    一回合怎麼出現、結局怎麼一段一段出現、狀態列、輸入框的提示。兩邊不一樣的地方（把輸入交給誰、回覆從哪裡來）是下面的掛勾。"""

    def __init__(self, view: View):
        self.view = view
        self.actor = ""  # 自己這回合還沒行動時是自己的名字，行動完是空的
        self.choices: list[str] = []
        self.draft = ""  # 已經交給介面、還在串流中的劇情
        self.busy = False
        self.timed = False
        self.shown: tuple[int, list[Status]] = (0, [])  # 狀態列目前的內容：(回合, 每位角色)，模式改變時重畫

    # ---------- 兩邊各自的掛勾 ----------

    @property
    def connected(self) -> bool:
        raise NotImplementedError

    async def run(self) -> None:
        raise NotImplementedError

    async def deliver(self, text: str) -> None:
        """把一句輸入交給核心或房間；回覆由各自的方式交給 handle()。"""
        raise NotImplementedError

    async def deliver_quietly(self, text: str) -> None:
        """前提對話框選好的模式與題材：交給核心或房間，回覆不需要顯示。"""
        raise NotImplementedError

    def premise_asker(self):
        """前提對話框用的 ask(*指令)：在背景執行緒呼叫，送出指令並回傳最後一個回覆（換題材、換一個、幫我想）。"""
        raise NotImplementedError

    def echo_for(self, text: str) -> str:
        """送出前先顯示的行動。"""
        raise NotImplementedError

    def progress(self) -> str:
        """等待時目前在做什麼（例如「規劃故事大綱」）。"""
        raise NotImplementedError

    async def timeout(self) -> None:
        """介面的倒數到了。"""

    async def narration_read(self, reply: Reply) -> None:
        """限時的一回合顯示完了：開始倒數（或告訴房間看完了）。"""

    async def story_over(self) -> None:
        """故事剛結束：接著寫尾聲。"""

    async def play_again(self) -> None:
        """玩家在結局選了再玩一次。"""

    def close(self) -> None:
        pass

    # ---------- 共用的流程 ----------

    @property
    def ready(self) -> bool:
        """可以接受玩家的輸入。"""
        return self.connected and not self.busy

    async def ask_name(self, claim, hint: str = "") -> str | None:
        """問名字，不能用時帶著原因再問。claim(名字) 負責佔用這個名字：成功回傳空字串，否則是不能用的原因。"""
        error = ""
        while True:
            raw = await self.view.ask_name(hint, error)
            if raw is None:
                return None
            try:
                name = check_name(raw)
            except InvalidName as e:
                error = str(e)
                continue
            if not (error := await claim(name)):
                return name

    async def act(self, text: str) -> None:
        """玩家的行動：選項編號或自由輸入。先在故事區顯示行動，再送出。"""
        await self.send(text, echo=self.echo_for(text))

    async def command(self, text: str) -> None:
        """指令（/state、/restart 等），不顯示在故事區。"""
        await self.send(text)

    async def send(self, text: str, echo: str = "") -> None:
        """送一句文字並顯示回覆。echo 是要先顯示在故事區的玩家行動。"""
        if self.busy:
            return
        self.view.stop_timer()
        if echo:
            self.set_choices([])
            self.view.show_action(echo)
        await self.deliver(text)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.view.set_busy(busy)

    def follow_draft(self, draft: str) -> None:
        """AI 正在寫的劇情有新的字：先交給介面顯示。"""
        if draft and draft != self.draft:
            self._continue_narration(draft)
            self.draft = draft
            self.view.extend_narration(draft)

    async def narrate(self, text: str) -> None:
        """顯示一段完整的劇情；已經在串流顯示的就接著顯示完。"""
        self._continue_narration(text)
        self.draft = ""
        await self.view.finish_narration(text)

    def _continue_narration(self, text: str) -> None:
        """text 接在已經顯示的劇情後面就繼續；不是的話（AI 重寫了）收回舊的，重新開始一段。"""
        if self.draft and not text.startswith(self.draft):
            self.discard_draft()
        if not self.draft:
            self.view.start_narration()

    def discard_draft(self) -> None:
        self.view.discard_narration()
        self.draft = ""

    def busy_text(self) -> str:
        """等待提示的文字，例如「故事生成中：規劃故事大綱…」。"""
        progress = self.progress()
        return UI["busy"].format(progress=UI["busy_progress"].format(progress=progress) if progress else "")

    async def handle(self, reply: Reply) -> None:
        """依照回覆的階段決定接下來的流程。"""
        if self.draft and not reply.narration:  # 串流到一半出錯，這回合沒有推進：收回寫到一半的劇情
            self.discard_draft()
        if reply.timed != self.timed:
            self.timed = reply.timed
            self.view.set_status(status_line(*self.shown, self.timed))
        self.actor = reply.actor
        if reply.phase != "playing":
            self.view.stop_timer()
        if reply.info:
            self.view.show_info(*reply.info)
        if reply.error == "api":
            self.view.notify(reply.notice, error=True)
        elif reply.notice and reply.phase in ("playing", "ending", "ended") and not reply.narration:
            self.view.notify(reply.notice)

        if reply.phase == "ask_continue":
            yes, no = reply.choices  # 核心給的「繼續」「開新遊戲」
            keep = await self.view.ask_confirm(UI["ask_continue"].format(notice=reply.notice), yes=yes, no=no)
            await self.send("1" if keep else "2")
        elif reply.phase == "ask_premise":
            await self.ask_premise(reply)
        elif reply.phase == "confirm_restart":
            sure = await self.view.ask_confirm(reply.notice, *reply.choices)  # 核心給的「確定」「取消」
            await self.send("1" if sure else "2")
        elif reply.phase in ("playing", "ending"):
            await self.show_turn(reply)
            if reply.phase == "ending":
                await self.story_over()
        elif reply.phase == "ended":
            await self.show_ending(reply.ending)

    async def ask_premise(self, reply: Reply) -> None:
        if reply.error == "api":
            return  # 開場生成失敗：錯誤已經提示了，留在原處，玩家可以用 /restart 再試
        answer = await self.view.ask_premise(reply, self.premise_asker())
        if answer is None:
            return
        premise, want_timed, genre = answer
        for command in [f"/timed {'on' if want_timed else 'off'}"] * (want_timed != reply.timed) + [f"/genre {genre}"]:
            await self.deliver_quietly(command)
        self.clear_story(premise)
        await self.send(premise)

    # ---------- 顯示一回合與結局 ----------

    async def show_turn(self, reply: Reply) -> None:
        """有新劇情時先顯示劇情，顯示完才出現變化、選項與更新狀態列，避免先劇透。"""
        if reply.narration:
            self.view.stop_timer()
            self.choices = list(reply.choices)
            self.view.prepare_choices(self.choices, timed=bool(reply.time_limit))
            self.refresh_hint()
            if reply.resumed:
                self.view.show_note(reply.notice)
            await self.narrate(reply.narration)
            for name, groups in reply.changes:
                self.view.show_changes(groups, name if len(reply.characters) > 1 else "")  # 一個人玩不用寫名字
            self.view.show_choices(self.choices)
        else:
            self.set_choices(reply.choices)
        self.set_status(reply.turn, reply.characters)
        if reply.narration and reply.time_limit:
            await self.narration_read(reply)

    async def show_ending(self, ending: Ending) -> None:
        """一段一段來：先讀完最後的劇情，按 Enter 才出現尾聲，再按一次才看總結。"""
        if ending.epilogue:
            await self.view.wait_enter(UI["wait_epilogue"])
            self.view.show_ending_title(ending.title)
            await self.narrate(ending.epilogue)
        else:
            self.view.show_ending_title(UI["story_over"])
        await self.view.wait_enter(UI["wait_ending"])
        if not await self.view.ask_ending(ending.title, ending.record):
            self.view.exit()
        else:
            await self.play_again()

    def clear_story(self, premise: str = "") -> None:
        self.choices = []
        self.shown = (0, [])
        self.view.clear_story(premise)
        self.refresh_hint()

    def set_choices(self, choices: list[str]) -> None:
        self.choices = list(choices)
        self.view.show_choices(self.choices)
        self.refresh_hint()

    def set_status(self, turn: int, characters: list[Status]) -> None:
        self.shown = (turn, characters)
        self.view.set_status(status_line(turn, characters, self.timed))

    def refresh_hint(self) -> None:
        self.view.set_hint(UI["hint_input"])


class LocalClient(Client):
    """終端機版：自己有一個核心（一個人玩，一人隊伍），在背景執行緒呼叫它。"""

    def __init__(self, view: View):
        super().__init__(view)
        self.core: StoryCore | None = None

    @property
    def connected(self) -> bool:
        return self.core is not None

    async def run(self) -> None:
        key = settings.api_key() or await self.ask_api_key(UI["ask_missing_key"])
        if key is None:
            self.view.exit()
            return
        self.core = StoryCore(key, [settings.get("name") or UI["default_name"]])
        await self.handle(self.core.start())

    async def ask_api_key(self, reason: str) -> str | None:
        result = await self.view.ask_api_key(reason)
        if result is None:
            return None
        key, keep = result
        if keep:
            settings.put("api_key", key)
        return key

    async def deliver(self, text: str) -> None:
        reply = await self.ask_core(text)
        if reply is not None:
            await self.handle(reply)

    async def deliver_quietly(self, text: str) -> None:
        await asyncio.to_thread(self.core.send, text)

    def premise_asker(self):
        def ask(*commands: str) -> Reply:
            for command in commands:
                answer = self.core.send(command)
            return answer

        return ask

    def echo_for(self, text: str) -> str:
        return self.core.action_for(text) or ""

    def progress(self) -> str:
        return self.core.progress if self.core else ""

    async def timeout(self) -> None:
        if self.core is not None:
            await self.send("/timeout", echo=self.core.action_for("/timeout") or "")

    async def narration_read(self, reply: Reply) -> None:
        self.view.start_timer(reply.time_limit)

    async def story_over(self) -> None:
        await self.send("")  # 讓核心接著寫尾聲

    async def play_again(self) -> None:
        await self.send("1")

    async def ask_core(self, text: str) -> Reply | None:
        """在背景執行緒呼叫核心；超過一下子才顯示等待提示。key 無效時請玩家換一個再重送。"""
        self.set_busy(True)
        try:
            while True:
                task = asyncio.create_task(asyncio.to_thread(self.core.send, text))
                waited = 0.0
                while not task.done():
                    await asyncio.wait({task}, timeout=DRAFT_POLL)
                    waited += DRAFT_POLL
                    self.follow_draft(self.core.draft)
                    if waited >= BUSY_DELAY and not self.draft:
                        self.view.show_busy()
                reply = await task
                if reply.error != "api_key":
                    return reply
                settings.put("api_key", None)
                self.set_busy(False)
                key = await self.ask_api_key(UI["ask_new_key"])
                if key is None:
                    return reply
                self.core.set_api_key(key)
                self.set_busy(True)
        finally:
            self.set_busy(False)
