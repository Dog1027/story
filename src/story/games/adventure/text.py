"""冒險自己的文字：給 AI 的提示詞在 prompts/語言/，給玩家看的在 ui/語言/adventure.md。"""

from pathlib import Path

from story.core.prompts import UI as CORE_UI
from story.core.prompts import Texts

TEXT = Texts(Path(__file__).resolve().parent)
UI = CORE_UI | TEXT.ui("adventure")  # 核心共用的文字加上冒險自己的
