"""多人模式：疊在單人模式上。

PartyEngine 繼承單人的 Engine，PartyCore 繼承單人的 StoryCore，只覆寫「主角變成一支隊伍」不一樣的地方；
規則（傷勢、痊癒、時間、背包、限時）、記憶、大綱與節奏、存檔、文字指令都直接沿用單人模式。

介面和單人一樣是 send(文字) → Reply。差別在遊戲中：
- reply.actor 是現在輪到誰輸入；送進來的文字就算是那位角色的行動，reply.choices 是那位角色的選項
- 所有還活著的角色都輸入後，才呼叫 AI 寫這一回合
- reply.party 是每位角色的狀態，reply.party_changes 是每位角色這回合的變化
- /timeout 會把還沒行動的人都當作「時間到」，直接推進這一回合

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
    Engine,
    advance_clock,
    apply_condition_changes,
    apply_items,
    apply_story_progress,
    body_conditions,
    body_level,
    body_score,
    clamp_time_limit,
    clock_text,
    ending_allowed,
    mind_conditions,
)
from story.core.models import Character, GameState, PartyBeat
from story.core.records import change_groups, snapshot
from story.core.session import Reply, Status, StoryCore, render_text

# 多人模式的 system prompt：規則和單人相同，只是主角變成一支隊伍
PARTY_SYSTEM_PROMPT = """你是一個多人互動式文字冒險遊戲的敘事者。每位玩家扮演隊伍中的一位角色。

規則：
- 用繁體中文敘述，文風生動但精簡。提到角色時用名字，不要用「你」；也不要用「他」「她」稱呼角色，直接用名字。
- 每回合會收到每位角色各自的行動。把所有人的行動編織成一段連貫的劇情，交代每個人行動的結果，好壞都可能；角色之間可以互相幫助、牽制或產生衝突。
- 「焦點」區塊指定的角色本回合要多一些描寫與抉擇的分量，但其他角色也要有交代。
- 「隊伍」區塊是唯一的事實來源。不要讓角色使用不在自己背包裡的物品；物品屬於個人，交給別人時用 items_lost／items_gained 分別記錄。
- 尊重已確立的劇情事實與重大事件，不要自相矛盾。
- 為每位還活著的角色提供 2-4 個彼此有明顯差異的選項；可以有一個朝「故事進度」中目前的里程碑前進，但不要每回合都急著達成，先讓劇情鋪陳開來。不要每次都只有逃跑、躲藏、戰鬥。已死亡的角色不要給選項。
- 依照「故事進度」的大綱推進劇情。節奏要張弛有度：危機過後給角色喘息、整理線索、互相交談的空間，並帶出新的發展；同一類場景（追逐、躲藏、戰鬥）不要連續超過三回合。
- 角色沒有生命值，而是用狀態描述，並標上程度（輕、中、重）與類別：身體（受傷、疲勞、中毒、疾病）或精神（恐懼、驚慌、絕望、憤怒）。痊癒或消失時移除；惡化或好轉時用相同名稱回報新的程度。
  已有的狀態一律沿用「隊伍」裡的原名，不要改名或換個說法重新新增。名稱只描述是什麼狀態，不要包含程度詞，程度只用 severity 表示。狀態要影響後續劇情與行動的成敗。
  精神狀態不會致命，但要影響角色的判斷與表現；危機解除後可以直接移除。
