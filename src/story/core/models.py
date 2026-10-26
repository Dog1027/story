"""遊戲資料結構：程式掌控的狀態（GameState）與 LLM 回傳的格式（StoryBeat）。"""

from typing import Literal, get_args

from pydantic import BaseModel, Field

from story.core import prompts

SCHEMA = prompts.sections("schema")  # 欄位說明（story/prompts/語言/schema.md），跟著回傳格式送給 AI

# 遊戲詞彙：程式與存檔用代號；給 AI 看、AI 回傳、顯示給玩家時，換成 story/prompts/語言/vocab.md 裡這個語言的詞
Severity = Literal["light", "moderate", "severe"]  # 由輕到重
ConditionKind = Literal["body", "mind"]
TimeSpan = Literal["instant", "moment", "while", "hours", "night", "days"]
TimeOfDay = Literal["dawn", "morning", "noon", "afternoon", "dusk", "evening", "late_night"]
Level = Literal["healthy", "minor", "injured", "serious", "dying", "dead"]  # 身體的整體狀態，由好到壞
SoupAnswer = Literal["yes", "no", "irrelevant", "partly", "not_question"]  # 海龜湯：裁判對提問的回答
CODES = {"severity": Severity, "kind": ConditionKind, "time_span": TimeSpan, "time_of_day": TimeOfDay, "level": Level, "soup_answer": SoupAnswer}
VOCAB = {category: prompts.table(body) for category, body in prompts.sections("vocab").items()}  # {類別: {代號: 詞}}
for _category, _codes in CODES.items():
    if missing := set(get_args(_codes)) - set(VOCAB.get(_category, {})):
        raise ValueError(f"vocab.md 的「{_category}」少了：{'、'.join(sorted(missing))}")


def word(category: str, code: str) -> str:
    """代號 → 這個語言的詞，例如 word("severity", "severe") 是「重」。"""
    return VOCAB[category][code]


def code(category: str, text: str) -> str:
    """這個語言的詞 → 代號（AI 回傳的是詞）。"""
    return next(c for c, w in VOCAB[category].items() if w == text)


def words(category: str):
    """AI 回傳格式用的選項：這個類別所有的詞，依代號的順序。"""
    return Literal[tuple(word(category, c) for c in get_args(CODES[category]))]


class ConditionChange(BaseModel):
    """AI 回報的一個狀態：新出現的，或程度改變的。"""

    name: str = Field(description=SCHEMA["ConditionChange.name"])
    kind: words("kind") = Field(description=SCHEMA["ConditionChange.kind"])
    severity: words("severity") = Field(description=SCHEMA["ConditionChange.severity"])


class Condition(BaseModel):
    """角色身上的一個狀態。程式另外記錄在目前程度下經過了多少遊戲內時間，用來計算痊癒。"""

    name: str
    kind: ConditionKind = "body"
    severity: Severity
    minutes: int = 0


class CharacterUpdate(BaseModel):
    """AI 回報某一位角色這回合的變化與下一步的選項。"""

    name: str = Field(description=SCHEMA["CharacterUpdate.name"])
    choices: list[str] = Field(description=SCHEMA["CharacterUpdate.choices"])
    conditions_changed: list[ConditionChange] = Field(description=SCHEMA["CharacterUpdate.conditions_changed"])
    conditions_removed: list[str] = Field(description=SCHEMA["CharacterUpdate.conditions_removed"])
    items_gained: list[str] = Field(description=SCHEMA["CharacterUpdate.items_gained"])
    items_lost: list[str] = Field(description=SCHEMA["CharacterUpdate.items_lost"])


