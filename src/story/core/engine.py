"""Harness 核心：組 prompt、呼叫 LLM、驗證輸出、更新狀態、管理記憶。"""

import json
import random
import time
from pathlib import Path

import httpx
from google import genai
from google.genai import types

from story.core.genres import Genre, load_genres
from story.core.models import Character, Condition, Epilogue, GameState, GenrePick, StoryArc, StoryBeat, Turn

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
TIMEOUT_ACTION = "（時間到：你遲疑太久，沒有在時限內做出反應）"

# 固定不變的 system prompt，放在最前面以利 prompt caching
SYSTEM_PROMPT = """你是一個互動式文字冒險遊戲的敘事者。

規則：
- 用繁體中文、第二人稱（「你」）敘述，文風生動但精簡。
- 每回合根據玩家的行動推進劇情，行動要有合理的後果，好壞都可能。
- 「遊戲狀態」區塊是唯一的事實來源。不要讓玩家使用不在背包裡的物品；若玩家嘗試，描述他們發現自己沒有。
- 尊重已確立的劇情事實與重大事件，不要自相矛盾。
- 提供 2-4 個彼此有明顯差異的選項；可以有一個朝「故事進度」中目前的里程碑前進，但不要每回合都急著達成，先讓劇情鋪陳開來。不要每次都只有逃跑、躲藏、戰鬥。玩家也可能不照選項自由行動。
- 依照「故事進度」的大綱推進劇情。節奏要張弛有度：危機過後給主角喘息、整理線索、與人互動的空間，並帶出新的發展；同一類場景（追逐、躲藏、戰鬥）不要連續超過三回合。
- 主角沒有生命值，而是用狀態描述，並標上程度（輕、中、重）與類別：身體（受傷、疲勞、中毒、疾病）或精神（恐懼、驚慌、絕望、憤怒）。
  精神狀態不會致命，但要影響主角的判斷與表現，例如恐懼時手抖、驚慌時聽不進別人的話；危機解除後可以直接移除。痊癒或消失時移除；惡化或好轉時用相同名稱回報新的程度。
  已有的狀態一律沿用「遊戲狀態」裡的原名，不要改名或換個說法重新新增。名稱只描述是什麼狀態（例如「右臂撕裂傷」），不要包含程度詞（輕傷、重傷、嚴重等），程度只用 severity 表示。狀態要影響後續劇情與行動的成敗。
- 主角會不會因傷勢而死，由程式依傷勢總分判定（見「遊戲狀態」）。不要自行讓主角因傷而死；傷勢接近致命時，在敘述中呈現危險。game_over 只用於劇情自然走到結局。
- 傷勢會隨時間自然好轉：輕微的幾小時後痊癒，中度的要休養幾天；重傷不會自己好，只有劇情中真的得到治療（包紮、縫合、就醫、用藥）時，才能用相同名稱回報降一級。
- 每回合用 time_passed 標出這段劇情經過了多久，並讓敘述符合「遊戲狀態」裡的時間（日夜、天色）。時間流逝也會推動世界：長時間休息時，飢餓、天候、其他角色的行動都可能帶來新的發展。
- 狀態變化要與敘述一致：敘述裡受傷就要加入對應的狀態，撿到東西就要列進 items_gained。
- key_event 只記真正改變故事走向的大事（結盟、背叛、重要發現、失去重要的人或物），大多數回合應該留空。flags_set 只記之後還會用到的長期事實，不要重複已有的事實，也不要記當下的動作。
- 若「模式」區塊說明是限時模式：當情勢緊迫（追逐、墜落、對峙、倒數）時設定 time_limit，越危急越短；平靜的場景設 0。非限時模式一律設 0。
- 若玩家行動是「（時間到……）」，代表玩家沒能及時反應，要描述猶豫帶來的後果。"""


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
    return f"第 {day} 天 {period}（{hour:02d}:{minute:02d}）"


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
        if not name:
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


EARLY_ENDING_RETRY = (
    "# 注意\n上一次的回覆太早結束了故事。故事還不能結束：重寫這一回合，不要寫出結局，"
    "game_over 設為 false，帶出新的發展並給出選項。"
)


