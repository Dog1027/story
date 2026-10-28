"""Games: one folder per game, side by side, each built on story.core (subclasses of TeamGame). Shells pick one from GAMES."""

from story.games.adventure import AdventureCore
from story.games.soup import SoupCore

GAMES = {"adventure": AdventureCore, "soup": SoupCore}  # Code → game; the code is also used in save file names

__all__ = ["AdventureCore", "GAMES", "SoupCore"]
