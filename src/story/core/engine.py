"""Harness 核心：組 prompt、呼叫 LLM、驗證輸出、更新狀態、管理記憶。"""

import json
import random
import re
import time
from pathlib import Path

import httpx
from google import genai
from google.genai import types

from story.core.genres import Genre, load_genres
from story.core.models import Character, Condition, Epilogue, GameState, GenrePick, StoryArc, StoryBeat, Turn
from story.core import prompts

MODEL = "gemini-3.5-flash-lite"
HISTORY_BUDGET = 20_000  # 劇情紀錄保留原文的字數上限；超過才把最舊的部分壓縮進摘要，一次壓到剩一半
KEEP_EVENTS, KEEP_FLAGS = 6, 12  # 重大事件、已確立的事實各保留最近幾條原文，較舊的在壓縮時併入摘要
TARGET_TURNS = 30  # 故事預定長度（回合）；超過時只提醒 AI 收尾，不強制結束
ACT_TURNS = TARGET_TURNS // 4  # 每一幕預計幾回合，待太久就提醒 AI 推進
MIN_ACT_TURNS = 5  # 每一幕至少幾回合；還沒到時 AI 說里程碑達成也不推進，避免故事一下子就跑完
REQUEST_TIMEOUT = 40  # 一次 AI 請求最多等幾秒；Gemini 偶爾卡住一兩分鐘，重送通常比較快
REQUEST_ATTEMPTS = 3  # 逾時或伺服器忙（429、5xx）時最多送幾次（含第一次）
TWIST_IDEAS = 3  # 規劃大綱時從題材包的 twists.md 隨機抽幾則轉折靈感
MIN_ENDING_TURN = 20  # 最早第幾回合才接受 AI 宣告的結局（還要進到最後一幕）；因傷死亡不受限制
MIN_TIME_LIMIT, MAX_TIME_LIMIT = 8, 60  # 限時模式的反應時間範圍（秒）
MAX_CONDITION_LEN = 12  # 單一狀態最多幾個字，避免 LLM 寫成一整句

# 身體狀況：LLM 只決定每個狀態的程度，總分與生死由程式計算
SEVERITY_POINTS = {"輕": 1, "中": 2, "重": 4}
DEATH_SCORE = 8  # 傷勢總分達到這個數字就死亡
DYING_SCORE = 6  # 總分達到這個數字就是瀕死
HEAVY_SCORE = 4  # 沒有重傷，但多處中傷累積到這個分數也算重傷
SEVERITY_ORDER = ["輕", "中", "重"]

# 遊戲內時間：AI 只挑類別，換算成分鐘由程式負責
HOUR, DAY = 60, 24 * 60
TIME_SPANS = {"瞬間": 1, "片刻": 10, "一陣子": HOUR, "數小時": 4 * HOUR, "一夜": 8 * HOUR, "數天": 3 * DAY}
TIME_OF_DAY_START = {"清晨": 6, "上午": 9, "中午": 12, "下午": 15, "傍晚": 18, "夜晚": 20, "深夜": 23}  # 開場時刻（點）
TIME_OF_DAY_RANGES = [(5, "清晨"), (7, "上午"), (11, "中午"), (13, "下午"), (17, "傍晚"), (19, "夜晚"), (23, "深夜")]

# 自然恢復：在同一程度下經過多久會好轉一級。身體的重傷不會自己好，要靠劇情中的治療；精神狀態都會隨時間平復
HEAL_TIME = {
    "身體": {"輕": 6 * HOUR, "中": 2 * DAY},
    "精神": {"輕": 2 * HOUR, "中": 12 * HOUR, "重": 2 * DAY},
}
LOG_PATH = Path("story_log.jsonl")  # 每回合的狀態變化紀錄

# 固定不變的 system prompt，放在最前面以利 prompt caching
SYSTEM_PROMPT = prompts.load("system")  # 給 AI 的寫作與遊戲規則（story/prompts/system.md）
CONTEXT = prompts.sections("context")  # 每回合送給 AI 的故事內容（前提、劇情紀錄、遊戲狀態……）
TURN = prompts.sections("turn")  # 每回合的指示
PROGRESS = prompts.sections("progress")  # 故事進度裡的提醒
PLAN = prompts.sections("plan")  # 挑題材、規劃大綱
PREMISE = prompts.sections("premise")  # 「幫我想」
MEMORY = prompts.sections("memory")  # 記憶壓縮
STATUS_KEYS = prompts.table(CONTEXT["status_keys"])  # 遊戲狀態 JSON 的欄位名稱：{代號: 給 AI 看的名稱}
STATUS_EMPTY = prompts.table(CONTEXT["status_empty"])  # 遊戲狀態裡沒有東西時顯示的字
TIMEOUT_ACTION = TURN["timeout_action"]  # 限時模式時間到時，代替玩家行動寫進劇情紀錄給 AI


