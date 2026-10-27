"""組提示詞：把遊戲狀態和 prompts/語言/ 的文字組成每一種 AI 呼叫的提示詞。不呼叫 AI，just prompts 用它預覽。

順序：不常變的在前、會變的在後，讓 Gemini 的自動快取（只認開頭完全相同的部分）命中得越多越好：
前提、模式、題材指引 → 摘要（很少變）→ 劇情紀錄（只往後追加）→ 重大事件、故事進度、遊戲狀態（隨劇情改變）→ 這回合的指示。
"""

import json
import random

from story.core import prompts
from story.games.adventure.text import TEXT
from story.games.adventure.genres import Genre
from story.games.adventure.models import Character, Condition, GameState, StoryArc, Turn, word
from story.games.adventure.rules import (
    ACT_TURNS,
    DAY,
    DEATH_SCORE,
    HOUR,
    MAX_TIME_LIMIT,
    MIN_ACT_TURNS,
    MIN_ENDING_TURN,
    MIN_TIME_LIMIT,
    TARGET_TURNS,
    body_conditions,
    body_level,
    body_score,
    ending_allowed,
    mind_conditions,
    time_of_day,
    to_compact,
)

# 給 AI 的文字，都在 prompts/語言/ 裡同名的檔案
SYSTEM_PROMPT = TEXT.load("system")
CONTEXT = TEXT.sections("context")
TURN = TEXT.sections("turn")
PROGRESS = TEXT.sections("progress")
PLAN = TEXT.sections("plan")
PREMISE = TEXT.sections("premise")
MEMORY = TEXT.sections("memory")
STATUS_KEYS = prompts.table(CONTEXT["status_keys"])  # 遊戲狀態 JSON 的欄位名稱：{代號: 給 AI 看的名稱}
STATUS_EMPTY = prompts.table(CONTEXT["status_empty"])  # 遊戲狀態裡沒有東西時顯示的字
TIMEOUT_ACTION = TURN["timeout_action"]  # 限時模式時間到時，代替玩家的行動寫進劇情紀錄
AWAY_ACTION = TURN["away_action"]  # 暫時離開（網頁版斷線時由房間送出），代替玩家的行動寫進劇情紀錄
TWIST_IDEAS = 3  # 規劃大綱時從題材包的 twists.md 隨機抽幾則轉折靈感
# 「幫我想」由程式隨機指定題材與情境，AI 才不會每次都想出相似的故事
PREMISE_GENRES = prompts.items(PREMISE["genres"])
PREMISE_SETTINGS = prompts.items(PREMISE["settings"])


# ---------- 遊戲狀態裡的一小段 ----------


def clock_text(minutes: int) -> str:
    """例如「第 2 天 傍晚（18:30）」。只放進給 AI 的提示，不顯示給玩家。"""
    day, hour, minute = minutes // DAY + 1, minutes % DAY // HOUR, minutes % HOUR
    return CONTEXT["clock"].format(day=day, period=word("time_of_day", time_of_day(minutes)), hour=hour, minute=minute)


def time_text(state: GameState) -> str:
    return STATUS_EMPTY["time_unknown"] if state.minutes is None else clock_text(state.minutes)


def history_entry(turn: Turn) -> str:
    """劇情紀錄裡的一回合：那時的劇情，與玩家們看完後做的事。"""
    return CONTEXT["history_entry"].format(narration=turn.narration, label=CONTEXT["turn_label"], action=turn.action)


def format_actions(actions: dict[str, str]) -> str:
    """每位角色這回合的行動，一人一行。也是劇情紀錄裡記下的行動。"""
    return "\n".join(TURN["action_entry"].format(name=name, action=action) for name, action in actions.items())


def names_text(names: list[str]) -> str:
    return TURN["names_sep"].join(names)


def character_status(c: Character) -> dict:
    """遊戲狀態裡的一位角色：身體、精神、整體（離死亡還有多遠）、背包。"""
    key, empty = STATUS_KEYS, STATUS_EMPTY
    if not c.alive:
        return {key["name"]: c.name, key["state"]: empty["dead"]}

    def listed(conditions: list[Condition], empty_key: str) -> list[str]:
        return [CONTEXT["condition"].format(name=x.name, severity=word("severity", x.severity)) for x in conditions] or [empty[empty_key]]

    overall = CONTEXT["overall"].format(level=word("level", body_level(c)), score=body_score(c), death=DEATH_SCORE)
    return {
        key["name"]: c.name,
        key["body"]: listed(body_conditions(c), "body"),
        key["mind"]: listed(mind_conditions(c), "mind"),
        key["overall"]: overall,
        key["inventory"]: c.inventory or [empty["inventory"]],
    }


# ---------- 每一種 AI 呼叫的提示詞 ----------


