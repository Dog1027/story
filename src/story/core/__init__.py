"""核心：送文字進去、拿回覆出來。外殼只應該使用這裡匯出的名稱。"""

from story.core.ai import new_client
from story.core.models import word
from story.core.prompts import ui as ui_text
from story.core.ratelimit import RateLimit
from story.core.records import ChangeGroups
from story.core.reply import MAX_PLAYERS, Ending, InputMode, Reply, Status, pick_choice
from story.core.session import GENRE_AUTO, GENRE_NONE, StoryCore
from story.core.soup import SoupCore
from story.core.team import TeamGame as Game

__all__ = ["GENRE_AUTO", "GENRE_NONE", "MAX_PLAYERS", "ChangeGroups", "Ending", "Game", "InputMode", "RateLimit", "Reply", "Status", "SoupCore", "StoryCore", "pick_choice", "new_client", "ui_text", "word"]
