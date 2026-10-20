"""終端機版與網頁版共用的部分：存讀檔、回合變化、結局紀錄、打字節奏、配色。"""

from collections import Counter
from pathlib import Path

from story.engine import DAY, body_level
from story.models import GameState

SAVE_PATH = Path("save.json")
DEFAULT_PREMISE = "你是一名失憶的旅人，在暴風雨夜醒來，發現自己躺在一座廢棄燈塔的底層，手裡握著一把不屬於你的鑰匙。"

CHAR_DELAY = 0.03  # 每個字的間隔秒數
FAST_FACTOR = 0.15  # 按一次 Enter 後，間隔縮成原本的幾倍
PAUSE_AFTER = {"。": 0.25, "！": 0.25, "？": 0.25, "，": 0.1, "、": 0.08, "…": 0.15, "\n": 0.1}

GOOD, BAD = "#9ece6a", "#f7768e"
SEVERITY_COLORS = {"輕": "#e0af68", "中": "#ff9e64", "重": "#f7768e"}
LEVEL_COLORS = {"良好": "#9ece6a", "輕傷": "#e0af68", "受傷": "#ff9e64", "重傷": "#f7768e", "瀕死": "#db4b4b", "死亡": "#db4b4b"}


def save(state: GameState, path: Path = SAVE_PATH) -> None:
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def load(path: Path = SAVE_PATH) -> GameState | None:
    if not path.exists():
        return None
    return GameState.model_validate_json(path.read_text(encoding="utf-8"))


def memory_text(state: GameState) -> str:
    events = "\n".join(f"  - {e}" for e in state.key_events) or "  （無）"
    return (
        f"[已確立的事實]\n  {'、'.join(state.flags) or '無'}\n\n"
        f"[重大事件]\n{events}\n\n"
        f"[長期摘要]\n  {state.summary or '（尚無）'}\n\n"
        f"[近期記憶] {len(state.recent)} 回合原文，{len(state.unsummarized)} 回合等待壓縮"
    )


def ending_record(state: GameState) -> str:
    """結局對話框裡的旅程紀錄。遊戲內時間只在這裡揭曉。"""
    days = (state.minutes or 0) // DAY + 1
    dead = body_level(state) == "死亡"
    record = f"共 {state.turn} 回合，歷時 {days} 天。\n" + ("你在這趟旅程中倒下了。" if dead else "你走到了故事的盡頭。")
    if state.key_events:
        record += "\n\n這趟旅程中：\n" + "\n".join(f"・{e}" for e in state.key_events[-5:])
    return record


# ---------- 回合間的變化 ----------

Snapshot = tuple[dict[str, str], Counter]  # (狀態名稱 → 程度, 背包物品數量)
ChangeGroups = list[tuple[str, list[tuple[str, str]]]]  # [(標籤, [(文字, 顏色)])]，顏色空字串代表預設、"dim" 代表淡色


def snapshot(state: GameState) -> Snapshot:
    return {c.name: c.severity for c in state.conditions}, Counter(state.inventory)


def change_groups(before: Snapshot, state: GameState) -> ChangeGroups:
    """比較回合前後，列出狀態與背包的變化。只回傳有內容的分組。"""
    old_conds, old_items = before
    new_conds, new_items = snapshot(state)
    order = ["輕", "中", "重"]
    groups: ChangeGroups = [
        ("新增", [(f"{n}（{v}）", SEVERITY_COLORS[v]) for n, v in new_conds.items() if n not in old_conds]),
        ("惡化", [(f"{n}（{old_conds[n]}→{v}）", BAD) for n, v in new_conds.items()
                if n in old_conds and order.index(v) > order.index(old_conds[n])]),
        ("好轉", [(f"{n}（{old_conds[n]}→{v}）", GOOD) for n, v in new_conds.items()
                if n in old_conds and order.index(v) < order.index(old_conds[n])]),
        ("痊癒", [(n, GOOD) for n in old_conds if n not in new_conds]),
        ("獲得", [(n, "") for n in (new_items - old_items).elements()]),
        ("失去", [(n, "dim") for n in (old_items - new_items).elements()]),
    ]
    return [(label, items) for label, items in groups if items]
