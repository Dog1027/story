"""遊戲規則：AI 只提議變化，套不套用、套用多少由這裡決定。傷勢與生死、遊戲內時間與痊癒、物品、故事的節奏、記憶的預算。

都是純粹的函式，只讀寫遊戲狀態（models.py），不呼叫 AI、不組提示詞。
"""

from typing import get_args

from story.core import prompts
from story.core.models import VOCAB, Character, Condition, GameState, Severity, Turn, code

TARGET_TURNS = 30  # 故事預定長度（回合）；超過時只提醒 AI 收尾，不強制結束
ACT_TURNS = TARGET_TURNS // 4  # 每一幕預計幾回合，待太久就提醒 AI 推進
MIN_ACT_TURNS = 5  # 每一幕至少幾回合；還沒到時 AI 說里程碑達成也不推進，避免故事一下子就跑完
MIN_ENDING_TURN = 20  # 最早第幾回合才接受 AI 宣告的結局（還要進到最後一幕）；因傷死亡不受限制
MIN_TIME_LIMIT, MAX_TIME_LIMIT = 8, 60  # 限時模式的反應時間範圍（秒）
MAX_CONDITION_LEN = 12  # 單一狀態最多幾個字（英文算詞），避免 LLM 寫成一整句
HISTORY_BUDGET = 20_000  # 劇情紀錄保留原文的字數上限（英文算詞）；超過才把最舊的部分壓縮進摘要，一次壓到剩一半
KEEP_EVENTS, KEEP_FLAGS = 6, 12  # 重大事件、已確立的事實各保留最近幾條原文，較舊的在壓縮時併入摘要

# 身體狀況：LLM 只決定每個狀態的程度，總分與生死由程式計算
SEVERITY_POINTS = {"light": 1, "moderate": 2, "severe": 4}
DEATH_SCORE = 8  # 傷勢總分達到這個數字就死亡
DYING_SCORE = 6  # 總分達到這個數字就是瀕死
HEAVY_SCORE = 4  # 沒有重傷，但多處中傷累積到這個分數也算重傷
SEVERITY_ORDER = list(get_args(Severity))  # 由輕到重
WARNING_LEVELS = ("serious", "dying")  # 整體狀態到這個程度要警告玩家：再受傷就有生命危險

# 遊戲內時間：AI 只挑類別，換算成分鐘由程式負責
HOUR, DAY = 60, 24 * 60
TIME_SPANS = {"instant": 1, "moment": 10, "while": HOUR, "hours": 4 * HOUR, "night": 8 * HOUR, "days": 3 * DAY}
TIME_OF_DAY_START = {"dawn": 6, "morning": 9, "noon": 12, "afternoon": 15, "dusk": 18, "evening": 20, "late_night": 23}  # 開場時刻（點）
TIME_OF_DAY_RANGES = [(5, "dawn"), (7, "morning"), (11, "noon"), (13, "afternoon"), (17, "dusk"), (19, "evening"), (23, "late_night")]

# 自然恢復：在同一程度下經過多久會好轉一級。身體的重傷不會自己好，要靠劇情中的治療；精神狀態都會隨時間平復
HEAL_TIME = {
    "body": {"light": 6 * HOUR, "moderate": 2 * DAY},
    "mind": {"light": 2 * HOUR, "moderate": 12 * HOUR, "severe": 2 * DAY},
}


# ---------- 傷勢與生死 ----------


def body_conditions(who: Character) -> list[Condition]:
    return [c for c in who.conditions if c.kind == "body"]


def mind_conditions(who: Character) -> list[Condition]:
    return [c for c in who.conditions if c.kind == "mind"]


def body_score(who: Character) -> int:
    """傷勢總分只算身體狀態；精神狀態影響劇情，但不會致命。"""
    return sum(SEVERITY_POINTS[c.severity] for c in body_conditions(who))


def condition_list(who: Character) -> list[tuple[str, str]]:
    """給外殼顯示的狀態：(名稱, 程度的代號)，身體在前、精神在後。"""
    return [(c.name, c.severity) for c in body_conditions(who) + mind_conditions(who)]


def body_level(who: Character) -> str:
    """整體狀態（models.Level 的代號）看最嚴重的那一項：有重傷才算重傷（或多處中傷累積），只有輕微狀態就是輕傷。"""
    score = body_score(who)
    worst = {c.severity for c in body_conditions(who)}
    if score >= DEATH_SCORE:
        return "dead"
    if score >= DYING_SCORE:
        return "dying"
    if "severe" in worst or score >= HEAVY_SCORE:
        return "serious"
    if "moderate" in worst:
        return "injured"
    return "minor" if worst else "healthy"


def warning_level(who: Character) -> str:
    """要警告玩家的整體狀態（serious、dying），不危險時是空字串。"""
    level = body_level(who)
    return level if level in WARNING_LEVELS else ""


# ---------- 時間 ----------


def time_of_day(minutes: int) -> str:
    """遊戲內時鐘的時段代號，例如 dusk。"""
    hour = minutes % DAY // HOUR
    return next((name for start, name in reversed(TIME_OF_DAY_RANGES) if hour >= start), "late_night")


def advance_clock(state: GameState, time_passed: str, start_time_of_day: str) -> tuple[int, bool]:
    """推進回合數與遊戲內時鐘（兩個參數是 AI 回傳的詞）。回傳 (經過的分鐘數, 是否為開場)。"""
    state.turn += 1
    is_opening_turn = state.turn == 1
    if state.minutes is None:  # 開場：時間由 AI 依劇情決定，這回合不計經過的時間
        state.minutes, elapsed = TIME_OF_DAY_START[code("time_of_day", start_time_of_day)] * HOUR, 0
    else:
        elapsed = TIME_SPANS[code("time_span", time_passed)]
        state.minutes += elapsed
    return elapsed, is_opening_turn


