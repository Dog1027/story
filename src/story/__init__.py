"""LLM 文字遊戲。共用的核心在 story.core，玩法（冒險、海龜湯）在 story.games，外殼在 story.shells。"""

import sys

from story import setup


def main() -> None:
    """uv run story：網頁版（大廳與房間）。第一次啟動時先問語言與 API key（玩家不用輸入 key，都用這一個）。
    --setup-only 只做第一次的設定就結束（just start 在背景啟動伺服器前用，背景裡沒辦法問）。"""
    setup.run()  # 要在 import 核心之前：語言在 import 時就決定了
    if "--setup-only" in sys.argv[1:]:
        return
    from story.shells.web import main as web_main

    web_main()
