"""engine 的遊戲規則：用假的 Gemini 回覆餵給真的 Engine，檢查程式有沒有正確把關。"""

import pytest
from conftest import ARC, InvalidKeyError, beat, cond, make_engine

from story.core.engine import (
    ACT_TURNS,
    DAY,
    DEATH_SCORE,
    HOUR,
    MAX_TIME_LIMIT,
    MIN_TIME_LIMIT,
    TARGET_TURNS,
    body_level,
    body_score,
    clock_text,
    is_key_error,
)
from story.core.models import Condition, GameState, Turn


def play(*beats, timed=False, **kwargs):
    """開場加上數個回合：第一個 beat 是開場，其餘每個 beat 對應一次行動。"""
    engine, gemini = make_engine(*beats, **kwargs)
    state = GameState(premise="測試", timed_mode=timed)
    engine.start(state)
    for _ in beats[1:]:
        engine.act(state, "行動")
    return state, engine, gemini


def conditions(state):
    return {c.name: c.severity for c in state.conditions}


# ---------- 狀態：新增、惡化、好轉、移除 ----------


def test_new_conditions_are_added_with_kind():
    state, *_ = play(beat(conditions_changed=[cond("擦傷", "輕"), cond("恐懼", "中", "精神")]))
    assert conditions(state) == {"擦傷": "輕", "恐懼": "中"}
    assert {c.name: c.kind for c in state.conditions} == {"擦傷": "身體", "恐懼": "精神"}


def test_worsening_is_unlimited():
    state, *_ = play(beat(conditions_changed=[cond("刀傷", "輕")]), beat(conditions_changed=[cond("刀傷", "重")]))
    assert conditions(state) == {"刀傷": "重"}


def test_improving_is_limited_to_one_level_per_turn():
    state, *_ = play(beat(conditions_changed=[cond("刀傷", "重")]), beat(conditions_changed=[cond("刀傷", "輕")]))
    assert conditions(state) == {"刀傷": "中"}


def test_removing_serious_body_condition_only_downgrades():
    state, *_ = play(
        beat(conditions_changed=[cond("骨折", "重")]),
        beat(conditions_removed=["骨折"]),
        beat(conditions_removed=["骨折"]),
        beat(conditions_removed=["骨折"]),
    )
    assert conditions(state) == {}  # 重 → 中 → 輕 → 消失，要三回合


def test_mind_conditions_can_be_removed_directly():
    state, *_ = play(beat(conditions_changed=[cond("極度恐懼", "重", "精神")]), beat(conditions_removed=["極度恐懼"]))
    assert conditions(state) == {}


def test_removing_unknown_condition_is_ignored():
    state, *_ = play(beat(conditions_changed=[cond("擦傷", "輕")]), beat(conditions_removed=["不存在"]))
    assert conditions(state) == {"擦傷": "輕"}


def test_long_condition_names_are_trimmed():
    state, *_ = play(beat(conditions_changed=[cond("這是一個非常非常長的狀態描述句子", "輕")]))
    assert len(state.conditions[0].name) <= 12


def test_ai_can_correct_kind_of_old_condition():
    engine, _ = make_engine(beat(conditions_changed=[cond("驚魂未定", "中", "精神")]))
    state = GameState(premise="舊存檔", turn=5, minutes=0, conditions=[Condition(name="驚魂未定", severity="中")])
    assert state.conditions[0].kind == "身體"  # 舊存檔一律先當成身體
    engine.act(state, "a")
    assert state.conditions[0].kind == "精神"


# ---------- 整體狀態與死亡 ----------


@pytest.mark.parametrize(
    "conds, level",
    [
        ([], "良好"),
        ([("疲憊", "輕")], "輕傷"),
        ([("扭傷", "中"), ("疲憊", "輕")], "受傷"),
        ([("扭傷", "中"), ("割傷", "中")], "重傷"),
        ([("骨折", "重")], "重傷"),
        ([("骨折", "重"), ("扭傷", "中")], "瀕死"),
        ([("骨折", "重"), ("失血", "重")], "死亡"),
    ],
)
def test_body_level(conds, level):
    state = GameState(premise="x", conditions=[Condition(name=n, severity=v) for n, v in conds])
    assert body_level(state) == level


