"""LLM 文字冒險遊戲。"""

import sys


def main() -> None:
    from story.ui import StoryApp

    # --web：由網頁殼（web.py）啟動時使用，先問名字、存檔依名字分開、API key 不存到伺服器
    StoryApp(web="--web" in sys.argv[1:]).run()
