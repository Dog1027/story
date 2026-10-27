"""海龜湯的題庫：一題一個 markdown 檔，段落是 title、surface（湯面）、truth（湯底）、key_points（關鍵點，一行一個）。

跟題材包一樣，內建的在 story/games/soup/puzzles/語言/，個人的在 ~/.config/story/puzzles/語言/；題目名稱相同時個人的優先。
格式不對的題目會略過，並說明原因。
"""

from pathlib import Path

from story import settings
from story.core import prompts
from story.games.soup.models import Puzzle
from story.games.soup.text import UI

BUILTIN_DIR = Path(__file__).resolve().parent / "puzzles" / prompts.LANGUAGE
PERSONAL_DIR = settings.CONFIG_DIR / "puzzles" / prompts.LANGUAGE
MIN_POINTS, MAX_POINTS = 2, 4  # 關鍵點的個數


class InvalidPuzzle(ValueError):
    """題目格式不對：訊息會說明是哪裡出錯。"""


def parse_puzzle(path: Path) -> Puzzle:
    parts = prompts.sections(path.stem, path.parent)
    missing = [key for key in ("title", "surface", "truth", "key_points") if not parts.get(key, "").strip()]
    if missing:
        raise InvalidPuzzle(UI["puzzle_missing"].format(sections="、".join(missing)))
    points = prompts.items(parts["key_points"])
    if not MIN_POINTS <= len(points) <= MAX_POINTS:
        raise InvalidPuzzle(UI["puzzle_points"].format(min=MIN_POINTS, max=MAX_POINTS))
    return Puzzle(title=parts["title"].strip(), surface=parts["surface"].strip(), truth=parts["truth"].strip(), key_points=points)


def load_puzzles(dirs: list[Path] | None = None) -> tuple[list[Puzzle], list[str]]:
    """讀取所有題目，回傳 (題目, 被略過的題目與原因)。後面的資料夾優先（個人的覆蓋內建的）。"""
    found: dict[str, Puzzle] = {}
    problems: list[str] = []
    for root in dirs if dirs is not None else [BUILTIN_DIR, PERSONAL_DIR]:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md")):
            try:
                puzzle = parse_puzzle(path)
            except InvalidPuzzle as e:
                problems.append(f"{path}：{e}")
                continue
            found[puzzle.title] = puzzle
    return list(found.values()), problems
