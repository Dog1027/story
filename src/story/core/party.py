"""多人模式：疊在單人模式上。

PartyEngine 繼承單人的 Engine，PartyCore 繼承單人的 StoryCore，只覆寫「主角變成一支隊伍」不一樣的地方；
規則（傷勢、痊癒、時間、背包、限時）、記憶、大綱與節奏、存檔、文字指令都直接沿用單人模式。

介面和單人一樣是 send(文字) → Reply。差別在遊戲中：
- reply.actor 是現在輪到誰輸入；送進來的文字就算是那位角色的行動，reply.choices 是那位角色的選項
- 所有還活著的角色都輸入後，才呼叫 AI 寫這一回合
- reply.characters 是每位角色的狀態，reply.changes 是每位角色這回合的變化（單人模式也用這兩個欄位，只是只有一位、沒有名字）
- /timeout 會把還沒行動的人都當作「時間到」，直接推進這一回合
- /away 是這位角色暫時離開（例如線上多人斷線），這回合不行動；給 AI 的文字是 AWAY_ACTION

同一台電腦輪流輸入時用 send()，照隊伍順序收行動；線上多人用 send_as(名字, 文字)，誰先送誰先記，
再用 view(名字) 取得某位玩家眼中的畫面（自己的選項）。
"""

import json
from dataclasses import replace
from pathlib import Path

from google.genai import types

from story.core.engine import (
    DEATH_SCORE,
    MODEL,
    STATUS_EMPTY,
    STATUS_KEYS,
    Engine,
    advance_clock,
    apply_condition_changes,
    apply_items,
    apply_story_progress,
    body_score,
    clamp_time_limit,
    clock_text,
    condition_fields,
    condition_list,
    ending_allowed,
    time_text,
    warning_level,
)
from story.core.models import Character, GameState, PartyBeat
from story.core.records import change_groups, snapshot
from story.core import prompts
from story.core.session import Reply, Status, StoryCore, render_text

PARTY_SYSTEM_PROMPT = prompts.load("party_system")
PARTY_TURN = prompts.sections("party_turn")

PARTY_SAVE_PATH = Path("party_save.json")
PARTY_LOG_PATH = Path("party_log.jsonl")
MIN_PLAYERS, MAX_PLAYERS = 1, 4  # 一個人也能開線上多人的房間先玩，其他人之後再一起玩下一局
AWAY_ACTION = PARTY_TURN["away_action"]  # /away：角色暫時不在（線上多人斷線時由房間送出），這句會寫進劇情紀錄給 AI


