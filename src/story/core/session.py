"""冒險：一支隊伍在 AI 寫的故事裡冒險。送文字進來、拿回覆出去。

外面看起來就像呼叫一個 LLM：`reply = core.send("往上爬")`（好幾位角色時是 `core.send_as("阿明", "往上爬")`）。
記憶、規則、存檔都藏在這裡；隊伍、存檔接續、收集行動這些跟海龜湯共用的流程在 team.py。
回覆和 LLM 的 API 一樣是「文字＋附帶資料」：只會印文字的外殼直接顯示 `reply.text`；
想做狀態列、倒數、選項按鈕的外殼，再去讀其他欄位。

API key、玩家名字、倒數計時、打字效果屬於外殼，不在這裡處理。
"""

import random
import threading
from pathlib import Path

from story.core.ai import LOG_PATH
from story.core.engine import Engine
from story.core.models import Character, GameState, word
from story.core.prompting import TURN
from story.core.records import DEFAULT_PREMISE, SAVE_PATH, ChangeGroups, change_groups, ending_record, memory_text, snapshot
from story.core.reply import UI, Ending, Reply, Status, join, pick_choice
from story.core.rules import condition_list, warning_level
from story.core.team import FAILURES, PLAY_AGAIN_CHOICES, TeamGame

GENRE_AUTO, GENRE_NONE = "auto", "none"  # 題材的兩個特別選項：依前提由 AI 挑、不套用題材（顯示的字是 genre_label()）


def genre_label(choice: str) -> str:
    """題材選擇顯示的字：特別選項換成這個語言的詞，題材包就是它的名稱。"""
    return {GENRE_AUTO: UI["genre_auto"], GENRE_NONE: UI["genre_none"]}.get(choice, choice)


