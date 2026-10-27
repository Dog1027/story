"""核心回給外殼的資料：Reply 與它裡面的 Status、Ending、InputMode。每種玩法都用同一種回覆，
外殼不用知道現在玩的是哪一種遊戲。"""

from dataclasses import asdict, dataclass, field
from typing import Literal

from story.core.prompts import UI  # 給玩家看的文字（story/core/ui/語言/core.md）

Phase = Literal[
    "ask_continue",  # 找到存檔，問要不要繼續
    "ask_premise",  # 冒險：等玩家輸入故事前提
    "ask_puzzle",  # 海龜湯：選要從題庫抽一題還是請 AI 出一題（choices 是兩個選項，notice 是問句）
    "playing",  # 遊戲中
    "confirm_restart",  # 確認是否放棄目前進度
    "ending",  # 剛結束，下一次輸入會整理結局（冒險會請 AI 寫尾聲）
    "ended",  # 結局整理好了，可以再玩一次
]

MAX_PLAYERS = 4  # 一隊最多幾位玩家

# 回合間的變化（Reply.changes）。每個項目的語氣，由外殼決定怎麼呈現（例如上什麼顏色）：
# light／moderate／severe＝新出現的狀態的程度；good＝好轉、痊癒；bad＝惡化；plain＝一般（獲得物品）；muted＝不重要（失去物品）
Tone = Literal["light", "moderate", "severe", "good", "bad", "plain", "muted"]
ChangeGroups = list[tuple[str, list[tuple[str, Tone]]]]  # [(標籤, [(文字, 語氣)])]


def join(items) -> str:
    return UI["list_sep"].join(items)


def pick_choice(raw: str, options: list[str]) -> str | None:
    """把「2」或選項本身的文字對應到選項，對不上時回傳 None。網頁版也用它，先顯示自己選了什麼。"""
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    return raw if raw in options else None


@dataclass
class Status:
    """狀態列上的一位玩家（冒險是他的角色）。背包不在這裡，變化在 changes，完整內容用 /state 看。"""

    conditions: list[tuple[str, str]]  # 要列出的項目：(文字, 語氣的代號)。冒險是狀態與程度（身體在前、精神在後），海龜湯是提問數、說中幾點
    warning: str = ""  # 要警告玩家的整體狀態代號（serious、dying：再受傷就有生命危險）；不危險時是空字串
    name: str = ""  # 名字
    alive: bool = True  # 角色是否還活著
    warning_text: str = ""  # 警告顯示的詞，例如「重傷」
    fine: str = ""  # conditions 是空的時候顯示的詞，例如「良好」


@dataclass
class Ending:
    title: str
    epilogue: str  # 冒險是尾聲，海龜湯是湯底
    record: str  # 旅程紀錄：回合數、天數、重大事件……
    reveal: str = ""  # 顯示 epilogue 之前，請玩家按 Enter 的提示；空的時候外殼用自己的（「按 Enter 看尾聲」）


@dataclass
class InputMode:
    """輸入的方式（海龜湯的「提問」「猜湯底」「放棄」）。有這些時，選項是切換方式，不是行動本身：
    選了要打字的方式，接下來輸入框打的字就用這個方式送出（command 加上文字）；不用打字的直接送出 command。"""

    label: str  # 選項上的字，也是行動前面的標籤（例如「問」）
    command: str  # 送給核心的指令，例如 /ask
    hint: str = ""  # 選了這個方式後，輸入框的提示
    needs_text: bool = True


@dataclass
class Reply:
    phase: Phase
    turn: int = 0  # 目前是第幾回合；還沒開始時是 0
    timed: bool = False  # 目前是否為限時模式（遊戲中是這一局的模式，等前提時是開新局會用的模式）
    narration: str = ""  # 這次產生（或讀檔重新顯示）的劇情；沒有新劇情時是空字串
    choices: list[str] = field(default_factory=list)
    characters: list[Status] = field(default_factory=list)  # 每位玩家的狀態（一個人玩只有一位）
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
    error: Literal["api"] | None = None  # 呼叫 AI 失敗（notice 是原因）：留在原本的階段，可以重試
    actor: str = ""  # 送出輸入的那位玩家（send_as、view 的對象；一個人玩就是他）這回合還沒行動時是他的名字，choices 是他的選項
    inputs: list[InputMode] = field(default_factory=list)  # 有的話，choices 是輸入的方式（見 InputMode），不是行動

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
        data["inputs"] = [InputMode(**m) for m in data.get("inputs", [])]
        return cls(**data)