class PartyEngine(Engine):
    """多人模式的 engine：提示詞的共用部分、呼叫 AI、尾聲、大綱都沿用 Engine，只覆寫隊伍相關的掛勾。"""

    system_prompt = PARTY_SYSTEM_PROMPT
    beat_schema = PartyBeat
    turn_label = PARTY_TURN["turn_label"]
    epilogue_look_back = PARTY_TURN["epilogue_look_back"]

    # ---------- 提示詞的掛勾 ----------

    def _cast_section(self, state: GameState) -> str:
        return PARTY_TURN["cast"].format(names="、".join(c.name for c in state.party)) + "\n"

    def _action_text(self, action: dict[str, str]) -> str:
        return format_actions(action)

    def _status_section(self, state: GameState) -> str:
        key = STATUS_KEYS
        party = {
            key["turn"]: state.turn,
            key["time"]: time_text(state),
            key["flags"]: state.flags or [STATUS_EMPTY["flags"]],
            key["characters"]: [prompt_status(c) for c in state.party],
        }
        return PARTY_TURN["status"].format(json=json.dumps(party, ensure_ascii=False, separators=(",", ":")))

    def _instruction_sections(self, state: GameState, action: dict[str, str] | None) -> list[str]:
        sections = []
        alive = [c.name for c in state.party if c.alive]
        if alive:  # 焦點由程式輪流指定，避免 AI 老是讓同一個人當主角
            sections.append(PARTY_TURN["focus"].format(name=alive[state.turn % len(alive)]))
        if action is None:
            sections.append(PARTY_TURN["opening"])
        else:
            sections.append(PARTY_TURN["action"].format(actions=format_actions(action)))
        return sections

    # ---------- 套用：每位角色各自套用單人的規則 ----------

    def _advance(self, state: GameState, action: dict[str, str] | None) -> None:
        beat = self._next_beat(state, action)
        newly_dead = self._apply(state, beat)
        self._log_turn(state, action, beat)
        if newly_dead:
            self._write_deaths(state, newly_dead)

    def _apply(self, state: GameState, beat: PartyBeat) -> list[str]:
        """套用多人回合。回傳這回合傷重死亡的角色名字。"""
        elapsed, is_opening_turn = advance_clock(state, beat.time_passed, beat.start_time_of_day)
        may_end = ending_allowed(state, state.turn)  # 在推進幕數之前判斷：剛進最後一幕的那回合還不能結束
        updates = {u.name.strip(): u for u in beat.character_updates}  # 不在隊伍裡的名字自然被忽略
        newly_dead = []
        for c in state.party:
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
        state.current_choices = []
        state.game_over = (beat.game_over and may_end) or not any(c.alive for c in state.party)
        state.current_time_limit = clamp_time_limit(state, beat.time_limit)
        return newly_dead

    def deaths_prompt(self, state: GameState, names: list[str]) -> str:
        """程式判定有角色傷重死亡：請 AI 接著寫一小段倒下的場景。"""
        who = "、".join(names)
        return "\n\n".join(self._context(state, None) + [PARTY_TURN["death"].format(narration=state.current_narration, who=who)])

    def _write_deaths(self, state: GameState, names: list[str]) -> None:
        prefix = state.current_narration + "\n\n"

        def on_text(text: str) -> None:  # 串流時接在剛才的劇情後面
            self.draft = prefix + text.lstrip()

        text, _ = self._stream(
            "倒下",
            on_text,
            model=MODEL,
            contents=self.deaths_prompt(state, names),
            config=types.GenerateContentConfig(system_instruction=self.system_prompt),
        )
        if text := text.strip():
            state.current_narration += "\n\n" + text

    def _log_turn(self, state: GameState, action: dict[str, str] | None, beat: PartyBeat) -> None:
        record = {
            "turn": state.turn,
            "actions": action,
            "ai": beat.model_dump(exclude={"narration"}),
            "party": {c.name: {"conditions": [f"{x.name}({x.severity})" for x in c.conditions], "alive": c.alive} for c in state.party},
            "time": clock_text(state.minutes),
        }
        self._write_log(record)


def format_actions(actions: dict[str, str]) -> str:
    return "\n".join(f"{name}：{action}" for name, action in actions.items())


def prompt_status(c: Character) -> dict:
    """給 AI 看的一位角色的狀態（提示詞「隊伍」裡的一項），格式和單人模式的「遊戲狀態」一致。"""
    key = STATUS_KEYS
    if not c.alive:
        return {key["name"]: c.name, key["state"]: STATUS_EMPTY["dead"]}
    return {key["name"]: c.name, **condition_fields(c), key["inventory"]: c.inventory or [STATUS_EMPTY["inventory"]]}