class StoryCore(TeamGame):
    """一局冒險：一支一到四位角色的隊伍，每位由一位玩家扮演（一個人玩就是只有一位）。
    所有還活著的角色都行動了才請 AI 寫這一回合。共用的流程見 TeamGame。"""

    setup_phase = "ask_premise"
    state_class = GameState

    def __init__(
        self,
        api_key: str,
        players: list[str],
        *,
        save_path: Path = SAVE_PATH,
        log_path: Path = LOG_PATH,
        engine: Engine | None = None,
        client=None,
    ):
        """client：要共用的 Gemini client（例如受 RateLimit 限制的），沒給就用 api_key 建一個。"""
        super().__init__(players, save_path)
        self.engine = engine or Engine(api_key=api_key, client=client, log_path=log_path)
        self.state: GameState | None = None
        self.timed = False  # 開新局時的模式，沿用上一局的選擇
        self.genre = GENRE_AUTO  # 開新局時的題材選擇，沿用上一局的選擇
        self.last_premise = ""
        self.suggested = ""  # /suggest 想出來的前提，留白送出時優先使用
        self.drawn = ""  # 從題材包的開頭靈感隨機抽到的前提；再玩一次時不抽，延續上一局的前提
        self._compaction: threading.Thread | None = None

    def set_api_key(self, api_key: str) -> None:
        self.engine.set_api_key(api_key)

    @property
    def progress(self) -> str:
        return self.engine.stage

    @property
    def draft(self) -> str:
        return self.engine.draft

    # ---------- 開新局：故事前提 ----------

    def _new_game(self) -> Reply:
        if self.state is not None:
            self.last_premise = self.state.premise  # 再玩一次時延續上一局的前提
        return self._ask_premise()

    def _on_setup(self, raw: str) -> Reply:
        if raw == "/suggest":
            try:
                chosen = self.genre if self.genre in self.engine.genres else ""
                suggestion = self.engine.suggest_premise(self.last_premise or DEFAULT_PREMISE, genre=chosen)
            except FAILURES as e:
                return self._failed(e, self._ask_premise)
            self.suggested = suggestion
            return self._ask_premise(suggestion=suggestion)
        if raw == "/random":
            self.suggested, self.drawn = "", self._draw_premise(avoid=self._default_premise())
            return self._ask_premise(notice=UI["rerolled"])
        if raw.startswith("/timed"):
            arg = raw.removeprefix("/timed").strip()
            self.timed = {"on": True, "off": False}.get(arg, not self.timed)
            return self._ask_premise(notice=UI["mode_switched_timed" if self.timed else "mode_switched_normal"])
        if raw.startswith("/genre"):
            typed = raw.removeprefix("/genre").strip()
            choice = {UI["genre_auto"]: GENRE_AUTO, UI["genre_none"]: GENRE_NONE}.get(typed, typed)  # 打字的也可以用顯示的詞
            if choice not in (GENRE_AUTO, GENRE_NONE, *self.engine.genres):
                options = join(genre_label(g) for g in (GENRE_AUTO, GENRE_NONE, *self.engine.genres))
                return self._ask_premise(notice=UI["genre_unknown"].format(choice=typed, options=options))
            self.genre = choice
            if self.drawn and not self.suggested and self.drawn not in self._premise_pool():
                self.drawn = self._draw_premise()  # 抽到的開頭跟著換成新題材的
            return self._ask_premise(notice=UI["genre_chosen"].format(choice=genre_label(choice)))
        if raw.startswith("/"):
            return self._ask_premise(notice=UI["unknown_command"].format(command=raw))

        premise = " ".join(raw.split()) or self._default_premise()
        state = self._new_state(premise)
        try:
            self.engine.start(state)
        except FAILURES as e:
            return self._failed(e, self._ask_premise)
        self.state, self._phase, self.last_premise, self.suggested, self.drawn = state, "playing", premise, "", ""
        self._save()
        return self._turn_reply(before=None)

    def _ask_premise(self, suggestion: str = "", notice: str = "", error=None) -> Reply:
        self._phase = "ask_premise"
        if not (self.suggested or self.drawn or self.last_premise):  # 第一次開新故事：隨機抽一個開頭
            self.drawn = self._draw_premise()
        return self._reply(
            premise_default=self._default_premise(),
            genre=self.genre,
            genres=[(g.name, g.description) for g in self.engine.genres.values()],
            suggestion=suggestion,
            notice=notice,
            error=error,
        )

    def _new_state(self, premise: str) -> GameState:
        self.pending = {}
        characters = [Character(name=n) for n in self._players]
        return GameState(premise=premise, characters=characters, timed_mode=self.timed, **self._genre_fields())

    def _genre_fields(self) -> dict:
        """新局的題材欄位：指定題材就直接套用；選「自動」時，規劃大綱時由 AI 從目錄挑。"""
        if self.genre in self.engine.genres:
            return {"genre": self.genre}
        return {"genre_pending": self.genre == GENRE_AUTO and bool(self.engine.genres)}

    def _default_premise(self) -> str:
        """留白時使用的前提：AI 想的 → 隨機抽的 → 上一局的（再玩一次）→ 預設的。"""
        return self.suggested or self.drawn or self.last_premise or DEFAULT_PREMISE

    def _premise_pool(self) -> list[str]:
        """可以隨機抽的開頭：指定了題材就用那個題材包的，否則用所有題材包的，再加上預設的前提。"""
        genres = self.engine.genres
        if self.genre in genres and genres[self.genre].premises:
            return list(genres[self.genre].premises)
        return [p for g in genres.values() for p in g.premises] + [DEFAULT_PREMISE]

    def _draw_premise(self, avoid: str = "") -> str:
        pool = self._premise_pool()
        return random.choice([p for p in pool if p != avoid] or pool)

    # ---------- 一回合 ----------

    def _action(self, raw: str, actor: str | None) -> str | None:
        if raw.startswith("/"):
            return None
        return pick_choice(raw, self._choices(actor) if actor else []) or raw

    def _play_round(self, actions: dict[str, str]) -> Reply:
        """請 AI 寫這一回合，存檔，回傳這回合的回覆。"""
        self._wait_compaction()
        before = {c.name: snapshot(c) for c in self.state.characters}
        self.engine.act(self.state, actions)
        self.pending = {}
        self._save()
        if self.state.game_over:
            self._phase = "ending"
        else:
            self._start_compaction()
        return self._turn_reply(before)

    def _on_ending(self, raw: str) -> Reply:
        """故事結束後的下一次輸入：寫尾聲。尾聲寫失敗也照樣進到結束階段，可以再玩一次。"""
        s = self.state
        notice = ""
        if not s.epilogue:
            try:
                self.engine.write_epilogue(s)
                self._save()
            except FAILURES as e:
                notice = UI["epilogue_failed"].format(error=str(e)[:200])
        self._phase = "ended"
        return self._reply(
            choices=PLAY_AGAIN_CHOICES,
            notice=notice,
            ending=Ending(title=s.ending_title, epilogue=s.epilogue, record=ending_record(s)),
        )

    def _turn_reply(self, before) -> Reply:
        s = self.state
        changes = []
        if before is not None:
            for c in s.characters:
                if groups := change_groups(before[c.name], c):
                    changes.append((c.name, groups))
        return self._reply(narration=s.current_narration, changes=changes, **self._screen())

    # ---------- 給 TeamGame 的資料 ----------

    def _active(self) -> list[str]:
        return [c.name for c in self.state.characters if c.alive]

    def _choices(self, name: str) -> list[str]:
        return next((list(c.choices) for c in self.state.characters if c.name == name), [])

    def _time_limit(self) -> int:
        return self.state.current_time_limit

    def _status(self) -> dict:
        s = self.state
        return {"turn": s.turn, "timed": s.timed_mode, "characters": [character_status(c) for c in s.characters]}

    def _next_timed(self) -> bool:
        return self.timed

    def _loaded(self) -> None:
        self.timed = self.state.timed_mode

    def _replay(self) -> dict:
        s = self.state
        return {"narration": s.current_narration, "resumed": True, "history": self._history(), "history_trimmed": bool(s.summary)}

    def _history(self) -> list[tuple[str, str]]:
        """之前的劇情（劇情紀錄的原文）：(劇情, 看完之後的行動)。只有一位角色時，行動前面不寫名字，跟平常顯示的一樣。"""
        s = self.state
        prefix = TURN["action_entry"].format(name=s.characters[0].name, action="") if s.solo else ""
        return [(t.narration, t.action.removeprefix(prefix)) for t in s.recent]

    def _memory(self) -> str:
        return memory_text(self.state)

    def _render(self, reply: Reply) -> str:
        return render_text(reply)

    # ---------- 背景壓縮記憶 ----------

    def _start_compaction(self) -> None:
        """玩家讀劇情時，在背景把舊的記憶壓縮進摘要。下一次需要呼叫 LLM 前會先等它完成。"""
        if not self.engine.needs_compaction(self.state):
            return
        state = self.state

        def run() -> None:
            try:
                self.engine.compact_memory(state)
            except Exception:
                return  # 失敗沒關係，下回合會再試
            if state is self.state:  # 期間開了新局的話，不要用舊局覆蓋存檔
                self._save()

        self._compaction = threading.Thread(target=run, daemon=True)
        self._compaction.start()

    def _wait_compaction(self) -> None:
        if self._compaction is not None:
            self._compaction.join()
            self._compaction = None