class EndingTooEarly(Exception):
    """串流時發現 AI 太早宣告結局：還沒有任何劇情顯示出來就中斷，請它重寫。"""


def raise_friendly(e: Exception) -> None:
    """重送幾次都逾時或連不上：轉成核心會處理的錯誤；其他錯誤照原樣丟出。"""
    if isinstance(e, (httpx.TimeoutException, httpx.ConnectError)):
        raise RuntimeError("Gemini 太久沒有回應或連不上，請稍後再試。") from e
    raise e


def partial_string(text: str, key: str) -> str | None:
    """從還沒生成完的 JSON 取出某個字串欄位目前收到的內容（例如串流中的 narration）。還沒出現時回傳 None。"""
    match = re.search(r'"%s"\s*:\s*"' % re.escape(key), text)
    if not match:
        return None
    out, i = [], match.end()
    while i < len(text) and text[i] != '"':
        if text[i] != "\\":
            out.append(text[i])
            i += 1
            continue
        if i + 1 >= len(text) or (text[i + 1] == "u" and i + 6 > len(text)):
            break  # 跳脫字元還沒收完整，等下一段
        escaped = text[i + 1]
        if escaped == "u":
            out.append(chr(int(text[i + 2 : i + 6], 16)))
            i += 6
        else:
            out.append({"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}.get(escaped, escaped))
            i += 2
    return "".join(out)


def partial_bool(text: str, key: str) -> bool | None:
    """從還沒生成完的 JSON 取出布林欄位；還沒出現時回傳 None。"""
    match = re.search(r'"%s"\s*:\s*(true|false)' % re.escape(key), text)
    return None if match is None else match.group(1) == "true"


def new_client(api_key: str | None) -> genai.Client:
    """逾時或伺服器忙時自動重送（間隔約 1、2 秒），不讓玩家一直等一個卡住的請求。"""
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT * 1000,  # 毫秒
            retry_options=types.HttpRetryOptions(attempts=REQUEST_ATTEMPTS),
        ),
    )


def is_key_error(e: Exception) -> bool:
    """判斷 Gemini 的錯誤是不是 API key 無效或沒有權限造成的。"""
    code = getattr(e, "code", None)
    text = str(e)
    return code in (400, 401, 403) and ("API key" in text or "API_KEY" in text)


def clock_text(minutes: int) -> str:
    """例如「第 2 天 傍晚（18:30）」。只放進給 AI 的提示，不顯示給玩家。"""
    day, hour, minute = minutes // DAY + 1, minutes % DAY // HOUR, minutes % HOUR
    period = next((name for start, name in reversed(TIME_OF_DAY_RANGES) if hour >= start), "深夜")
    return CONTEXT["clock"].format(day=day, period=period, hour=hour, minute=minute)


# 下面的規則函式都只用到 conditions／inventory：單人模式傳 GameState（主角），多人模式傳 Character
Holder = GameState | Character


def body_conditions(who: Holder) -> list[Condition]:
    return [c for c in who.conditions if c.kind == "身體"]


def mind_conditions(who: Holder) -> list[Condition]:
    return [c for c in who.conditions if c.kind == "精神"]


def body_score(who: Holder) -> int:
    """傷勢總分只算身體狀態；精神狀態影響劇情，但不會致命。"""
    return sum(SEVERITY_POINTS[c.severity] for c in body_conditions(who))


def condition_list(who: Holder) -> list[tuple[str, str]]:
    """給外殼顯示的狀態：(名稱, 程度)，身體在前、精神在後。"""
    return [(c.name, c.severity) for c in body_conditions(who) + mind_conditions(who)]


LEVEL_NAMES = ("良好", "輕傷", "受傷", "重傷", "瀕死", "死亡")  # body_level() 的整體狀態
WARNING_LEVELS = ("重傷", "瀕死")  # 整體狀態到這個程度要警告玩家：再受傷就有生命危險


def warning_level(who: Holder) -> str:
    """要警告玩家的整體狀態（重傷、瀕死），不危險時是空字串。"""
    level = body_level(who)
    return level if level in WARNING_LEVELS else ""


def body_level(who: Holder) -> str:
    """整體狀態看最嚴重的那一項：有重傷才算重傷（或多處中傷累積），只有輕微狀態就是輕傷。"""
    score = body_score(who)
    worst = {c.severity for c in body_conditions(who)}
    if score >= DEATH_SCORE:
        return "死亡"
    if score >= DYING_SCORE:
        return "瀕死"
    if "重" in worst or score >= HEAVY_SCORE:
        return "重傷"
    if "中" in worst:
        return "受傷"
    return "輕傷" if worst else "良好"


