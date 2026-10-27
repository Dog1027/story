"""外殼的介面文字：story/shells/ui/語言/（shells.md 是共用層與網頁伺服器的，dialogs.md 是兩種介面都有的對話框，
terminal.md、web.md 是各介面自己的）。"""

from pathlib import Path

from story.core import Texts

ui_text = Texts(Path(__file__).resolve().parent).ui
