"""遊戲資料結構：程式掌控的狀態（GameState）與 LLM 回傳的格式（StoryBeat）。"""

from pydantic import BaseModel, Field


class StoryBeat(BaseModel):
    """LLM 每回合必須回傳的結構。程式會驗證後才套用到狀態。"""

    narration: str = Field(description="本回合的劇情敘述，第二人稱，150-300 字")
    choices: list[str] = Field(description="給玩家的 2-4 個行動選項，每個一句話")
    conditions_added: list[str] = Field(description="本回合新出現的身體或精神狀態，每項 2-8 字，例如「左臂擦傷」「疲憊」「中毒」「驚魂未定」")
    conditions_removed: list[str] = Field(description="本回合痊癒或消失的狀態，必須是目前已有的狀態")
    time_limit: int = Field(description="限時模式下，情勢緊迫時給玩家的反應秒數（8-60，越危急越短）；不緊迫或非限時模式為 0")
    items_gained: list[str] = Field(description="玩家本回合獲得的物品名稱")
    items_lost: list[str] = Field(description="玩家本回合失去或用掉的物品名稱，必須是目前持有的")
    flags_set: list[str] = Field(description="本回合確立的劇情事實，例如「與守門人結仇」「得知密道位置」")
    key_event: str = Field(description="若本回合有值得長期記住的大事，用一句話記下；沒有則為空字串")
    game_over: bool = Field(description="故事是否在本回合結束（死亡、達成結局等）")


class Turn(BaseModel):
    """一回合的原文紀錄，用於近期記憶。"""

    narration: str
    action: str  # 玩家在看完 narration 之後做的事


class GameState(BaseModel):
    """所有程式記住的東西。存檔就是把它序列化成 JSON。"""

    premise: str
    turn: int = 0
    conditions: list[str] = Field(default_factory=list)  # 身體與精神狀態，空的代表狀況良好
    timed_mode: bool = False  # 限時模式：緊急情況要在時間內做出決定
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
