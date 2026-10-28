"""Reading text files: prompts for the AI and interface text for players are markdown files; the program only combines them with game data.

Each layer has its own text in its own folder, read with Texts:
- the core's shared interface text: story/core/ui/<lang>/
- each game: story/games/<game>/prompts/<lang>/ (for the AI) and ui/<lang>/ (for players)
- the shells: story/shells/ui/<lang>/

To change how the AI writes (rules, pacing reminders, the epilogue…), edit those files; no code changes needed. How to edit them: story/games/adventure/prompts/README.md.
One folder per language (zh-TW, en), with the same file and section names. The language comes from language in the config or the STORY_LANG environment variable (story/settings.py).

File format:
- <!-- --> comments at the top are notes for whoever writes the prompts (purpose, available variables) and are never sent to the AI.
- A file that is one whole prompt (e.g. system.md) is read with Texts.load().
- A file holding several short prompts starts each with "## name", read with Texts.sections() into {name: content}.
  Names may contain dots, e.g. "## StoryBeat.narration" in schema.md.
- A list with one item per line inside a section is read with items(); a "code: text" table with table().
- {name} is a variable filled in when combining (str.format). No other braces may appear in the content.
"""

import re
from pathlib import Path

from story import settings

LANGUAGE = settings.language()  # The language: the folder name under prompts/ and ui/
COMMENT = re.compile(r"<!--.*?-->", re.S)
HEADING = re.compile(r"^## ([\w.]+)\s*$", re.M)


# Text length: each CJK character counts as one; in other languages, each word (a run without spaces) counts as one.
# That way a length limit uses the same number in every language: 300 Chinese characters and 300 English words are about the same amount
_CJK = "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
UNIT = re.compile(f"[{_CJK}]|[^\\s{_CJK}]+")


def text_length(text: str) -> int:
    return len(UNIT.findall(text))


def clip(text: str, limit: int) -> str:
    """Keep only the first limit characters (or words); see text_length()."""
    units = list(UNIT.finditer(text))
    return text if len(units) <= limit else text[: units[limit - 1].end()]


def _read(name: str, folder: Path) -> str:
    path = folder / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found (language is {LANGUAGE}; every language needs a full set of files with the same names)")
    return COMMENT.sub("", path.read_text(encoding="utf-8").replace("\r\n", "\n"))


def sections(name: str, folder: Path) -> dict[str, str]:
    """The content under each "## name" in folder/<name>.md (blank lines at both ends removed, newlines in between kept)."""
    parts = HEADING.split(_read(name, folder))
    return {key: body.strip("\n") for key, body in zip(parts[1::2], parts[2::2], strict=True)}


class Texts:
    """One layer's own text (the core, a game, the shells): base is that layer's folder, with prompts/<lang>/ and ui/<lang>/ under it."""

    def __init__(self, base: Path):
        self.prompts_dir = Path(base) / "prompts" / LANGUAGE
        self.ui_dir = Path(base) / "ui" / LANGUAGE

    def load(self, name: str) -> str:
        """The whole file is one prompt."""
        return _read(name, self.prompts_dir).strip("\n")

    def sections(self, name: str) -> dict[str, str]:
        """Each section of a prompt file (prompts/<lang>/<name>.md)."""
        return sections(name, self.prompts_dir)

    def ui(self, name: str) -> dict[str, str]:
        """Interface text (ui/<lang>/<name>.md), same format as sections()."""
        return sections(name, self.ui_dir)


CORE = Texts(Path(__file__).resolve().parent)  # The core's shared interface text (story/core/ui/<lang>/core.md)
UI = CORE.ui("core")


def items(text: str) -> list[str]:
    """A list with one item per line (may start with -)."""
    return [item for line in text.splitlines() if (item := line.strip().removeprefix("- ").strip())]


def table(text: str) -> dict[str, str]:
    """A "code: text" table, one per line, e.g. the game state field names in context.md."""
    pairs = (line.split(":", 1) for line in text.splitlines() if ":" in line)
    return {key.strip(): value.strip() for key, value in pairs}
