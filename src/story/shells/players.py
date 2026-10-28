"""Player names on the web: which names are allowed. A name becomes part of the save file name (see team_save in web/hosting.py)."""

import re

from story.shells.text import ui_text

UI = ui_text("shells")  # story/shells/ui/<lang>/shells.md

MAX_NAME_LEN = 20
# Names become file names: allow only letters, digits, underscores and hyphens (including CJK), blocking path characters like ../
NAME_PATTERN = re.compile(r"^[\w\-]+$")


class InvalidName(ValueError):
    """Raised when a name can't be used; the message is shown to the player as is."""


def check_name(raw: str) -> str:
    name = raw.strip()
    if not name:
        raise InvalidName(UI["name_empty"])
    if len(name) > MAX_NAME_LEN:
        raise InvalidName(UI["name_too_long"].format(max=MAX_NAME_LEN))
    if not NAME_PATTERN.match(name):
        raise InvalidName(UI["name_bad_chars"])
    return name
