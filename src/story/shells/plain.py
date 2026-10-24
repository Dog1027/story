"""最簡單的外殼：只用 input() 和 print() 跟核心對話，示範核心「送文字進去、拿文字出來」。"""

from getpass import getpass

from story.core import StoryCore, ui_text
from story.shells.apikey import get_saved_api_key


def main() -> None:
    UI = ui_text("shells")
    key = get_saved_api_key() or getpass(UI["plain_ask_key"]).strip()
    if not key:
        return
    core = StoryCore(api_key=key)
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
