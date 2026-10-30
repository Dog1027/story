"""Saves: write a game's state (a pydantic model) to JSON and read it back. Each game has its own save format; this only reads and writes files."""

import logging
import os
import tempfile
from pathlib import Path
from typing import Protocol, Self

from pydantic import ValidationError

log = logging.getLogger(__name__)


class Saveable(Protocol):
    """A save format: in practice a pydantic model, which already has both."""

    def model_dump_json(self, *, indent: int | None = None) -> str: ...

    @classmethod
    def model_validate_json(cls, json_data: str) -> Self: ...


def save(state: Saveable, path: Path) -> None:
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


def load[S: Saveable](path: Path, kind: type[S]) -> S | None:
    """Read a save; None if there is none. kind is the save format (GameState for the adventure, SoupState for turtle soup).
    A save that can't be read (broken, or from an older format) counts as none: it's renamed to *.broken so nothing is lost, and the team can start over."""
    if not path.exists():
        return None
    try:
        return kind.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        log.exception("could not read the save %s; moved it aside", path)
        path.replace(path.with_name(path.name + ".broken"))
        return None