def test_mind_conditions_do_not_count_toward_death():
    state = GameState(premise="x", conditions=[
        Condition(name="恐懼", kind="精神", severity="重"),
        Condition(name="絕望", kind="精神", severity="重"),
    ])
    assert body_score(state) == 0
    assert body_level(state) == "良好"


def test_lethal_injury_ends_game_and_asks_ai_for_death_scene():
    engine, gemini = make_engine(
        beat(conditions_changed=[cond("骨折", "重")]),
        beat(narration="你咬牙撐著。", conditions_changed=[cond("失血", "重")]),
        beat(narration="你倒下了。", game_over=True),  # 程式判定死亡後，要求 AI 補寫的結局
    )
    state = GameState(premise="x")
    engine.start(state)
    engine.act(state, "硬闖")
    assert body_score(state) >= DEATH_SCORE
    assert state.game_over
    assert state.current_choices == []
    assert "你咬牙撐著。" in state.current_narration and "你倒下了。" in state.current_narration
    assert "傷勢已經致命" in gemini.prompts[-1]


# ---------- 遊戲內時間與痊癒 ----------


def test_opening_sets_clock_from_time_of_day():
    state, *_ = play(beat(start_time_of_day="清晨"))
    assert state.minutes == 6 * HOUR
    assert clock_text(state.minutes) == "第 1 天 清晨（06:00）"


def test_time_passes_by_category():
    state, *_ = play(beat(), beat(time_passed="一夜"), beat(time_passed="數天"))
    assert state.minutes == 18 * HOUR + 8 * HOUR + 3 * DAY


def test_old_save_without_clock_lets_ai_choose_time():
    engine, gemini = make_engine(beat(start_time_of_day="夜晚"))
    state = GameState(premise="舊存檔", turn=30)
    engine.act(state, "a")
    assert '"時間":"尚未確定"' in gemini.prompts[-1]
    assert state.minutes == 20 * HOUR


def test_light_injury_heals_after_six_hours():
    state, *_ = play(beat(conditions_changed=[cond("擦傷", "輕")]), beat(time_passed="數小時"))
    assert "擦傷" in conditions(state)
    state2, *_ = play(beat(conditions_changed=[cond("擦傷", "輕")]), beat(time_passed="數小時"), beat(time_passed="數小時"))
    assert "擦傷" not in conditions(state2)


def test_medium_injury_can_fully_heal_over_days():
    state, *_ = play(beat(conditions_changed=[cond("扭傷", "中")]), beat(time_passed="數天"))
    assert conditions(state) == {}  # 2 天降為輕，多出來的 1 天讓輕傷痊癒


def test_serious_body_injury_does_not_heal_by_time():
    state, *_ = play(beat(conditions_changed=[cond("骨折", "重")]), beat(time_passed="數天"), beat(time_passed="數天"))
    assert conditions(state) == {"骨折": "重"}


def test_serious_mind_condition_fades_over_days():
    state, *_ = play(beat(conditions_changed=[cond("恐懼", "重", "精神")]), beat(time_passed="一夜"))
    assert conditions(state) == {"恐懼": "重"}  # 重度要 2 天才降一級
    state2, *_ = play(beat(conditions_changed=[cond("恐懼", "重", "精神")]), beat(time_passed="數天"))
    assert conditions(state2) == {}  # 72 小時：重 → 中（48h）→ 輕（12h）→ 消失（2h）


# ---------- 限時模式 ----------


@pytest.mark.parametrize("given, expected", [(0, 0), (3, MIN_TIME_LIMIT), (20, 20), (999, MAX_TIME_LIMIT)])
def test_time_limit_is_clamped_in_timed_mode(given, expected):
    state, *_ = play(beat(time_limit=given), timed=True)
    assert state.current_time_limit == expected


def test_time_limit_is_ignored_in_normal_mode():
    state, *_ = play(beat(time_limit=20), timed=False)
    assert state.current_time_limit == 0


def test_no_time_limit_when_game_over():
    state, *_ = play(beat(time_limit=20, game_over=True), timed=True)
    assert state.current_time_limit == 0


# ---------- 背包、事實、事件 ----------


def test_cannot_lose_items_you_do_not_have():
    state, *_ = play(beat(items_gained=["油燈"]), beat(items_lost=["寶劍", "油燈"]))
    assert state.inventory == []


