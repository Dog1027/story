"""Settings: ~/.config/story/config.toml, which can be edited by hand.

    language = "en"          # Language: zh-TW (default) or en
    api_key = "…"            # Gemini API key

In code, a setting is named "section.name", e.g. get("api_key"); settings with a section are written under [section].

Environment variables win over this file: STORY_LANG overrides language, GEMINI_API_KEY (or GOOGLE_API_KEY) overrides api_key,
so you can switch language or key temporarily without editing the file. The language and API key entered on first launch are written here (handwritten comments are lost).
The core, games and shells all read it; personal genre packs and turtle soup puzzles live in the same folder (~/.config/story/genres/<lang>/, puzzles/<lang>/).
"""

import json
import os
import tomllib
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "story"
CONFIG_PATH = CONFIG_DIR / "config.toml"
KEY_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
OLD_FILES = {"api_key": "api_key"}  # Each setting used to have its own file; moved into config.toml when read


def load() -> dict:
    """Read the config, flattened to {"section.name": value}; empty if there is none. An old api_key file is moved in first."""
    try:
        data = _flatten(tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except FileNotFoundError:
        data = {}
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"{CONFIG_PATH} is not valid TOML: {e}")
    if _migrate(data):
        _write(data)
    return data


def get(key: str) -> str | None:
    return load().get(key) or None


def put(key: str, value: str | None) -> None:
    """Write one setting; None deletes it."""
    data = load()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    _write(data)


def language() -> str:
    return os.environ.get("STORY_LANG") or get("language") or "zh-TW"


def api_key() -> str | None:
    """The API key from the environment or the config; None if neither has one."""
    for var in KEY_ENV_VARS:
        if key := os.environ.get(var, "").strip():
            return key
    return get("api_key")


def _migrate(data: dict) -> bool:
    changed = False
    for key, name in OLD_FILES.items():
        old = CONFIG_DIR / name
        if not old.is_file():
            continue
        value = old.read_text(encoding="utf-8").strip()
        if value and key not in data:
            data[key] = value
        old.unlink()
        changed = True
    return changed


def _flatten(table: dict, prefix: str = "") -> dict:
    flat = {}
    for key, value in table.items():
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{prefix}{key}."))
        else:
            flat[prefix + key] = value
    return flat


def _write(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Settings without a section come first; "section.name" goes under its own [section]. Values are all strings: a JSON string is also valid TOML
    line = lambda key, value: f"{key} = {json.dumps(value, ensure_ascii=False)}\n"  # noqa: E731
    sections: dict[str, dict] = {}
    for key, value in data.items():
        section, _, name = key.rpartition(".")
        sections.setdefault(section, {})[name] = value
    text = "".join(line(k, v) for k, v in sections.pop("", {}).items())
    for section, values in sections.items():
        text += ("\n" if text else "") + f"[{section}]\n" + "".join(line(k, v) for k, v in values.items())
    # It holds the API key: only the owner can read it, set when the file is created so no one can read it mid-write
    fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(CONFIG_PATH, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
