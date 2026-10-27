"""核心：每種玩法共用的內部核心（隊伍遊戲的流程、回覆的格式、呼叫 AI、存檔、文字檔）。
玩法在 story.games，外殼在 story.shells；外殼只應該使用這裡與 story.games 匯出的名稱。"""

from story.core.ai import new_client
from story.core.prompts import Texts
from story.core.ratelimit import RateLimit
from story.core.reply import MAX_PLAYERS, ChangeGroups, Ending, InputMode, Reply, Status, pick_choice
from story.core.team import TeamGame as Game

__all__ = ["MAX_PLAYERS", "ChangeGroups", "Ending", "Game", "InputMode", "RateLimit", "Reply", "Status", "Texts", "pick_choice", "new_client"]
