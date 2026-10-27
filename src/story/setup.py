"""第一次啟動時的設定：在終端機裡問語言與 API key，存進設定檔（story/settings.py）。

只問設定檔（與環境變數）裡還沒有的；之後再啟動就不會再問。不是在終端機裡執行（例如在背景啟動伺服器）時不問，用預設值。
語言要最先問：程式在 import 核心時就決定語言，所以這裡在 import 核心之前執行，問完才讀取這個語言的文字。
"""

import os
import re
import sys
from getpass import getpass
from pathlib import Path

from story import settings

LANGUAGES_DIR = Path(__file__).resolve().parent / "shells" / "ui"  # 有介面文字的語言才能選


def language_names() -> dict[str, str]:
    """{語言: 顯示的名稱}，名稱是各語言 shells.md 的 language_name。"""
    names = {}
    for folder in sorted((p for p in LANGUAGES_DIR.iterdir() if p.is_dir()), key=lambda p: (p.name != "zh-TW", p.name)):  # 預設的中文排第一
        match = re.search(r"^## language_name\s*\n(?:<!--.*?-->\s*\n)?(.+)$", (folder / "shells.md").read_text(encoding="utf-8"), re.M)
        names[folder.name] = match.group(1).strip() if match else folder.name
    return names


def run() -> None:
    """問設定檔裡還沒有的語言與 API key（網頁伺服器呼叫 AI 用架站者的 key）。"""
    if not sys.stdin.isatty():
        return
    if not (settings.get("language") or "STORY_LANG" in os.environ):
        ask_language()
    from story.shells.text import ui_text  # 語言決定之後才讀這個語言的文字

    ui = ui_text("shells")
    if not settings.api_key():
        print(ui["setup_key"])
        if value := getpass(ui["setup_key_prompt"]).strip():
            settings.put("api_key", value)


def ask_language() -> None:
    names = language_names()
    codes = list(names)
    print("選擇語言 / Choose a language")
    for i, code in enumerate(codes, 1):
        print(f"  {i}. {names[code]}")
    settings.put("language", choose("> ", codes, codes[0]))


def choose(prompt: str, options: list[str], default: str) -> str:
    """輸入編號選一項；直接按 Enter 用預設值，輸入看不懂就再問一次。"""
    while True:
        answer = input(prompt).strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        if answer in options:
            return answer
