"""外殼共用層：跟真人玩家互動的流程。每個瀏覽器分頁一個 Client，連進大廳與房間。

分工：
- 核心（story.core）與玩法（story.games）：遊戲規則、AI、存檔。送文字進去、拿 Reply 出來，沒有時間感，也不知道畫面的存在。
- 大廳與房間（lobby.py、room.py）：誰在哪個房間、把每個人的輸入交給核心、把回覆送給房間裡的每個人。
- 這一層（Client）：「什麼時候顯示什麼」。依回覆的階段跳出哪個對話框、打完字才顯示選項、
  大家看完才倒數、結局一段一段出現……
- 介面（View 的實作，網頁版的 WebView）：只負責「長什麼樣子」，把 View 的每個方法畫出來，
  再把玩家的輸入交給 Client（act、command）。

新功能盡量改在這一層；只有新的畫面元素才需要在介面加一點顯示程式。
判斷標準：改變遊戲結果或事實 → 核心；改變真人看到的順序、時機、流程 → 這一層；改變長相 → 介面。
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from story.core import ChangeGroups, Ending, InputMode, Reply, Status, pick_choice
from story.games import GENRE_AUTO, GENRE_NONE
from story.shells.connection import Connection
from story.shells.lobby import Lobby
from story.shells.players import MAX_NAME_LEN, InvalidName, check_name
from story.shells.text import ui_text

# 介面的對話框也會用到的規則（名字怎樣才能用），一律從這裡取用
__all__ = ["MAX_NAME_LEN", "CharacterLine", "Client", "PremiseForm", "StatusLine", "View", "status_line"]

UI = ui_text("shells")  # 外殼共用的文字（story/shells/ui/語言/shells.md）
DIALOGS = ui_text("dialogs")  # 對話框的文字（story/shells/ui/語言/dialogs.md）


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
    # 哪些程度要警告是遊戲規則，由玩法判斷（status.warning），顯示的詞也由玩法給
    items = list(status.conditions) or ([(status.fine, "healthy")] if status.fine else [])
    return CharacterLine(status.name, status.alive, status.warning, status.warning_text, items)


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

    def show_past_narration(self, text: str) -> None:
        """讀檔、重新連線時之前的劇情：直接整段顯示，不用打字效果，也不捲動。"""
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

    def mark_choice(self, index: int) -> None:
        """標出目前選的輸入方式（海龜湯的「提問」「猜湯底」，見 Reply.inputs）；-1 是取消標記。不需要的介面可以不做。"""

    def set_hint(self, placeholder: str) -> None:
        """輸入框的提示，例如網頁版行動完之後的「等待 小華 行動…」。"""
        raise NotImplementedError

    def set_status(self, status: StatusLine | None) -> None:
        raise NotImplementedError

    def show_lobby(self, screen: dict) -> None:
        """網頁版的大廳或房間的等人畫面，內容見 lobby.py、room.py 開頭的說明（view 是 lobby 或 room）。
        choices 裡的選項畫成按鈕，按下時用 client.act(編號) 送出。"""
        raise NotImplementedError

    def set_busy(self, busy: bool) -> None:
        """核心在忙：不接受輸入。"""
        raise NotImplementedError

    def show_busy(self) -> None:
        """顯示等待的提示（文字用 client.busy_text()，會隨進度改變）。"""
        raise NotImplementedError

    # 限時模式：房間負責計時，時間到由房間送出；介面只顯示倒數
    def start_timer(self, seconds: int) -> None:
        raise NotImplementedError

    def stop_timer(self) -> None:
        raise NotImplementedError

    # 通知與對話框
    def notify(self, text: str, error: bool = False, lasting: bool = False) -> None:
        raise NotImplementedError

    def show_activity(self, text: str) -> None:
        """簡短、不擋住劇情的動態（例如網頁版「小華 已行動」），一下子就消失。不需要的介面可以不做。"""

    def show_info(self, title: str, body: str) -> None:
        raise NotImplementedError

    async def ask_confirm(self, question: str, yes: str, no: str) -> bool:
        raise NotImplementedError

    async def ask_premise(self, form: "PremiseForm") -> tuple[str, bool, str] | None:
        """開新故事的對話框：照 form 畫出題材選單、題材介紹、預設的開頭、限時模式；玩家的操作交給 form，
        照它回傳的結果更新文字框。按開始時回傳 form.finish(文字框, 要不要限時)，離開時 None。"""
        raise NotImplementedError

    async def ask_ending(self, title: str, record: str) -> bool:
        """顯示結局與旅程紀錄，回傳要不要再玩一次。"""
        raise NotImplementedError

    async def ask_name(self, hint: str, error: str) -> str | None:
        """問名字，回傳玩家輸入的文字（取消時 None）。error 是上一次不能用的原因，第一次是空字串；hint 空白時用介面自己的說明。"""
        raise NotImplementedError

    def exit(self) -> None:
        raise NotImplementedError


# ---------- 新故事的對話框 ----------


class PremiseForm:
    """新故事對話框的規則：介面只負責畫出來，把玩家的操作交給這裡，照回傳的文字更新文字框。
    回傳 None 時文字框保持原樣（玩家改過了，或這個結果已經被後來的操作取代）。"""

    def __init__(self, reply: Reply, request: Callable[..., Awaitable[Reply]]):
        self.default = reply.premise_default  # 目前預設的開頭：文字框留白、或玩家沒改過時用它
        self.timed = reply.timed
        self.genres = dict(reply.genres)  # 可選的題材：名稱 → 描述；沒有題材包時是空的，介面不顯示題材選單
        known = (GENRE_AUTO, GENRE_NONE, *self.genres)
        self.genre = reply.genre if not self.genres or reply.genre in known else GENRE_AUTO
        self.request = request  # 送指令給核心，見 Client.ask_room()
        self.asking = asyncio.Lock()  # 一次只送一個：核心不能同時處理兩個請求
        self.latest = 0  # 最新一次操作的編號

    def genre_options(self) -> list[tuple[str, str]]:
        """題材選單：(顯示的文字, 題材)。自動、不指定在最前面。"""
        if not self.genres:
            return []
        return [(DIALOGS["genre_auto_option"], GENRE_AUTO), (DIALOGS["genre_none_option"], GENRE_NONE)] + [
            (DIALOGS["genre_option"].format(name=name), name) for name in self.genres
        ]

    def genre_hint(self, choice: str) -> str:
        """選單下面的題材介紹。"""
        if choice == GENRE_AUTO:
            return DIALOGS["genre_auto_hint"]
        if choice == GENRE_NONE:
            return DIALOGS["genre_none_hint"]
        return self.genres.get(choice, "")

    async def change_genre(self, choice: str, text: str) -> str | None:
        """換題材：隨機抽到的開頭也換成新題材的（玩家改過文字框就不換）。text 是文字框目前的內容。"""
        self.genre = choice
        reply = await self._ask(f"/genre {choice}")
        return None if reply is None or reply.error else self._new_default(reply.premise_default, text)

    async def reroll(self, text: str) -> str | None:
        """換一個：從題材包的開頭靈感裡重抽，不用等 AI。玩家按了就一定換掉文字框。"""
        reply = await self._ask(f"/genre {self.genre}", "/random")
        return None if reply is None or reply.error else self._new_default(reply.premise_default, text, replace=True)

    async def suggest(self, text: str) -> str:
        """幫我想：請 AI 想一個開頭，一定換掉文字框。失敗時丟出 RuntimeError（介面提示就好，不中斷開新局）。"""
        reply = await self._ask(f"/genre {self.genre}", "/suggest", latest_only=False)
        if reply.error:
            raise RuntimeError(reply.notice)
        return self._new_default(reply.suggestion, text, replace=True)

    def finish(self, text: str, timed: bool) -> tuple[str, bool, str]:
        """按開始：(前提, 要不要限時, 題材)。文字框留白就用預設的開頭。"""
        return " ".join(text.split()) or self.default, timed, self.genre

    async def _ask(self, *commands: str, latest_only: bool = True) -> Reply | None:
        """latest_only 時，等待期間又有新的操作（例如快速切換題材）就回傳 None，舊的結果不用了。"""
        self.latest += 1
        mine = self.latest
        async with self.asking:
            reply = await self.request(*commands)
        return reply if not latest_only or mine == self.latest else None

    def _new_default(self, premise: str, text: str, replace: bool = False) -> str | None:
        edited = " ".join(text.split()) not in ("", " ".join(self.default.split()))
        self.default = premise
        return None if edited and not replace else premise


# ---------- 共用的流程 ----------


class Client:
    """一個瀏覽器分頁跟真人玩家互動的流程：連進網頁伺服器的大廳（lobby.py），在房間（room.py）裡玩。
    一回合怎麼出現、結局怎麼一段一段出現、狀態列、輸入框的提示都在這裡。

    沒有自己的核心：輸入送到房間，回覆、進度、正在寫的劇情由房間推回來，再照回覆的階段交給 View 顯示。"""

    def __init__(self, view: View, lobby: Lobby | None, token: str = ""):
        self.view = view
        self.lobby = lobby
        self.token = token  # 瀏覽器記住的識別碼：同一個瀏覽器再連進來時，新的連線取代舊的（見 lobby.py）
        self.room: Connection | None = None  # 和大廳（與房間）的連線
        self.replaced = False
        self.my_name = ""
        self.actor = ""  # 自己這回合還沒行動時是自己的名字，行動完是空的
        self.choices: list[str] = []
        self.inputs: list[InputMode] = []  # 輸入的方式（海龜湯）：有的話，選項是切換方式，打的字用目前的方式送出
        self.input_mode = 0  # 目前選的方式（inputs 的索引）
        self.draft = ""  # 已經交給介面、還在串流中的劇情
        self.busy = False
        self.timed = False
        self.shown: tuple[int, list[Status]] = (0, [])  # 狀態列目前的內容：(回合, 每位角色)，模式改變時重畫
        self.waiting: list[str] = []  # 這回合還沒行動的人
        self.progress = ""  # 房間推來的進度（例如「規劃故事大綱」）
        self.inbox: asyncio.Queue[dict] = asyncio.Queue()  # 房間推來、要依序處理的訊息
        self.premise_answer: asyncio.Future | None = None  # 前提對話框在等房間回覆

    @property
    def ready(self) -> bool:
        """可以接受玩家的輸入：連線還在（斷了再送會丟出 ConnectionError），也不在等 AI。"""
        return self.room is not None and self.room.open and not self.busy

    async def run(self) -> None:
        self.room = self.lobby.connect()
        name = await self.ask_name(self.claim_seat)
        if name is None:
            self.view.exit()
            return
        self.my_name = name
        inbox = asyncio.create_task(self.process_inbox())
        try:
            await self.listen()
        finally:
            inbox.cancel()

    def close(self) -> None:
        if self.room:
            self.room.close()

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
        if self.inputs and self.actor:
            await self.act_with_inputs(text)
        else:
            await self.send(text, echo=self.echo_for(text))

    def echo_for(self, text: str) -> str:
        """送出前先顯示的行動：還沒行動時，照畫面上的選項對應；指令不顯示。"""
        if not self.actor or text.startswith("/"):
            return ""
        return pick_choice(text, self.choices) or text

    async def act_with_inputs(self, text: str) -> None:
        """有輸入方式時（海龜湯）：選了要打字的方式就切換過去，等玩家打字；不用打字的直接送出；打的字用目前的方式送出。"""
        labels = [m.label for m in self.inputs]
        if (picked := pick_choice(text, labels)) is not None:
            index = labels.index(picked)
            mode = self.inputs[index]
            if not mode.needs_text:
                await self.send(mode.command, echo=mode.label)
                return
            self.input_mode = index
            self.view.mark_choice(index)
            self.refresh_hint()
            return
        mode = self.inputs[self.input_mode]
        await self.send(f"{mode.command} {text}", echo=UI["input_echo"].format(label=mode.label, text=text))

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

    async def deliver(self, text: str) -> None:
        """把一句輸入交給房間；回覆會由房間推回來。"""
        await self.room.send({"type": "send", "text": text})

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
        progress = self.progress
        return UI["busy"].format(progress=UI["busy_progress"].format(progress=progress) if progress else "")

    async def handle(self, reply: Reply) -> None:
        """依照回覆的階段決定接下來的流程。"""
        if reply.phase != "playing":
            self.waiting = []  # 這一局的行動結束了（結局、回到前提……）：提示不再寫「等待 X 行動」
        if self.draft and not reply.narration:  # 串流到一半出錯，這回合沒有推進：收回寫到一半的劇情
            self.discard_draft()
        if reply.timed != self.timed:
            self.timed = reply.timed
            self.view.set_status(status_line(*self.shown, self.timed))
        self.actor = reply.actor
        if reply.inputs != self.inputs or reply.narration:  # 新的一回合：回到第一個方式（提問）
            self.inputs, self.input_mode = list(reply.inputs), 0
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
        elif reply.phase in ("confirm_restart", "ask_puzzle"):
            sure = await self.view.ask_confirm(reply.notice, *reply.choices)  # 核心給的兩個選項：確定／取消、題庫／AI 出題
            await self.send("1" if sure else "2")
        elif reply.phase in ("playing", "ending"):
            await self.show_turn(reply)  # 結束的這一回合；接著房間會寫尾聲
        elif reply.phase == "ended":
            await self.show_ending(reply.ending)

    async def ask_premise(self, reply: Reply) -> None:
        if reply.error == "api":
            return  # 開場生成失敗：錯誤已經提示了，留在原處，玩家可以用 /restart 再試
        answer = await self.view.ask_premise(PremiseForm(reply, self.ask_room))
        if answer is None:
            return
        premise, want_timed, genre = answer
        for command in [f"/timed {'on' if want_timed else 'off'}"] * (want_timed != reply.timed) + [f"/genre {genre}"]:
            await self.deliver(command)  # 前提對話框選好的模式與題材：回覆不需要顯示
        self.clear_story(premise)
        await self.send(premise)

    # ---------- 顯示一回合與結局 ----------

    async def show_turn(self, reply: Reply) -> None:
        """有新劇情時先顯示劇情，顯示完才出現變化、選項與更新狀態列，避免先劇透。"""
        if reply.narration:
            self.view.stop_timer()
            if reply.resumed:  # 讀檔、重新連線：從乾淨的畫面一次顯示之前的劇情與目前這一段，都看過了，不用再打字
                self.clear_story()
                self.show_history(reply)
                self.view.show_past_narration(reply.narration)
                self.choices = list(reply.choices)  # 清空畫面會清掉選項，所以放在清空之後
                self.refresh_hint()
            else:
                self.choices = list(reply.choices)
                self.view.prepare_choices(self.choices, timed=bool(reply.time_limit))
                self.refresh_hint()
                await self.narrate(reply.narration)
            for name, groups in reply.changes:
                self.view.show_changes(groups, name if len(reply.characters) > 1 else "")  # 一個人玩不用寫名字
            self.view.show_choices(self.choices)
        else:
            self.set_choices(reply.choices)
        self.set_status(reply.turn, reply.characters)
        if reply.narration and reply.time_limit:
            await self.room.send({"type": "ready"})  # 大家都看完，房間才開始倒數

    def show_history(self, reply: Reply) -> None:
        """讀檔、重新連線：先一次顯示之前的劇情與大家的行動，再接著顯示目前這一段。"""
        if reply.notice:
            self.view.show_note(reply.notice)  # 「讀取存檔：……」
        if reply.history_trimmed:
            self.view.show_note(UI["history_trimmed"])
        for narration, action in reply.history:
            self.view.show_past_narration(narration)
            for line in action.splitlines():
                self.view.show_action(line)
        if reply.history:
            self.view.show_note(UI["history_end"])

    async def show_ending(self, ending: Ending) -> None:
        """一段一段來：先讀完最後的劇情，按 Enter 才出現尾聲，再按一次才看總結。"""
        if ending.epilogue:
            await self.view.wait_enter(ending.reveal or UI["wait_epilogue"])
            self.view.show_ending_title(ending.title)
            await self.narrate(ending.epilogue)
        else:
            self.view.show_ending_title(UI["story_over"])
        await self.view.wait_enter(UI["wait_ending"])
        if not await self.view.ask_ending(ending.title, ending.record):
            self.view.exit()  # 再玩一次的話，房間會回到等人的畫面

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
        """行動的進度放在輸入框的提示，不用會蓋住劇情的通知：自己行動完了提示還在等誰，還沒行動時提示誰已經行動了。"""
        team = [s.name for s in self.shown[1] if s.alive]  # 狀態列上的隊伍
        acted = [n for n in team if n not in self.waiting and n != self.my_name] if self.waiting else []
        if not self.actor and self.waiting:
            self.view.set_hint(UI["hint_waiting"].format(names=UI["list_sep"].join(self.waiting)))
        elif self.actor and acted:
            self.view.set_hint(UI["hint_others_acted"].format(names=UI["list_sep"].join(acted), hint=self.input_hint()))
        else:
            self.view.set_hint(self.input_hint())

    def input_hint(self) -> str:
        """輸入框平常的提示；有輸入方式時是目前這個方式的說明。"""
        if self.inputs and self.actor and self.inputs[self.input_mode].hint:
            return self.inputs[self.input_mode].hint
        return UI["hint_input"]

    # ---------- 和大廳、房間對話 ----------

    async def claim_seat(self, name: str) -> str:
        await self.room.send({"type": "join", "name": name, "token": self.token})
        answer = await self.room.receive()
        if answer is None:
            return UI["room_lost"]
        return answer.get("reason", "") if answer["type"] == "rejected" else ""

    async def listen(self) -> None:
        """收房間推來的訊息。簡單的直接處理；回覆、大廳等要等前一個顯示完的，排進 inbox 依序處理。"""
        while (message := await self.room.receive()) is not None:
            kind = message["type"]
            if kind == "busy":
                self.progress = message.get("progress", "")
                self.set_busy(message["on"])
                if message["on"]:
                    self.view.show_busy()
            elif kind == "draft":  # 房間轉來的 AI 正在寫的劇情
                self.follow_draft(message["text"])
            elif kind == "timer":
                self.view.start_timer(message["seconds"])
            elif kind == "waiting":
                self.update_waiting(message["names"])
            elif kind == "notice":
                self.view.notify(message["text"])
            elif kind == "replaced":  # 同一個瀏覽器從別的地方進來了：這裡結束
                self.replaced = True
                self.view.notify(UI["session_replaced"], lasting=True)
                self.view.exit()
            elif kind == "new_story":  # 立刻清空，不排隊：緊接著的「故事生成中」才不會被一起清掉
                self.clear_story(message.get("premise", ""))
            elif kind == "premise" and self.premise_answer:
                self.premise_answer.set_result(Reply.from_dict(message["reply"]))
            else:
                self.inbox.put_nowait(message)
        if self.premise_answer and not self.premise_answer.done():  # 前提對話框還在等房間：不然會一直等下去
            self.premise_answer.set_exception(ConnectionError(UI["room_disconnected"]))
        self.set_busy(False)
        if not self.replaced:
            self.view.notify(UI["room_disconnected"], error=True, lasting=True)

    def update_waiting(self, names: list[str]) -> None:
        """這回合還沒行動的人變了：有人剛行動就簡短地通知一下，並更新提示（不重建選項，畫面才不會閃）。"""
        if set(names) < set(self.waiting):  # 名單變短：有人剛行動（新回合時名單會變回全部的人）
            if acted := [n for n in self.waiting if n not in names and n != self.my_name]:
                self.view.show_activity(UI["acted"].format(names=UI["list_sep"].join(acted)))
        self.waiting = names
        self.refresh_hint()

    async def process_inbox(self) -> None:
        while True:
            message = await self.inbox.get()
            kind = message["type"]
            if kind == "reply":
                await self.handle(Reply.from_dict(message["reply"]))
            elif kind == "lobby":
                self.show_lobby(message)

    async def ask_room(self, *commands: str) -> Reply:
        """前提對話框的操作（換題材、換一個、幫我想）：依序送出指令，只有最後一個要求房間回覆（answer），收到的一定是這一個的結果。"""
        self.premise_answer = asyncio.get_running_loop().create_future()
        for i, command in enumerate(commands):
            await self.room.send({"type": "send", "text": command, "answer": i == len(commands) - 1})
        try:
            return await self.premise_answer
        finally:
            self.premise_answer = None

    def show_lobby(self, screen: dict) -> None:
        """大廳或房間的等人畫面（內容由大廳、房間決定）。剛進來或剛離開房間時先清空畫面。"""
        if screen.get("clear"):
            self.clear_story()
        self.view.show_lobby({k: v for k, v in screen.items() if k not in ("type", "clear", "hint")})
        self.actor, self.waiting = "", []
        self.choices = list(screen["choices"])  # 輸入框打編號也能選；按鈕由介面畫在大廳的畫面裡，下方的選項區不用再列一次
        self.view.show_choices([])
        self.view.set_hint(screen["hint"])