# ---------- 套用 AI 提議的規則（單人、多人共用） ----------


def advance_clock(state: GameState, time_passed: str, start_time_of_day: str) -> tuple[int, bool]:
    """推進回合數與遊戲內時鐘。回傳 (經過的分鐘數, 是否為開場)。"""
    state.turn += 1
    is_opening_turn = state.turn == 1
    if state.minutes is None:  # 開場或舊存檔：時間由 AI 依劇情決定，這回合不計經過的時間
        state.minutes, elapsed = TIME_OF_DAY_START[start_time_of_day] * HOUR, 0
    else:
        elapsed = TIME_SPANS[time_passed]
        state.minutes += elapsed
    return elapsed, is_opening_turn


def apply_condition_changes(who: Holder, changed: list, removed_names: list[str], elapsed: int) -> None:
    # 先讓既有狀態隨時間自然恢復，再套用 AI 回報的變化
    remaining = []
    for c in who.conditions:
        c.minutes += elapsed
        heal = HEAL_TIME[c.kind]
        while c.severity in heal and c.minutes >= heal[c.severity]:
            # 多出來的時間延續到下一級，例如「數天」可能讓中傷一路好到痊癒
            c.minutes -= heal[c.severity]
            if c.severity == "輕":
                break
            c.severity = SEVERITY_ORDER[SEVERITY_ORDER.index(c.severity) - 1]
        else:
            remaining.append(c)  # 迴圈沒有因為輕傷痊癒而 break，代表狀態還在
    who.conditions = remaining

    # 移除：精神狀態與輕微的身體狀態可以直接移除；身體的中、重只能降一級，避免 AI 一句話讓重傷消失
    removed = {name.strip() for name in removed_names}
    remaining = []
    for c in who.conditions:
        if c.name in removed and c.kind == "身體" and c.severity != "輕":
            c.severity, c.minutes = SEVERITY_ORDER[SEVERITY_ORDER.index(c.severity) - 1], 0
        elif c.name in removed:
            continue
        remaining.append(c)
    who.conditions = remaining  # 不存在的名稱自然被忽略

    for change in changed:
        name = change.name.strip()[:MAX_CONDITION_LEN]
        if not name or name in LEVEL_NAMES:  # 「良好」「重傷」這類是整體狀態的評語，不是一種傷勢
            continue
        existing = next((c for c in who.conditions if c.name == name), None)
        if existing:
            existing.kind = change.kind  # 舊存檔的狀態一律當成身體，AI 回報時順便更正
            old_level = SEVERITY_ORDER.index(existing.severity)
            new_level = SEVERITY_ORDER.index(change.severity)
            if new_level == old_level:
                continue
            # 惡化不設限；好轉一回合最多一級，避免 AI 一次把重傷變成痊癒
            existing.severity = SEVERITY_ORDER[max(new_level, old_level - 1)]
            existing.minutes = 0
        else:
            who.conditions.append(Condition(name=name, kind=change.kind, severity=change.severity))


def apply_items(who: Holder, gained: list[str], lost: list[str]) -> None:
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


EARLY_ENDING_RETRY = TURN["early_ending_retry"]


def clamp_time_limit(state: GameState, given: int) -> int:
    """限時與否由程式決定：非限時模式忽略 LLM 給的秒數，限時模式把秒數夾在合理範圍。"""
    limit = given if state.timed_mode and not state.game_over else 0
    return 0 if limit <= 0 else max(MIN_TIME_LIMIT, min(MAX_TIME_LIMIT, limit))


# 讓 AI 想故事開頭時隨機指定題材，避免它每次都想出相似的故事
PREMISE_GENRES = prompts.items(PREMISE["genres"])  # 「幫我想」隨機挑的題材（prompts/語言/premise.md）
PREMISE_SETTINGS = prompts.items(PREMISE["settings"])  # 「幫我想」隨機挑的情境

SUMMARY_SYSTEM = MEMORY["system"]  # 壓縮記憶時給 AI 的規則


def history(state: GameState) -> list[Turn]:
    """完整的劇情紀錄（由舊到新）。舊存檔可能還有等待壓縮的回合（unsummarized），一起算進來。"""
    return state.unsummarized + state.recent


def history_size(turns: list[Turn]) -> int:
    return sum(len(t.narration) + len(t.action) for t in turns)


def history_entry(turn: Turn, label: str) -> str:
    """劇情紀錄裡的一回合：那時的劇情，與玩家看完後做的事。"""
    return CONTEXT["history_entry"].format(narration=turn.narration, label=label, action=turn.action)


def overall_text(who: Holder) -> str:
    """遊戲狀態裡的「整體」：讓 AI 知道離死亡還有多遠。"""
    return CONTEXT["overall"].format(level=body_level(who), score=body_score(who), death=DEATH_SCORE)


