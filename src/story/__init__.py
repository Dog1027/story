"""LLM 文字冒險遊戲。核心在 story.core，外殼在 story.shells。"""

import sys


def main() -> None:
    """依參數選外殼：預設是 Textual 終端機介面，--plain 是純文字。加上 --party 是多人模式（大家輪流在同一台電腦上輸入）。
    網頁版是另一個指令：story-web（story.shells.web）。"""
    args = sys.argv[1:]
    party = "--party" in args
    if "--plain" in args:
        from story.shells.plain import main as plain_main

        plain_main(party=party)
        return
    from story.shells.textual import StoryApp

    StoryApp(party=party).run()
