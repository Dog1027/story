"""外殼共用層：跟真人玩家互動的流程，終端機、網頁等介面都用這一層。

分工：
- 核心（story.core）：遊戲規則、AI、存檔。送文字進去、拿 Reply 出來，沒有時間感，也不知道畫面的存在。
- 這一層（Client）：「什麼時候顯示什麼」。開局要問什麼、連本機核心還是線上多人的房間、
  依回覆的階段跳出哪個對話框、打完字才顯示選項、大家看完才倒數、結局一段一段出現……
- 介面（View 的實作，例如 Textual 的 StoryApp）：只負責「長什麼樣子」，把 View 的每個方法畫出來，
  再把玩家的輸入交給 Client（act、command、choose、timeout）。

新功能盡量改在這一層；只有新的畫面元素才需要在每個介面各加一點顯示程式。
判斷標準：改變遊戲結果或事實 → 核心；改變真人看到的順序、時機、流程 → 這一層；改變長相 → 介面。
"""

import asyncio
from dataclasses import dataclass, field

from story.core import ChangeGroups, Ending, PartyCore, Reply, Status, StoryCore
from story.shells.apikey import KEY_PATH, forget_api_key, get_saved_api_key, save_api_key
from story.shells.players import MAX_NAME_LEN, InvalidName, Player, check_name
from story.shells.room import START, RoomConnection

# 介面的對話框也會用到的規則（名字怎樣才能用、key 存在哪裡），一律從這裡取用
__all__ = ["KEY_PATH", "MAX_NAME_LEN", "CharacterLine", "Client", "InvalidName", "StatusLine", "View", "check_name", "status_line"]

WARNING_LEVELS = ("重傷", "瀕死")  # 整體狀態到這個程度才在狀態列警告：再受傷就有生命危險
BUSY_DELAY = 0.15  # 核心超過這麼久還沒回覆才顯示「故事生成中」，很快的回覆就不閃一下


# ---------- 給介面的顯示資料：只說內容與程度，不說顏色與排版 ----------


@dataclass
class CharacterLine:
    """狀態列上一位角色（單人模式只有一位，名字是空的）。"""

    name: str
    alive: bool
    warning: str  # 「重傷」「瀕死」時要醒目地警告；平常是空字串
    items: list[tuple[str, str]]  # (文字, 程度)：每個狀態，不分身體與精神；沒有狀態時是 [("良好", "良好")]


@dataclass
class StatusLine:
    turn: int
    mode: str  # 「限時模式」或「一般模式」，跟回合寫在同一排
    timed: bool
    characters: list[CharacterLine] = field(default_factory=list)
    party: bool = False  # 多人模式：每位角色一列


def character_line(status: Status) -> CharacterLine:
    """背包不放在狀態列：每回合的「獲得／失去」會顯示在故事裡，完整內容用 /state 看。"""
    items = [(name, severity) for name, severity in status.body + status.mind]
    return CharacterLine(
        name=status.name,
        alive=status.alive,
        warning=status.level if status.level in WARNING_LEVELS else "",
        items=items or [("良好", "良好")],
    )


def status_line(status: Status | None, party: list[Status], timed: bool) -> StatusLine | None:
    if party:
        return StatusLine(party[0].turn, *_mode(timed), [character_line(s) for s in party], party=True)
    if status is None:
        return None
    return StatusLine(status.turn, *_mode(timed), [character_line(status)])


