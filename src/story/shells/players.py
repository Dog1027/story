"""網頁版的玩家名字：怎樣的名字可以用。名字會變成存檔的檔名（見 lobby.py 的 team_save）。"""

import re
from pathlib import Path

from story.shells.text import ui_text

UI = ui_text("shells")  # story/shells/ui/語言/shells.md

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
