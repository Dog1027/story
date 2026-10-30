"""Genre packs: let people who like designing stories add new genres without touching code.

The structure follows Agent Skills (Claude Code's skills): one folder per genre with a GENRE.md,
starting with settings fields (name, description) followed by writing guidance for the AI; premises.md, names.md and twists.md may be added.

    genres/<lang>/
    └── wuxia/            Folder names are in English; the genre name shown is name in GENRE.md (e.g. "Wuxia")
        ├── GENRE.md      Required: settings fields + writing guidance
        ├── premises.md   Optional: opening ideas, one per line (random openings, "another one", "suggest one")
        ├── names.md      Optional: material for names of people, places and groups, consulted when planning the outline
        └── twists.md     Optional: twist ideas, one per line, a few drawn at random when planning the outline

Like skills, disclosure is progressive, loading things only when needed:
- The catalog (name + description): when the players choose "auto", the AI gets the catalog at the start and picks a genre for the premise; players can also pick one themselves
- The guidance (GENRE.md's body): once chosen, placed near the start of every turn's prompt for the whole game (it never changes, so caching isn't affected)
- Extra files: only used at specific moments: premises.md for random openings, "another one" and "suggest one"; names.md for the outline and the opening; twists.md for the outline

Genre packs live in two places: built-in ones in story/games/adventure/genres/<lang>/ (with the project), personal ones in ~/.config/story/genres/<lang>/. Personal ones win on the same name.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from story import settings
from story.core import prompts
from story.games.adventure.text import UI  # Messages about genre pack format problems (ui/<lang>/adventure.md)

# A full set of genre packs per language (like the prompts; the language comes from story/settings.py)
BUILTIN_DIR = Path(__file__).resolve().parent / "genres" / prompts.LANGUAGE


def personal_dir() -> Path:
    """Your own genre packs, next to the config (read when loading, so it follows settings.CONFIG_DIR)."""
    return settings.CONFIG_DIR / "genres" / prompts.LANGUAGE


# Length limits (characters in Chinese, words in English; see prompts.text_length)
MAX_DESCRIPTION = 200  # Description: the whole catalog is sent every time an outline is planned
MAX_GUIDE = 2000  # Writing guidance: sent every turn; too long slows things down and dilutes the other rules
MAX_EXTRA = 2000  # premises.md, names.md, twists.md

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)


@dataclass
class Genre:
    name: str
    description: str
    guide: str  # GENRE.md's body: writing guidance
    premises: list[str] = field(default_factory=list)  # premises.md: opening ideas
    names: str = ""  # names.md: naming material
    twists: list[str] = field(default_factory=list)  # twists.md: twist ideas
    path: Path | None = None


class InvalidGenre(ValueError):
    """A genre pack's format is wrong: the message says where."""


def parse_genre(folder: Path) -> Genre:
    """Read one genre folder. Raises InvalidGenre if the format is wrong."""
    try:
        text = (folder / "GENRE.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    except OSError as e:
        raise InvalidGenre(UI["genre_no_file"]) from e
    match = FRONTMATTER.match(text)
    if not match:
        raise InvalidGenre(UI["genre_no_header"])
    fields = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            fields[key.strip()] = value.strip().strip("\"'")
    name = fields.get("name") or folder.name
    description = fields.get("description", "")
    guide = match.group(2).strip()
    if not description:
        raise InvalidGenre(UI["genre_no_description"])
    if prompts.text_length(description) > MAX_DESCRIPTION:
        raise InvalidGenre(UI["genre_long_description"].format(max=MAX_DESCRIPTION))
    if not guide:
        raise InvalidGenre(UI["genre_no_guide"])
    if (length := prompts.text_length(guide)) > MAX_GUIDE:
        raise InvalidGenre(UI["genre_long_guide"].format(max=MAX_GUIDE, length=length))
    return Genre(
        name=name,
        description=description,
        guide=guide,
        premises=_items(_extra(folder / "premises.md")),
        names=_extra(folder / "names.md"),
        twists=_items(_extra(folder / "twists.md")),
        path=folder,
    )


def _items(text: str) -> list[str]:
    """A list with one item per line, which may start with - or *."""
    return [item for line in text.splitlines() if (item := line.strip().lstrip("-*").strip())]


def _extra(path: Path) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    if prompts.text_length(text) > MAX_EXTRA:
        raise InvalidGenre(UI["genre_long_extra"].format(file=path.name, max=MAX_EXTRA))
    return text


def load_genres(dirs: list[Path] | None = None) -> tuple[dict[str, Genre], list[str]]:
    """Read every genre pack; returns (genre name → genre, skipped genres with reasons). Later folders win (personal over built-in)."""
    genres: dict[str, Genre] = {}
    problems: list[str] = []
    for root in dirs if dirs is not None else [BUILTIN_DIR, personal_dir()]:
        if not root.is_dir():
            continue
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            try:
                genre = parse_genre(folder)
            except InvalidGenre as e:
                problems.append(f"{folder}: {e}")
                continue
            genres[genre.name] = genre
    return genres, problems
