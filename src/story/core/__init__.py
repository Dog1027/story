"""核心：送文字進去、拿回覆出來。外殼只應該使用這裡匯出的名稱。"""

from story.core.records import ChangeGroups, Tone
from story.core.session import Ending, Phase, Reply, Status, StoryCore

__all__ = ["ChangeGroups", "Ending", "Phase", "Reply", "Status", "StoryCore", "Tone"]
