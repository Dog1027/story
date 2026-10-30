"""Games: one folder per game, side by side, each built on story.core (subclasses of TeamGame). Shells pick one from GAMES."""

from story.games.adventure.game import AdventureCore
from story.games.soup.game import SoupCore

GAMES = {"adventure": AdventureCore, "soup": SoupCore}  # Code → game (each one a story.core.GameMaker); the code is also used in save file names

__all__ = ["AdventureCore", "GAMES", "SoupCore"]