def _mode(timed: bool) -> tuple[str, bool]:
    return ("限時模式" if timed else "一般模式"), timed


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

    async def show_narration(self, text: str) -> None:
        """顯示一段劇情（例如打字效果），顯示完才回傳。"""
        raise NotImplementedError

    def show_changes(self, groups: ChangeGroups, name: str = "") -> None:
        """回合間的變化（新增、痊癒、獲得……）；多人模式有角色名字。"""
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

    def set_hint(self, title: str, placeholder: str) -> None:
        """選項區的標題（例如「輪到 阿明」）與輸入框的提示。"""
        raise NotImplementedError

    def set_status(self, status: StatusLine | None) -> None:
        raise NotImplementedError

    def show_lobby(self, members: list[str]) -> None:
        """線上多人的大廳：狀態列列出在房間裡的人（房主已標出）。"""
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

    def show_fatal(self, text: str) -> None:
        """沒辦法繼續的錯誤，例如連不上遊戲房間。"""
        raise NotImplementedError

    async def ask_confirm(self, question: str, yes: str = "確定", no: str = "取消") -> bool:
        raise NotImplementedError

    async def ask_premise(self, reply: Reply, ask) -> tuple[str, bool, str] | None:
        """開新故事：回傳 (前提, 要不要限時, 題材)。ask(*指令) 會在背景執行緒呼叫，送指令給核心並回傳最後一個回覆
        （換題材、換一個、幫我想）。"""
        raise NotImplementedError

    async def ask_ending(self, title: str, record: str) -> bool:
        """顯示結局與旅程紀錄，回傳要不要再玩一次。"""
        raise NotImplementedError

    async def ask_name(self, claim, hint: str = "") -> str | None:
        """問名字。claim(名字) 是 async 函式，回傳空字串代表可以用，否則是不能用的原因。"""
        raise NotImplementedError

    async def ask_api_key(self, reason: str, can_save: bool) -> tuple[str, bool] | None:
        """回傳 (key, 要不要存起來)。"""
        raise NotImplementedError

    async def ask_party_names(self) -> list[str] | None:
        raise NotImplementedError

    def exit(self) -> None:
        raise NotImplementedError


# ---------- 共用的流程 ----------


