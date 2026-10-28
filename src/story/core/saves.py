"""Saves: write a game's state (a pydantic model) to JSON and read it back. Each game has its own save format; this only reads and writes files."""

import os
import tempfile
from pathlib import Path

from pydantic import BaseModel

def save(state: BaseModel, path: Path) -> None:
    """Write to a temp file in the same folder, then swap it in at once. Any read sees a complete save,
    never an empty or broken file because a background memory compaction saved at the same moment or the program was killed mid-write."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(state.model_dump_json(indent=2))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load(path: Path, kind: type[BaseModel]):
    """Read a save; None if there is none. kind is the save format (GameState for the adventure, SoupState for turtle soup)."""
    if not path.exists():
        return None
    return kind.model_validate_json(path.read_text(encoding="utf-8"))
