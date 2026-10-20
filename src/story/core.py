"""最小核心：送文字進來、拿回覆出去。

外面看起來就像呼叫一個 LLM：`reply = core.send("往上爬")`。記憶、規則、存檔、遊戲流程都藏在這裡。
回覆和 LLM 的 API 一樣是「文字＋附帶資料」：只會印文字的外殼直接顯示 `reply.text`；
想做狀態列、倒數、選項按鈕的外殼，再去讀其他欄位。

API key、玩家名字、倒數計時、打字效果屬於外殼，不在這裡處理。
"""

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from google.genai import errors

from story.apikey import is_key_error
from story.common import DEFAULT_PREMISE, SAVE_PATH, ChangeGroups, change_groups, ending_record, load, memory_text, save, snapshot
from story.engine import LOG_PATH, TIMEOUT_ACTION, Engine, body_conditions, body_level, mind_conditions
from story.models import GameState

Phase = Literal[
    "ask_continue",  # 找到存檔，問要不要繼續
    "ask_premise",  # 等玩家輸入故事前提
    "playing",  # 遊戲中
    "confirm_restart",  # 確認是否放棄目前進度
    "ending",  # 故事剛結束，下一次輸入會寫尾聲
    "ended",  # 尾聲寫完，可以再玩一次
]

HELP_TEXT = """\
遊戲中：輸入數字選擇選項，或直接寫下你的行動。

/state      看程式記住了什麼
/restart    重新開始
/help       顯示這份說明

開新故事時：
直接送出空白        使用預設的故事前提
/suggest           讓 AI 幫你想一個開頭
/timed on|off      開啟或關閉限時模式（情勢緊迫時要在時間內做出決定）

限時模式的倒數由外殼負責，時間到時送出 /timeout。"""


@dataclass
class Status:
    """狀態列需要的資料。"""

    turn: int
    level: str  # 整體狀態：良好、輕傷、受傷、重傷、瀕死、死亡
    body: list[tuple[str, str]]  # 身體狀態：(名稱, 程度)
    mind: list[tuple[str, str]]  # 精神狀態：(名稱, 程度)
    inventory: list[str]


@dataclass
class Ending:
    title: str
    epilogue: str
    record: str  # 旅程紀錄：回合數、天數、重大事件


@dataclass
class Reply:
    phase: Phase
    timed: bool = False  # 目前是否為限時模式（遊戲中是這一局的模式，等前提時是開新局會用的模式）
    text: str = ""  # 完整的純文字，只會印文字的外殼直接顯示這個就好
    narration: str = ""  # 這次產生（或讀檔重新顯示）的劇情；沒有新劇情時是空字串
    choices: list[str] = field(default_factory=list)
    status: Status | None = None
    changes: ChangeGroups = field(default_factory=list)  # 這回合的變化：新增、惡化、痊癒、獲得……
    time_limit: int = 0  # 限時秒數；0 代表不限時
    notice: str = ""  # 簡短的系統訊息，例如「讀取存檔」「沒有這個指令」
    resumed: bool = False  # 這次是讀取存檔、重新顯示上次的劇情
    info: tuple[str, str] | None = None  # 要另外顯示的內容：(標題, 內容)，例如記憶、說明
    premise_default: str = ""  # ask_premise：留白時使用的前提
    suggestion: str = ""  # ask_premise：/suggest 想出來的前提
    ending: Ending | None = None  # ended：尾聲與旅程紀錄
    error: Literal["api_key", "api"] | None = None  # api_key：key 無效，外殼換 key 後可以重送同一句