class Client:
    def __init__(self, view: View, web: bool = False, party: bool = False, room: str | None = None):
        self.view = view
        self.web = web  # 網頁版：先問名字，存檔依名字分開，API key 不存到伺服器
        self.party = party  # 多人模式：大家輪流在這台電腦上輸入行動
        self.room_path = room  # 線上多人：房間的 socket；這時不建立自己的核心
        self.core: StoryCore | None = None
        self.room: RoomConnection | None = None
        self.player: Player | None = None
        self.my_name = ""  # 線上多人：自己的名字
        self.actor = ""  # 多人模式：現在輪到誰（線上多人：輪到自己時是自己的名字）
        self.waiting: list[str] = []  # 線上多人：這回合還沒行動的人
        self.choices: list[str] = []
        self.busy = False
        self.progress = ""  # 線上多人：房間推來的進度（單人直接讀核心的 progress）
        self.timed = False
        self.shown: tuple[Status | None, list[Status]] = (None, [])  # 狀態列目前的內容（模式改變時重畫）
        self.inbox: asyncio.Queue[dict] = asyncio.Queue()  # 房間推來、要依序處理的訊息
        self.premise_answer: asyncio.Future | None = None  # 線上多人：前提對話框在等房間回覆

    @property
    def connected(self) -> bool:
        return self.core is not None or self.room is not None

    @property
    def ready(self) -> bool:
        """可以接受玩家的輸入。"""
        return self.connected and not self.busy

    def close(self) -> None:
        if self.player:
            self.player.release()  # 連線異常中斷沒跑到這裡也沒關係：下次會發現鎖的程序已不存在而接手
        if self.room:
            self.room.close()

    # ---------- 啟動：取得 key，建立核心 ----------

    async def run(self) -> None:
        if self.room_path:
            await self.join_room()
            return
        if self.web:
            name = await self.view.ask_name(self.claim_name)
            if name is None:
                self.view.exit()
                return
            key = await self.ask_api_key(f"{name}，請輸入你的 Gemini API key")
        else:
            key = get_saved_api_key() or await self.ask_api_key("找不到 Gemini API key。")
        if key is None:
            self.view.exit()
            return
        if self.party:
            names = await self.view.ask_party_names()
            if names is None:
                self.view.exit()
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
        result = await self.view.ask_api_key(reason, can_save=not self.web)
        if result is None:
            return None
        key, keep = result
        if keep:
            save_api_key(key)
        return key

    # ---------- 玩家的輸入 ----------

    async def act(self, text: str) -> None:
        """玩家的行動：選項編號或自由輸入。先在故事區顯示行動，再送出。"""
        await self.send(text, echo=self.echo_for(text))

    async def command(self, text: str) -> None:
        """指令（/state、/restart 等），不顯示在故事區。"""
        await self.send(text)

    async def timeout(self) -> None:
        """介面的倒數到了。線上多人由房間統一計時，不用送。"""
        if self.room is None and self.core is not None:
            await self.send("/timeout", echo=self.core.action_for("/timeout") or "")

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

    # ---------- 和核心對話 ----------

    async def send(self, text: str, echo: str = "") -> None:
        """送一句文字給核心並顯示回覆。echo 是要先顯示在故事區的玩家行動。"""
        if self.busy:
            return
        if not self.party:  # 多人模式的倒數以整回合為單位，換人輸入時繼續跑
            self.view.stop_timer()
        if echo:
            self.set_choices([])
            self.view.show_action(echo)
        if self.room:  # 線上多人：回覆會由房間推回來
            await self.room.send({"type": "send", "text": text})
            return
        reply = await self.ask_core(text)
        if reply is not None:
            await self.handle(reply)

    async def ask_core(self, text: str) -> Reply | None:
        """在背景執行緒呼叫核心；超過一下子才顯示等待提示。key 無效時請玩家換一個再重送。"""
        self.set_busy(True)
        try:
            while True:
                task = asyncio.create_task(asyncio.to_thread(self.core.send, text))
                done, _ = await asyncio.wait({task}, timeout=BUSY_DELAY)
                if not done:
                    self.view.show_busy()
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

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.view.set_busy(busy)

    def busy_text(self) -> str:
        """等待提示的文字，例如「故事生成中：規劃故事大綱…」。"""
        progress = self.progress if self.room else (self.core.progress if self.core else "")
        return f"故事生成中{'：' + progress if progress else ''}…"

    async def handle(self, reply: Reply) -> None:
        """依照回覆的階段決定接下來的流程。"""
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
            keep = await self.view.ask_confirm(f"{reply.notice}\n\n要繼續嗎？", yes="繼續", no="開新遊戲")
            await self.send("1" if keep else "2")
        elif reply.phase == "ask_premise":
            await self.ask_premise(reply)
        elif reply.phase == "confirm_restart":
            sure = await self.view.ask_confirm(reply.notice)
            await self.send("1" if sure else "2")
        elif reply.phase in ("playing", "ending"):
            await self.show_turn(reply)
            if reply.phase == "ending" and not self.room:  # 線上多人由房間接著寫尾聲
                await self.send("")  # 讓核心接著寫尾聲
        elif reply.phase == "ended":
            await self.show_ending(reply.ending)

    async def ask_premise(self, reply: Reply) -> None:
        if reply.error == "api":
            return  # 開場生成失敗：錯誤已經提示了，留在原處，玩家可以用 /restart 再試
        loop = asyncio.get_running_loop()

        def ask(*commands: str) -> Reply:
            """對話框在背景執行緒呼叫：把指令送給核心，回傳最後一個回覆（換題材、換一個、幫我想）。"""
            if self.room:  # 請房間代問後等結果
                return asyncio.run_coroutine_threadsafe(self.ask_room(list(commands)), loop).result()
            for command in commands:
                answer = self.core.send(command)
            return answer

        answer = await self.view.ask_premise(reply, ask)
        if answer is None:
            return
        premise, want_timed, genre = answer
        commands = [f"/timed {'on' if want_timed else 'off'}"] * (want_timed != reply.timed) + [f"/genre {genre}"]
        for command in commands:  # 模式與題材的選擇送給核心（回覆不需要顯示）
            if self.room:
                await self.room.send({"type": "send", "text": command})
            else:
                await asyncio.to_thread(self.core.send, command)
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
            await self.view.show_narration(reply.narration)
            if reply.changes:
                self.view.show_changes(reply.changes)
            for name, groups in reply.party_changes:
                if groups:
                    self.view.show_changes(groups, name)
            self.view.show_choices(self.choices)
        else:
            self.set_choices(reply.choices)
        self.set_status(reply.status, reply.party)
        if reply.narration and reply.time_limit:
            if self.room:  # 線上多人：告訴房間看完了，大家都看完房間才開始倒數
                await self.room.send({"type": "ready"})
            else:
                self.view.start_timer(reply.time_limit)

    async def show_ending(self, ending: Ending) -> None:
        """一段一段來：先讀完最後的劇情，按 Enter 才出現尾聲，再按一次才看總結。"""
        if ending.epilogue:
            await self.view.wait_enter("按 Enter 看尾聲")
            self.view.show_ending_title(ending.title)
            await self.view.show_narration(ending.epilogue)
        else:
            self.view.show_ending_title("故事結束")
        await self.view.wait_enter("按 Enter 查看結局")
        if not await self.view.ask_ending(ending.title, ending.record):
            self.view.exit()
        elif not self.room:  # 線上多人：房間會自動回到大廳
            await self.send("1")

    def clear_story(self, premise: str = "") -> None:
        self.choices = []
        self.shown = (None, [])
        self.view.clear_story(premise)
        self.refresh_hint()

    def set_choices(self, choices: list[str]) -> None:
        self.choices = list(choices)
        self.view.show_choices(self.choices)
        self.refresh_hint()

    def set_status(self, status: Status | None, party: list[Status]) -> None:
        self.shown = (status, party)
        self.view.set_status(status_line(status, party, self.timed))

    def refresh_hint(self) -> None:
        """選項區的標題與輸入框的提示：輪到誰；線上多人時還在等誰。"""
        title = f"輪到 {self.actor}" if self.actor else "接下來"
        placeholder = f"輪到 {self.actor}：↑↓ 選擇，或寫下行動" if self.actor else "↑↓ 選擇，或寫下你的行動"
        if self.room and not self.actor and self.waiting:
            placeholder = f"等待 {'、'.join(self.waiting)} 行動…"
        self.view.set_hint(title, placeholder)

    # ---------- 線上多人：和房間對話 ----------

    async def join_room(self) -> None:
        try:
            self.room = await RoomConnection.open(self.room_path)
        except OSError:
            self.view.show_fatal("連不上遊戲房間，請稍後重新整理。")
            return
        name = await self.view.ask_name(self.claim_seat, hint="大家在同一局裡，每個名字就是一位角色。中途斷線可以用同一個名字回來。")
        if name is None:
            self.view.exit()
            return
        self.my_name = name
        inbox = asyncio.create_task(self.process_inbox())
        try:
            await self.listen()
        finally:
            inbox.cancel()

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
                    self.view.show_busy()
            elif kind == "timer":
                self.view.start_timer(message["seconds"])
            elif kind == "waiting":
                self.update_waiting(message["names"])
            elif kind == "notice":
                self.view.notify(message["text"])
            elif kind == "new_story":  # 立刻清空，不排隊：緊接著的「故事生成中」才不會被一起清掉
                self.clear_story(message.get("premise", ""))
            elif kind == "premise" and self.premise_answer:
                self.premise_answer.set_result(Reply.from_dict(message["reply"]))
            else:
                self.inbox.put_nowait(message)
        self.set_busy(False)
        self.view.notify("和遊戲房間的連線中斷了，請重新整理頁面。", error=True, lasting=True)

    def update_waiting(self, names: list[str]) -> None:
        """這回合還沒行動的人變了：有人行動時跳出通知，並更新提示（不重建選項，畫面才不會閃）。"""
        if set(names) < set(self.waiting):  # 名單變短：有人剛行動（新回合時名單會變回全部的人）
            acted = [n for n in self.waiting if n not in names and n != self.my_name]
            if acted:
                self.view.notify(f"{'、'.join(acted)} 已行動")
        self.waiting = names
        self.refresh_hint()

    async def process_inbox(self) -> None:
        while True:
            message = await self.inbox.get()
            kind = message["type"]
            if kind == "reply":
                await self.handle(Reply.from_dict(message["reply"]))
            elif kind == "lobby":
                self.show_lobby(message["members"], message["host"])

    async def ask_room(self, commands: list[str]) -> Reply:
        """依序送出指令，只有最後一個要求房間回覆（answer），收到的一定是這一個的結果。"""
        self.premise_answer = asyncio.get_running_loop().create_future()
        for i, command in enumerate(commands):
            await self.room.send({"type": "send", "text": command, "answer": i == len(commands) - 1})
        try:
            return await self.premise_answer
        finally:
            self.premise_answer = None

    def show_lobby(self, members: list[str], host: str) -> None:
        self.view.show_lobby([f"{n}（房主）" if n == host else n for n in members])
        self.actor, self.waiting = "", []
        if self.my_name == host:
            self.set_choices([START] if len(members) >= 2 else [])
            placeholder = "選「開始遊戲」，大家就會一起進入故事" if len(members) >= 2 else "等其他玩家加入（至少 2 人）…"
        else:
            self.set_choices([])
            placeholder = f"等房主 {host} 開始遊戲…"
        self.view.set_hint("接下來", placeholder)