class PartyCore(StoryCore):
    def __init__(
        self,
        api_key: str,
        players: list[str],
        save_path: Path = PARTY_SAVE_PATH,
        log_path: Path = PARTY_LOG_PATH,
        engine: Engine | None = None,
    ):
        names = [n.strip() for n in players if n.strip()]
        if not MIN_PLAYERS <= len(names) <= MAX_PLAYERS or len(set(names)) != len(names):
            raise ValueError(f"多人模式需要 {MIN_PLAYERS} 到 {MAX_PLAYERS} 位不重複的玩家。")
        super().__init__(api_key, save_path=save_path, log_path=log_path, engine=engine or PartyEngine(api_key=api_key, log_path=log_path))
        self._players = names
        self.pending: dict[str, str] = {}  # 這一回合已經輸入的行動
        self._as: str | None = None  # send_as() 指定的角色

    # ---------- 覆寫 StoryCore 的掛勾 ----------

    def _resumable(self, state: GameState) -> bool:
        return not state.game_over and sorted(c.name for c in state.party) == sorted(self._players)  # 玩家不同就開新局

    def _new_state(self, premise: str) -> GameState:
        self.pending = {}
        return GameState(premise=premise, timed_mode=self.timed, party=[Character(name=n) for n in self._players], **self._genre_fields())

    def _current_choices(self) -> list[str]:
        actor = self._actor()
        return actor.choices if actor else []

    def action_for(self, text: str) -> str | None:
        if text.strip() == "/away" and self._phase == "playing":
            return AWAY_ACTION
        return super().action_for(text)

    def _take_action(self, action: str, timeout: bool) -> Reply:
        """記下這位角色的行動；所有人都行動後才推進一回合。時間到時，還沒行動的人都算遲疑。"""
        if timeout:
            for c in self._waiting():
                self.pending[c.name] = action
        else:
            actor = self._actor()
            self.pending[actor.name] = action
            if self._waiting():
                return self._reply(notice=f"已記下 {actor.name} 的行動。", **self._screen())

        return self._play_turn({c.name: self.pending[c.name] for c in self.state.party if c.name in self.pending})

    def _snapshot(self):
        return {c.name: snapshot(c) for c in self.state.party}

    def _turn_failed(self) -> None:
        # 撤回這回合所有的行動，大家重新選擇。只撤回最後一個人不夠：時間到或替離線的人自動填入的行動失敗時，
        # 會變成每個人都「已行動」卻沒有人能重送，整局卡住
        self.pending = {}

    # ---------- 回覆 ----------

    def _turn_reply(self, before) -> Reply:
        self.pending = {}  # 這一回合已經推進，下一回合從第一位重新輸入
        s = self.state
        changes = []
        if before is not None:
            for c in s.party:
                if groups := change_groups(before[c.name], c):
                    changes.append((c.name, groups))
        return self._reply(narration=s.current_narration, changes=changes, **self._screen())

    def _screen(self) -> dict:
        if self.state is None or self._phase not in ("playing", "ending"):
            return {}
        actor = self._actor() if self._phase == "playing" else None
        return {
            "actor": actor.name if actor else "",
            "choices": list(actor.choices) if actor else [],
            "time_limit": self.state.current_time_limit,
        }

    def _characters(self) -> list[Status]:
        return [reply_status(c) for c in self.state.party]

    # ---------- 線上多人：每位玩家各自送行動 ----------

    @property
    def players(self) -> list[str]:
        """隊伍裡的玩家名字（唯讀），依建立時的順序。"""
        return list(self._players)

    def send_as(self, name: str, text: str) -> Reply:
        """以某位角色的身分送出輸入，不用照隊伍順序。遊戲中以外的階段（前提、確認……）等同 send()。"""
        if self._phase == "playing" and (not text.strip().startswith("/") or text.strip() == "/away"):  # 行動才要檢查
            character = next((c for c in self.state.party if c.name == name), None)
            if character is None or not character.alive:
                return self._reply(notice="你的角色已經倒下了。", **self._screen())
            if name in self.pending:
                return self._reply(notice="你這回合已經行動了，等其他人行動。", **self._screen())
        self._as = name
        try:
            return self.send(text)
        finally:
            self._as = None

    def view(self, name: str, reply: Reply | None = None) -> Reply:
        """某位玩家眼中的畫面：actor 與 choices 換成這位角色的（已經行動或倒下的人沒有選項）。
        給了 reply 就沿用它的其他欄位，否則是目前這一回合的畫面（重新連線時用）。"""
        if reply is None:
            reply = self._reply(**self._screen())
            if self._phase == "playing":
                reply.narration, reply.resumed = self.state.current_narration, True
        if self._phase != "playing":
            mine = replace(reply, actor="", choices=[] if reply.actor else reply.choices)
        else:
            actor = next((c for c in self._waiting() if c.name == name), None)
            mine = replace(reply, actor=name if actor else "", choices=list(actor.choices) if actor else [])
        mine.text = render_text(mine)
        return mine

    def waiting(self) -> list[str]:
        """這回合還沒行動的角色名字。"""
        return [c.name for c in self._waiting()] if self.state and self._phase == "playing" else []

    # ---------- 輪到誰 ----------

    def _waiting(self) -> list[Character]:
        """還活著、這回合還沒輸入行動的角色，依隊伍順序。"""
        return [c for c in self.state.party if c.alive and c.name not in self.pending]

    def _actor(self) -> Character | None:
        waiting = self._waiting() if self.state else []
        if self._as is not None:
            return next((c for c in waiting if c.name == self._as), None)
        return waiting[0] if waiting else None


def reply_status(c: Character) -> Status:
    """給外殼顯示的一位角色的狀態（Reply.characters 裡的一項）。"""
    return Status(conditions=condition_list(c), warning=warning_level(c) if c.alive else "", name=c.name, alive=c.alive)
