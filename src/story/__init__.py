"""LLM 文字冒險遊戲。核心在 story.core，外殼在 story.shells。"""

import sys


def main() -> None:
    """依參數選外殼：預設是 Textual 終端機介面，--plain 是純文字，--web 是給網頁殼用的網頁模式。"""
    args = sys.argv[1:]
    if "--plain" in args:
        from story.shells.plain import main as plain_main

        plain_main()
        return
    from story.shells.textual import StoryApp

    StoryApp(web="--web" in args).run()
