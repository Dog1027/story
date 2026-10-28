"""First-launch setup: ask for the language and API key in the terminal and save them to the config (story/settings.py).

Only asks for what the config (and environment) doesn't have yet, so later launches don't ask again. Doesn't ask when not run in a terminal (e.g. a server started in the background).
The language comes first: the program fixes the language when the core is imported, so this runs before that import and only then reads that language's text.
"""

import os
import re
import sys
from getpass import getpass
from pathlib import Path

from story import settings

LANGUAGES_DIR = Path(__file__).resolve().parent / "shells" / "ui"  # Only languages with interface text can be chosen


def language_names() -> dict[str, str]:
    """{language: display name}; the name is language_name in each language's shells.md."""
    names = {}
    for folder in sorted((p for p in LANGUAGES_DIR.iterdir() if p.is_dir()), key=lambda p: (p.name != "zh-TW", p.name)):  # The default (Chinese) first
        match = re.search(r"^## language_name\s*\n(?:<!--.*?-->\s*\n)?(.+)$", (folder / "shells.md").read_text(encoding="utf-8"), re.M)
        names[folder.name] = match.group(1).strip() if match else folder.name
    return names


def run() -> None:
    """Ask for the language and API key if the config doesn't have them (the web server calls the AI with the host's key)."""
    if not sys.stdin.isatty():
        return
    if not (settings.get("language") or "STORY_LANG" in os.environ):
        ask_language()
    from story.shells.text import ui_text  # Read this language's text only once the language is decided

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
    """Pick an option by number; Enter uses the default, and anything unrecognized asks again."""
    while True:
        answer = input(prompt).strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        if answer in options:
            return answer