# ---------- 套用 AI 提議的變化 ----------


def apply_condition_changes(who: Character, changed: list, removed_names: list[str], elapsed: int) -> None:
    # 先讓既有狀態隨時間自然恢復，再套用 AI 回報的變化
    remaining = []
    for c in who.conditions:
        c.minutes += elapsed
        heal = HEAL_TIME[c.kind]
        while c.severity in heal and c.minutes >= heal[c.severity]:
            # 多出來的時間延續到下一級，例如「數天」可能讓中傷一路好到痊癒
            c.minutes -= heal[c.severity]
            if c.severity == "light":
                break
            c.severity = SEVERITY_ORDER[SEVERITY_ORDER.index(c.severity) - 1]
        else:
            remaining.append(c)  # 迴圈沒有因為輕傷痊癒而 break，代表狀態還在
    who.conditions = remaining

    # 移除：精神狀態與輕微的身體狀態可以直接移除；身體的中、重只能降一級，避免 AI 一句話讓重傷消失
    removed = {name.strip() for name in removed_names}
    remaining = []
    for c in who.conditions:
        if c.name in removed and c.kind == "body" and c.severity != "light":
            c.severity, c.minutes = SEVERITY_ORDER[SEVERITY_ORDER.index(c.severity) - 1], 0
        elif c.name in removed:
            continue
        remaining.append(c)
    who.conditions = remaining  # 不存在的名稱自然被忽略

    for change in changed:  # AI 回報的類別與程度是這個語言的詞，換成代號
        name = prompts.clip(change.name.strip(), MAX_CONDITION_LEN)
        if not name or name in VOCAB["level"].values():  # 「良好」「重傷」這類是整體狀態的評語，不是一種傷勢
            continue
        kind, severity = code("kind", change.kind), code("severity", change.severity)
        existing = next((c for c in who.conditions if c.name == name), None)
        if existing:
            existing.kind = kind  # AI 可以更正類別
            old_level = SEVERITY_ORDER.index(existing.severity)
            new_level = SEVERITY_ORDER.index(severity)
            if new_level == old_level:
                continue
            # 惡化不設限；好轉一回合最多一級，避免 AI 一次把重傷變成痊癒
            existing.severity = SEVERITY_ORDER[max(new_level, old_level - 1)]
            existing.minutes = 0
        else:
            who.conditions.append(Condition(name=name, kind=kind, severity=severity))


def apply_items(who: Character, gained: list[str], lost: list[str]) -> None:
    for item in lost:
        if item in who.inventory:  # 不能失去沒有的東西
            who.inventory.remove(item)
    who.inventory.extend(gained)


def apply_story_progress(state: GameState, flags: list[str], key_event: str, milestone_reached: bool, is_opening_turn: bool) -> None:
    for flag in flags:
        if flag not in state.flags:
            state.flags.append(flag)
    if key_event.strip():
        state.key_events.append(key_event.strip())
    if state.arc is not None and not is_opening_turn:
        state.act_turns += 1
        # 節奏由程式把關：這一幕至少要演 MIN_ACT_TURNS 回合，AI 太早說達成也不推進
        if milestone_reached and state.act_turns >= MIN_ACT_TURNS and state.act < len(state.arc.acts) - 1:
            state.act, state.act_turns = state.act + 1, 0


def ending_allowed(state: GameState, turn: int) -> bool:
    """第 turn 回合能不能結束故事：進到最後一幕、而且到了 MIN_ENDING_TURN 回合；超過預定長度一律可以。
    只管 AI 宣告的結局，因傷死亡由程式另外判定，不受限制。"""
    if turn >= TARGET_TURNS:
        return True
    final = state.arc is None or state.act == len(state.arc.acts) - 1
    return final and turn >= MIN_ENDING_TURN


def clamp_time_limit(state: GameState, given: int) -> int:
    """限時與否由程式決定：非限時模式忽略 LLM 給的秒數，限時模式把秒數夾在合理範圍。"""
    limit = given if state.timed_mode and not state.game_over else 0
    return 0 if limit <= 0 else max(MIN_TIME_LIMIT, min(MAX_TIME_LIMIT, limit))


# ---------- 記憶的預算 ----------


def history_size(turns: list[Turn]) -> int:
    return sum(prompts.text_length(t.narration) + prompts.text_length(t.action) for t in turns)


def needs_compaction(state: GameState) -> bool:
    return history_size(state.recent) > HISTORY_BUDGET or len(state.key_events) > KEEP_EVENTS * 2 or len(state.flags) > KEEP_FLAGS * 2


def to_compact(state: GameState) -> tuple[list[Turn], list[str], list[str]]:
    """這次壓縮要併入摘要的東西：最舊的回合、較舊的重大事件、較舊的事實。"""
    return oldest_turns_to_compact(state.recent), state.key_events[:-KEEP_EVENTS], state.flags[:-KEEP_FLAGS]


def oldest_turns_to_compact(turns: list[Turn]) -> list[Turn]:
    """劇情紀錄超過預算時，要壓縮掉的最舊回合：壓到剩下不超過預算的一半。沒超過就不壓縮。"""
    if history_size(turns) <= HISTORY_BUDGET:
        return []
    size, cut = history_size(turns), 0
    while cut < len(turns) - 1 and size > HISTORY_BUDGET // 2:
        size -= prompts.text_length(turns[cut].narration) + prompts.text_length(turns[cut].action)
        cut += 1
    return turns[:cut]
