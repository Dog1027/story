"""讀文字檔：給 AI 的提示詞與給玩家看的介面文字都是 markdown 檔，程式只負責把它們跟遊戲資料組合起來。

每一層有自己的文字，放在那一層的資料夾裡，用 Texts 讀：
- 核心共用的介面文字：story/core/ui/語言/
- 每種玩法：story/games/玩法/prompts/語言/（給 AI）與 ui/語言/（給玩家）
- 外殼：story/shells/ui/語言/

想調整 AI 的寫法（規則、節奏提醒、尾聲……）時改那些檔案就好，不用動程式。怎麼改見 story/games/adventure/prompts/README.md。
每種語言一個資料夾（zh-TW、en），檔名與段落名稱都一樣。語言由設定檔的 language 或環境變數 STORY_LANG 選擇（story/settings.py）。

檔案格式：
- 開頭的 <!-- --> 註解是給寫提示詞的人看的說明（用途、可用的變數），不會送給 AI。
- 整份是一段提示詞的檔案（例如 system.md）用 Texts.load() 讀。
- 一個檔案放好幾段短提示詞時，每段以「## 名稱」開頭，用 Texts.sections() 讀成 {名稱: 內容}。
  名稱可以有點，例如 schema.md 的「## StoryBeat.narration」。
- 一段裡一行一項的清單用 items() 讀；「代號: 文字」的對照表用 table() 讀。
- {名稱} 是變數，程式組合時填入（str.format）。內容裡不能出現其他的大括號。
"""

import re
from pathlib import Path

from story import settings

LANGUAGE = settings.language()  # 語言：prompts/、ui/ 底下的資料夾名稱
COMMENT = re.compile(r"<!--.*?-->", re.S)
HEADING = re.compile(r"^## ([\w.]+)\s*$", re.M)


# 文字的長度：中文（與日文）每個字算一個，其他語言每個詞（連續不含空白的一串）算一個。
# 這樣字數限制在各語言用同一個數字就好：中文 300 字、英文 300 個詞，份量差不多
_CJK = "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
UNIT = re.compile(f"[{_CJK}]|[^\\s{_CJK}]+")


def text_length(text: str) -> int:
    return len(UNIT.findall(text))


def clip(text: str, limit: int) -> str:
    """只留前 limit 個字（或詞），見 text_length()。"""
    units = list(UNIT.finditer(text))
    return text if len(units) <= limit else text[: units[limit - 1].end()]


def _read(name: str, folder: Path) -> str:
    path = folder / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}（語言是 {LANGUAGE}；每種語言要有一整套同名的檔案）")
    return COMMENT.sub("", path.read_text(encoding="utf-8").replace("\r\n", "\n"))


def sections(name: str, folder: Path) -> dict[str, str]:
    """folder/名稱.md 裡每個「## 名稱」底下的內容（前後的空行去掉，中間的換行照原樣保留）。"""
    parts = HEADING.split(_read(name, folder))
    return {key: body.strip("\n") for key, body in zip(parts[1::2], parts[2::2])}


class Texts:
    """一層（核心、一種玩法、外殼）自己的文字：base 是那一層的資料夾，底下有 prompts/語言/ 與 ui/語言/。"""

    def __init__(self, base: Path):
        self.prompts_dir = Path(base) / "prompts" / LANGUAGE
        self.ui_dir = Path(base) / "ui" / LANGUAGE

    def load(self, name: str) -> str:
        """整份檔案就是一段提示詞。"""
        return _read(name, self.prompts_dir).strip("\n")

    def sections(self, name: str) -> dict[str, str]:
        """提示詞（prompts/語言/名稱.md）的每一段。"""
        return sections(name, self.prompts_dir)

    def ui(self, name: str) -> dict[str, str]:
        """介面文字（ui/語言/名稱.md），格式同 sections()。"""
        return sections(name, self.ui_dir)


CORE = Texts(Path(__file__).resolve().parent)  # 核心共用的介面文字（story/core/ui/語言/core.md）
UI = CORE.ui("core")


def items(text: str) -> list[str]:
    """一行一項的清單（可以用 - 開頭）。"""
    return [item for line in text.splitlines() if (item := line.strip().removeprefix("- ").strip())]


def table(text: str) -> dict[str, str]:
    """「代號: 文字」一行一項的對照表，例如 context.md 的遊戲狀態欄位名稱。"""
    pairs = (line.split(":", 1) for line in text.splitlines() if ":" in line)
    return {key.strip(): value.strip() for key, value in pairs}