def character_status(c: Character) -> Status:
    """給外殼顯示的一位角色的狀態（Reply.characters 裡的一項）。"""
    return Status(conditions=condition_list(c), warning=warning_level(c) if c.alive else "", name=c.name, alive=c.alive)


# ---------- 純文字版的回覆 ----------


def conditions_text(status: Status) -> str:
    """狀態直接列出，不分身體與精神；危險時先警告。背包的變化會寫在每回合的變化裡，完整內容用 /state 看。"""
    items = join(UI["condition"].format(name=n, severity=word("severity", v)) for n, v in status.conditions) or word("level", "healthy")
    return UI["text_warning"].format(level=word("level", status.warning), conditions=items) if status.warning else items


def status_line(turn: int, status: Status, timed: bool) -> str:
    return UI["text_status"].format(turn=turn, timed=UI["text_status_timed"] if timed else "", conditions=conditions_text(status))


def character_line(status: Status) -> str:
    return UI["text_character_line"].format(name=status.name, conditions=conditions_text(status) if status.alive else UI["text_fallen"])


def changes_line(groups: ChangeGroups) -> str:
    return UI["text_changes_sep"].join(UI["text_changes"].format(label=label, items=join(text for text, _ in items)) for label, items in groups)


def render_text(reply: Reply) -> str:
    """把回覆組成一段完整的純文字。只有一位角色時不列名字，也不說輪到誰。"""
    several = len(reply.characters) > 1
    parts: list[str] = []
    if reply.notice:
        parts.append(UI["text_notice"].format(notice=reply.notice))
    if reply.info:
        title, body = reply.info
        parts.append(UI["text_info"].format(title=title, body=body))
    if reply.phase == "ask_premise":
        if reply.suggestion:
            parts.append(UI["text_suggested"])
        mode = UI["text_mode_timed" if reply.timed else "text_mode_normal"]
        parts.append(UI["text_new_story"].format(mode=mode, genre=genre_label(reply.genre), premise=reply.premise_default))
        if reply.genres:
            choices = [GENRE_AUTO, GENRE_NONE, *(name for name, _ in reply.genres)]
            parts.append(UI["text_genres"].format(genres=join(genre_label(g) for g in choices)))
    if reply.history_trimmed:
        parts.append(UI["text_history_trimmed"])
    for narration, action in reply.history:
        parts.append(narration)
        parts.append(UI["text_action"].format(action=action))
    if reply.narration:
        parts.append(reply.narration)
    for name, groups in reply.changes:
        parts.append(UI["text_named_changes"].format(name=name, changes=changes_line(groups)) if several else changes_line(groups))
    if reply.ending:
        e = reply.ending
        parts.append(UI["text_ending_title"].format(title=e.title or UI["text_story_over"]))
        if e.epilogue:
            parts.append(e.epilogue)
        parts.append(e.record)
    if reply.characters and reply.phase in ("playing", "ending") and reply.narration:
        if several:  # 每位角色一行
            parts.append("\n".join(character_line(st) for st in reply.characters) + ("\n" + UI["text_mode_timed"] if reply.timed else ""))
        else:
            parts.append(status_line(reply.turn, reply.characters[0], reply.timed))
    if reply.phase == "ending":
        parts.append(UI["text_send_for_epilogue"])
    if reply.actor and several:
        parts.append(UI["text_actor"].format(name=reply.actor))
    if reply.choices:
        parts.append("\n".join(f"{i}. {c}" for i, c in enumerate(reply.choices, 1)))
    if reply.time_limit:
        parts.append(UI["text_time_limit"].format(seconds=reply.time_limit))
    return "\n\n".join(parts)
