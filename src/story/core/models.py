"""遊戲資料結構：程式掌控的狀態（GameState）與 LLM 回傳的格式（StoryBeat）。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from story.core import prompts

SCHEMA = prompts.sections("schema")  # 欄位說明（story/prompts/語言/schema.md），跟著回傳格式送給 AI

Severity = Literal["輕", "中", "重"]
ConditionKind = Literal["身體", "精神"]
TimeSpan = Literal["瞬間", "片刻", "一陣子", "數小時", "一夜", "數天"]
TimeOfDay = Literal["清晨", "上午", "中午", "下午", "傍晚", "夜晚", "深夜"]


class ConditionChange(BaseModel):
    """LLM 回報的狀態：新出現的，或程度改變的。"""

    name: str = Field(description=SCHEMA["ConditionChange.name"])
    kind: ConditionKind = Field(description=SCHEMA["ConditionChange.kind"])
    severity: Severity = Field(description=SCHEMA["ConditionChange.severity"])


class Condition(BaseModel):
    """玩家身上的一個狀態。程式另外記錄在目前程度下經過了多少遊戲內時間，用來計算痊癒。"""

    name: str
    kind: ConditionKind = "身體"  # 舊存檔沒有這個欄位，先當成身體；AI 下次回報時會更正
    severity: Severity
    minutes: int = 0


class StoryBeat(BaseModel):
    """LLM 每回合必須回傳的結構。程式會驗證後才套用到狀態。
    欄位順序就是 AI 輸出的順序：先決定是不是結局，接著是劇情（串流時邊收邊顯示），其他變化最後由程式驗證後套用。"""

    game_over: bool = Field(description=SCHEMA["StoryBeat.game_over"])
    narration: str = Field(description=SCHEMA["StoryBeat.narration"])
    choices: list[str] = Field(description=SCHEMA["StoryBeat.choices"])
    conditions_changed: list[ConditionChange] = Field(description=SCHEMA["StoryBeat.conditions_changed"])
    conditions_removed: list[str] = Field(description=SCHEMA["StoryBeat.conditions_removed"])
    time_passed: TimeSpan = Field(description=SCHEMA["StoryBeat.time_passed"])
    start_time_of_day: TimeOfDay = Field(description=SCHEMA["StoryBeat.start_time_of_day"])
    time_limit: int = Field(description=SCHEMA["StoryBeat.time_limit"])
    milestone_reached: bool = Field(description=SCHEMA["StoryBeat.milestone_reached"])
    items_gained: list[str] = Field(description=SCHEMA["StoryBeat.items_gained"])
    items_lost: list[str] = Field(description=SCHEMA["StoryBeat.items_lost"])
    flags_set: list[str] = Field(description=SCHEMA["StoryBeat.flags_set"])
    key_event: str = Field(description=SCHEMA["StoryBeat.key_event"])


class CharacterUpdate(BaseModel):
    """多人模式：AI 回報某一位角色這回合的變化與下一步的選項。"""

    name: str = Field(description=SCHEMA["CharacterUpdate.name"])
    choices: list[str] = Field(description=SCHEMA["CharacterUpdate.choices"])
    conditions_changed: list[ConditionChange] = Field(description=SCHEMA["CharacterUpdate.conditions_changed"])
    conditions_removed: list[str] = Field(description=SCHEMA["CharacterUpdate.conditions_removed"])
    items_gained: list[str] = Field(description=SCHEMA["CharacterUpdate.items_gained"])
    items_lost: list[str] = Field(description=SCHEMA["CharacterUpdate.items_lost"])


class PartyBeat(BaseModel):
    """多人模式每回合的回傳：一段包含所有角色的劇情，加上每位角色各自的變化。欄位順序同 StoryBeat。"""

    game_over: bool = Field(description=SCHEMA["PartyBeat.game_over"])
    narration: str = Field(description=SCHEMA["PartyBeat.narration"])
    character_updates: list[CharacterUpdate] = Field(description=SCHEMA["PartyBeat.character_updates"])
    time_passed: TimeSpan = Field(description=SCHEMA["PartyBeat.time_passed"])
    start_time_of_day: TimeOfDay = Field(description=SCHEMA["PartyBeat.start_time_of_day"])
    time_limit: int = Field(description=SCHEMA["PartyBeat.time_limit"])
    milestone_reached: bool = Field(description=SCHEMA["PartyBeat.milestone_reached"])
    flags_set: list[str] = Field(description=SCHEMA["PartyBeat.flags_set"])
    key_event: str = Field(description=SCHEMA["PartyBeat.key_event"])


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

    @model_validator(mode="before")
    @classmethod
    def _old_saves(cls, data):
        """舊存檔的大綱沒有真相與伏筆：補空值，照常讀取（只是沒有轉折的提醒）。"""
        if isinstance(data, dict):
            data = {"twist": "", "clues": [], **data}
        return data


class GenrePick(BaseModel):
    """玩家選「自動」題材時，AI 依故事前提挑一個。"""

    genre: str = Field(description=SCHEMA["GenrePick.genre"])


class Epilogue(BaseModel):
    """故事結束後的尾聲。"""

    title: str = Field(description=SCHEMA["Epilogue.title"])
    text: str = Field(description=SCHEMA["Epilogue.text"])


class Turn(BaseModel):
    """一回合的原文紀錄（劇情與玩家行動）。"""

    narration: str
    action: str  # 玩家在看完 narration 之後做的事


class Character(BaseModel):
    """多人模式的一位角色。單人模式不用這個，主角的狀態直接放在 GameState 上。"""

    name: str
    conditions: list[Condition] = Field(default_factory=list)
    inventory: list[str] = Field(default_factory=list)
    choices: list[str] = Field(default_factory=list)  # 這位角色目前的選項
    alive: bool = True


class GameState(BaseModel):
    """所有程式記住的東西。存檔就是把它序列化成 JSON。"""

    premise: str
    turn: int = 0
    conditions: list[Condition] = Field(default_factory=list)  # 身體與精神狀態，空的代表狀況良好
    timed_mode: bool = False  # 限時模式：緊急情況要在時間內做出決定
    genre: str = ""  # 題材包的名稱（GENRE.md 的 name）；空的代表不套用題材
    genre_pending: bool = False  # 玩家選「自動」：規劃大綱時由 AI 依前提從題材目錄挑一個
    party: list[Character] = Field(default_factory=list)  # 多人模式的隊伍；空的代表單人模式（主角用下面的 conditions、inventory）
    arc: StoryArc | None = None  # 隱藏的故事大綱（舊存檔沒有，會在下回合補上）
    act: int = 0  # 目前在第幾幕（0-3）
    act_turns: int = 0  # 在目前這一幕已經待了幾回合
    minutes: int | None = None  # 遊戲內時鐘：從第 1 天 0:00 起算的分鐘數；None 代表還沒決定（開場前或舊存檔）。只給 AI 看，不顯示給玩家
    inventory: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)

    # 分層記憶
    summary: str = ""  # 長期：較早劇情的壓縮摘要
    key_events: list[str] = Field(default_factory=list)  # 長期：重大事件清單
    recent: list[Turn] = Field(default_factory=list)  # 劇情紀錄：每回合的原文，只往後追加，太長時最舊的才壓縮進摘要
    unsummarized: list[Turn] = Field(default_factory=list)  # 舊存檔用：以前擠出近期、等待壓縮的回合（新的遊戲不會用到）

    # 目前畫面（讀檔後能接續顯示）
    current_narration: str = ""
    current_choices: list[str] = Field(default_factory=list)
    current_time_limit: int = 0  # 本回合的反應時間（秒），0 代表不限時
    game_over: bool = False
    ending_title: str = ""  # 故事結束後才有：結局名稱與尾聲
    epilogue: str = ""

    @field_validator("conditions", mode="before")
    @classmethod
    def _upgrade_old_conditions(cls, value):
        """相容舊存檔：以前的狀態只是字串，一律當成輕微。"""
        return [{"name": c, "severity": "輕"} if isinstance(c, str) else c for c in value]
