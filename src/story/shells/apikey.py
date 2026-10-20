"""Gemini API key 的讀取、儲存與刪除。"""

import os
from pathlib import Path

KEY_PATH = Path.home() / ".config" / "story" / "api_key"
ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


def get_saved_api_key() -> str | None:
    """從環境變數或已儲存的設定檔取得 API key；都沒有就回傳 None（交給介面詢問玩家）。"""
    for var in ENV_VARS:
        if key := os.environ.get(var, "").strip():
            return key
    if KEY_PATH.exists() and (key := KEY_PATH.read_text(encoding="utf-8").strip()):
        return key
    return None


def save_api_key(key: str) -> None:
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 建檔時就設成只有自己能讀，避免寫入過程中被別人讀到
    fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key)


def forget_api_key() -> None:
    KEY_PATH.unlink(missing_ok=True)

