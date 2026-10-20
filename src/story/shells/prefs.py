"""外殼的偏好設定（目前只有配色主題），存在 ~/.config/story/ 底下。"""

from pathlib import Path

THEME_PATH = Path.home() / ".config" / "story" / "theme"


def get_saved_theme() -> str | None:
    try:
        return THEME_PATH.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def save_theme(name: str) -> None:
    THEME_PATH.parent.mkdir(parents=True, exist_ok=True)
    THEME_PATH.write_text(name, encoding="utf-8")
