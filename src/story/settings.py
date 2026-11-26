"""Settings: config.toml in the project folder (next to pyproject.toml), which can be edited by hand. It holds the API key, so git ignores it;
config.example.toml shows what can go in it.

    language = "en"          # Language: zh-TW (default) or en
    ai = "gemini"            # Which AI: gemini, or ollama (a local model); gemini when unset

    [gemini]
    api_key = "…"            # Gemini API key

    [ollama]                 # A local model through Ollama (no API key needed)
    model = "…"              # The model's name in Ollama (ollama list)
    url = "http://localhost:11434"
    num_ctx = "16384"        # Context length in tokens

In code, a setting is named "section.name", e.g. get("gemini.api_key"); settings with a section are written under [section].

Environment variables win over this file: STORY_LANG overrides language, STORY_AI overrides ai, GEMINI_API_KEY (or GOOGLE_API_KEY) overrides gemini.api_key,
so you can switch language or key temporarily without editing the file. The language and API key entered on first launch are written here (handwritten comments are lost).
The core, games and shells all read it. It used to be in ~/.config/story/: migrate() moves an old one into the project folder.
"""

import json
import os
import tomllib
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "story"  # Where config.toml was before 2026-11 (only read to move it)
# The project folder (where pyproject.toml is): config.toml, saves/ and eval_results/ go here, whatever folder the program is started from
DATA_DIR = Path(__file__).resolve().parents[2]
KEY_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
AIS = ("gemini", "ollama")


class InvalidConfig(Exception):
    """config.toml exists but can't be read as TOML; the message says where and why, for the person who edited it."""


def config_path() -> Path:
    """Where config.toml is: computed each time, so redirecting DATA_DIR (e.g. in tests) moves it too."""
    return DATA_DIR / "config.toml"


def old_config_path() -> Path:
    """Where config.toml was before 2026-11."""
    return CONFIG_DIR / "config.toml"


def _reading_path() -> Path:
    """The config to read: the old one until migrate() has moved it (importing the core reads the language before setup runs)."""
    path = config_path()
    return path if path.exists() or not old_config_path().is_file() else old_config_path()


def load() -> dict[str, str]:
    """Read the config, flattened to {"section.name": value}; empty if there is none. Only reads: importing the core reads the language through here."""
    path = _reading_path()
    try:
        data = _flatten(tomllib.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        data = {}
    except tomllib.TOMLDecodeError as e:
        raise InvalidConfig(f"{path} is not valid TOML: {e}") from e
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
    return get("gemini.api_key") or get("api_key")  # api_key: where it was before [gemini] (until migrate() moves it)


def ai() -> str:
    """Which AI to call: "gemini" (the default) or "ollama"."""
    value = (os.environ.get("STORY_AI") or get("ai") or "gemini").strip().lower()
    if value not in AIS:
        raise InvalidConfig(f'ai = "{value}" in {config_path()} (or STORY_AI) should be "gemini" or "ollama"')
    return value


def use_ollama() -> bool:
    return ai() == "ollama"


def ollama_model() -> str | None:
    """The local model in Ollama (ollama.model); used when ai is ollama."""
    return get("ollama.model")


def ollama_url() -> str:
    return get("ollama.url") or "http://localhost:11434"


def ollama_num_ctx() -> int:
    try:
        return int(get("ollama.num_ctx") or 16384)
    except ValueError:
        return 16384


def ai_ready() -> bool:
    """Whether the chosen AI can be called: a Gemini API key, or a local model's name for Ollama."""
    return bool(ollama_model() if use_ollama() else api_key())


def migrate() -> None:
    """Move old settings into the project's config.toml (setup.run() calls this on launch):
    ~/.config/story/config.toml (before 2026-11), the API key in its own file ~/.config/story/api_key (older still),
    and a top-level api_key (before [gemini], 2026-11) into gemini.api_key."""
    new, old_config = config_path(), old_config_path()
    if old_config.is_file() and not new.exists() and old_config.resolve() != new.resolve():
        _write(load())  # Written fresh, so the new file gets the owner-only permissions too
        old_config.unlink()
    old = CONFIG_DIR / "api_key"
    if old.is_file():
        data = load()
        if (value := old.read_text(encoding="utf-8").strip()) and not data.get("api_key") and not data.get("gemini.api_key"):
            data["gemini.api_key"] = value
        old.unlink()
        _write(data)
    data = load()
    if "api_key" in data:
        value = data.pop("api_key")
        data.setdefault("gemini.api_key", value)
        _write(data)


def _flatten(table: dict, prefix: str = "") -> dict:
    flat = {}
    for key, value in table.items():
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{prefix}{key}."))
        else:
            flat[prefix + key] = value
    return flat


def _write(data: dict) -> None:
    # Settings without a section come first; "section.name" goes under its own [section]. Values are all strings: a JSON string is also valid TOML
    def line(key: str, value: str) -> str:
        return f"{key} = {json.dumps(value, ensure_ascii=False)}\n"

    sections: dict[str, dict] = {}
    for key, value in data.items():
        section, _, name = key.rpartition(".")
        sections.setdefault(section, {})[name] = value
    text = "".join(line(k, v) for k, v in sections.pop("", {}).items())
    for section, values in sections.items():
        text += ("\n" if text else "") + f"[{section}]\n" + "".join(line(k, v) for k, v in values.items())
    # It holds the API key: only the owner can read it, set when the file is created so no one can read it mid-write
    path = config_path()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(path, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
