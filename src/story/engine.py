"""Harness 核心：組 prompt、呼叫 LLM、驗證輸出、更新狀態、管理記憶。"""

import json

from google import genai
from google.genai import types

from story.models import GameState, StoryBeat, Turn

MODEL = "gemini-3.5-flash-lite"
RECENT_WINDOW = 4  # 近期記憶保留幾回合原文
SUMMARIZE_EVERY = 4  # 累積幾回合擠出的內容就壓縮一次摘要
MIN_TIME_LIMIT, MAX_TIME_LIMIT = 8, 60  # 限時模式的反應時間範圍（秒）
MAX_CONDITION_LEN = 12  # 單一狀態最多幾個字，避免 LLM 寫成一整句
TIMEOUT_ACTION = "（時間到：你遲疑太久，沒有在時限內做出反應）"

# 固定不變的 system prompt，放在最前面以利 prompt caching
SYSTEM_PROMPT = """你是一個互動式文字冒險遊戲的敘事者。

規則：
- 用繁體中文、第二人稱（「你」）敘述，文風生動但精簡。
- 每回合根據玩家的行動推進劇情，行動要有合理的後果，好壞都可能。
- 「遊戲狀態」區塊是唯一的事實來源。不要讓玩家使用不在背包裡的物品；若玩家嘗試，描述他們發現自己沒有。
- 尊重已確立的劇情事實與重大事件，不要自相矛盾。
- 提供 2-4 個彼此有明顯差異的選項；玩家也可能不照選項自由行動。
- 主角沒有生命值，而是用「身體狀況」描述：受傷、疲勞、中毒、恐懼等都列成狀態，痊癒或消失時移除。狀態要影響後續劇情與行動的成敗。
- 傷勢累積到致命、或劇情自然走到結局時，設 game_over 為 true，並寫出結局。
- 狀態變化要與敘述一致：敘述裡受傷就要加入對應的狀態，撿到東西就要列進 items_gained。
- 若「模式」區塊說明是限時模式：當情勢緊迫（追逐、墜落、對峙、倒數）時設定 time_limit，越危急越短；平靜的場景設 0。非限時模式一律設 0。
- 若玩家行動是「（時間到……）」，代表玩家沒能及時反應，要描述猶豫帶來的後果。"""

SUMMARY_SYSTEM = "你負責壓縮文字冒險遊戲的劇情紀錄。用繁體中文，保留人物、地點、承諾、恩怨、伏筆等之後可能用到的資訊，捨棄修辭。"