def test_flags_are_not_duplicated_and_empty_events_are_skipped():
    state, *_ = play(beat(flags_set=["與守門人結仇"], key_event=""), beat(flags_set=["與守門人結仇"], key_event="找到地下室"))
    assert state.flags == ["與守門人結仇"]
    assert state.key_events == ["找到地下室"]


def test_at_most_four_choices():
    state, *_ = play(beat(choices=["1", "2", "3", "4", "5", "6"]))
    assert len(state.current_choices) == 4


# ---------- 故事大綱與節奏 ----------


def test_start_plans_arc_before_opening():
    state, _, gemini = play(beat())
    assert state.arc == ARC
    assert "規劃大綱" in gemini.prompts[0]
    assert "故事進度（玩家看不到）" in gemini.prompts[1]


def test_milestone_advances_act():
    state, *_ = play(beat(), beat(milestone_reached=True))
    assert (state.act, state.act_turns) == (1, 0)


def test_final_act_does_not_advance_further():
    engine, _ = make_engine(beat(milestone_reached=True))
    state = GameState(premise="x", turn=5, minutes=0, arc=ARC, act=3)
    engine.act(state, "a")
    assert state.act == 3


def test_pacing_reminder_when_act_drags_on():
    engine, gemini = make_engine(beat())
    state = GameState(premise="x", turn=5, minutes=0, arc=ARC, act=0, act_turns=ACT_TURNS)
    engine.act(state, "a")
    assert "節奏提醒" in gemini.prompts[-1]


def test_wrap_up_reminder_after_target_length():
    engine, gemini = make_engine(beat())
    state = GameState(premise="x", turn=TARGET_TURNS, minutes=0, arc=ARC, act=3)
    engine.act(state, "a")
    assert "超過預定的" in gemini.prompts[-1]


def test_old_save_gets_arc_and_jumps_to_matching_act():
    engine, gemini = make_engine(beat())
    state = GameState(premise="舊存檔", turn=109, minutes=0, summary="主角把證據交給媒體")
    engine.act(state, "a")
    assert state.arc == ARC and state.act == 3
    assert "已經進行了 109 回合" in gemini.prompts[0]


# ---------- 提示詞與記憶 ----------


def test_prompt_includes_unsummarized_turns_and_no_duplicate_action():
    engine, gemini = make_engine(beat())
    state = GameState(
        premise="x", turn=10, minutes=0, current_narration="上一段劇情",
        unsummarized=[Turn(narration="待壓縮的回合", action="舊行動")],
        recent=[Turn(narration="最近的回合", action="近行動")],
    )
    engine.act(state, "推開門")
    prompt = gemini.prompts[-1]
    assert "待壓縮的回合" in prompt and "最近的回合" in prompt
    assert prompt.count("推開門") == 1


def test_compaction_folds_old_events_and_flags_into_summary():
    engine, gemini = make_engine(summary="壓縮後的摘要")
    state = GameState(
        premise="x",
        unsummarized=[Turn(narration=f"第{i}回合", action="a") for i in range(4)],
        key_events=[f"事件{i}" for i in range(16)],
        flags=[f"事實{i}" for i in range(30)],
    )
    assert engine.needs_compaction(state)
    engine.compact_memory(state)
    assert state.summary == "壓縮後的摘要"
    assert state.unsummarized == []
    assert state.key_events == [f"事件{i}" for i in range(10, 16)]
    assert state.flags == [f"事實{i}" for i in range(18, 30)]
    assert "事件0" in gemini.prompts[-1] and "事件15" not in gemini.prompts[-1]


def test_turns_beyond_recent_window_wait_for_compaction():
    state, *_ = play(*[beat() for _ in range(7)])
    assert len(state.recent) == 4 and len(state.unsummarized) == 2


def test_turn_log_is_written(isolated):
    engine, _ = make_engine(beat(), beat(conditions_changed=[cond("擦傷", "輕")]))
    engine.log_path = isolated / "log.jsonl"
    state = GameState(premise="x")
    engine.start(state)
    engine.act(state, "a")
    lines = engine.log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and "擦傷(輕)" in lines[-1]


def test_is_key_error():
    assert is_key_error(InvalidKeyError())
    assert not is_key_error(RuntimeError("網路斷線"))
