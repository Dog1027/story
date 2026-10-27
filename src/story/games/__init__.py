"""玩法：每種玩法一個資料夾，彼此平行，都建立在 story.core 之上（TeamGame 的子類別）。外殼用 GAMES 選要玩哪一種。"""

from story.games.adventure import GENRE_AUTO, GENRE_NONE, StoryCore
from story.games.soup import SoupCore

GAMES = {"story": StoryCore, "soup": SoupCore}  # 代號 → 玩法；代號也用在存檔的檔名

__all__ = ["GAMES", "GENRE_AUTO", "GENRE_NONE", "SoupCore", "StoryCore"]
