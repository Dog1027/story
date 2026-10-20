"""最簡單的外殼：只用 input() 和 print() 跟核心對話，示範核心「送文字進去、拿文字出來」。"""

from getpass import getpass

from story.core import PartyCore, StoryCore
from story.shells.apikey import get_saved_api_key


def main(party: bool = False) -> None:
    key = get_saved_api_key() or getpass("Gemini API key（輸入時不會顯示）：").strip()
    if not key:
        return
    if party:
        while True:
            try:
                names = input("玩家名字（2 到 4 位，用逗號隔開）：").replace("，", ",").split(",")
            except (EOFError, KeyboardInterrupt):
                return
            try:
                core = PartyCore(api_key=key, players=names)
                break
            except ValueError as e:
                print(e)
    else:
        core = StoryCore(api_key=key)
    reply = core.start()
    while True:
        print(f"\n{reply.text}\n")
        try:
            text = input(f"{reply.actor} > " if reply.actor else "> ")
        except (EOFError, KeyboardInterrupt):
            break
        if text.strip() == "/quit":
            break
        reply = core.send(text)
    print("\n已存檔，下次見。")
