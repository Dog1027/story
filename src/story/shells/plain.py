"""最簡單的外殼：只用 input() 和 print() 跟核心對話，示範核心「送文字進去、拿文字出來」。"""

from getpass import getpass

from story.games import StoryCore
from story.shells.text import ui_text
from story import settings


def main() -> None:
    UI = ui_text("shells")
    key = settings.api_key() or getpass(UI["plain_ask_key"]).strip()
    if not key:
        return
    core = StoryCore(key, [settings.get("name") or UI["default_name"]])  # 一個人玩：一人隊伍
    reply = core.start()
    while True:
        print(f"\n{reply.text}\n")
        try:
            text = input("> ")
        except (EOFError, KeyboardInterrupt):
            break
        if text.strip() == "/quit":
            break
        reply = core.send(text)
    print("\n" + UI["plain_bye"])
