"""Turtle soup's own text: prompts for the AI in prompts/<lang>/, text for players in ui/<lang>/soup.md."""

from pathlib import Path

from story.core.prompts import UI as CORE_UI
from story.core.prompts import Texts

TEXT = Texts(Path(__file__).resolve().parent)
UI = CORE_UI | TEXT.ui("soup")  # The core's shared text plus turtle soup's own
