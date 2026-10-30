"""An LLM text game. The shared core is in story.core, the games (adventure, turtle soup) in story.games, the shells in story.shells."""

import sys

from story import settings
from story.shells import setup


def main() -> None:
    """uv run story: the web version (lobby and rooms). On first launch, asks for the language and API key (players never enter a key; everyone uses this one).
    --setup-only does only the first-launch setup and exits (just start uses it before starting the server in the background, where it can't ask)."""
    try:
        setup.run()  # Must run before importing the core: the language is fixed at import time
    except settings.InvalidConfig as e:
        sys.exit(str(e))  # A hand-edited config that broke: say where, not a traceback
    if "--setup-only" in sys.argv[1:]:
        return
    from story.shells.web.server import main as web_main

    web_main()