class StoryCore:
    def __init__(self, api_key: str, save_path: Path = SAVE_PATH, log_path: Path = LOG_PATH, engine: Engine | None = None):
        self.engine = engine or Engine(api_key=api_key, log_path=log_path)
        self.save_path = save_path
        self.state: GameState | None = None
        self.phase: Phase = "ask_premise"
        self.timed = False  # 開新局時的模式，沿用上一局的選擇
        self.last_premise = ""
        self.suggested = ""  # /suggest 想出來的前提，留白送出時優先使用
        self._compaction: threading.Thread | None = None

    def set_api_key(self, api_key: str) -> None:
        self.engine.set_api_key(api_key)

    # ---------- 對外介面 ----------

    def start(self) -> Reply:
        """第一個回覆：有存檔就問要不要繼續，否則請玩家輸入故事前提。"""
        state = load(self.save_path)
        if state and not state.game_over:
            self.state, self.timed, self.phase = state, state.timed_mode, "ask_continue"
            return self._reply(
                choices=["繼續", "開新遊戲"],
                notice=f"找到存檔（第 {state.turn} 回合）：{state.premise}",
            )
        return self._ask_premise()

    def action_for(self, text: str) -> str | None:
        """這句輸入在遊戲中代表的行動文字（例如「2」→ 第二個選項），讓外殼可以在等待回覆前先顯示。
        不是行動（指令、空白、不在遊戲中）時回傳 None。"""
        raw = text.strip()
        if self.phase != "playing" or not raw:
            return None
        if raw == "/timeout":
            return TIMEOUT_ACTION
        if raw.startswith("/"):
            return None
        return self._pick(raw, self.state.current_choices) or raw

    def send(self, text: str) -> Reply:
        """送出一句玩家輸入，拿回覆。可能會呼叫 LLM，所以會花幾秒。"""
        raw = text.strip()
        if raw == "/help":
            return self._reply(info=("說明", HELP_TEXT), **self._screen())
        if raw == "/state":
            if self.state is None:
                return self._reply(notice="還沒有開始故事。", **self._screen())
            return self._reply(info=("程式記住的東西", memory_text(self.state)), **self._screen())

        handler = {
            "ask_continue": self._on_ask_continue,
            "ask_premise": self._on_ask_premise,
            "playing": self._on_playing,
            "confirm_restart": self._on_confirm_restart,
            "ending": self._on_ending,
            "ended": self._on_ended,
        }[self.phase]
        return handler(raw)

    # ---------- 各階段 ----------

    def _on_ask_continue(self, raw: str) -> Reply:
        if self._pick(raw, ["繼續", "開新遊戲"]) == "繼續" or raw == "/continue":
            return self._resume()
        if self._pick(raw, ["繼續", "開新遊戲"]) == "開新遊戲" or raw in ("/new", "/restart"):
            self.last_premise = self.state.premise if self.state else ""
            return self._ask_premise()
        return self._reply(choices=["繼續", "開新遊戲"], notice="請輸入 1（繼續）或 2（開新遊戲）。")

    def _on_ask_premise(self, raw: str) -> Reply:
        if raw == "/suggest":
            try:
                suggestion = self.engine.suggest_premise(self.last_premise or DEFAULT_PREMISE)
            except (errors.APIError, RuntimeError) as e:
                return self._failed(e, self._ask_premise)
            self.suggested = suggestion
            return self._ask_premise(suggestion=suggestion)
        if raw.startswith("/timed"):
            arg = raw.removeprefix("/timed").strip()
            self.timed = {"on": True, "off": False}.get(arg, not self.timed)
            return self._ask_premise(notice=f"已切換為{'限時' if self.timed else '一般'}模式。")
        if raw.startswith("/"):
            return self._ask_premise(notice=f"沒有 {raw} 這個指令，輸入 /help 查看說明。")

        premise = " ".join(raw.split()) or self._default_premise()
        state = GameState(premise=premise, timed_mode=self.timed)
        try:
            self.engine.start(state)
        except (errors.APIError, RuntimeError) as e:
            return self._failed(e, self._ask_premise)
        self.state, self.phase, self.last_premise, self.suggested = state, "playing", premise, ""
        save(state, self.save_path)
        return self._turn_reply(before=None)

    def _on_playing(self, raw: str) -> Reply:
        if raw == "/restart":
            self.phase = "confirm_restart"
            return self._reply(choices=["確定", "取消"], notice="確定要放棄目前進度、重新開始嗎？")
        action = self.action_for(raw)
        if action is None:
            notice = f"沒有 {raw} 這個指令，輸入 /help 查看說明。" if raw else "請輸入行動，或輸入數字選擇選項。"
            return self._reply(notice=notice, **self._screen())

        self._wait_compaction()
        before = snapshot(self.state)
        try:
            self.engine.act(self.state, action)
        except (errors.APIError, RuntimeError) as e:
            self.state = load(self.save_path) or self.state  # act() 可能已經改了一半的狀態，從存檔還原
            return self._failed(e, lambda **kw: self._reply(**self._screen(), **kw))
        save(self.state, self.save_path)
        if self.state.game_over:
            self.phase = "ending"
        else:
            self._start_compaction()
        return self._turn_reply(before)

    def _on_confirm_restart(self, raw: str) -> Reply:
        answer = self._pick(raw, ["確定", "取消"])
        if answer == "確定":
            self.last_premise = self.state.premise
            return self._ask_premise()
        if answer == "取消":
            self.phase = "playing"
            return self._reply(**self._screen())
        return self._reply(choices=["確定", "取消"], notice="請輸入 1（確定）或 2（取消）。")

    def _on_ending(self, raw: str) -> Reply:
        """故事結束後的下一次輸入：寫尾聲。尾聲寫失敗也照樣進到結束階段，可以再玩一次。"""
        s = self.state
        notice = ""
        if not s.epilogue:
            try:
                self.engine.write_epilogue(s)
                save(s, self.save_path)
            except (errors.APIError, RuntimeError) as e:
                notice = f"尾聲生成失敗：{str(e)[:200]}"
        self.phase = "ended"
        return self._reply(
            choices=["再玩一次"],
            notice=notice,
            ending=Ending(title=s.ending_title, epilogue=s.epilogue, record=ending_record(s)),
        )

    def _on_ended(self, raw: str) -> Reply:
        if self._pick(raw, ["再玩一次"]) or raw in ("/new", "/restart"):
            self.last_premise = self.state.premise
            return self._ask_premise()
        return self._reply(choices=["再玩一次"], notice="輸入 1 再玩一次。")

    # ---------- 共用 ----------

    def _ask_premise(self, suggestion: str = "", notice: str = "", error=None) -> Reply:
        self.phase = "ask_premise"
        return self._reply(
            premise_default=self._default_premise(),
            suggestion=suggestion,
            notice=notice,
            error=error,
        )

    def _default_premise(self) -> str:
        return self.suggested or self.last_premise or DEFAULT_PREMISE

    def _resume(self) -> Reply:
        self.phase = "playing"
        s = self.state
        return self._reply(narration=s.current_narration, notice=f"讀取存檔：{s.premise}", resumed=True, **self._screen())

    def _turn_reply(self, before) -> Reply:
        s = self.state
        return self._reply(
            narration=s.current_narration,
            changes=change_groups(before, s) if before is not None else [],
            **self._screen(),
        )

    def _screen(self) -> dict:
        """遊戲中畫面的固定部分：選項與限時。"""
        if self.state is None or self.phase not in ("playing", "ending"):
            return {}
        return {"choices": list(self.state.current_choices), "time_limit": self.state.current_time_limit}

    def _failed(self, e: Exception, retry_screen) -> Reply:
        """LLM 呼叫失敗：留在原本的階段，讓外殼決定要不要換 key 後重送。"""
        if is_key_error(e):
            return retry_screen(error="api_key", notice="API key 無效或沒有權限。")
        return retry_screen(error="api", notice=f"出錯了：{str(e)[:300]}")

    @staticmethod
    def _pick(raw: str, options: list[str]) -> str | None:
        """把「2」或選項本身的文字對應到選項。"""
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        return raw if raw in options else None

    def _status(self) -> Status | None:
        s = self.state
        if s is None:
            return None
        return Status(
            turn=s.turn,
            level=body_level(s),
            body=[(c.name, c.severity) for c in body_conditions(s)],
            mind=[(c.name, c.severity) for c in mind_conditions(s)],
            inventory=list(s.inventory),
        )

    def _reply(self, **fields) -> Reply:
        timed = self.state.timed_mode if self.state and self.phase != "ask_premise" else self.timed
        reply = Reply(phase=self.phase, timed=timed, status=self._status() if self.phase != "ask_premise" else None, **fields)
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