class PromptBuilder:
    def __init__(self, genres: dict[str, Genre]):
        self.genres = genres  # 題材包（genres.py）

    def turn(self, state: GameState, actions: dict[str, str] | None) -> str:
        """這一回合：故事內容加上這回合的指示（actions 是 None 時是開場）。每次呼叫都是無狀態的，記憶全靠這裡。"""
        return "\n\n".join(self.context(state, actions is not None) + self.instructions(state, actions))

    def death(self, state: GameState, names: list[str]) -> str:
        """程式判定有角色傷重死亡：請 AI 接著寫一小段倒下的場景。"""
        return "\n\n".join(self.context(state) + [TURN["death"].format(narration=state.current_narration, who=names_text(names))])

    def epilogue(self, state: GameState) -> str:
        return "\n\n".join(self.context(state) + [TURN["epilogue"].format(narration=state.current_narration)])

    def pick_genre(self, state: GameState) -> str:
        catalog = "\n".join(PLAN["catalog_entry"].format(name=g.name, description=g.description) for g in self.genres.values())
        return PLAN["pick_genre"].format(premise=state.premise, catalog=catalog)

    def arc(self, state: GameState) -> str:
        if state.turn == 0:
            situation = PLAN["arc_new"]
        else:  # 開場前規劃失敗，之後補一份：接續目前的劇情
            situation = PLAN["arc_resume"].format(turn=state.turn, summary=state.summary or PLAN["summary_none"], events="\n".join(state.key_events))
        cast = TURN["cast"].format(names=names_text(state.names)) + "\n"
        prompt = PLAN["arc"].format(target_turns=TARGET_TURNS, premise=state.premise, cast=cast, situation=situation)
        if genre := self.genres.get(state.genre):  # 大綱要符合題材
            prompt += "\n\n" + PLAN["genre"].format(name=genre.name, guide=genre.guide)
            if genre.names:
                prompt += "\n\n" + PLAN["names"].format(names=genre.names)
            if genre.twists:  # 每局隨機抽幾則，同一個題材玩很多次也不會總是同一招
                ideas = "\n".join(f"- {t}" for t in random.sample(genre.twists, min(TWIST_IDEAS, len(genre.twists))))
                prompt += "\n\n" + PLAN["twist_ideas"].format(ideas=ideas)
        return prompt

    def premise(self, avoid: str = "", genre: str = "") -> str:
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

    def compaction(self, state: GameState) -> str:
        """劇情紀錄太長時：把最舊的回合、較舊的重大事件與事實併入長期摘要。"""
        turns, old_events, old_flags = to_compact(state)
        old = old_events + old_flags
        parts = [MEMORY["summary"].format(summary=state.summary or MEMORY["summary_none"])]
        if turns:
            parts.append(MEMORY["turns"].format(entries="\n\n".join(history_entry(t) for t in turns)))
        if old:
            parts.append(MEMORY["old_facts"].format(items="\n".join(f"- {x}" for x in old)))
        parts.append(MEMORY["compact"])
        return "\n\n".join(parts)

    # ---------- 組成的零件 ----------

    def context(self, state: GameState, acting: bool = False) -> list[str]:
        """故事內容（指示以外的部分）。尾聲、傷重倒下的場景也用它，再接上各自的指示。
        acting：這回合有玩家的行動，最後一回合的行動會在指示裡另外列出，劇情紀錄裡就不重複。"""
        mode = TURN["mode_timed"].format(min=MIN_TIME_LIMIT, max=MAX_TIME_LIMIT) if state.timed_mode else TURN["mode_normal"]
        sections = [CONTEXT["premise"].format(premise=state.premise), CONTEXT["mode"].format(mode=mode)]
        if state.solo:  # 系統提示詞也有說，但 AI 看到名字常會改用第三人稱，在這裡再提醒一次
            sections.append(TURN["second_person"].format(name=state.characters[0].name))
        genre = self.genres.get(state.genre)
        if genre:
            sections.append(CONTEXT["genre_guide"].format(name=genre.name, guide=genre.guide))
        if state.summary:
            sections.append(CONTEXT["summary"].format(summary=state.summary))
        if turns := state.recent:
            entries = [history_entry(t) for t in turns]
            if acting:
                entries[-1] = CONTEXT["history_last"].format(narration=turns[-1].narration)
            sections.append(CONTEXT["history"].format(entries="\n\n".join(entries)))
        if state.key_events:
            sections.append(CONTEXT["key_events"].format(events="\n".join(f"- {e}" for e in state.key_events)))
        if progress := self.progress(state):
            sections.append(progress)
        if genre and genre.names and not acting and state.turn == 0:  # 開場要介紹人物與地點：附上命名素材
            sections.append(PLAN["names"].format(names=genre.names))
        sections.append(self.status(state))
        return sections

    def status(self, state: GameState) -> str:
        key = STATUS_KEYS
        status = {
            key["turn"]: state.turn,
            key["time"]: time_text(state),
            key["flags"]: state.flags or [STATUS_EMPTY["flags"]],
            key["characters"]: [character_status(c) for c in state.characters],
        }
        return CONTEXT["status"].format(json=json.dumps(status, ensure_ascii=False, separators=(",", ":")))

    def instructions(self, state: GameState, actions: dict[str, str] | None) -> list[str]:
        sections = []
        alive = [c.name for c in state.characters if c.alive]
        if len(alive) > 1:  # 焦點由程式輪流指定，避免 AI 老是讓同一個人當主角
            sections.append(TURN["focus"].format(name=alive[state.turn % len(alive)]))
        sections.append(TURN["opening"] if actions is None else TURN["action"].format(actions=format_actions(actions)))
        return sections

    def progress(self, state: GameState) -> str:
        """隱藏的故事大綱與節奏提醒。只給 AI 看。"""
        arc = state.arc
        if arc is None:
            return ""
        lines = [PROGRESS["goal"].format(goal=arc.goal)]
        for i, act in enumerate(arc.acts):
            mark = PROGRESS["act_current"] if i == state.act else (PROGRESS["act_done"] if i < state.act else "")
            lines.append(PROGRESS["act"].format(number=i + 1, name=act.name, milestone=act.milestone, mark=mark))
        lines.append(PROGRESS["endings"].format(endings=PROGRESS["endings_sep"].join(arc.endings)))
        if arc.twist:
            lines += self.twist_lines(arc, state.act)

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
    def twist_lines(arc: StoryArc, act: int) -> list[str]:
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
