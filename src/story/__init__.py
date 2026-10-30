"""An LLM text game. The shared core is in story.core, the games (adventure, turtle soup) in story.games, the shells in story.shells."""

import sys

from story.shells import setup


def main() -> None:
    """uv run story: the web version (lobby and rooms). On first launch, asks for the language and API key (players never enter a key; everyone uses this one).
    --setup-only does only the first-launch setup and exits (just start uses it before starting the server in the background, where it can't ask)."""
    setup.run()  # Must run before importing the core: the language is fixed at import time
    if "--setup-only" in sys.argv[1:]:
        return
    from story.shells.web import main as web_main

    web_main()
