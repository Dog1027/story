"""存檔：把一局的狀態（pydantic 模型）存成 JSON、讀回來。每種玩法的存檔格式不同，這裡只管寫檔與讀檔。"""

import os
import tempfile
from pathlib import Path

from pydantic import BaseModel

SAVE_PATH = Path("save.json")


def save(state: BaseModel, path: Path = SAVE_PATH) -> None:
    """先寫到同資料夾的暫存檔，寫完再一次換上去。任何時候讀到的都是完整的存檔，
    不會因為背景壓縮記憶時剛好在存檔、或寫到一半程式被關掉，而讀到空檔案或壞掉的檔案。"""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(state.model_dump_json(indent=2))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load(path: Path, kind: type[BaseModel]):
    """讀存檔；沒有就回傳 None。kind 是存檔的格式（冒險是 GameState，海龜湯是 SoupState）。"""
    if not path.exists():
        return None
    return kind.model_validate_json(path.read_text(encoding="utf-8"))
