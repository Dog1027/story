"""遊戲資料結構：程式掌控的狀態（GameState）與 LLM 回傳的格式（StoryBeat）。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["輕", "中", "重"]
ConditionKind = Literal["身體", "精神"]
TimeSpan = Literal["瞬間", "片刻", "一陣子", "數小時", "一夜", "數天"]
TimeOfDay = Literal["清晨", "上午", "中午", "下午", "傍晚", "夜晚", "深夜"]


class ConditionChange(BaseModel):
    """LLM 回報的狀態：新出現的，或程度改變的。"""

    name: str = Field(description="狀態名稱，2-8 字，例如「右腿骨折」「中毒」「恐懼」")
    kind: ConditionKind = Field(description="身體＝受傷、疲勞、中毒、疾病；精神＝恐懼、驚慌、絕望、憤怒")
    severity: Severity = Field(description="輕＝不影響行動；中＝明顯妨礙行動；重＝危及性命")


class Condition(BaseModel):
    """玩家身上的一個狀態。程式另外記錄在目前程度下經過了多少遊戲內時間，用來計算痊癒。"""

    name: str
    kind: ConditionKind = "身體"  # 舊存檔沒有這個欄位，先當成身體；AI 下次回報時會更正
    severity: Severity
    minutes: int = 0


class StoryBeat(BaseModel):
    """LLM 每回合必須回傳的結構。程式會驗證後才套用到狀態。"""

    narration: str = Field(description="本回合的劇情敘述，第二人稱，150-300 字")
    choices: list[str] = Field(description="給玩家的 2-4 個行動選項，每個一句話")
    conditions_changed: list[ConditionChange] = Field(description="新出現的狀態，或程度改變的既有狀態")
    conditions_removed: list[str] = Field(description="痊癒或消失的既有狀態名稱")
    time_passed: TimeSpan = Field(
        description="本回合經過的時間：瞬間＝打鬥閃避；片刻＝對話、搜索；一陣子＝趕路，約一小時；一夜＝睡覺"
    )
    start_time_of_day: TimeOfDay = Field(description="現在的時段；只在開場或時間「尚未確定」時採用")
    time_limit: int = Field(description="限時模式下緊迫時的反應秒數，否則為 0")
    milestone_reached: bool = Field(description="本回合是否達成了「故事進度」中目前這一幕的里程碑")
    items_gained: list[str] = Field(description="玩家本回合獲得的物品名稱")
    items_lost: list[str] = Field(description="玩家本回合失去或用掉的物品名稱")
    flags_set: list[str] = Field(description="新確立的長期事實，例如「與守門人結仇」；通常為空")
    key_event: str = Field(description="改變故事走向的大事，一句話；大多數回合為空字串")
    game_over: bool = Field(description="故事是否在本回合結束（死亡、達成結局等）")


class CharacterUpdate(BaseModel):
    """多人模式：AI 回報某一位角色這回合的變化與下一步的選項。"""

    name: str = Field(description="角色名字，必須是「隊伍」裡的名字")
    choices: list[str] = Field(description="給這位角色的 2-4 個行動選項，每個一句話；角色已死亡時留空")
    conditions_changed: list[ConditionChange] = Field(description="這位角色新出現的狀態，或程度改變的既有狀態")
    conditions_removed: list[str] = Field(description="這位角色痊癒或消失的既有狀態名稱")
    items_gained: list[str] = Field(description="這位角色本回合獲得的物品名稱")
    items_lost: list[str] = Field(description="這位角色本回合失去或用掉的物品名稱")


class PartyBeat(BaseModel):
    """多人模式每回合的回傳：一段包含所有角色的劇情，加上每位角色各自的變化。"""

    narration: str = Field(description="本回合的劇情敘述，包含每位角色行動的結果，200-400 字；提到角色時用名字")
    character_updates: list[CharacterUpdate] = Field(description="隊伍中每位角色各一筆，順序和「隊伍」相同")
    time_passed: TimeSpan = Field(
        description="本回合經過的時間：瞬間＝打鬥閃避；片刻＝對話、搜索；一陣子＝趕路，約一小時；一夜＝睡覺"
    )
    start_time_of_day: TimeOfDay = Field(description="現在的時段；只在開場或時間「尚未確定」時採用")
    time_limit: int = Field(description="限時模式下緊迫時的反應秒數，否則為 0")
    milestone_reached: bool = Field(description="本回合是否達成了「故事進度」中目前這一幕的里程碑")
    flags_set: list[str] = Field(description="新確立的長期事實，例如「與守門人結仇」；通常為空")
    key_event: str = Field(description="改變故事走向的大事，一句話；大多數回合為空字串")
    game_over: bool = Field(description="故事是否在本回合自然走到結局")


class Act(BaseModel):
    name: str = Field(description="這一幕的名稱，4-8 字")
    milestone: str = Field(description="這一幕結束前必須發生的關鍵事件，一句話，要具體可判斷")


class StoryArc(BaseModel):
    """隱藏的故事大綱：AI 依照它推進劇情，程式依照它控制節奏。不顯示給玩家。"""

    goal: str = Field(description="主角在這個故事裡的核心目標或要解開的謎團，一句話")
    acts: list[Act] = Field(description="剛好四幕：起（建立處境）、承（深入與阻礙）、轉（重大轉折）、合（高潮與結局）")
    endings: list[str] = Field(description="2-3 種可能的結局方向，依玩家的抉擇而定，各一句話")


class Epilogue(BaseModel):
    """故事結束後的尾聲。"""

    title: str = Field(description="結局名稱，4-10 字，像小說的章名，例如「燈塔守望者」「未寄出的信」")
    text: str = Field(description="尾聲，150-250 字：回顧主角這趟旅程的關鍵抉擇，交代結局帶來的餘韻，可以提到其他角色之後的命運")


class Turn(BaseModel):
    """一回合的原文紀錄，用於近期記憶。"""

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
    recent: list[Turn] = Field(default_factory=list)  # 近期：最近幾回合原文
    unsummarized: list[Turn] = Field(default_factory=list)  # 擠出近期、等待併入摘要的回合

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
