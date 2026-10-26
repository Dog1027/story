"""最小核心：送文字進來、拿回覆出去。

外面看起來就像呼叫一個 LLM：`reply = core.send("往上爬")`（好幾位角色時是 `core.send_as("阿明", "往上爬")`）。
記憶、規則、存檔、遊戲流程都藏在這裡。
回覆和 LLM 的 API 一樣是「文字＋附帶資料」：只會印文字的外殼直接顯示 `reply.text`；
想做狀態列、倒數、選項按鈕的外殼，再去讀其他欄位。

API key、玩家名字、倒數計時、打字效果屬於外殼，不在這裡處理。
"""

import random
import threading
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Literal

from google.genai import errors


from story.core import prompts
from story.core.ai import LOG_PATH, is_key_error
from story.core.engine import Engine
from story.core.models import Character, GameState, word
from story.core.prompting import AWAY_ACTION, TIMEOUT_ACTION, TURN
from story.core.records import DEFAULT_PREMISE, SAVE_PATH, ChangeGroups, change_groups, ending_record, load, memory_text, save, snapshot
from story.core.rules import condition_list, warning_level

Phase = Literal[
    "ask_continue",  # 找到存檔，問要不要繼續
    "ask_premise",  # 等玩家輸入故事前提
    "playing",  # 遊戲中
    "confirm_restart",  # 確認是否放棄目前進度
    "ending",  # 故事剛結束，下一次輸入會寫尾聲
    "ended",  # 尾聲寫完，可以再玩一次
]

UI = prompts.ui("core")  # 給玩家看的文字（story/ui/語言/core.md）
MAX_PLAYERS = 4  # 一隊最多幾位角色
GENRE_AUTO, GENRE_NONE = "auto", "none"  # 題材的兩個特別選項：依前提由 AI 挑、不套用題材（顯示的字是 genre_label()）
CONTINUE_CHOICES = [UI["choice_continue"], UI["choice_new_game"]]
CONFIRM_CHOICES = [UI["choice_confirm"], UI["choice_cancel"]]
PLAY_AGAIN_CHOICES = [UI["choice_play_again"]]


def genre_label(choice: str) -> str:
    """題材選擇顯示的字：特別選項換成這個語言的詞，題材包就是它的名稱。"""
    return {GENRE_AUTO: UI["genre_auto"], GENRE_NONE: UI["genre_none"]}.get(choice, choice)


def join(items) -> str:
    return UI["list_sep"].join(items)


@dataclass
class Status:
    """狀態列需要的資料：一位角色。背包不在這裡，變化在 changes，完整內容用 /state 看。"""

    conditions: list[tuple[str, str]]  # 目前的狀態：(名稱, 程度的代號)，身體在前、精神在後
    warning: str = ""  # 要警告玩家的整體狀態代號（serious、dying：再受傷就有生命危險）；不危險時是空字串。顯示的詞用 word("level", …)
    name: str = ""  # 角色名字
    alive: bool = True  # 角色是否還活著


@dataclass
class Ending:
    title: str
    epilogue: str
    record: str  # 旅程紀錄：回合數、天數、重大事件


