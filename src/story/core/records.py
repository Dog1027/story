"""核心的紀錄工具：存讀檔、回合變化、結局紀錄、記憶文字。只處理資料，不管外觀。"""

import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Literal

from story.core import prompts
from story.core.models import Character, GameState, word
from story.core.prompting import PREMISE
from story.core.rules import DAY, SEVERITY_ORDER

UI = prompts.ui("core")  # 給玩家看的文字（story/ui/語言/core.md）
join = UI["list_sep"].join

SAVE_PATH = Path("save.json")
DEFAULT_PREMISE = PREMISE["default"]  # 沒有題材包可以抽、玩家也沒輸入時用的前提


def save(state: GameState, path: Path = SAVE_PATH) -> None:
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


def load(path: Path = SAVE_PATH) -> GameState | None:
    if not path.exists():
        return None
    return GameState.model_validate_json(path.read_text(encoding="utf-8"))


def memory_text(state: GameState) -> str:
    events = "\n".join(UI["memory_event"].format(event=e) for e in state.key_events) or UI["memory_no_events"]
    if state.solo:
        bags = UI["memory_bag"].format(items=join(state.characters[0].inventory) or UI["memory_empty_bag"])
    else:
        bags = "\n".join(UI["memory_named_bag"].format(name=c.name, items=join(c.inventory) or UI["memory_empty_bag"]) for c in state.characters)
    return UI["memory"].format(
        bags=bags,
        flags=join(state.flags) or UI["memory_no_flags"],
        events=events,
        summary=state.summary or UI["memory_no_summary"],
        turns=len(state.recent),
    )


def ending_record(state: GameState) -> str:
    """結局的旅程紀錄。遊戲內時間只在這裡揭曉。"""
    days = (state.minutes or 0) // DAY + 1
    record = UI["record"].format(turns=state.turn, days=days) + "\n"
    fallen = [c.name for c in state.characters if not c.alive]
    if state.solo:
        record += UI["record_dead"] if fallen else UI["record_alive"]
    elif len(fallen) == len(state.characters):
        record += UI["record_all_fallen"]
    elif fallen:
        record += UI["record_some_fallen"].format(names=join(fallen))
    else:
        record += UI["record_all_alive"]
    if state.key_events:
        events = "\n".join(UI["record_event"].format(event=e) for e in state.key_events[-5:])
        record += "\n\n" + UI["record_events"].format(events=events)
    return record


# ---------- 回合間的變化 ----------

Snapshot = tuple[dict[str, str], Counter]  # (狀態名稱 → 程度, 背包物品數量)

# 每個項目的語氣，由外殼決定怎麼呈現（例如上什麼顏色）：
# light／moderate／severe＝新出現的狀態的程度；good＝好轉、痊癒；bad＝惡化；plain＝一般（獲得物品）；muted＝不重要（失去物品）
Tone = Literal["light", "moderate", "severe", "good", "bad", "plain", "muted"]
ChangeGroups = list[tuple[str, list[tuple[str, Tone]]]]  # [(標籤, [(文字, 語氣)])]


def snapshot(who: Character) -> Snapshot:
    return {c.name: c.severity for c in who.conditions}, Counter(who.inventory)


def change_groups(before: Snapshot, who: Character) -> ChangeGroups:
    """比較一位角色回合前後的狀態與背包，列出變化。只回傳有內容的分組。"""
    old_conds, old_items = before
    new_conds, new_items = snapshot(who)
    rank, w = SEVERITY_ORDER.index, lambda v: word("severity", v)
    added = lambda n, v: UI["condition"].format(name=n, severity=w(v))  # noqa: E731
    moved = lambda n, v: UI["condition_change"].format(name=n, old=w(old_conds[n]), new=w(v))  # noqa: E731
    groups: ChangeGroups = [
        (UI["change_new"], [(added(n, v), v) for n, v in new_conds.items() if n not in old_conds]),
        (UI["change_worse"], [(moved(n, v), "bad") for n, v in new_conds.items()
                              if n in old_conds and rank(v) > rank(old_conds[n])]),
        (UI["change_better"], [(moved(n, v), "good") for n, v in new_conds.items()
                               if n in old_conds and rank(v) < rank(old_conds[n])]),
        (UI["change_healed"], [(n, "good") for n in old_conds if n not in new_conds]),
        (UI["change_gained"], [(n, "plain") for n in (new_items - old_items).elements()]),
        (UI["change_lost"], [(n, "muted") for n in (old_items - new_items).elements()]),
    ]
    return [(label, items) for label, items in groups if items]