def clamp_time_limit(state: GameState, given: int) -> int:
    """限時與否由程式決定：非限時模式忽略 LLM 給的秒數，限時模式把秒數夾在合理範圍。"""
    limit = given if state.timed_mode and not state.game_over else 0
    return 0 if limit <= 0 else max(MIN_TIME_LIMIT, min(MAX_TIME_LIMIT, limit))


# 讓 AI 想故事開頭時隨機指定題材，避免它每次都想出相似的故事
PREMISE_GENRES = [
    "奇幻冒險", "賽博龐克", "克蘇魯式恐怖", "武俠江湖", "末日求生", "蒸氣龐克", "太空探索",
    "偵探推理", "民俗怪談", "海盜航海", "宮廷權謀", "童話黑化", "校園怪談", "西部荒野",
]
PREMISE_SETTINGS = ["深夜", "暴風雨中", "一場葬禮上", "逃亡途中", "剛醒來時", "一封信送達時", "節慶當天", "一切看似平靜時"]

SUMMARY_SYSTEM = "你負責壓縮文字冒險遊戲的劇情紀錄。用繁體中文純文字（不要用 Markdown 或 LaTeX），保留人物、地點、承諾、恩怨、伏筆等之後可能用到的資訊，捨棄修辭。"


def history(state: GameState) -> list[Turn]:
    """完整的劇情紀錄（由舊到新）。舊存檔可能還有等待壓縮的回合（unsummarized），一起算進來。"""
    return state.unsummarized + state.recent