@dataclass
class Reply:
    phase: Phase
    turn: int = 0  # 目前是第幾回合；還沒開始故事時是 0
    timed: bool = False  # 目前是否為限時模式（遊戲中是這一局的模式，等前提時是開新局會用的模式）
    text: str = ""  # 完整的純文字，只會印文字的外殼直接顯示這個就好
    narration: str = ""  # 這次產生（或讀檔重新顯示）的劇情；沒有新劇情時是空字串
    choices: list[str] = field(default_factory=list)
    characters: list[Status] = field(default_factory=list)  # 每位角色的狀態（一個人玩只有一位）
    changes: list[tuple[str, ChangeGroups]] = field(default_factory=list)  # 這回合有變化的角色：(名字, 新增、痊癒、獲得……)
    time_limit: int = 0  # 限時秒數；0 代表不限時
    notice: str = ""  # 簡短的系統訊息，例如「讀取存檔」「沒有這個指令」
    resumed: bool = False  # 這次是讀取存檔、重新顯示上次的劇情
    history: list[tuple[str, str]] = field(default_factory=list)  # resumed：之前的劇情，每回合 (劇情, 看完之後的行動，每人一行)
    history_trimmed: bool = False  # resumed：更早的劇情已經壓縮成摘要，history 從中間開始
    info: tuple[str, str] | None = None  # 要另外顯示的內容：(標題, 內容)，例如記憶、說明
    premise_default: str = ""  # ask_premise：留白時使用的前提
    genre: str = ""  # ask_premise：開新局會用的題材選擇（GENRE_AUTO、GENRE_NONE 或題材名稱）
    genres: list[tuple[str, str]] = field(default_factory=list)  # ask_premise：可選的題材（名稱, 描述）
    suggestion: str = ""  # ask_premise：/suggest 想出來的前提
    ending: Ending | None = None  # ended：尾聲與旅程紀錄
    error: Literal["api_key", "api"] | None = None  # api_key：key 無效，外殼換 key 後可以重送同一句
    actor: str = ""  # 送出輸入的那位玩家（send_as、view 的對象；一個人玩就是他）這回合還沒行動時是他的名字，choices 是他的選項

    def to_dict(self) -> dict:
        """轉成可以存成 JSON 的 dict（網頁版的房間傳送回覆用）。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Reply":
        """to_dict() 的反向。JSON 沒有 tuple，tuple 會變成 list，外殼拆開使用時沒有差別。"""
        data = dict(data)
        if data.get("ending"):
            data["ending"] = Ending(**data["ending"])
        data["characters"] = [Status(**s) for s in data.get("characters", [])]
        return cls(**data)


def pick_choice(raw: str, options: list[str]) -> str | None:
    """把「2」或選項本身的文字對應到選項，對不上時回傳 None。網頁版也用它，先顯示自己選了什麼。"""
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    return raw if raw in options else None


class StoryCore:
    """一局遊戲：一支一到四位角色的隊伍，每位由一位玩家扮演（一個人玩就是只有一位）。

    每位角色的行動用 send_as(名字, 文字) 送，誰先送誰先記，所有還活著的角色都行動了才呼叫 AI 寫這一回合；
    隊伍只有一位時，send(文字) 就是他的行動。不屬於某位玩家的輸入（時間到、對話框的回答、寫尾聲、/state）用 send()。
    view(名字) 取得某位玩家眼中的畫面（自己的選項）。"""

    def __init__(
        self,
        api_key: str,
        players: list[str],
        *,
        save_path: Path = SAVE_PATH,
        log_path: Path = LOG_PATH,
        engine: Engine | None = None,
        client=None,
    ):
        """client：要共用的 Gemini client（例如受 RateLimit 限制的），沒給就用 api_key 建一個。"""
        names = [n.strip() for n in players if n.strip()]
        if not 1 <= len(names) <= MAX_PLAYERS or len(set(names)) != len(names):
            raise ValueError(UI["team_size"].format(min=1, max=MAX_PLAYERS))
        self.engine = engine or Engine(api_key=api_key, client=client, log_path=log_path)
        self.save_path = save_path
        self._players = names
        self.state: GameState | None = None
        self._phase: Phase = "ask_premise"
        self.timed = False  # 開新局時的模式，沿用上一局的選擇
        self.genre = GENRE_AUTO  # 開新局時的題材選擇，沿用上一局的選擇
        self.last_premise = ""
        self.suggested = ""  # /suggest 想出來的前提，留白送出時優先使用
        self.drawn = ""  # 從題材包的開頭靈感隨機抽到的前提；再玩一次時不抽，延續上一局的前提
        self.pending: dict[str, str] = {}  # 這一回合已經送出的行動
        self._as: str | None = None  # send_as() 指定的角色
        self._compaction: threading.Thread | None = None

    def set_api_key(self, api_key: str) -> None:
        self.engine.set_api_key(api_key)

    @property
    def players(self) -> list[str]:
        """隊伍裡的玩家名字（唯讀），依建立時的順序。"""
        return list(self._players)

    @property
    def phase(self) -> Phase:
        """目前的遊戲階段（唯讀），和最近一次回覆的 reply.phase 相同。網頁版的房間用它決定輸入要交給誰。"""
        return self._phase

    @property
    def progress(self) -> str:
        """send() 執行中時，目前在做什麼（例如「規劃故事大綱」）；沒有特別的階段時是空字串。
        外殼可以在另一個執行緒讀取，顯示在等待畫面上。"""
        return self.engine.stage

    @property
    def draft(self) -> str:
        """send() 執行中時，AI 正在寫的劇情（串流中目前收到的部分）；沒有在寫時是空字串。
        外殼可以在另一個執行緒讀取，邊收邊顯示；send() 回傳的 Reply 才是最後的完整內容。"""
        return self.engine.draft

    # ---------- 對外介面 ----------

    def start(self) -> Reply:
        """第一個回覆：同一組玩家有沒結束的存檔就問要不要繼續，否則請玩家輸入故事前提。"""
        state = load(self.save_path)
        if state and not state.game_over and sorted(state.names) == sorted(self._players):  # 順序不同也是同一組人
            self.state, self.timed, self._phase = state, state.timed_mode, "ask_continue"
            return self._reply(choices=CONTINUE_CHOICES, notice=UI["found_save"].format(turn=state.turn, premise=state.premise))
        return self._ask_premise()

    def action_for(self, text: str) -> str | None:
        """這句輸入在遊戲中代表的行動文字（例如「2」→ 第二個選項），讓外殼可以在等待回覆前先顯示。
        不是行動（指令、空白、不在遊戲中）時回傳 None。"""
        raw = text.strip()
        if self._phase != "playing" or not raw:
            return None
        if raw == "/timeout":
            return TIMEOUT_ACTION
        if raw == "/away":
            return AWAY_ACTION
        if raw.startswith("/"):
            return None
        actor = self._actor()
        return pick_choice(raw, actor.choices if actor else []) or raw

    def send(self, text: str) -> Reply:
        """送出一句輸入，拿回覆。可能會呼叫 LLM，所以會花幾秒。"""
        raw = text.strip()
        if raw == "/help":
            return self._reply(info=(UI["help_title"], UI["help"]), **self._screen())
        if raw == "/state":
            if self.state is None:
                return self._reply(notice=UI["no_story_yet"], **self._screen())
            return self._reply(info=(UI["memory_title"], memory_text(self.state)), **self._screen())

        handler = {
            "ask_continue": self._on_ask_continue,
            "ask_premise": self._on_ask_premise,
            "playing": self._on_playing,
            "confirm_restart": self._on_confirm_restart,
            "ending": self._on_ending,
            "ended": self._on_ended,
        }[self._phase]
        return handler(raw)

    def send_as(self, name: str, text: str) -> Reply:
        """以某位角色的身分送出輸入，不用照隊伍順序。遊戲中以外的階段（前提、確認……）等同 send()。"""
        if self._phase == "playing" and (not text.strip().startswith("/") or text.strip() == "/away"):  # 行動才要檢查
            character = next((c for c in self.state.characters if c.name == name), None)
            if character is None or not character.alive:
                return self._reply(notice=UI["character_fallen"], **self._screen())
            if name in self.pending:
                return self._reply(notice=UI["already_acted"], **self._screen())
        self._as = name
        try:
            return self.send(text)
        finally:
            self._as = None

    def view(self, name: str, reply: Reply | None = None) -> Reply:
        """某位玩家眼中的畫面：actor 與 choices 換成這位角色的（已經行動或倒下的人沒有選項）。
        給了 reply 就沿用它的其他欄位，否則是目前這一回合的畫面（重新連線時用）。"""
        if reply is None:
            reply = self._reply(**self._screen())
            if self._phase == "playing":
                reply.narration, reply.resumed = self.state.current_narration, True
                reply.history, reply.history_trimmed = self._history(), bool(self.state.summary)
        if self._phase != "playing":
            mine = replace(reply, actor="", choices=[] if reply.actor else reply.choices)
        else:
            actor = next((c for c in self._waiting() if c.name == name), None)
            mine = replace(reply, actor=name if actor else "", choices=list(actor.choices) if actor else [])
        mine.text = render_text(mine)
        return mine

    def waiting(self) -> list[str]:
        """這回合還沒行動的角色名字。"""
        return [c.name for c in self._waiting()] if self.state and self._phase == "playing" else []

    # ---------- 各階段 ----------

    def _on_ask_continue(self, raw: str) -> Reply:
        answer = pick_choice(raw, CONTINUE_CHOICES)
        if answer == CONTINUE_CHOICES[0] or raw == "/continue":
            return self._resume()
        if answer == CONTINUE_CHOICES[1] or raw in ("/new", "/restart"):
            self.last_premise = self.state.premise if self.state else ""
            return self._ask_premise()
        return self._reply(choices=CONTINUE_CHOICES, notice=UI["answer_continue"])

    def _on_ask_premise(self, raw: str) -> Reply:
        if raw == "/suggest":
            try:
                chosen = self.genre if self.genre in self.engine.genres else ""
                suggestion = self.engine.suggest_premise(self.last_premise or DEFAULT_PREMISE, genre=chosen)
            except (errors.APIError, RuntimeError) as e:
                return self._failed(e, self._ask_premise)
            self.suggested = suggestion
            return self._ask_premise(suggestion=suggestion)
        if raw == "/random":
            self.suggested, self.drawn = "", self._draw_premise(avoid=self._default_premise())
            return self._ask_premise(notice=UI["rerolled"])
        if raw.startswith("/timed"):
            arg = raw.removeprefix("/timed").strip()
            self.timed = {"on": True, "off": False}.get(arg, not self.timed)
            return self._ask_premise(notice=UI["mode_switched_timed" if self.timed else "mode_switched_normal"])
        if raw.startswith("/genre"):
            typed = raw.removeprefix("/genre").strip()
            choice = {UI["genre_auto"]: GENRE_AUTO, UI["genre_none"]: GENRE_NONE}.get(typed, typed)  # 打字的也可以用顯示的詞
            if choice not in (GENRE_AUTO, GENRE_NONE, *self.engine.genres):
                options = join(genre_label(g) for g in (GENRE_AUTO, GENRE_NONE, *self.engine.genres))
                return self._ask_premise(notice=UI["genre_unknown"].format(choice=typed, options=options))
            self.genre = choice
            if self.drawn and not self.suggested and self.drawn not in self._premise_pool():
                self.drawn = self._draw_premise()  # 抽到的開頭跟著換成新題材的
            return self._ask_premise(notice=UI["genre_chosen"].format(choice=genre_label(choice)))
        if raw.startswith("/"):
            return self._ask_premise(notice=UI["unknown_command"].format(command=raw))

        premise = " ".join(raw.split()) or self._default_premise()
        state = self._new_state(premise)
        try:
            self.engine.start(state)
        except (errors.APIError, RuntimeError) as e:
            return self._failed(e, self._ask_premise)
        self.state, self._phase, self.last_premise, self.suggested, self.drawn = state, "playing", premise, "", ""
        save(state, self.save_path)
        return self._turn_reply(before=None)

    def _on_playing(self, raw: str) -> Reply:
        if raw == "/restart":
            self._phase = "confirm_restart"
            return self._reply(choices=CONFIRM_CHOICES, notice=UI["confirm_restart"])
        action = self.action_for(raw)
        if action is None:
            notice = UI["unknown_command"].format(command=raw) if raw else UI["enter_action"]
            return self._reply(notice=notice, **self._screen())
        return self._take_action(action, timeout=raw == "/timeout")

    def _take_action(self, action: str, timeout: bool) -> Reply:
        """記下這位角色的行動；所有人都行動後才推進一回合。時間到時，還沒行動的人都算遲疑。"""
        if timeout:
            for c in self._waiting():
                self.pending[c.name] = action
        else:
            actor = self._actor()
            if actor is None:
                raise ValueError("好幾位角色時，行動要用 send_as(名字, 文字) 送，才知道是誰的行動")
            self.pending[actor.name] = action
            if self._waiting():
                return self._reply(**self._screen())  # 還在等其他人：畫面上誰還沒行動由外殼用 waiting() 顯示
        return self._play_turn({c.name: self.pending[c.name] for c in self.state.characters if c.name in self.pending})

    def _play_turn(self, actions: dict[str, str]) -> Reply:
        """呼叫 engine 推進一回合，存檔，回傳這回合的回覆。"""
        self._wait_compaction()
        before = {c.name: snapshot(c) for c in self.state.characters}
        try:
            self.engine.act(self.state, actions)
        except (errors.APIError, RuntimeError) as e:
            self.state = load(self.save_path) or self.state  # act() 可能已經改了一半的狀態，從存檔還原
            # 撤回這回合所有的行動，大家重新選擇。只撤回最後一個人不夠：時間到或替離線的人自動填入的行動失敗時，
            # 會變成每個人都「已行動」卻沒有人能重送，整局卡住
            self.pending = {}
            return self._failed(e, lambda **kw: self._reply(**self._screen(), **kw), hint=UI["failed_turn"])
        self.pending = {}
        save(self.state, self.save_path)
        if self.state.game_over:
            self._phase = "ending"
        else:
            self._start_compaction()
        return self._turn_reply(before)

    def _on_confirm_restart(self, raw: str) -> Reply:
        answer = pick_choice(raw, CONFIRM_CHOICES)
        if answer == CONFIRM_CHOICES[0]:
            self.last_premise = self.state.premise
            return self._ask_premise()
        if answer == CONFIRM_CHOICES[1]:
            self._phase = "playing"
            return self._reply(**self._screen())
        return self._reply(choices=CONFIRM_CHOICES, notice=UI["answer_confirm"])

    def _on_ending(self, raw: str) -> Reply:
        """故事結束後的下一次輸入：寫尾聲。尾聲寫失敗也照樣進到結束階段，可以再玩一次。"""
        s = self.state
        notice = ""
        if not s.epilogue:
            try:
                self.engine.write_epilogue(s)
                save(s, self.save_path)
            except (errors.APIError, RuntimeError) as e:
                notice = UI["epilogue_failed"].format(error=str(e)[:200])
        self._phase = "ended"
        return self._reply(
            choices=PLAY_AGAIN_CHOICES,
            notice=notice,
            ending=Ending(title=s.ending_title, epilogue=s.epilogue, record=ending_record(s)),
        )

    def _on_ended(self, raw: str) -> Reply:
        if pick_choice(raw, PLAY_AGAIN_CHOICES) or raw in ("/new", "/restart"):
            self.last_premise = self.state.premise
            return self._ask_premise()
        return self._reply(choices=PLAY_AGAIN_CHOICES, notice=UI["answer_play_again"])

    # ---------- 共用 ----------

    def _ask_premise(self, suggestion: str = "", notice: str = "", error=None) -> Reply:
        self._phase = "ask_premise"
        if not (self.suggested or self.drawn or self.last_premise):  # 第一次開新故事：隨機抽一個開頭
            self.drawn = self._draw_premise()
        return self._reply(
            premise_default=self._default_premise(),
            genre=self.genre,
            genres=[(g.name, g.description) for g in self.engine.genres.values()],
            suggestion=suggestion,
            notice=notice,
            error=error,
        )

    def _new_state(self, premise: str) -> GameState:
        self.pending = {}
        characters = [Character(name=n) for n in self._players]
        return GameState(premise=premise, characters=characters, timed_mode=self.timed, **self._genre_fields())

    def _genre_fields(self) -> dict:
        """新局的題材欄位：指定題材就直接套用；選「自動」時，規劃大綱時由 AI 從目錄挑。"""
        if self.genre in self.engine.genres:
            return {"genre": self.genre}
        return {"genre_pending": self.genre == GENRE_AUTO and bool(self.engine.genres)}

    def _waiting(self) -> list[Character]:
        """還活著、這回合還沒送出行動的角色，依隊伍順序。"""
        return [c for c in self.state.characters if c.alive and c.name not in self.pending]

    def _actor(self) -> Character | None:
        """這句輸入是誰的：send_as() 指定的角色；隊伍只有一位時就是他。已經行動或倒下了就沒有。"""
        if self.state is None:
            return None
        name = self._as if self._as is not None else (self.state.characters[0].name if self.state.solo else None)
        return next((c for c in self._waiting() if c.name == name), None)

    def _default_premise(self) -> str:
        """留白時使用的前提：AI 想的 → 隨機抽的 → 上一局的（再玩一次）→ 預設的。"""
        return self.suggested or self.drawn or self.last_premise or DEFAULT_PREMISE

    def _premise_pool(self) -> list[str]:
        """可以隨機抽的開頭：指定了題材就用那個題材包的，否則用所有題材包的，再加上預設的前提。"""
        genres = self.engine.genres
        if self.genre in genres and genres[self.genre].premises:
            return list(genres[self.genre].premises)
        return [p for g in genres.values() for p in g.premises] + [DEFAULT_PREMISE]

    def _draw_premise(self, avoid: str = "") -> str:
        pool = self._premise_pool()
        return random.choice([p for p in pool if p != avoid] or pool)

    def _resume(self) -> Reply:
        self._phase = "playing"
        self.pending = {}
        s = self.state
        return self._reply(
            narration=s.current_narration, notice=UI["resumed"].format(premise=s.premise), resumed=True,
            history=self._history(), history_trimmed=bool(s.summary), **self._screen(),
        )

    def _history(self) -> list[tuple[str, str]]:
        """之前的劇情（劇情紀錄的原文）：(劇情, 看完之後的行動)。只有一位角色時，行動前面不寫名字，跟平常顯示的一樣。"""
        s = self.state
        prefix = TURN["action_entry"].format(name=s.characters[0].name, action="") if s.solo else ""
        return [(t.narration, t.action.removeprefix(prefix)) for t in s.recent]

    def _turn_reply(self, before) -> Reply:
        s = self.state
        changes = []
        if before is not None:
            for c in s.characters:
                if groups := change_groups(before[c.name], c):
                    changes.append((c.name, groups))
        return self._reply(narration=s.current_narration, changes=changes, **self._screen())

    def _screen(self) -> dict:
        """遊戲中畫面的固定部分：送出輸入的那位角色（隊伍只有一位時就是他）的選項，以及限時。"""
        if self.state is None or self._phase not in ("playing", "ending"):
            return {}
        actor = self._actor() if self._phase == "playing" else None
        return {
            "actor": actor.name if actor else "",
            "choices": list(actor.choices) if actor else [],
            "time_limit": self.state.current_time_limit,
        }

    def _failed(self, e: Exception, retry_screen, hint: str = "") -> Reply:
        """LLM 呼叫失敗：留在原本的階段，讓外殼決定要不要換 key 後重送。"""
        if is_key_error(e):
            return retry_screen(error="api_key", notice=UI["key_invalid"])
        return retry_screen(error="api", notice=UI["failed"].format(hint=hint, error=str(e)[:300]))

    def _reply(self, **fields) -> Reply:
        in_story = self.state is not None and self._phase != "ask_premise"  # 有一局在進行（等前提時還沒有）
        reply = Reply(
            phase=self._phase,
            turn=self.state.turn if in_story else 0,
            timed=self.state.timed_mode if in_story else self.timed,
            characters=[character_status(c) for c in self.state.characters] if in_story else [],
            **fields,
        )
        reply.text = render_text(reply)
        return reply

    # ---------- 背景壓縮記憶 ----------

    def _start_compaction(self) -> None:
        """玩家讀劇情時，在背景把舊的記憶壓縮進摘要。下一次需要呼叫 LLM 前會先等它完成。"""
        if not self.engine.needs_compaction(self.state):
            return
        state = self.state

        def run() -> None:
            try:
                self.engine.compact_memory(state)
            except Exception:
                return  # 失敗沒關係，下回合會再試
            if state is self.state:  # 期間開了新局的話，不要用舊局覆蓋存檔
                save(state, self.save_path)

        self._compaction = threading.Thread(target=run, daemon=True)
        self._compaction.start()

    def _wait_compaction(self) -> None:
        if self._compaction is not None:
            self._compaction.join()
            self._compaction = None


def character_status(c: Character) -> Status:
    """給外殼顯示的一位角色的狀態（Reply.characters 裡的一項）。"""
    return Status(conditions=condition_list(c), warning=warning_level(c) if c.alive else "", name=c.name, alive=c.alive)


# ---------- 純文字版的回覆 ----------


def conditions_text(status: Status) -> str:
    """狀態直接列出，不分身體與精神；危險時先警告。背包的變化會寫在每回合的變化裡，完整內容用 /state 看。"""
    items = join(UI["condition"].format(name=n, severity=word("severity", v)) for n, v in status.conditions) or word("level", "healthy")
    return UI["text_warning"].format(level=word("level", status.warning), conditions=items) if status.warning else items


def status_line(turn: int, status: Status, timed: bool) -> str:
    return UI["text_status"].format(turn=turn, timed=UI["text_status_timed"] if timed else "", conditions=conditions_text(status))


def character_line(status: Status) -> str:
    return UI["text_character_line"].format(name=status.name, conditions=conditions_text(status) if status.alive else UI["text_fallen"])


def changes_line(groups: ChangeGroups) -> str:
    return UI["text_changes_sep"].join(UI["text_changes"].format(label=label, items=join(text for text, _ in items)) for label, items in groups)


def render_text(reply: Reply) -> str:
    """把回覆組成一段完整的純文字。只有一位角色時不列名字，也不說輪到誰。"""
    several = len(reply.characters) > 1
    parts: list[str] = []
    if reply.notice:
        parts.append(UI["text_notice"].format(notice=reply.notice))
    if reply.info:
        title, body = reply.info
        parts.append(UI["text_info"].format(title=title, body=body))
    if reply.phase == "ask_premise":
        if reply.suggestion:
            parts.append(UI["text_suggested"])
        mode = UI["text_mode_timed" if reply.timed else "text_mode_normal"]
        parts.append(UI["text_new_story"].format(mode=mode, genre=genre_label(reply.genre), premise=reply.premise_default))
        if reply.genres:
            choices = [GENRE_AUTO, GENRE_NONE, *(name for name, _ in reply.genres)]
            parts.append(UI["text_genres"].format(genres=join(genre_label(g) for g in choices)))
    if reply.history_trimmed:
        parts.append(UI["text_history_trimmed"])
    for narration, action in reply.history:
        parts.append(narration)
        parts.append(UI["text_action"].format(action=action))
    if reply.narration:
        parts.append(reply.narration)
    for name, groups in reply.changes:
        parts.append(UI["text_named_changes"].format(name=name, changes=changes_line(groups)) if several else changes_line(groups))
    if reply.ending:
        e = reply.ending
        parts.append(UI["text_ending_title"].format(title=e.title or UI["text_story_over"]))
        if e.epilogue:
            parts.append(e.epilogue)
        parts.append(e.record)
    if reply.characters and reply.phase in ("playing", "ending") and reply.narration:
        if several:  # 每位角色一行
            parts.append("\n".join(character_line(st) for st in reply.characters) + ("\n" + UI["text_mode_timed"] if reply.timed else ""))
        else:
            parts.append(status_line(reply.turn, reply.characters[0], reply.timed))
    if reply.phase == "ending":
        parts.append(UI["text_send_for_epilogue"])
    if reply.actor and several:
        parts.append(UI["text_actor"].format(name=reply.actor))
    if reply.choices:
        parts.append("\n".join(f"{i}. {c}" for i, c in enumerate(reply.choices, 1)))
    if reply.time_limit:
        parts.append(UI["text_time_limit"].format(seconds=reply.time_limit))
    return "\n\n".join(parts)
