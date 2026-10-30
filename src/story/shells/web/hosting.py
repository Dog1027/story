"""What the web server hosts: every game in GAMES, all calling the AI with the host's key under one shared call limit,
with each team's saves in the project folder. The only place that ties the lobby and rooms to the games, settings and the AI client.
"""

from collections.abc import Callable
from pathlib import Path

from story import settings
from story.core import RateLimit, TeamGame, new_client
from story.games import GAMES
from story.shells.rooms.lobby import Lobby
from story.shells.rooms.room import GameChoice

AI_PER_MINUTE = 15  # Most AI calls per minute across all rooms (the free tier's flash-lite limit; raise it on a paid plan)


def saves_dir() -> Path:
    """Saves and game logs: saves/ in the project folder (settings.DATA_DIR)."""
    return settings.DATA_DIR / "saves"


def team_save(players: list[str], game: str) -> tuple[Path, Path]:
    """A team's save and log: the same people (in any order) can continue when they open a room again. One per game, with the game's code at the end of the file name.
    Names only have letters, digits, underscores and hyphens, so they work as file names directly."""
    team = "+".join(sorted(players)) + f".{game}"
    return saves_dir() / f"team-{team}.json", saves_dir() / f"team-{team}.log.jsonl"


def game_choices() -> list[GameChoice]:
    """Every game in GAMES, for the host's game picker."""
    return [GameChoice(code, game.title, game.description) for code, game in GAMES.items()]


def make_lobby(api_key: str) -> Lobby:
    """The web server's lobby: every room's core uses the host's key and shares one call limit."""
    saves_dir().mkdir(exist_ok=True)
    limit, client = RateLimit(AI_PER_MINUTE), new_client(api_key)

    def make_core(players: list[str], on_queue: Callable[[bool], None], game: str) -> TeamGame:
        save_path, log_path = team_save(players, game)
        return GAMES[game](api_key, players, save_path=save_path, log_path=log_path, client=limit.wrap(client, on_queue))

    return Lobby(game_choices(), make_core)
