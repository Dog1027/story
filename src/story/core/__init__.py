"""核心：送文字進去、拿回覆出來。外殼只應該使用這裡匯出的名稱。"""

from story.core.records import ChangeGroups, Tone
from story.core.party import MAX_PLAYERS, MIN_PLAYERS, PartyCore
from story.core.session import GENRE_AUTO, GENRE_NONE, Ending, Phase, Reply, Status, StoryCore, pick_choice

__all__ = ["GENRE_AUTO", "GENRE_NONE", "MAX_PLAYERS", "MIN_PLAYERS", "ChangeGroups", "Ending", "PartyCore", "Phase", "Reply", "Status", "StoryCore", "Tone", "pick_choice"]
