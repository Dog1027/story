"""LLM 文字冒險遊戲。核心在 story.core，外殼在 story.shells。"""

import sys


def main() -> None:
    """依參數選外殼：預設是 Textual 終端機介面，--plain 是純文字。
    網頁版（包括線上多人）是另一個指令：story-web（story.shells.web）。"""
    if "--plain" in sys.argv[1:]:
        from story.shells.plain import main as plain_main

        plain_main()
        return
    from story.shells.textual import StoryApp

    StoryApp().run()
