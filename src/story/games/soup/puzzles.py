"""The turtle soup puzzle bank: one markdown file per puzzle, with sections title, surface (the scenario), truth (the answer), key_points (one per line).

Like genre packs, built-in puzzles are in story/games/soup/puzzles/<lang>/ and personal ones in ~/.config/story/puzzles/<lang>/; personal ones win on the same name.
Puzzles with a bad format are skipped, with the reason.
"""

from pathlib import Path

from story import settings
from story.core import prompts
from story.games.soup.models import Puzzle
from story.games.soup.text import UI

BUILTIN_DIR = Path(__file__).resolve().parent / "puzzles" / prompts.LANGUAGE
PERSONAL_DIR = settings.CONFIG_DIR / "puzzles" / prompts.LANGUAGE
MIN_POINTS, MAX_POINTS = 2, 4  # How many key points


class InvalidPuzzle(ValueError):
    """A puzzle's format is wrong: the message says where."""


def parse_puzzle(path: Path) -> Puzzle:
    parts = prompts.sections(path.stem, path.parent)
    missing = [key for key in ("title", "surface", "truth", "key_points") if not parts.get(key, "").strip()]
    if missing:
        raise InvalidPuzzle(UI["puzzle_missing"].format(sections=UI["list_sep"].join(missing)))
    points = prompts.items(parts["key_points"])
    if not MIN_POINTS <= len(points) <= MAX_POINTS:
        raise InvalidPuzzle(UI["puzzle_points"].format(min=MIN_POINTS, max=MAX_POINTS))
    return Puzzle(title=parts["title"].strip(), surface=parts["surface"].strip(), truth=parts["truth"].strip(), key_points=points)


def load_puzzles(dirs: list[Path] | None = None) -> tuple[list[Puzzle], list[str]]:
    """Read every puzzle; returns (puzzles, skipped puzzles with reasons). Later folders win (personal over built-in)."""
    found: dict[str, Puzzle] = {}
    problems: list[str] = []
    for root in dirs if dirs is not None else [BUILTIN_DIR, PERSONAL_DIR]:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md")):
            try:
                puzzle = parse_puzzle(path)
            except InvalidPuzzle as e:
                problems.append(f"{path}: {e}")
                continue
            found[puzzle.title] = puzzle
    return list(found.values()), problems
