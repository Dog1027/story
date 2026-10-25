"""推進一局遊戲：規劃大綱、請 AI 寫每一回合、驗證並套用 AI 提議的變化、寫尾聲、壓縮記憶。

規則在 rules.py，提示詞在 prompting.py（文字在 story/prompts/語言/），呼叫 AI 在 ai.py。
"""

from pathlib import Path

from google.genai import types

from story.core.ai import LOG_PATH, MODEL, UI, AICaller, EndingTooEarly
from story.core.genres import Genre, load_genres
from story.core.models import Epilogue, GameState, GenrePick, StoryArc, StoryBeat, Turn
from story.core.prompting import MEMORY, SYSTEM_PROMPT, TURN, PromptBuilder, clock_text, format_actions
from story.core.rules import (
    ACT_TURNS,
    DEATH_SCORE,
    advance_clock,
    apply_condition_changes,
    apply_items,
    apply_story_progress,
    body_score,
    clamp_time_limit,
    ending_allowed,
    needs_compaction,
    to_compact,
)


class Engine(AICaller):
    def __init__(
        self,
        api_key: str | None = None,
        client=None,
        log_path: Path = LOG_PATH,
        genres: dict[str, Genre] | None = None,
    ):
        super().__init__(api_key, client, log_path)
        self.genres = load_genres()[0] if genres is None else genres  # 題材包（見 genres.py）
        self.build = PromptBuilder(self.genres)  # 組提示詞
        self.stage = ""  # 開新故事時目前在做什麼，外殼顯示在等待畫面上（例如「規劃故事大綱」）

    # ---------- 對外介面 ----------

    def start(self, state: GameState) -> None:
        """先規劃隱藏的故事大綱，再產生開場（題材選「自動」時，最前面再多一次挑題材）。
        要呼叫好幾次 AI，比一般回合久，所以用 stage 告訴外殼進度。"""
        try:
            if state.genre_pending and self.genres:
                self.stage = UI["stage_genre"]
                self.pick_genre(state)
            self.stage = UI["stage_arc"]
            self.plan_arc(state)
            self.stage = UI["stage_opening"]
            self._advance(state, None)
        finally:
            self.stage, self.draft = "", ""

    def pick_genre(self, state: GameState) -> None:
        """玩家選「自動」：給 AI 題材目錄，請它依故事前提挑一個。先挑好，規劃大綱時才用得上題材的指引與轉折靈感。"""
        picked = ""
        if self.genres:
            response = self.generate(
                "genre",
                model=MODEL,
                contents=self.build.pick_genre(state),
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
        """請 AI 規劃故事大綱。開場前規劃失敗時，之後的回合會依目前的劇情補一份，並依回合數決定從哪一幕接著走。"""
        if state.genre_pending:
            self.pick_genre(state)
        response = self.generate(
            "arc",
            model=MODEL,
            contents=self.build.arc(state),
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
        state.act, state.act_turns = min(3, state.turn // ACT_TURNS), 0  # 補的大綱：依回合數推估目前在哪一幕

    def act(self, state: GameState, actions: dict[str, str]) -> None:
        """每位角色都行動了（{名字: 行動}），推進一回合。"""
        if state.arc is None:
            self.plan_arc(state)
        state.recent.append(Turn(narration=state.current_narration, action=format_actions(actions)))  # 只往後追加
        try:
            self._advance(state, actions)
        finally:
            self.draft = ""

    def suggest_premise(self, avoid: str = "", genre: str = "") -> str:
        """請 AI 想一個新的故事開頭。題材由程式隨機挑選（玩家指定了題材就用那個），AI 負責發揮。"""
        response = self.generate(
            "suggest",
            model=MODEL,
            contents=self.build.premise(avoid, genre),
            config=types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level="low")),
        )
        text = (response.text or "").strip().strip("「」\"")
        if not text:
            raise RuntimeError(UI["no_suggestion"])
        return text

    def write_epilogue(self, state: GameState) -> None:
        """故事結束後，請 AI 回顧整段旅程寫出尾聲與結局名稱。"""
        response = self.generate(
            "epilogue",
            model=MODEL,
            contents=self.build.epilogue(state),
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, response_mime_type="application/json", response_schema=Epilogue),
        )
        if not isinstance(response.parsed, Epilogue):
            raise RuntimeError(UI["no_epilogue"])
        state.ending_title, state.epilogue = response.parsed.title.strip(), response.parsed.text.strip()
        self.write_log({"turn": state.turn, "epilogue": state.ending_title})

    # ---------- 一回合 ----------

    def _next_beat(self, state: GameState, actions: dict[str, str] | None) -> StoryBeat:
        """請 AI 寫這一回合。太早寫出結局時請它重寫一次；重寫後還是結局的話，_apply() 會忽略結局的宣告。"""
        prompt = self.build.turn(state, actions)
        try:
            # game_over 是 AI 第一個輸出的欄位：太早的結局在劇情出現之前就會發現，玩家不會看到被換掉的版本
            return self.stream_beat(SYSTEM_PROMPT, prompt, stop_on_ending=not ending_allowed(state, state.turn + 1))
        except EndingTooEarly:
            self.draft = ""
            return self.stream_beat(SYSTEM_PROMPT, prompt + "\n\n" + TURN["early_ending_retry"], kind="rewrite")

    def _advance(self, state: GameState, actions: dict[str, str] | None) -> None:
        beat = self._next_beat(state, actions)
        newly_dead = self._apply(state, beat)
        self._log_turn(state, actions, beat)
        if newly_dead:
            self._write_deaths(state, newly_dead)

    def _apply(self, state: GameState, beat: StoryBeat) -> list[str]:
        """AI 只能「提議」變化，由程式決定接受多少：每位角色各自套用規則。回傳這回合傷重死亡的角色名字。"""
        elapsed, is_opening_turn = advance_clock(state, beat.time_passed, beat.start_time_of_day)
        may_end = ending_allowed(state, state.turn)  # 在推進幕數之前判斷：剛進最後一幕的那回合還不能結束
        updates = {u.name.strip(): u for u in beat.character_updates}  # 不在隊伍裡的名字自然被忽略
        if state.solo and beat.character_updates and state.characters[0].name not in updates:
            updates[state.characters[0].name] = beat.character_updates[0]  # 只有一位角色時，AI 寫錯名字也算他的
        newly_dead = []
        for c in state.characters:
            if not c.alive:
                continue
            u = updates.get(c.name)
            if u is None:  # AI 漏掉這位角色：時間照樣經過，選項留空（玩家可以自由行動）
                apply_condition_changes(c, [], [], elapsed)
                c.choices = []
                continue
            apply_condition_changes(c, u.conditions_changed, u.conditions_removed, elapsed)
            apply_items(c, u.items_gained, u.items_lost)
            c.choices = u.choices[:4]
            if body_score(c) >= DEATH_SCORE:
                c.alive, c.choices = False, []
                newly_dead.append(c.name)
        apply_story_progress(state, beat.flags_set, beat.key_event, beat.milestone_reached, is_opening_turn)

        state.current_narration = beat.narration
        state.game_over = (beat.game_over and may_end) or not any(c.alive for c in state.characters)
        state.current_time_limit = clamp_time_limit(state, beat.time_limit)
        return newly_dead

    def _write_deaths(self, state: GameState, names: list[str]) -> None:
        """程式判定有角色傷重死亡：請 AI 接著寫一小段倒下的場景，接在這回合的劇情後面。"""
        prefix = state.current_narration + "\n\n"

        def on_text(text: str) -> None:  # 串流時接在剛才的劇情後面
            self.draft = prefix + text.lstrip()

        text, _ = self.stream(
            "death",
            on_text,
            model=MODEL,
            contents=self.build.death(state, names),
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        )
        if text := text.strip():
            state.current_narration += "\n\n" + text

    def _log_turn(self, state: GameState, actions: dict[str, str] | None, beat: StoryBeat) -> None:
        """把 AI 這回合提議的變化和程式套用後的結果記到檔案，方便事後查「為什麼會這樣」。"""
        self.write_log({
            "turn": state.turn,
            "actions": actions,
            "ai": beat.model_dump(exclude={"narration"}),
            "characters": {c.name: {"conditions": [f"{x.name}({x.severity})" for x in c.conditions], "alive": c.alive} for c in state.characters},
            "time": clock_text(state.minutes),
        })

    # ---------- 記憶壓縮 ----------

    def needs_compaction(self, state: GameState) -> bool:
        return needs_compaction(state)

    def compact_memory(self, state: GameState) -> None:
        """劇情紀錄太長時，把最舊的回合（壓到剩一半）、較舊的重大事件與事實併入長期摘要。
        由核心在背景呼叫，玩家讀劇情時順便完成。很少發生：30 回合的故事大約只有七、八千字。"""
        if not needs_compaction(state):
            return
        turns, old_events, old_flags = to_compact(state)
        response = self.generate(
            "compaction",
            model=MODEL,
            contents=self.build.compaction(state),
            config=types.GenerateContentConfig(system_instruction=MEMORY["system"], thinking_config=types.ThinkingConfig(thinking_level="low")),
        )
        text = (response.text or "").strip()
        if not text:
            return  # 失敗就先保留原樣，下次再試
        # 只移除這次確實併入摘要的部分（壓縮期間不會有新回合，但仍以數量為準比較保險）
        state.summary = text
        del state.recent[: len(turns)]
        del state.key_events[: len(old_events)]
        del state.flags[: len(old_flags)]