def history_size(turns: list[Turn]) -> int:
    return sum(len(t.narration) + len(t.action) for t in turns)


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
    turn_label = "玩家"  # 「劇情紀錄」裡行動那一行的標籤
    epilogue_look_back = "回顧主角做過的關鍵抉擇與付出的代價；若主角死去，寫出主角留下的痕跡。"

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
            self.stage = ""

    def pick_genre(self, state: GameState) -> None:
        """玩家選「自動」：給 AI 題材目錄，請它依故事前提挑一個。先挑好，規劃大綱時才用得上題材的指引與轉折靈感。"""
        catalog = "\n".join(f"- {g.name}：{g.description}" for g in self.genres.values())
        picked = ""
        if catalog:
            response = self._generate(
                "題材",
                model=MODEL,
                contents=f"為這個互動文字冒險故事挑一個題材。\n# 故事前提\n{state.premise}\n\n# 題材目錄\n{catalog}",
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
        if state.turn == 0:
            situation = "故事還沒開始。"
        else:
            situation = (
                f"故事已經進行了 {state.turn} 回合，大綱要接續目前的劇情，已經發生的事放在前面的幕裡。\n"
                f"# 先前劇情摘要\n{state.summary or '（無）'}\n# 重大事件\n" + "\n".join(state.key_events)
            )
        cast = self._cast_section(state)
        prompt = (
            f"為這個互動文字冒險故事規劃大綱，預定約 {TARGET_TURNS} 回合。\n# 故事前提\n{state.premise}\n{cast}{situation}\n"
            "里程碑要具體、可以判斷是否達成。結局方向要依玩家的抉擇而不同，不要只有逃脫成功。\n"
            "先想好隱藏的真相（twist），第三幕的里程碑就是揭露它；再設計前兩幕能自然出現的伏筆（clues），"
            "讓真相揭露時玩家回想起來覺得「原來如此」，而不是突然冒出來的。避免老套的「同伴背叛」「幕後還有黑手」，除非有新意。\n"
            "真相不能決定玩家角色的生死，也不能讓玩家角色其實不是人（例如早就死了、是鬼、被寄生）：角色的生死與狀態由程式判定。"
            "真相要關係到所有主角，不要只落在某一位身上；可以是關於 NPC、事件、地點、物品或主角們的過去。"
            "伏筆要放在環境、NPC、物品或文件上，不要寫成玩家角色自己的感受或行動，那些由玩家決定。"
        )
        if state.genre_pending:
            self.pick_genre(state)
        if genre := self.genres.get(state.genre):  # 大綱要符合題材
            prompt += f"\n\n# 題材：{genre.name}\n{genre.guide}"
            if genre.names:
                prompt += f"\n\n# 命名素材（可以參考，不必全用）\n{genre.names}"
            if genre.twists:  # 每局隨機抽幾則，同一個題材玩很多次也不會總是同一招
                ideas = "\n".join(f"- {t}" for t in random.sample(genre.twists, min(TWIST_IDEAS, len(genre.twists))))
                prompt += f"\n\n# 轉折靈感（挑一則改寫成適合這個故事的版本，或想出更好的；不要照抄）\n{ideas}"
        response = self._generate(
            "大綱",
            model=MODEL,
            contents=prompt,
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
        self._advance(state, action=action)

    def suggest_premise(self, avoid: str = "", genre: str = "") -> str:
        """請 AI 想一個新的故事開頭。題材由程式隨機挑選（玩家指定了題材就用那個），AI 負責發揮。
        挑到題材包時，附上它的描述與幾則開頭靈感（premises.md）。"""
        if genre not in self.genres:
            genre = random.choice([*self.genres, *(g for g in PREMISE_GENRES if g not in self.genres)])
        setting = random.choice(PREMISE_SETTINGS)
        prompt = f"為互動文字冒險遊戲想一個原創的故事前提。題材：{genre}；故事開始於：{setting}。\n"
        if pack := self.genres.get(genre):
            prompt += f"題材說明：{pack.description}\n"
            if pack.premises:
                ideas = "\n".join(f"- {p}" for p in random.sample(pack.premises, min(3, len(pack.premises))))
                prompt += f"靈感（不要照抄，寫出新的）：\n{ideas}\n"
        prompt += (
            "用繁體中文、第二人稱（「你」），一到兩句、80 字以內。交代主角身分、所在處境，並留下一個引人好奇的謎團或危機。"
            "只輸出前提本身，不要標題或其他說明。"
        )
        if avoid:
            prompt += f"\n不要和這個前提相似：{avoid}"
        response = self._generate(
            "幫我想",
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level="low")),
        )
        text = (response.text or "").strip().strip("「」\"")
        if not text:
            raise RuntimeError("AI 沒有想出開頭，請再試一次。")
        return text

    def write_epilogue(self, state: GameState) -> None:
        """故事結束後，請 AI 回顧整段旅程寫出尾聲與結局名稱。"""
        prompt = self._build_prompt(state, None).rsplit("# 指示", 1)[0] + (
            f"# 故事的最後一段\n{state.current_narration}\n\n"
            "# 指示\n故事已經結束。寫一段尾聲，為這趟旅程收尾，並為這個結局取一個名稱。"
            f"{self.epilogue_look_back}不要開啟新的劇情。"
        )
        response = self._generate(
            "尾聲",
            model=MODEL,
            contents=prompt,
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
        prompt = self._build_prompt(state, action)
        beat = self._call(prompt)
        if beat.game_over and not ending_allowed(state, state.turn + 1):
            beat = self._call(prompt + "\n\n" + EARLY_ENDING_RETRY, kind="重寫")
        return beat

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
        prompt = self._build_prompt(state, action=None).rsplit("# 指示", 1)[0] + (
            f"# 剛才發生的事\n{state.current_narration}\n\n"
            "# 指示\n主角的傷勢已經致命。接續上面的敘述，寫出主角傷重死亡的結局，choices 留空，game_over 設為 true。"
        )
        ending = self._call(prompt, kind="倒下")
        state.current_narration += "\n\n" + ending.narration
        state.current_choices = []
        state.current_time_limit = 0
        state.game_over = True

    def _build_prompt(self, state: GameState, action: str | None) -> str:
        """把程式記得的所有東西組成本回合的輸入。每次呼叫都是無狀態的，記憶全靠這裡。

        順序：不常變的在前、會變的在後，讓 Gemini 的自動快取（只認開頭完全相同的部分）命中得越多越好：
        前提、模式 → 摘要（很少變）→ 劇情紀錄（只往後追加）→ 重大事件、故事進度、狀態、本回合行動（隨劇情改變）。
        """
        mode = (
            f"限時模式：緊迫時用 time_limit 給玩家 {MIN_TIME_LIMIT}-{MAX_TIME_LIMIT} 秒反應時間。"
            if state.timed_mode
            else "一般模式：time_limit 一律為 0。"
        )
        sections = [f"# 故事前提\n{state.premise}", f"# 模式\n{mode}"]
        genre = self.genres.get(state.genre)
        if genre:  # 整局固定，放在前段不影響快取
            sections.append(f"# 題材：{genre.name}（寫作指引）\n{genre.guide}")
        if state.summary:
            sections.append(f"# 先前劇情摘要\n{state.summary}")

        turns = history(state)
        if turns:
            lines = [f"[敘述] {t.narration}\n[{self.turn_label}] {t.action}" for t in turns]
            if action is not None:  # 最後一筆的行動就是本回合行動，下面另外列出，不重複
                lines[-1] = f"[敘述] {turns[-1].narration}"
            sections.append("# 劇情紀錄（由舊到新）\n" + "\n\n".join(lines))

        if state.key_events:
            sections.append("# 重大事件\n" + "\n".join(f"- {e}" for e in state.key_events))
        if progress := self._progress_section(state):
            sections.append(progress)
        if genre and genre.names and action is None and state.turn == 0:  # 開場要介紹人物與地點：附上命名素材
            sections.append(f"# 命名素材（可以參考，不必全用）\n{genre.names}")
        sections.append(self._status_section(state))
        sections += self._instruction_sections(state, action)
        return "\n\n".join(sections)

    # ---------- 多人模式覆寫的掛勾（下面是單人模式的版本） ----------

    def _cast_section(self, state: GameState) -> str:
        """規劃大綱時的主角名單。單人模式不需要。"""
        return ""

    def _action_text(self, action) -> str:
        """記在「劇情紀錄」裡的行動文字。"""
        return action

    def _status_section(self, state: GameState) -> str:
        status = {
            "回合": state.turn,
            "時間": "尚未確定" if state.minutes is None else clock_text(state.minutes),
            "身體狀況": [f"{c.name}（{c.severity}）" for c in body_conditions(state)] or ["良好"],
            "精神狀況": [f"{c.name}（{c.severity}）" for c in mind_conditions(state)] or ["平穩"],
            "整體": f"{body_level(state)}（身體傷勢 {body_score(state)}/{DEATH_SCORE}，達 {DEATH_SCORE} 即死亡；輕=1 中=2 重=4）",
            "背包": state.inventory or ["（空）"],
            "已確立的事實": state.flags or ["（無）"],
        }
        return "# 遊戲狀態\n" + json.dumps(status, ensure_ascii=False, separators=(",", ":"))

    def _instruction_sections(self, state: GameState, action) -> list[str]:
        if action is None:
            return ["# 指示\n這是故事的開場。介紹場景與主角處境，給出第一組選項。"]
        return [f"# 玩家本回合的行動\n{action}\n\n# 指示\n敘述這個行動的結果並推進劇情。"]

    def _progress_section(self, state: GameState) -> str:
        """隱藏的故事大綱與節奏提醒。只給 AI 看。"""
        arc = state.arc
        if arc is None:
            return ""
        lines = [f"目標：{arc.goal}"]
        for i, act in enumerate(arc.acts):
            mark = "→ 目前" if i == state.act else ("✓ 已完成" if i < state.act else "")
            lines.append(f"第{i + 1}幕「{act.name}」：{act.milestone} {mark}")
        lines.append("可能的結局：" + "；".join(arc.endings))
        if arc.twist:
            lines += self._twist_lines(arc, state.act)

        final = state.act == len(arc.acts) - 1
        if not final and state.act_turns + 1 < MIN_ACT_TURNS:
            left = MIN_ACT_TURNS - state.act_turns - 1
            lines.append(f"節奏提醒：這一幕剛開始，至少還要鋪陳 {left} 回合；這回合不要達成里程碑，milestone_reached 設為 false。")
        if not ending_allowed(state, state.turn + 1):
            lines.append(f"結局限制：故事最早要到第 {MIN_ENDING_TURN} 回合、進入最後一幕之後才能結束；在那之前 game_over 一律設為 false，也不要寫出結局。")
        if state.turn >= TARGET_TURNS:
            lines.append(f"收尾提醒：故事已經超過預定的 {TARGET_TURNS} 回合。這一兩回合內就要寫出高潮與結局，達成時設 game_over 為 true。不要再開啟新的支線或危機。")
        elif final:
            lines.append("收尾提醒：已進入最後一幕。朝高潮與結局推進，不要再開啟新的支線；最後的里程碑達成時寫出結局並設 game_over 為 true。")
        elif state.act_turns >= ACT_TURNS:
            lines.append("節奏提醒：這一幕已經拖太久了。本回合就要出現轉折，明顯朝目前的里程碑推進。")
        return "# 故事進度（玩家看不到）\n" + "\n".join(lines)

    @staticmethod
    def _twist_lines(arc: StoryArc, act: int) -> list[str]:
        """隱藏的真相：前兩幕只埋伏筆，第三幕揭露，之後當作已知的事。"""
        clues = "\n".join(f"- {c}" for c in arc.clues)
        if act < 2:
            lines = [f"隱藏的真相（第三幕才揭露，在那之前不要說破，也不要暗示得太明顯）：{arc.twist}"]
            if clues:
                lines.append(f"伏筆（前兩幕找合適的時機自然帶到，一次一個，不要解釋它的意義）：\n{clues}")
            return lines
        if act == 2:
            return [f"本幕要揭露隱藏的真相：{arc.twist}" + (f"\n揭露時呼應之前埋下的伏筆：\n{clues}" if clues else "")]
        return [f"已揭露的真相：{arc.twist}"]

    def _generate(self, kind: str, **request):
        """所有 AI 呼叫都經過這裡：記下種類、花了幾秒與 Gemini 回報的 token 用量（送出、命中快取、輸出、思考），
        寫進每回合的紀錄，方便查等待時間花在哪裡。"""
        started = time.monotonic()
        try:
            response = self.client.models.generate_content(**request)
        except Exception as e:  # 重送幾次都失敗：失敗的呼叫也記下來，跟下一回合的紀錄寫在一起
            self.calls.append({"kind": kind, "seconds": round(time.monotonic() - started, 2), "error": str(e)[:200]})
            if isinstance(e, (httpx.TimeoutException, httpx.ConnectError)):  # 轉成核心會處理的錯誤
                raise RuntimeError("Gemini 太久沒有回應或連不上，請稍後再試。") from e
            raise
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
        self.calls.append(call)
        return response

    def _write_log(self, record: dict) -> None:
        """寫一行紀錄，附上這段期間的 AI 呼叫。"""
        record["calls"], self.calls = self.calls, []
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # 紀錄寫不進去不影響遊戲

    def _call(self, prompt: str, kind: str = "劇情"):
        """呼叫 Gemini，取得結構化的回傳（單人是 StoryBeat，多人是 PartyBeat）。"""
        response = self._generate(
            kind,
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                response_mime_type="application/json",
                response_schema=self.beat_schema,
            ),
        )
        if not isinstance(response.parsed, self.beat_schema):
            reason = response.candidates[0].finish_reason if response.candidates else response.prompt_feedback
            raise RuntimeError(f"模型輸出無法解析（{reason}），請換個行動試試。")
        return response.parsed

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

        parts = [f"# 目前的摘要\n{state.summary or '（尚無）'}"]
        if turns:
            parts.append("# 新增的劇情紀錄\n" + "\n\n".join(f"[敘述] {t.narration}\n[玩家] {t.action}" for t in turns))
        if old_events or old_flags:
            parts.append("# 要併入的舊事件與事實\n" + "\n".join(f"- {x}" for x in old_events + old_flags))
        parts.append("把以上內容併入摘要，輸出更新後的完整摘要（500 字以內），只輸出摘要本身。")

        response = self._generate(
            "壓縮",
            model=MODEL,
            contents="\n\n".join(parts),
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