- 角色會不會因傷勢而死，由程式依傷勢總分判定。不要自行讓角色因傷而死；傷勢接近致命時，在敘述中呈現危險。game_over 只用於劇情自然走到結局。
- 傷勢會隨時間自然好轉：輕微的幾小時後痊癒，中度的要休養幾天；重傷不會自己好，只有劇情中真的得到治療時，才能用相同名稱回報降一級。
- 每回合用 time_passed 標出這段劇情經過了多久，並讓敘述符合「隊伍」裡的時間（日夜、天色）。
- 狀態變化要與敘述一致，並記在對應角色的 character_updates 裡。key_event 只記真正改變故事走向的大事，大多數回合應該留空。flags_set 只記之後還會用到的長期事實。
- 若「模式」區塊說明是限時模式：當情勢緊迫時設定 time_limit，越危急越短；平靜的場景設 0。非限時模式一律設 0。
- 若某位角色的行動是「（時間到……）」，代表那位玩家沒能及時反應，要描述猶豫帶來的後果。"""


PARTY_SAVE_PATH = Path("party_save.json")
PARTY_LOG_PATH = Path("party_log.jsonl")
MAX_PLAYERS = 4


class PartyEngine(Engine):
    """多人模式的 engine：提示詞的共用部分、呼叫 AI、尾聲、大綱都沿用 Engine，只覆寫隊伍相關的掛勾。"""

    system_prompt = PARTY_SYSTEM_PROMPT
    beat_schema = PartyBeat
    turn_label = "行動"
    epilogue_look_back = "回顧每位角色做過的關鍵抉擇與付出的代價；死去的角色，寫出他們留下的痕跡。"

    # ---------- 提示詞的掛勾 ----------

    def _cast_section(self, state: GameState) -> str:
        return f"# 主角（多人，各由一位玩家扮演）\n{'、'.join(c.name for c in state.party)}\n"

    def _action_text(self, action: dict[str, str]) -> str:
        return format_actions(action)

    def _status_section(self, state: GameState) -> str:
        party = {
            "回合": state.turn,
            "時間": "尚未確定" if state.minutes is None else clock_text(state.minutes),
            "已確立的事實": state.flags or ["（無）"],
            "角色": [character_status(c) for c in state.party],
        }
        return "# 隊伍\n" + json.dumps(party, ensure_ascii=False, separators=(",", ":"))

    def _instruction_sections(self, state: GameState, action: dict[str, str] | None) -> list[str]:
        sections = []
        alive = [c.name for c in state.party if c.alive]
        if alive:  # 焦點由程式輪流指定，避免 AI 老是讓同一個人當主角
            sections.append(f"# 焦點\n本回合多給「{alive[state.turn % len(alive)]}」一些描寫與抉擇的分量。")
        if action is None:
            sections.append("# 指示\n這是故事的開場。介紹場景與每位角色的處境，並給每位角色各自的第一組選項。")
        else:
            sections.append(f"# 本回合每位角色的行動\n{format_actions(action)}\n\n# 指示\n敘述這些行動的結果並推進劇情。")
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

    def _write_deaths(self, state: GameState, names: list[str]) -> None:
        """程式判定有角色傷重死亡：請 AI 接著寫一小段倒下的場景。"""
        who = "、".join(names)
        prompt = self._build_prompt(state, None).rsplit("# 焦點", 1)[0] + (
            f"# 剛才發生的事\n{state.current_narration}\n\n"
            f"# 指示\n{who} 的傷勢已經致命。接續上面的敘述，寫一小段（100 字以內）{who} 傷重倒下的場景，只輸出敘述本身。"
        )
        response = self.client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=self.system_prompt),
        )
        if text := (response.text or "").strip():
            state.current_narration += "\n\n" + text

    def _log_turn(self, state: GameState, action: dict[str, str] | None, beat: PartyBeat) -> None:
        record = {
            "turn": state.turn,
            "actions": action,
            "ai": beat.model_dump(exclude={"narration"}),
            "party": {c.name: {"conditions": [f"{x.name}({x.severity})" for x in c.conditions], "alive": c.alive} for c in state.party},
            "time": clock_text(state.minutes),
        }
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # 紀錄寫不進去不影響遊戲


def format_actions(actions: dict[str, str]) -> str:
    return "\n".join(f"{name}：{action}" for name, action in actions.items())


def character_status(c: Character) -> dict:
    """提示詞裡一位角色的狀態，格式和單人模式的「遊戲狀態」一致。"""
    if not c.alive:
        return {"名字": c.name, "狀態": "已死亡"}
    return {
        "名字": c.name,
        "身體狀況": [f"{x.name}（{x.severity}）" for x in body_conditions(c)] or ["良好"],
        "精神狀況": [f"{x.name}（{x.severity}）" for x in mind_conditions(c)] or ["平穩"],
        "整體": f"{body_level(c)}（身體傷勢 {body_score(c)}/{DEATH_SCORE}，達 {DEATH_SCORE} 即死亡；輕=1 中=2 重=4）",
        "背包": c.inventory or ["（空）"],
    }


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
        if not 2 <= len(names) <= MAX_PLAYERS or len(set(names)) != len(names):
            raise ValueError(f"多人模式需要 2 到 {MAX_PLAYERS} 位不重複的玩家。")
        super().__init__(api_key, save_path=save_path, log_path=log_path, engine=engine or PartyEngine(api_key=api_key, log_path=log_path))
        self._players = names
        self.pending: dict[str, str] = {}  # 這一回合已經輸入的行動
        self._last_actor: str | None = None  # 最後輸入行動的人（推進失敗時讓他重送）
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

    def _take_action(self, action: str, timeout: bool) -> Reply:
        """記下這位角色的行動；所有人都行動後才推進一回合。時間到時，還沒行動的人都算遲疑。"""
        self._last_actor = None
        if timeout:
            for c in self._waiting():
                self.pending[c.name] = action
        else:
            actor = self._actor()
            self.pending[actor.name], self._last_actor = action, actor.name
            if self._waiting():  # 還有人沒輸入：換下一位
                return self._reply(notice=f"已記下 {actor.name} 的行動。", **self._screen())

        return self._play_turn({c.name: self.pending[c.name] for c in self.state.party if c.name in self.pending})

    def _snapshot(self):
        return {c.name: snapshot(c) for c in self.state.party}

    def _turn_failed(self) -> None:
        if self._last_actor:
            self.pending.pop(self._last_actor, None)  # 讓最後輸入的人重送同一句就能重試，其他人的行動保留

    # ---------- 回覆 ----------

    def _turn_reply(self, before) -> Reply:
        self.pending = {}  # 這一回合已經推進，下一回合從第一位重新輸入
        s = self.state
        party_changes = []
        if before is not None:
            for c in s.party:
                if groups := change_groups(before[c.name], c):
                    party_changes.append((c.name, groups))
        return self._reply(narration=s.current_narration, party_changes=party_changes, **self._screen())

    def _screen(self) -> dict:
        if self.state is None or self._phase not in ("playing", "ending"):
            return {}
        actor = self._actor() if self._phase == "playing" else None
        return {
            "actor": actor.name if actor else "",
            "choices": list(actor.choices) if actor else [],
            "time_limit": self.state.current_time_limit,
        }

    def _status(self) -> Status | None:
        return None  # 多人模式的狀態放在 reply.party

    def _reply(self, **fields) -> Reply:
        if self.state is not None and self._phase != "ask_premise":
            fields.setdefault("party", [_character_status(self.state.turn, c) for c in self.state.party])
        return super()._reply(**fields)

    # ---------- 線上多人：每位玩家各自送行動 ----------

    @property
    def players(self) -> list[str]:
        """隊伍裡的玩家名字（唯讀），依建立時的順序。"""
        return list(self._players)

    def send_as(self, name: str, text: str) -> Reply:
        """以某位角色的身分送出輸入，不用照隊伍順序。遊戲中以外的階段（前提、確認……）等同 send()。"""
        if self._phase == "playing" and not text.strip().startswith("/"):
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


def _character_status(turn: int, c: Character) -> Status:
    return Status(
        turn=turn,
        level=body_level(c) if c.alive else "死亡",
        body=[(x.name, x.severity) for x in body_conditions(c)],
        mind=[(x.name, x.severity) for x in mind_conditions(c)],
        inventory=list(c.inventory),
        name=c.name,
        alive=c.alive,
    )
