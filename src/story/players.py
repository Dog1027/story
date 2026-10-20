"""網頁版的玩家：依名字分開存檔，並確保同一個名字同時只有一個連線。"""

import os
import re
from pathlib import Path

SAVES_DIR = Path("saves")
MAX_NAME_LEN = 20
# 名字會變成檔名，只允許文字、數字、底線與連字號（含中文），擋掉 ../ 這類路徑字元
NAME_PATTERN = re.compile(r"^[\w\-]+$")


class InvalidName(ValueError):
    """名字不能用時的錯誤，訊息會直接顯示給玩家。"""


def check_name(raw: str) -> str:
    name = raw.strip()
    if not name:
        raise InvalidName("請輸入名字。")
    if len(name) > MAX_NAME_LEN:
        raise InvalidName(f"名字最多 {MAX_NAME_LEN} 個字。")
    if not NAME_PATTERN.match(name):
        raise InvalidName("名字只能包含文字、數字、底線和連字號。")
    return name


class Player:
    def __init__(self, name: str):
        self.name = name
        self.save_path = SAVES_DIR / f"{name}.json"
        self.log_path = SAVES_DIR / f"{name}.log.jsonl"
        self.lock_path = SAVES_DIR / f"{name}.lock"
        self.locked = False

    def acquire(self) -> bool:
        """佔用這個名字。已經有人以這個名字在線上就回傳 False。"""
        SAVES_DIR.mkdir(exist_ok=True)
        try:
            fd = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            if _lock_owner_alive(self.lock_path):
                return False
            self.lock_path.unlink(missing_ok=True)  # 上一個連線異常結束留下的鎖，可以接手
            return self.acquire()
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        self.locked = True
        return True

    def release(self) -> None:
        if self.locked:
            self.lock_path.unlink(missing_ok=True)
            self.locked = False


def _lock_owner_alive(lock_path: Path) -> bool:
    try:
        pid = int(lock_path.read_text())
        os.kill(pid, 0)  # 只檢查程序是否存在，不會真的送出訊號
    except (ValueError, OSError):
        return False
    return True