class StoryBeat(BaseModel):
    """AI 每回合必須回傳的結構：一段包含所有角色的劇情，加上每位角色各自的變化。程式驗證後才套用到狀態。
    欄位順序就是 AI 輸出的順序：先決定是不是結局，接著是劇情（串流時邊收邊顯示），其他變化最後由程式驗證後套用。"""

    game_over: bool = Field(description=SCHEMA["StoryBeat.game_over"])
    narration: str = Field(description=SCHEMA["StoryBeat.narration"])
    character_updates: list[CharacterUpdate] = Field(description=SCHEMA["StoryBeat.character_updates"])
    time_passed: words("time_span") = Field(description=SCHEMA["StoryBeat.time_passed"])
    start_time_of_day: words("time_of_day") = Field(description=SCHEMA["StoryBeat.start_time_of_day"])
    time_limit: int = Field(description=SCHEMA["StoryBeat.time_limit"])
    milestone_reached: bool = Field(description=SCHEMA["StoryBeat.milestone_reached"])
    flags_set: list[str] = Field(description=SCHEMA["StoryBeat.flags_set"])
    key_event: str = Field(description=SCHEMA["StoryBeat.key_event"])


class Act(BaseModel):
    name: str = Field(description=SCHEMA["Act.name"])
    milestone: str = Field(description=SCHEMA["Act.milestone"])


class StoryArc(BaseModel):
    """隱藏的故事大綱：AI 依照它推進劇情，程式依照它控制節奏。不顯示給玩家。"""

    goal: str = Field(description=SCHEMA["StoryArc.goal"])
    twist: str = Field(description=SCHEMA["StoryArc.twist"])
    clues: list[str] = Field(description=SCHEMA["StoryArc.clues"])
    acts: list[Act] = Field(description=SCHEMA["StoryArc.acts"])
    endings: list[str] = Field(description=SCHEMA["StoryArc.endings"])


class GenrePick(BaseModel):
    """玩家選「自動」題材時，AI 依故事前提挑一個。"""

    genre: str = Field(description=SCHEMA["GenrePick.genre"])


class Epilogue(BaseModel):
    """故事結束後的尾聲。"""

    title: str = Field(description=SCHEMA["Epilogue.title"])
    text: str = Field(description=SCHEMA["Epilogue.text"])


class Turn(BaseModel):
    """一回合的原文紀錄（劇情與玩家的行動）。"""

    narration: str
    action: str  # 玩家們在看完 narration 之後做的事（每位角色一行）


class Character(BaseModel):
    """隊伍裡的一位角色，由一位玩家扮演。"""

    name: str
    conditions: list[Condition] = Field(default_factory=list)  # 身體與精神狀態，空的代表狀況良好
    inventory: list[str] = Field(default_factory=list)
    choices: list[str] = Field(default_factory=list)  # 這位角色目前的選項
    alive: bool = True


class GameState(BaseModel):
    """所有程式記住的東西。存檔就是把它序列化成 JSON。"""

    premise: str
    characters: list[Character]  # 隊伍：一到四位角色，一個人玩就是只有一位
    turn: int = 0
    timed_mode: bool = False  # 限時模式：緊急情況要在時間內做出決定
    genre: str = ""  # 題材包的名稱（GENRE.md 的 name）；空的代表不套用題材
    genre_pending: bool = False  # 玩家選「自動」：規劃大綱時由 AI 依前提從題材目錄挑一個
    arc: StoryArc | None = None  # 隱藏的故事大綱（開場前規劃，失敗時下回合再補）
    act: int = 0  # 目前在第幾幕（0-3）
    act_turns: int = 0  # 在目前這一幕已經待了幾回合
    minutes: int | None = None  # 遊戲內時鐘：從第 1 天 0:00 起算的分鐘數；None 代表還沒決定（開場前）。只給 AI 看，不顯示給玩家
    flags: list[str] = Field(default_factory=list)

    # 分層記憶
    summary: str = ""  # 長期：較早劇情的壓縮摘要
    key_events: list[str] = Field(default_factory=list)  # 長期：重大事件清單
    recent: list[Turn] = Field(default_factory=list)  # 劇情紀錄：每回合的原文，只往後追加，太長時最舊的才壓縮進摘要

    # 目前畫面（讀檔後能接續顯示）
    current_narration: str = ""
    current_time_limit: int = 0  # 本回合的反應時間（秒），0 代表不限時
    game_over: bool = False
    ending_title: str = ""  # 故事結束後才有：結局名稱與尾聲
    epilogue: str = ""

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.characters]

    @property
    def solo(self) -> bool:
        """只有一位角色：提示詞與畫面用第二人稱「你」、不列名字。"""
        return len(self.characters) == 1
