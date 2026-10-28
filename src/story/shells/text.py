"""The shells' interface text: story/shells/ui/<lang>/ (shells.md for the shared layer, rooms and web server, dialogs.md for dialogs,
web.md for the web page)."""

from pathlib import Path

from story.core import Texts

ui_text = Texts(Path(__file__).resolve().parent).ui
