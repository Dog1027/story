"""核心的紀錄工具：存讀檔、回合變化、結局紀錄、記憶文字。只處理資料，不管外觀。"""

import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Literal

from story.core.engine import DAY, body_level
from story.core.models import GameState

SAVE_PATH = Path("save.json")
DEFAULT_PREMISE = "你是一名失憶的旅人，在暴風雨夜醒來，發現自己躺在一座廢棄燈塔的底層，手裡握著一把不屬於你的鑰匙。"


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
    events = "\n".join(f"  - {e}" for e in state.key_events) or "  （無）"
    if state.party:
        bags = "\n".join(f"  {c.name}：{'、'.join(c.inventory) or '空'}" for c in state.party)
    else:
        bags = f"  {'、'.join(state.inventory) or '空'}"
    return (
        f"[背包]\n{bags}\n\n"
        f"[已確立的事實]\n  {'、'.join(state.flags) or '無'}\n\n"
        f"[重大事件]\n{events}\n\n"
        f"[長期摘要]\n  {state.summary or '（尚無）'}\n\n"
        f"[劇情紀錄] {len(state.unsummarized) + len(state.recent)} 回合原文"
    )


def ending_record(state: GameState) -> str:
    """結局的旅程紀錄。遊戲內時間只在這裡揭曉。"""
    days = (state.minutes or 0) // DAY + 1
    record = f"共 {state.turn} 回合，歷時 {days} 天。\n"
    if state.party:
        fallen = [c.name for c in state.party if not c.alive]
        if len(fallen) == len(state.party):
            record += "隊伍全員都在這趟旅程中倒下了。"
        elif fallen:
            record += f"{'、'.join(fallen)} 在這趟旅程中倒下了，其他人走到了故事的盡頭。"
        else:
            record += "所有人一起走到了故事的盡頭。"
    else:
        record += "你在這趟旅程中倒下了。" if body_level(state) == "死亡" else "你走到了故事的盡頭。"
    if state.key_events:
        record += "\n\n這趟旅程中：\n" + "\n".join(f"・{e}" for e in state.key_events[-5:])
    return record


# ---------- 回合間的變化 ----------

Snapshot = tuple[dict[str, str], Counter]  # (狀態名稱 → 程度, 背包物品數量)

# 每個項目的語氣，由外殼決定怎麼呈現（例如上什麼顏色）：
# 輕／中／重＝新出現的狀態的程度；good＝好轉、痊癒；bad＝惡化；plain＝一般（獲得物品）；muted＝不重要（失去物品）
Tone = Literal["輕", "中", "重", "good", "bad", "plain", "muted"]
ChangeGroups = list[tuple[str, list[tuple[str, Tone]]]]  # [(標籤, [(文字, 語氣)])]


def snapshot(state: GameState) -> Snapshot:
    return {c.name: c.severity for c in state.conditions}, Counter(state.inventory)


def change_groups(before: Snapshot, state: GameState) -> ChangeGroups:
    """比較回合前後，列出狀態與背包的變化。只回傳有內容的分組。"""
    old_conds, old_items = before
    new_conds, new_items = snapshot(state)
    order = ["輕", "中", "重"]
    groups: ChangeGroups = [
        ("新增", [(f"{n}（{v}）", v) for n, v in new_conds.items() if n not in old_conds]),
        ("惡化", [(f"{n}（{old_conds[n]}→{v}）", "bad") for n, v in new_conds.items()
                if n in old_conds and order.index(v) > order.index(old_conds[n])]),
        ("好轉", [(f"{n}（{old_conds[n]}→{v}）", "good") for n, v in new_conds.items()
                if n in old_conds and order.index(v) < order.index(old_conds[n])]),
        ("痊癒", [(n, "good") for n in old_conds if n not in new_conds]),
        ("獲得", [(n, "plain") for n in (new_items - old_items).elements()]),
        ("失去", [(n, "muted") for n in (old_items - new_items).elements()]),
    ]
    return [(label, items) for label, items in groups if items]
