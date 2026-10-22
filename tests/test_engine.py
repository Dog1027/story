"""engine 的遊戲規則：用假的 Gemini 回覆餵給真的 Engine，檢查程式有沒有正確把關。"""

import pytest
from conftest import ARC, InvalidKeyError, beat, cond, make_engine

from story.core.engine import (
    ACT_TURNS,
    DAY,
    DEATH_SCORE,
    HOUR,
    MAX_TIME_LIMIT,
    MIN_ACT_TURNS,
    MIN_ENDING_TURN,
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
    engine, _ = make_engine(beat(time_limit=20, game_over=True))
    state = GameState(premise="x", turn=TARGET_TURNS, minutes=0, arc=ARC, act=3, timed_mode=True)
    engine.act(state, "a")
    assert state.game_over and state.current_time_limit == 0


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
    engine, _ = make_engine(beat(milestone_reached=True))
    state = GameState(premise="x", turn=8, minutes=0, arc=ARC, act=0, act_turns=MIN_ACT_TURNS - 1)
    engine.act(state, "a")
    assert (state.act, state.act_turns) == (1, 0)


def test_milestone_too_early_in_an_act_is_ignored():
    """這一幕還沒演滿 MIN_ACT_TURNS 回合：AI 說達成也不推進，提示詞也會叫它先鋪陳。"""
    engine, gemini = make_engine(beat(milestone_reached=True))
    state = GameState(premise="x", turn=2, minutes=0, arc=ARC, act=0, act_turns=1)
    engine.act(state, "a")
    assert (state.act, state.act_turns) == (0, 2)
    assert "這回合不要達成里程碑" in gemini.prompts[-1]


def test_early_ending_is_rewritten_then_ignored():
    """太早寫出結局：先請 AI 重寫一次；重寫後還是結局就忽略，故事繼續。"""
    engine, gemini = make_engine(beat(game_over=True, narration="全劇終"), beat(narration="新的發展", choices=["追上去"]))
    state = GameState(premise="x", turn=5, minutes=0, arc=ARC, act=1)
    engine.act(state, "a")
    assert not state.game_over and state.current_narration == "新的發展"
    assert "結局限制" in gemini.prompts[0] and "太早結束了故事" in gemini.prompts[1]

    engine, _ = make_engine(beat(game_over=True), beat(game_over=True, choices=["繼續"]))
    state = GameState(premise="x", turn=5, minutes=0, arc=ARC, act=1)
    engine.act(state, "a")
    assert not state.game_over and state.current_choices == ["繼續"]


def test_ending_needs_the_final_act_and_enough_turns():
    for turn, act, allowed in ((MIN_ENDING_TURN - 1, 3, True), (MIN_ENDING_TURN - 2, 3, False), (25, 2, False), (TARGET_TURNS - 1, 1, True)):
        engine, gemini = make_engine(beat(game_over=True), beat(game_over=True))
        state = GameState(premise="x", turn=turn, minutes=0, arc=ARC, act=act)
        engine.act(state, "a")
        assert state.game_over is allowed, (turn, act)
        assert len(gemini.prompts) == (1 if allowed else 2)  # 不能結束時會請 AI 重寫一次


def test_death_ends_the_story_at_any_time():
    """因傷死亡由程式判定，不受最早結局回合的限制。"""
    lethal = [cond("失血", "重"), cond("骨折", "重")]
    engine, _ = make_engine(beat(conditions_changed=lethal), beat(narration="主角倒下了。", game_over=True))
    state = GameState(premise="x", turn=3, minutes=0, arc=ARC, act=0)
    engine.act(state, "a")
    assert state.game_over


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


def test_twist_is_foreshadowed_then_revealed_in_the_third_act():
    """前兩幕只給真相與伏筆、叫 AI 不要說破；第三幕要揭露；最後一幕當作已知。"""
    prompts = {}
    for act in range(4):
        engine, gemini = make_engine(beat())
        engine.act(GameState(premise="x", turn=8, minutes=0, arc=ARC, act=act), "a")
        prompts[act] = gemini.prompts[-1]
    for act in (0, 1):
        assert "在那之前不要說破" in prompts[act] and "- 鑰匙上刻著你的生日" in prompts[act]
    assert "本幕要揭露隱藏的真相：鑰匙的主人就是失憶前的你" in prompts[2] and "呼應之前埋下的伏筆" in prompts[2]
    assert "已揭露的真相" in prompts[3] and "伏筆" not in prompts[3]


def test_old_save_arc_without_twist_still_loads():
    old = ARC.model_dump(exclude={"twist", "clues"}) | {"genre": "武俠"}  # 舊版大綱還有 genre 欄位
    state = GameState.model_validate({"premise": "x", "arc": old})
    assert state.arc.twist == "" and state.arc.clues == []
    engine, gemini = make_engine(beat())
    engine.act(state, "a")
    assert "隱藏的真相" not in gemini.prompts[-1]


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
    turns = [Turn(narration=f"第{i}回合", action="a") for i in range(4)]
    state = GameState(
        premise="x",
        unsummarized=turns[:2],  # 舊存檔留下的等待壓縮回合
        recent=turns[2:],
        key_events=[f"事件{i}" for i in range(16)],
        flags=[f"事實{i}" for i in range(30)],
    )
    assert engine.needs_compaction(state)
    engine.compact_memory(state)
    assert state.summary == "壓縮後的摘要"
    assert state.unsummarized == [] and state.recent == turns  # 劇情紀錄沒有超過預算：原文全部保留
    assert state.key_events == [f"事件{i}" for i in range(10, 16)]
    assert state.flags == [f"事實{i}" for i in range(18, 30)]
    assert "事件0" in gemini.prompts[-1] and "事件15" not in gemini.prompts[-1]


def test_every_turn_is_kept_in_the_history():
    state, *_ = play(*[beat() for _ in range(7)])
    assert len(state.recent) == 6 and state.unsummarized == []  # 開場之後的 6 回合全部保留原文


def test_history_over_budget_compacts_the_oldest_half(monkeypatch):
    import story.core.engine as engine_module

    monkeypatch.setattr(engine_module, "HISTORY_BUDGET", 100)
    engine, gemini = make_engine(summary="早期劇情的摘要")
    turns = [Turn(narration=f"第{i}回合" + "。" * 16, action="a") for i in range(6)]  # 每回合 21 字，共 126 字
    state = GameState(premise="x", recent=list(turns))
    assert engine.needs_compaction(state)
    engine.compact_memory(state)
    assert state.summary == "早期劇情的摘要"
    assert state.recent == turns[-2:]  # 壓到剩預算的一半以內（42 字）
    assert "第0回合" in gemini.prompts[-1] and "第5回合" not in gemini.prompts[-1]
    assert not engine.needs_compaction(state)


def test_prompt_keeps_changing_sections_after_the_history():
    """會隨劇情改變的區塊（重大事件、故事進度、狀態）放在劇情紀錄後面，前面的部分每回合都一樣，快取才命中得到。"""
    engine, gemini = make_engine(beat())
    state = GameState(
        premise="燈塔", turn=3, minutes=0, arc=ARC, summary="早期的摘要", key_events=["找到鑰匙"],
        current_narration="上一段", recent=[Turn(narration="第一段", action="開門")],
    )
    engine.act(state, "往上爬")
    prompt = gemini.prompts[-1]
    order = ["# 故事前提", "# 先前劇情摘要", "# 劇情紀錄", "# 重大事件", "# 故事進度", "# 遊戲狀態", "# 玩家本回合的行動"]
    positions = [prompt.index(title) for title in order]
    assert positions == sorted(positions)


def test_turn_log_is_written(isolated):
    engine, _ = make_engine(beat(), beat(conditions_changed=[cond("擦傷", "輕")]))
    engine.log_path = isolated / "log.jsonl"
    state = GameState(premise="x")
    engine.start(state)
    engine.act(state, "a")
    lines = engine.log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and "擦傷(輕)" in lines[-1]


def test_turn_log_records_each_ai_call_with_time_and_tokens(isolated):
    """每回合的紀錄附上這段期間的 AI 呼叫：種類、秒數，以及 Gemini 回報的 token 用量（查等待時間花在哪裡）。"""
    import json
    from types import SimpleNamespace

    engine, gemini = make_engine(beat(), beat(game_over=True), beat())
    generate = gemini.generate_content

    def with_usage(**request):
        response = generate(**request)
        response.usage_metadata = SimpleNamespace(
            prompt_token_count=1200, cached_content_token_count=800, candidates_token_count=300, thoughts_token_count=50,
        )
        return response

    gemini.models.generate_content = with_usage
    engine.log_path = isolated / "log.jsonl"
    state = GameState(premise="x")
    engine.start(state)
    engine.act(state, "a")  # AI 太早寫出結局：請它重寫一次
    opening, turn = [json.loads(line) for line in engine.log_path.read_text(encoding="utf-8").splitlines()]
    assert [c["kind"] for c in opening["calls"]] == ["大綱", "劇情"]
    assert [c["kind"] for c in turn["calls"]] == ["劇情", "重寫"]
    call = turn["calls"][0]
    assert call["seconds"] >= 0
    assert (call["prompt"], call["cached"], call["output"], call["thinking"]) == (1200, 800, 300, 50)


def test_requests_time_out_and_retry():
    """Gemini 偶爾卡住一兩分鐘：每次請求有逾時，逾時或伺服器忙時自動重送。"""
    from story.core.engine import REQUEST_ATTEMPTS, REQUEST_TIMEOUT, new_client

    options = new_client("key")._api_client._http_options
    assert options.timeout == REQUEST_TIMEOUT * 1000 and options.retry_options.attempts == REQUEST_ATTEMPTS


def test_timeout_after_retries_becomes_a_normal_error():
    """重送都逾時：轉成核心會處理的 RuntimeError（不然會讓程式出錯），失敗的呼叫記進下一筆紀錄。"""
    import httpx

    engine, gemini = make_engine(beat())

    def timeout(**request):
        raise httpx.ReadTimeout("timed out")

    gemini.models.generate_content = timeout
    with pytest.raises(RuntimeError, match="太久沒有回應"):
        engine.act(GameState(premise="x", arc=ARC), "a")
    assert engine.calls[0]["kind"] == "劇情" and "timed out" in engine.calls[0]["error"]


def test_is_key_error():
    assert is_key_error(InvalidKeyError())
    assert not is_key_error(RuntimeError("網路斷線"))
