"""玩家的設定：~/.config/story/config.toml，可以手動編輯。

    language = "en"          # 語言：zh-TW（預設）或 en
    api_key = "…"            # Gemini API key

程式裡用「區塊.名稱」指一項設定，例如 get("api_key")；有區塊的設定寫在 [區塊] 底下。

環境變數優先於這個檔案：STORY_LANG 蓋過 language，GEMINI_API_KEY（或 GOOGLE_API_KEY）蓋過 api_key，
所以臨時換語言或 key 時不用改檔案。第一次啟動時輸入的語言與 API key 會寫進這個檔案（手寫的註解會不見）。
核心、玩法與外殼都會讀它；個人的題材包與海龜湯題目也放在同一個資料夾（~/.config/story/genres/語言/、puzzles/語言/）。
"""

import json
import os
import tomllib
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "story"
CONFIG_PATH = CONFIG_DIR / "config.toml"
KEY_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
OLD_FILES = {"api_key": "api_key"}  # 以前每個設定各存一個檔案，讀取時搬進 config.toml


def load() -> dict:
    """讀取設定檔，攤平成 {"區塊.名稱": 值}；沒有就是空的。舊的 api_key 檔案會先搬進來。"""
    try:
        data = _flatten(tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except FileNotFoundError:
        data = {}
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"{CONFIG_PATH} 的格式有誤：{e}")
    if _migrate(data):
        _write(data)
    return data


def get(key: str) -> str | None:
    return load().get(key) or None


def put(key: str, value: str | None) -> None:
    """寫入一項設定；None 代表刪掉這一項。"""
    data = load()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    _write(data)


def language() -> str:
    return os.environ.get("STORY_LANG") or get("language") or "zh-TW"


def api_key() -> str | None:
    """環境變數或設定檔裡的 API key；都沒有就回傳 None（交給介面詢問玩家）。"""
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
    # 沒有區塊的設定在前，「區塊.名稱」寫到各自的 [區塊] 底下。值都是字串：JSON 的字串寫法也是合法的 TOML
    line = lambda key, value: f"{key} = {json.dumps(value, ensure_ascii=False)}\n"  # noqa: E731
    sections: dict[str, dict] = {}
    for key, value in data.items():
        section, _, name = key.rpartition(".")
        sections.setdefault(section, {})[name] = value
    text = "".join(line(k, v) for k, v in sections.pop("", {}).items())
    for section, values in sections.items():
        text += ("\n" if text else "") + f"[{section}]\n" + "".join(line(k, v) for k, v in values.items())
    # 裡面有 API key：只有自己能讀，建檔時就設好，避免寫入過程中被別人讀到
    fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(CONFIG_PATH, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
