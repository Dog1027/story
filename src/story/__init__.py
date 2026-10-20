"""LLM 文字冒險遊戲。核心在 story.core，外殼在 story.shells。"""

import sys


def main() -> None:
    """依參數選外殼：預設是 Textual 終端機介面，--plain 是純文字，--web 是給網頁殼用的網頁模式。
    加上 --party 是多人模式（大家輪流在同一台電腦上輸入）。
    --room 路徑 是線上多人（由網頁殼使用）：連到網頁伺服器裡的房間，和其他瀏覽器一起玩同一局。"""
    args = sys.argv[1:]
    party = "--party" in args
    room = args[args.index("--room") + 1] if "--room" in args[:-1] else None
    if "--plain" in args:
        from story.shells.plain import main as plain_main

        plain_main(party=party)
        return
    from story.shells.textual import StoryApp

    StoryApp(web="--web" in args, party=party, room=room).run()
