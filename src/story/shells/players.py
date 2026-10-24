"""網頁版的玩家：依名字分開存檔，並確保同一個名字同時只有一個連線。"""

import re
from pathlib import Path

from story.core import ui_text

UI = ui_text("shells")  # story/ui/語言/shells.md

SAVES_DIR = Path("saves")
MAX_NAME_LEN = 20
# 名字會變成檔名，只允許文字、數字、底線與連字號（含中文），擋掉 ../ 這類路徑字元
NAME_PATTERN = re.compile(r"^[\w\-]+$")


class InvalidName(ValueError):
    """名字不能用時的錯誤，訊息會直接顯示給玩家。"""


def check_name(raw: str) -> str:
    name = raw.strip()
    if not name:
        raise InvalidName(UI["name_empty"])
    if len(name) > MAX_NAME_LEN:
        raise InvalidName(UI["name_too_long"].format(max=MAX_NAME_LEN))
    if not NAME_PATTERN.match(name):
        raise InvalidName(UI["name_bad_chars"])
    return name


class Player:
    """網頁版（每個人各自玩）的一位玩家。同一個名字同時只能有一個分頁在玩，不然兩邊會互相蓋掉存檔。"""

    online: set[str] = set()  # 正在玩的名字；整個網頁伺服器是同一個程式，伺服器重開時自然清空

    def __init__(self, name: str):
        self.name = name
        self.save_path = SAVES_DIR / f"{name}.json"
        self.log_path = SAVES_DIR / f"{name}.log.jsonl"
        self.locked = False

    def acquire(self) -> bool:
        """佔用這個名字。已經有人以這個名字在線上就回傳 False。"""
        if self.name in Player.online:
            return False
        SAVES_DIR.mkdir(exist_ok=True)
        Player.online.add(self.name)
        self.locked = True
        return True

    def release(self) -> None:
        if self.locked:
            Player.online.discard(self.name)
            self.locked = False
