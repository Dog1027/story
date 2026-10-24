"""給 AI 的提示詞：放在 story/prompts/語言/ 的 markdown 檔，程式只負責把它們跟遊戲資料組合起來。
給玩家看的介面文字放在 story/ui/語言/，格式相同，用 ui() 讀。

想調整 AI 的寫法（規則、節奏提醒、尾聲……）時改那些檔案就好，不用動程式。怎麼改見 story/prompts/README.md。
每種語言一個資料夾（目前只有 zh-TW），檔名與段落名稱都一樣，用環境變數 STORY_LANG 選擇。

檔案格式：
- 開頭的 <!-- --> 註解是給寫提示詞的人看的說明（用途、可用的變數），不會送給 AI。
- 整份是一段提示詞的檔案（system.md、party_system.md）用 load() 讀。
- 一個檔案放好幾段短提示詞時，每段以「## 名稱」開頭，用 sections() 讀成 {名稱: 內容}。
  名稱可以有點，例如 schema.md 的「## StoryBeat.narration」。
- 一段裡一行一項的清單用 items() 讀；「代號: 文字」的對照表用 table() 讀。
- {名稱} 是變數，程式組合時填入（str.format）。內容裡不能出現其他的大括號。
"""

import os
import re
from pathlib import Path

LANGUAGE = os.environ.get("STORY_LANG", "zh-TW")  # 語言：story/prompts/、story/ui/ 底下的資料夾名稱
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts" / LANGUAGE
UI_DIR = Path(__file__).resolve().parent.parent / "ui" / LANGUAGE
COMMENT = re.compile(r"<!--.*?-->", re.S)
HEADING = re.compile(r"^## ([\w.]+)\s*$", re.M)


def _read(name: str, folder: Path = PROMPTS_DIR) -> str:
    path = folder / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}（STORY_LANG={LANGUAGE}；每種語言要有一整套同名的檔案）")
    return COMMENT.sub("", path.read_text(encoding="utf-8").replace("\r\n", "\n"))


def load(name: str) -> str:
    """整份檔案就是一段提示詞。"""
    return _read(name).strip("\n")


def sections(name: str, folder: Path = PROMPTS_DIR) -> dict[str, str]:
    """檔案裡每個「## 名稱」底下的內容（前後的空行去掉，中間的換行照原樣保留）。"""
    parts = HEADING.split(_read(name, folder))
    return {key: body.strip("\n") for key, body in zip(parts[1::2], parts[2::2])}


def ui(name: str) -> dict[str, str]:
    """介面文字（story/ui/語言/名稱.md），格式同 sections()。"""
    return sections(name, UI_DIR)


def items(text: str) -> list[str]:
    """一行一項的清單（可以用 - 開頭）。"""
    return [item for line in text.splitlines() if (item := line.strip().removeprefix("- ").strip())]


def table(text: str) -> dict[str, str]:
    """「代號: 文字」一行一項的對照表，例如 context.md 的遊戲狀態欄位名稱。"""
    pairs = (line.split(":", 1) for line in text.splitlines() if ":" in line)
    return {key.strip(): value.strip() for key, value in pairs}
