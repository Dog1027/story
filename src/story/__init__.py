"""LLM 文字冒險遊戲。"""

import sys


def main() -> None:
    args = sys.argv[1:]
    if "--plain" in args:  # 純文字外殼：只用 input() 和 print()
        from story.plain import main as plain_main

        plain_main()
        return
    from story.ui import StoryApp

    # --web：由網頁殼（web.py）啟動時使用，先問名字、存檔依名字分開、API key 不存到伺服器
    StoryApp(web="--web" in args).run()