class Engine:
    def __init__(self, api_key: str | None = None, client: genai.Client | None = None):
        self.client = client or genai.Client(api_key=api_key)

    def set_api_key(self, api_key: str) -> None:
        self.client = genai.Client(api_key=api_key)

    # ---------- 對外介面 ----------

    def start(self, state: GameState) -> None:
        """產生開場。"""
        self._advance(state, action=None)

    def act(self, state: GameState, action: str) -> None:
        """玩家做出行動，推進一回合。"""
        state.recent.append(Turn(narration=state.current_narration, action=action))
        self._compact_memory(state)
        self._advance(state, action=action)

    # ---------- 生成劇情 ----------

    def _advance(self, state: GameState, action: str | None) -> None:
        beat = self._call_story(self._build_prompt(state, action))
        self._apply(state, beat)

    def _build_prompt(self, state: GameState, action: str | None) -> str:
        """把程式記得的所有東西組成本回合的輸入。每次呼叫都是無狀態的，記憶全靠這裡。"""
        sections = [f"# 故事前提\n{state.premise}"]

        status = {
            "回合": state.turn,
            "身體狀況": state.conditions or ["良好"],
            "背包": state.inventory or ["（空）"],
            "已確立的事實": state.flags or ["（無）"],
        }
        sections.append("# 遊戲狀態\n" + json.dumps(status, ensure_ascii=False, indent=2))
        mode = (
            f"限時模式：緊迫時用 time_limit 給玩家 {MIN_TIME_LIMIT}-{MAX_TIME_LIMIT} 秒反應時間。"
            if state.timed_mode
            else "一般模式：time_limit 一律為 0。"
        )
        sections.append(f"# 模式\n{mode}")

        if state.summary:
            sections.append(f"# 先前劇情摘要\n{state.summary}")
        if state.key_events:
            sections.append("# 重大事件\n" + "\n".join(f"- {e}" for e in state.key_events))
        if state.recent:
            lines = [f"[敘述] {t.narration}\n[玩家] {t.action}" for t in state.recent]
            sections.append("# 最近幾回合\n" + "\n\n".join(lines))

        if action is None:
            sections.append("# 指示\n這是故事的開場。介紹場景與主角處境，給出第一組選項。")
        else:
            sections.append(f"# 玩家本回合的行動\n{action}\n\n# 指示\n敘述這個行動的結果並推進劇情。")

        return "\n\n".join(sections)

    def _call_story(self, prompt: str) -> StoryBeat:
        response = self.client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=StoryBeat,
            ),
        )
        if not isinstance(response.parsed, StoryBeat):
            reason = response.candidates[0].finish_reason if response.candidates else response.prompt_feedback
            raise RuntimeError(f"模型輸出無法解析（{reason}），請換個行動試試。")
        return response.parsed

    # ---------- 驗證並套用 ----------

    def _apply(self, state: GameState, beat: StoryBeat) -> None:
        """LLM 只能「提議」狀態變化，由程式決定接受多少。"""
        state.turn += 1

        for cond in beat.conditions_removed:
            if cond in state.conditions:  # 不能移除沒有的狀態
                state.conditions.remove(cond)
        for cond in beat.conditions_added:
            cond = cond.strip()[:MAX_CONDITION_LEN]
            if cond and cond not in state.conditions:
                state.conditions.append(cond)

        for item in beat.items_lost:
            if item in state.inventory:  # 不能失去沒有的東西
                state.inventory.remove(item)
        for item in beat.items_gained:
            state.inventory.append(item)

        for flag in beat.flags_set:
            if flag not in state.flags:
                state.flags.append(flag)
        if beat.key_event.strip():
            state.key_events.append(beat.key_event.strip())

        state.current_narration = beat.narration
        state.current_choices = beat.choices[:4]
        state.game_over = beat.game_over

        # 限時與否由程式決定：非限時模式忽略 LLM 給的秒數，限時模式把秒數夾在合理範圍
        limit = beat.time_limit if state.timed_mode and not state.game_over else 0
        state.current_time_limit = 0 if limit <= 0 else max(MIN_TIME_LIMIT, min(MAX_TIME_LIMIT, limit))

    # ---------- 記憶壓縮 ----------

    def _compact_memory(self, state: GameState) -> None:
        """近期記憶超出視窗時，把最舊的回合移出；累積夠多就壓縮進長期摘要。"""
        while len(state.recent) > RECENT_WINDOW:
            state.unsummarized.append(state.recent.pop(0))

        if len(state.unsummarized) < SUMMARIZE_EVERY:
            return

        log = "\n\n".join(f"[敘述] {t.narration}\n[玩家] {t.action}" for t in state.unsummarized)
        prompt = (
            f"# 目前的摘要\n{state.summary or '（尚無）'}\n\n"
            f"# 新增的劇情紀錄\n{log}\n\n"
            "把新增紀錄併入摘要，輸出更新後的完整摘要（400 字以內），只輸出摘要本身。"
        )
        response = self.client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SUMMARY_SYSTEM,
                thinking_config=types.ThinkingConfig(thinking_level="low"),
            ),
        )
        text = (response.text or "").strip()
        if text:
            state.summary = text
            state.unsummarized.clear()
        # 失敗就先保留 unsummarized，下回合再試