# ---------- 純文字版的回覆 ----------


def status_line(status: Status, timed: bool) -> str:
    parts = [f"回合 {status.turn}", f"狀態 {status.level}"]
    if status.body:
        parts[-1] += "：" + "、".join(f"{n}（{v}）" for n, v in status.body)
    if status.mind:
        parts.append("精神 " + "、".join(f"{n}（{v}）" for n, v in status.mind))
    parts.append("背包 " + ("、".join(status.inventory) or "空"))
    if timed:
        parts.append("限時模式")
    return "｜".join(parts)


def changes_line(groups: ChangeGroups) -> str:
    return "　".join(f"{label} " + "、".join(text for text, _ in items) for label, items in groups)


def render_text(reply: Reply) -> str:
    """把回覆組成一段完整的純文字。"""
    parts: list[str] = []
    if reply.notice:
        parts.append(f"（{reply.notice}）")
    if reply.info:
        title, body = reply.info
        parts.append(f"【{title}】\n{body}")
    if reply.phase == "ask_premise":
        if reply.suggestion:
            parts.append("想到一個開頭了，直接送出空白就用它開始，也可以自己修改後送出。")
        parts.append(
            f"新的故事（{'限時' if reply.timed else '一般'}模式）。輸入故事前提，或直接送出空白使用：\n{reply.premise_default}\n"
            "（/suggest 讓 AI 幫你想，/timed 切換限時模式）"
        )
    if reply.narration:
        parts.append(reply.narration)
    if reply.changes:
        parts.append(changes_line(reply.changes))
    if reply.ending:
        e = reply.ending
        parts.append(f"─── {e.title or '故事結束'} ───")
        if e.epilogue:
            parts.append(e.epilogue)
        parts.append(e.record)
    if reply.status and reply.phase in ("playing", "ending") and reply.narration:
        parts.append(status_line(reply.status, reply.timed))
    if reply.phase == "ending":
        parts.append("（故事結束了。送出任何文字查看尾聲。）")
    if reply.choices:
        parts.append("\n".join(f"{i}. {c}" for i, c in enumerate(reply.choices, 1)))
    if reply.time_limit:
        parts.append(f"（限時 {reply.time_limit} 秒）")
    return "\n\n".join(parts)