def time_text(state: GameState) -> str:
    return STATUS_EMPTY["time_unknown"] if state.minutes is None else clock_text(state.minutes)


def condition_fields(who: Holder) -> dict:
    """遊戲狀態裡主角（或一位角色）的身體、精神與整體狀況。"""
    def listed(conditions: list[Condition], empty: str) -> list[str]:
        return [CONTEXT["condition"].format(name=c.name, severity=c.severity) for c in conditions] or [STATUS_EMPTY[empty]]

    return {
        STATUS_KEYS["body"]: listed(body_conditions(who), "body"),
        STATUS_KEYS["mind"]: listed(mind_conditions(who), "mind"),
        STATUS_KEYS["overall"]: overall_text(who),
    }


def oldest_turns_to_compact(turns: list[Turn]) -> list[Turn]:
    """劇情紀錄超過預算時，要壓縮掉的最舊回合：壓到剩下不超過預算的一半。沒超過就不壓縮。"""
    if history_size(turns) <= HISTORY_BUDGET:
        return []
    size, cut = history_size(turns), 0
    while cut < len(turns) - 1 and size > HISTORY_BUDGET // 2:
        size -= len(turns[cut].narration) + len(turns[cut].action)
        cut += 1
    return turns[:cut]


class Engine:
    """單人模式的 engine。多人模式（story.core.party.PartyEngine）繼承它，只覆寫下面這些掛勾。"""

    system_prompt = SYSTEM_PROMPT  # 給 AI 的寫作與遊戲規則
    beat_schema = StoryBeat  # 每回合強制 AI 回傳的格式
    turn_label = CONTEXT["turn_label"]  # 「劇情紀錄」裡行動那一行的標籤
    epilogue_look_back = TURN["epilogue_look_back"]

    def __init__(
        self,
        api_key: str | None = None,
        client: genai.Client | None = None,
        log_path: Path = LOG_PATH,
        genres: dict[str, Genre] | None = None,
    ):
        self.client = client or new_client(api_key)
        self.genres = load_genres()[0] if genres is None else genres  # 題材包（見 genres.py）
        self.calls: list[dict] = []  # 上次寫紀錄之後的 AI 呼叫：種類、秒數、token 用量（寫進紀錄後清空）
        self.log_path = log_path  # 網頁版每個玩家各自一份紀錄
        self.stage = ""  # 開新故事時目前在做什麼，外殼顯示在等待畫面上（例如「規劃故事大綱」）
        self.draft = ""  # AI 正在寫的劇情（串流中目前收到的部分），外殼可以先顯示；沒有在寫時是空字串

    def set_api_key(self, api_key: str) -> None:
        self.client = new_client(api_key)

    # ---------- 對外介面 ----------

    def start(self, state: GameState) -> None:
        """先規劃隱藏的故事大綱，再產生開場（題材選「自動」時，最前面再多一次挑題材）。
        要呼叫好幾次 AI，比一般回合久，所以用 stage 告訴外殼進度。"""
        try:
            if state.genre_pending and self.genres:
                self.stage = "挑選題材"
                self.pick_genre(state)
            self.stage = "規劃故事大綱"
            self.plan_arc(state)
            self.stage = "寫開場"
            self._advance(state, action=None)
        finally:
            self.stage, self.draft = "", ""

    def pick_genre(self, state: GameState) -> None:
        """玩家選「自動」：給 AI 題材目錄，請它依故事前提挑一個。先挑好，規劃大綱時才用得上題材的指引與轉折靈感。"""
        picked = ""
        if self.genres:
            response = self._generate(
                "題材",
                model=MODEL,
                contents=self.genre_prompt(state),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=GenrePick,
                    thinking_config=types.ThinkingConfig(thinking_level="low"),
                ),
            )
            if isinstance(response.parsed, GenrePick):
                picked = response.parsed.genre.strip()
        state.genre, state.genre_pending = (picked if picked in self.genres else ""), False  # 不在目錄裡（或留空）就不套用

    def plan_arc(self, state: GameState) -> None:
        """請 AI 規劃故事大綱。舊存檔沒有大綱時，依目前的劇情補一份，並依回合數決定從哪一幕接著走。"""
        if state.genre_pending:
            self.pick_genre(state)
        response = self._generate(
            "大綱",
            model=MODEL,
            contents=self.arc_prompt(state),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=StoryArc,
                thinking_config=types.ThinkingConfig(thinking_level="low"),
            ),
        )
        if not isinstance(response.parsed, StoryArc) or len(response.parsed.acts) < 4:
            return  # 規劃失敗就先不用大綱，下回合再試
        state.arc = response.parsed
        state.arc.acts = state.arc.acts[:4]
        # 已經進行很久的故事：依回合數推估目前在哪一幕
        state.act, state.act_turns = min(3, state.turn // ACT_TURNS), 0

    def act(self, state: GameState, action) -> None:
        """玩家做出行動，推進一回合。單人模式的 action 是一句話，多人模式是 {角色名字: 行動}。"""
        if state.arc is None:
            self.plan_arc(state)
        state.recent.append(Turn(narration=state.current_narration, action=self._action_text(action)))  # 只往後追加
        try:
            self._advance(state, action=action)
        finally:
            self.draft = ""

    def suggest_premise(self, avoid: str = "", genre: str = "") -> str:
        """請 AI 想一個新的故事開頭。題材由程式隨機挑選（玩家指定了題材就用那個），AI 負責發揮。
        挑到題材包時，附上它的描述與幾則開頭靈感（premises.md）。"""
        response = self._generate(
            "幫我想",
            model=MODEL,
            contents=self.premise_prompt(avoid, genre),
            config=types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level="low")),
        )
        text = (response.text or "").strip().strip("「」\"")
        if not text:
            raise RuntimeError("AI 沒有想出開頭，請再試一次。")
        return text

    def write_epilogue(self, state: GameState) -> None:
        """故事結束後，請 AI 回顧整段旅程寫出尾聲與結局名稱。"""
        response = self._generate(
            "尾聲",
            model=MODEL,
            contents=self.epilogue_prompt(state),
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                response_mime_type="application/json",
                response_schema=Epilogue,
            ),
        )
        if not isinstance(response.parsed, Epilogue):
            raise RuntimeError("尾聲生成失敗。")
        state.ending_title, state.epilogue = response.parsed.title.strip(), response.parsed.text.strip()
        self._write_log({"turn": state.turn, "epilogue": state.ending_title})

    # ---------- 生成劇情 ----------

    def _next_beat(self, state: GameState, action) -> StoryBeat:
        """請 AI 寫這一回合。太早寫出結局時請它重寫一次；重寫後還是結局的話，_apply() 會忽略結局的宣告。"""
        prompt = self.turn_prompt(state, action)
        try:
            # game_over 是 AI 第一個輸出的欄位：太早的結局在劇情出現之前就會發現，玩家不會看到被換掉的版本
            return self._call(prompt, stop_on_ending=not ending_allowed(state, state.turn + 1))
        except EndingTooEarly:
            self.draft = ""
            return self._call(prompt + "\n\n" + EARLY_ENDING_RETRY, kind="重寫")

    def _advance(self, state: GameState, action: str | None) -> None:
        beat = self._next_beat(state, action)
        before = [f"{c.name}({c.severity})" for c in state.conditions]
        self._apply(state, beat)
        self._log_turn(state, action, beat, before)
        if body_score(state) >= DEATH_SCORE and not beat.game_over:
            self._write_death(state)

    def _log_turn(self, state: GameState, action: str | None, beat: StoryBeat, before: list[str]) -> None:
        """把 AI 這回合提議的變化和程式套用後的結果記到檔案，方便事後查「為什麼會這樣」。"""
        record = {
            "turn": state.turn,
            "action": action,
            "ai": beat.model_dump(exclude={"narration", "choices"}),
            "conditions_before": before,
            "conditions_after": [f"{c.name}({c.severity})" for c in state.conditions],
            "level": body_level(state),
            "time": clock_text(state.minutes),
        }
        self._write_log(record)

    def _write_death(self, state: GameState) -> None:
        """程式判定傷重死亡，但 LLM 寫的劇情裡主角還活著：請 LLM 接著寫死亡結局。"""
        ending = self._call(self.death_prompt(state), kind="倒下", prefix=state.current_narration + "\n\n")  # 串流時接在剛才的劇情後面
        state.current_narration += "\n\n" + ending.narration
        state.current_choices = []
        state.current_time_limit = 0
        state.game_over = True

    # ---------- 提示詞：每一種 AI 呼叫各自怎麼組（文字在 story/prompts/，just prompts 可以預覽） ----------

    def turn_prompt(self, state: GameState, action: str | None) -> str:
        """把程式記得的所有東西組成本回合的輸入：故事內容加上這回合的指示（action 是 None 時是開場）。
        每次呼叫都是無狀態的，記憶全靠這裡。"""
        return "\n\n".join(self._context(state, action) + self._instruction_sections(state, action))

    def death_prompt(self, state: GameState) -> str:
        """程式判定傷重死亡，但 AI 寫的劇情裡主角還活著：請 AI 接著寫死亡結局。"""
        return "\n\n".join(self._context(state, None) + [TURN["death"].format(narration=state.current_narration)])

    def epilogue_prompt(self, state: GameState) -> str:
        epilogue = TURN["epilogue"].format(narration=state.current_narration, look_back=self.epilogue_look_back)
        return "\n\n".join(self._context(state, None) + [epilogue])

    def genre_prompt(self, state: GameState) -> str:
        catalog = "\n".join(f"- {g.name}：{g.description}" for g in self.genres.values())
        return PLAN["pick_genre"].format(premise=state.premise, catalog=catalog)

    def arc_prompt(self, state: GameState) -> str:
        if state.turn == 0:
            situation = PLAN["arc_new"]
        else:
            situation = PLAN["arc_resume"].format(turn=state.turn, summary=state.summary or PLAN["summary_none"], events="\n".join(state.key_events))
        prompt = PLAN["arc"].format(target_turns=TARGET_TURNS, premise=state.premise, cast=self._cast_section(state), situation=situation)
        if genre := self.genres.get(state.genre):  # 大綱要符合題材
            prompt += "\n\n" + PLAN["genre"].format(name=genre.name, guide=genre.guide)
            if genre.names:
                prompt += "\n\n" + PLAN["names"].format(names=genre.names)
            if genre.twists:  # 每局隨機抽幾則，同一個題材玩很多次也不會總是同一招
                ideas = "\n".join(f"- {t}" for t in random.sample(genre.twists, min(TWIST_IDEAS, len(genre.twists))))
                prompt += "\n\n" + PLAN["twist_ideas"].format(ideas=ideas)
        return prompt

    def premise_prompt(self, avoid: str = "", genre: str = "") -> str:
        """「幫我想」：題材由程式隨機挑選（玩家指定了題材就用那個）；挑到題材包時附上它的描述與幾則開頭靈感。"""
        if genre not in self.genres:
            genre = random.choice([*self.genres, *(g for g in PREMISE_GENRES if g not in self.genres)])
        parts = [PREMISE["intro"].format(genre=genre, setting=random.choice(PREMISE_SETTINGS))]
        if pack := self.genres.get(genre):
            parts.append(PREMISE["pack"].format(description=pack.description))
            if pack.premises:
                ideas = "\n".join(f"- {p}" for p in random.sample(pack.premises, min(3, len(pack.premises))))
                parts.append(PREMISE["pack_ideas"].format(ideas=ideas))
        parts.append(PREMISE["rules"])
        if avoid:
            parts.append(PREMISE["avoid"].format(avoid=avoid))
        return "\n".join(parts)

    def compaction_prompt(self, state: GameState) -> str:
        """劇情紀錄太長時：把最舊的回合、較舊的重大事件與事實併入長期摘要。"""
        turns = oldest_turns_to_compact(history(state))
        old = state.key_events[:-KEEP_EVENTS] + state.flags[:-KEEP_FLAGS]
        parts = [MEMORY["summary"].format(summary=state.summary or MEMORY["summary_none"])]
        if turns:
            parts.append(MEMORY["turns"].format(entries="\n\n".join(history_entry(t, CONTEXT["turn_label"]) for t in turns)))
        if old:
            parts.append(MEMORY["old_facts"].format(items="\n".join(f"- {x}" for x in old)))
        parts.append(MEMORY["compact"])
        return "\n\n".join(parts)

    def _context(self, state: GameState, action: str | None) -> list[str]:
        """故事內容（指示以外的部分）。尾聲、傷重死亡的場景也用它，再接上各自的指示。

        順序：不常變的在前、會變的在後，讓 Gemini 的自動快取（只認開頭完全相同的部分）命中得越多越好：
        前提、模式 → 摘要（很少變）→ 劇情紀錄（只往後追加）→ 重大事件、故事進度、狀態（隨劇情改變）。
        """
        mode = TURN["mode_timed"].format(min=MIN_TIME_LIMIT, max=MAX_TIME_LIMIT) if state.timed_mode else TURN["mode_normal"]
        sections = [CONTEXT["premise"].format(premise=state.premise), CONTEXT["mode"].format(mode=mode)]
        genre = self.genres.get(state.genre)
        if genre:  # 整局固定，放在前段不影響快取
            sections.append(CONTEXT["genre_guide"].format(name=genre.name, guide=genre.guide))
        if state.summary:
            sections.append(CONTEXT["summary"].format(summary=state.summary))

        turns = history(state)
        if turns:
            entries = [history_entry(t, self.turn_label) for t in turns]
            if action is not None:  # 最後一筆的行動就是本回合行動，在指示裡另外列出，不重複
                entries[-1] = CONTEXT["history_last"].format(narration=turns[-1].narration)
            sections.append(CONTEXT["history"].format(entries="\n\n".join(entries)))

        if state.key_events:
            sections.append(CONTEXT["key_events"].format(events="\n".join(f"- {e}" for e in state.key_events)))
        if progress := self._progress_section(state):
            sections.append(progress)
        if genre and genre.names and action is None and state.turn == 0:  # 開場要介紹人物與地點：附上命名素材
            sections.append(PLAN["names"].format(names=genre.names))
        sections.append(self._status_section(state))
        return sections

    # ---------- 多人模式覆寫的掛勾（下面是單人模式的版本） ----------

    def _cast_section(self, state: GameState) -> str:
        """規劃大綱時的主角名單。單人模式不需要。"""
        return ""

    def _action_text(self, action) -> str:
        """記在「劇情紀錄」裡的行動文字。"""
        return action

    def _status_section(self, state: GameState) -> str:
        key, empty = STATUS_KEYS, STATUS_EMPTY
        status = {
            key["turn"]: state.turn,
            key["time"]: time_text(state),
            **condition_fields(state),
            key["inventory"]: state.inventory or [empty["inventory"]],
            key["flags"]: state.flags or [empty["flags"]],
        }
        return CONTEXT["status"].format(json=json.dumps(status, ensure_ascii=False, separators=(",", ":")))

    def _instruction_sections(self, state: GameState, action) -> list[str]:
        if action is None:
            return [TURN["opening"]]
        return [TURN["action"].format(action=action)]

    def _progress_section(self, state: GameState) -> str:
        """隱藏的故事大綱與節奏提醒。只給 AI 看。"""
        arc = state.arc
        if arc is None:
            return ""
        lines = [PROGRESS["goal"].format(goal=arc.goal)]
        for i, act in enumerate(arc.acts):
            mark = PROGRESS["act_current"] if i == state.act else (PROGRESS["act_done"] if i < state.act else "")
            lines.append(PROGRESS["act"].format(number=i + 1, name=act.name, milestone=act.milestone, mark=mark))
        lines.append(PROGRESS["endings"].format(endings="；".join(arc.endings)))
        if arc.twist:
            lines += self._twist_lines(arc, state.act)

        final = state.act == len(arc.acts) - 1
        if not final and state.act_turns + 1 < MIN_ACT_TURNS:
            left = MIN_ACT_TURNS - state.act_turns - 1
            lines.append(PROGRESS["act_just_started"].format(left=left))
        if not ending_allowed(state, state.turn + 1):
            lines.append(PROGRESS["ending_locked"].format(min_ending_turn=MIN_ENDING_TURN))
        if state.turn >= TARGET_TURNS:
            lines.append(PROGRESS["overdue"].format(target_turns=TARGET_TURNS))
        elif final:
            lines.append(PROGRESS["final_act"])
        elif state.act_turns >= ACT_TURNS:
            lines.append(PROGRESS["act_too_long"])
        return PROGRESS["header"].format(lines="\n".join(lines))

    @staticmethod
    def _twist_lines(arc: StoryArc, act: int) -> list[str]:
        """隱藏的真相：前兩幕只埋伏筆，第三幕揭露，之後當作已知的事。"""
        clues = "\n".join(f"- {c}" for c in arc.clues)
        if act < 2:
            lines = [PROGRESS["twist_hidden"].format(twist=arc.twist)]
            if clues:
                lines.append(PROGRESS["twist_clues"].format(clues=clues))
            return lines
        if act == 2:
            reveal = PROGRESS["twist_reveal"].format(twist=arc.twist)
            return [reveal + ("\n" + PROGRESS["twist_reveal_clues"].format(clues=clues) if clues else "")]
        return [PROGRESS["twist_known"].format(twist=arc.twist)]

    def _generate(self, kind: str, **request):
        """所有一次拿完整結果的 AI 呼叫都經過這裡：記下種類、花了幾秒與 Gemini 回報的 token 用量
        （送出、命中快取、輸出、思考），寫進每回合的紀錄，方便查等待時間花在哪裡。"""
        started = time.monotonic()
        try:
            response = self.client.models.generate_content(**request)
        except Exception as e:  # 重送幾次都失敗：失敗的呼叫也記下來，跟下一回合的紀錄寫在一起
            self._record(kind, started, None, error=str(e)[:200])
            raise_friendly(e)
        self._record(kind, started, response)
        return response

    def _stream(self, kind: str, on_text, **request):
        """串流的 AI 呼叫：每收到一段，就用目前為止的全文呼叫 on_text。紀錄方式跟 _generate() 一樣。
        回傳 (全文, 最後一段)。on_text 丟出 EndingTooEarly 時中斷並往外丟。"""
        started, text, last, extra = time.monotonic(), "", None, {}
        stream = None
        try:
            stream = self.client.models.generate_content_stream(**request)
            for chunk in stream:
                last = chunk
                if piece := chunk.text:
                    text += piece
                    on_text(text)
        except EndingTooEarly:
            extra["stopped"] = "太早寫出結局"
            raise
        except Exception as e:
            extra["error"] = str(e)[:200]
            raise_friendly(e)
        finally:
            if stream is not None and hasattr(stream, "close"):
                stream.close()  # 中斷時不再接收剩下的部分
            self._record(kind, started, last, **extra)
        return text, last

    def _record(self, kind: str, started: float, response, **extra) -> None:
        call = {"kind": kind, "seconds": round(time.monotonic() - started, 2)}
        usage = getattr(response, "usage_metadata", None)
        for field, name in (
            ("prompt_token_count", "prompt"),
            ("cached_content_token_count", "cached"),
            ("candidates_token_count", "output"),
            ("thoughts_token_count", "thinking"),
        ):
            if (value := getattr(usage, field, None)) is not None:
                call[name] = value
        self.calls.append(call | extra)

    def _write_log(self, record: dict) -> None:
        """寫一行紀錄，附上這段期間的 AI 呼叫。"""
        record["calls"], self.calls = self.calls, []
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # 紀錄寫不進去不影響遊戲

    def _call(self, prompt: str, kind: str = "劇情", stop_on_ending: bool = False, prefix: str = ""):
        """串流呼叫 Gemini，取得結構化的回傳（單人是 StoryBeat，多人是 PartyBeat）。
        收到劇情的同時更新 draft（前面接上 prefix），外殼可以先顯示。stop_on_ending 時，AI 一宣告結局就中斷（EndingTooEarly）。"""

        def on_text(text: str) -> None:
            if stop_on_ending and partial_bool(text, "game_over") is True:
                raise EndingTooEarly
            if (narration := partial_string(text, "narration")) is not None:
                self.draft = prefix + narration

        text, last = self._stream(
            kind,
            on_text,
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                response_mime_type="application/json",
                response_schema=self.beat_schema,
            ),
        )
        try:
            return self.beat_schema.model_validate_json(text)
        except ValueError:
            reason = last.candidates[0].finish_reason if last is not None and last.candidates else "沒有內容"
            raise RuntimeError(f"模型輸出無法解析（{reason}），請換個行動試試。")

    # ---------- 驗證並套用 ----------

    def _apply(self, state: GameState, beat: StoryBeat) -> None:
        """LLM 只能「提議」狀態變化，由程式決定接受多少。"""
        elapsed, is_opening_turn = advance_clock(state, beat.time_passed, beat.start_time_of_day)
        may_end = ending_allowed(state, state.turn)  # 在推進幕數之前判斷：剛進最後一幕的那回合還不能結束
        apply_condition_changes(state, beat.conditions_changed, beat.conditions_removed, elapsed)
        apply_items(state, beat.items_gained, beat.items_lost)
        apply_story_progress(state, beat.flags_set, beat.key_event, beat.milestone_reached, is_opening_turn)

        state.current_narration = beat.narration
        state.current_choices = beat.choices[:4]
        state.game_over = (beat.game_over and may_end) or body_score(state) >= DEATH_SCORE
        state.current_time_limit = clamp_time_limit(state, beat.time_limit)

    # ---------- 記憶壓縮 ----------

    def needs_compaction(self, state: GameState) -> bool:
        return (
            history_size(history(state)) > HISTORY_BUDGET
            or len(state.key_events) > KEEP_EVENTS * 2
            or len(state.flags) > KEEP_FLAGS * 2
        )

    def compact_memory(self, state: GameState) -> None:
        """劇情紀錄太長時，把最舊的回合（壓到剩一半）、較舊的重大事件與事實併入長期摘要。
        由介面在背景呼叫，玩家讀劇情時順便完成。很少發生：30 回合的故事大約只有七、八千字。"""
        if not self.needs_compaction(state):
            return
        turns = oldest_turns_to_compact(history(state))
        old_events = state.key_events[:-KEEP_EVENTS]
        old_flags = state.flags[:-KEEP_FLAGS]

        response = self._generate(
            "壓縮",
            model=MODEL,
            contents=self.compaction_prompt(state),
            config=types.GenerateContentConfig(
                system_instruction=SUMMARY_SYSTEM,
                thinking_config=types.ThinkingConfig(thinking_level="low"),
            ),
        )
        text = (response.text or "").strip()
        if not text:
            return  # 失敗就先保留原樣，下次再試
        # 只移除這次確實併入摘要的部分（壓縮期間不會有新回合，但仍以數量為準比較保險）
        state.summary = text
        remaining = history(state)[len(turns):]
        state.unsummarized, state.recent = [], remaining
        del state.key_events[: len(old_events)]
        del state.flags[: len(old_flags)]
