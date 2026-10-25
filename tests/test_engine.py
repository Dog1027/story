"""engine 的遊戲規則：用假的 Gemini 回覆餵給真的 Engine，檢查程式有沒有正確把關。"""

import pytest
from conftest import ARC, HERO, InvalidKeyError, beat, cond, hero, make_engine, solo

from story.core.ai import is_key_error
from story.core.models import Condition, Turn
from story.core.prompting import clock_text
from story.core.rules import (
    ACT_TURNS,
    DAY,
    DEATH_SCORE,
    HOUR,
    MAX_TIME_LIMIT,
    MIN_ACT_TURNS,
    MIN_ENDING_TURN,
    MIN_TIME_LIMIT,
    TARGET_TURNS,
    apply_condition_changes,
    body_level,
    body_score,
)


def play(*beats, timed=False, **kwargs):
    """開場加上數個回合：第一個 beat 是開場，其餘每個 beat 對應一次行動。"""
    engine, gemini = make_engine(*beats, **kwargs)
    state = solo(premise="測試", timed_mode=timed)
    engine.start(state)
    for _ in beats[1:]:
        engine.act(state, {HERO: "行動"})
    return state, engine, gemini


def conditions(state):
    return {c.name: c.severity for c in hero(state).conditions}


# ---------- 狀態：新增、惡化、好轉、移除 ----------


def test_new_conditions_are_added_with_kind():
    state, *_ = play(beat(conditions_changed=[cond("擦傷", "輕"), cond("恐懼", "中", "精神")]))
    assert conditions(state) == {"擦傷": "light", "恐懼": "moderate"}
    assert {c.name: c.kind for c in hero(state).conditions} == {"擦傷": "body", "恐懼": "mind"}


def test_worsening_is_unlimited():
    state, *_ = play(beat(conditions_changed=[cond("刀傷", "輕")]), beat(conditions_changed=[cond("刀傷", "重")]))
    assert conditions(state) == {"刀傷": "severe"}


def test_improving_is_limited_to_one_level_per_turn():
    state, *_ = play(beat(conditions_changed=[cond("刀傷", "重")]), beat(conditions_changed=[cond("刀傷", "輕")]))
    assert conditions(state) == {"刀傷": "moderate"}


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
    assert conditions(state) == {"擦傷": "light"}


def test_long_condition_names_are_trimmed():
    state, *_ = play(beat(conditions_changed=[cond("這是一個非常非常長的狀態描述句子", "輕")]))
    assert len(hero(state).conditions[0].name) <= 12


def test_ai_can_correct_kind_of_old_condition():
    engine, _ = make_engine(beat(conditions_changed=[cond("驚魂未定", "中", "精神")]))
    state = solo(premise="舊存檔", turn=5, minutes=0, conditions=[Condition(name="驚魂未定", severity="moderate")])
    assert hero(state).conditions[0].kind == "body"  # 舊存檔一律先當成身體
    engine.act(state, {HERO: "a"})
    assert hero(state).conditions[0].kind == "mind"


# ---------- 整體狀態與死亡 ----------


@pytest.mark.parametrize(
    "conds, level",
    [
        ([], "healthy"),
        ([("疲憊", "light")], "minor"),
        ([("扭傷", "moderate"), ("疲憊", "light")], "injured"),
        ([("扭傷", "moderate"), ("割傷", "moderate")], "serious"),
        ([("骨折", "severe")], "serious"),
        ([("骨折", "severe"), ("扭傷", "moderate")], "dying"),
        ([("骨折", "severe"), ("失血", "severe")], "dead"),
    ],
)
def test_body_level(conds, level):
    state = solo(premise="x", conditions=[Condition(name=n, severity=v) for n, v in conds])
    assert body_level(hero(state)) == level


def test_mind_conditions_do_not_count_toward_death():
    state = solo(premise="x", conditions=[
        Condition(name="恐懼", kind="mind", severity="severe"),
        Condition(name="絕望", kind="mind", severity="severe"),
    ])
    assert body_score(hero(state)) == 0
    assert body_level(hero(state)) == "healthy"


def test_lethal_injury_ends_game_and_asks_ai_for_death_scene():
    engine, gemini = make_engine(
        beat(conditions_changed=[cond("骨折", "重")]),
        beat(narration="你咬牙撐著。", conditions_changed=[cond("失血", "重")]),
    )
    state = solo(premise="x")
    engine.start(state)
    engine.act(state, {HERO: "硬闖"})
    assert body_score(hero(state)) >= DEATH_SCORE
    assert state.game_over
    assert hero(state).choices == []
    assert state.current_narration == "你咬牙撐著。\n\n（倒下的場景）"  # 程式判定死亡後，AI 接著寫倒下的場景
    assert "傷勢已經致命" in gemini.prompts[-1] and HERO in gemini.prompts[-1]


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
    state = solo(premise="舊存檔", turn=30)
    engine.act(state, {HERO: "a"})
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
    assert conditions(state) == {"骨折": "severe"}


def test_serious_mind_condition_fades_over_days():
    state, *_ = play(beat(conditions_changed=[cond("恐懼", "重", "精神")]), beat(time_passed="一夜"))
    assert conditions(state) == {"恐懼": "severe"}  # 重度要 2 天才降一級
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
    state = solo(premise="x", turn=TARGET_TURNS, minutes=0, arc=ARC, act=3, timed_mode=True)
    engine.act(state, {HERO: "a"})
    assert state.game_over and state.current_time_limit == 0


# ---------- 背包、事實、事件 ----------


def test_cannot_lose_items_you_do_not_have():
    state, *_ = play(beat(items_gained=["油燈"]), beat(items_lost=["寶劍", "油燈"]))
    assert hero(state).inventory == []


def test_flags_are_not_duplicated_and_empty_events_are_skipped():
    state, *_ = play(beat(flags_set=["與守門人結仇"], key_event=""), beat(flags_set=["與守門人結仇"], key_event="找到地下室"))
    assert state.flags == ["與守門人結仇"]
    assert state.key_events == ["找到地下室"]


def test_at_most_four_choices():
    state, *_ = play(beat(choices=["1", "2", "3", "4", "5", "6"]))
    assert len(hero(state).choices) == 4


# ---------- 故事大綱與節奏 ----------


def test_start_plans_arc_before_opening():
    state, _, gemini = play(beat())
    assert state.arc == ARC
    assert "規劃大綱" in gemini.prompts[0]
    assert "故事進度（玩家看不到）" in gemini.prompts[1]


def test_milestone_advances_act():
    engine, _ = make_engine(beat(milestone_reached=True))
    state = solo(premise="x", turn=8, minutes=0, arc=ARC, act=0, act_turns=MIN_ACT_TURNS - 1)
    engine.act(state, {HERO: "a"})
    assert (state.act, state.act_turns) == (1, 0)


def test_milestone_too_early_in_an_act_is_ignored():
    """這一幕還沒演滿 MIN_ACT_TURNS 回合：AI 說達成也不推進，提示詞也會叫它先鋪陳。"""
    engine, gemini = make_engine(beat(milestone_reached=True))
    state = solo(premise="x", turn=2, minutes=0, arc=ARC, act=0, act_turns=1)
    engine.act(state, {HERO: "a"})
    assert (state.act, state.act_turns) == (0, 2)
    assert "這回合不要達成里程碑" in gemini.prompts[-1]


def test_early_ending_is_rewritten_then_ignored():
    """太早寫出結局：先請 AI 重寫一次；重寫後還是結局就忽略，故事繼續。"""
    engine, gemini = make_engine(beat(game_over=True, narration="全劇終"), beat(narration="新的發展", choices=["追上去"]))
    state = solo(premise="x", turn=5, minutes=0, arc=ARC, act=1)
    engine.act(state, {HERO: "a"})
    assert not state.game_over and state.current_narration == "新的發展"
    assert "結局限制" in gemini.prompts[0] and "太早結束了故事" in gemini.prompts[1]

    engine, _ = make_engine(beat(game_over=True), beat(game_over=True, choices=["繼續"]))
    state = solo(premise="x", turn=5, minutes=0, arc=ARC, act=1)
    engine.act(state, {HERO: "a"})
    assert not state.game_over and hero(state).choices == ["繼續"]


def test_ending_needs_the_final_act_and_enough_turns():
    for turn, act, allowed in ((MIN_ENDING_TURN - 1, 3, True), (MIN_ENDING_TURN - 2, 3, False), (25, 2, False), (TARGET_TURNS - 1, 1, True)):
        engine, gemini = make_engine(beat(game_over=True), beat(game_over=True))
        state = solo(premise="x", turn=turn, minutes=0, arc=ARC, act=act)
        engine.act(state, {HERO: "a"})
        assert state.game_over is allowed, (turn, act)
        assert len(gemini.prompts) == (1 if allowed else 2)  # 不能結束時會請 AI 重寫一次


def test_death_ends_the_story_at_any_time():
    """因傷死亡由程式判定，不受最早結局回合的限制。"""
    lethal = [cond("失血", "重"), cond("骨折", "重")]
    engine, _ = make_engine(beat(conditions_changed=lethal), beat(narration="主角倒下了。", game_over=True))
    state = solo(premise="x", turn=3, minutes=0, arc=ARC, act=0)
    engine.act(state, {HERO: "a"})
    assert state.game_over


def test_final_act_does_not_advance_further():
    engine, _ = make_engine(beat(milestone_reached=True))
    state = solo(premise="x", turn=5, minutes=0, arc=ARC, act=3)
    engine.act(state, {HERO: "a"})
    assert state.act == 3


def test_pacing_reminder_when_act_drags_on():
    engine, gemini = make_engine(beat())
    state = solo(premise="x", turn=5, minutes=0, arc=ARC, act=0, act_turns=ACT_TURNS)
    engine.act(state, {HERO: "a"})
    assert "節奏提醒" in gemini.prompts[-1]


def test_wrap_up_reminder_after_target_length():
    engine, gemini = make_engine(beat())
    state = solo(premise="x", turn=TARGET_TURNS, minutes=0, arc=ARC, act=3)
    engine.act(state, {HERO: "a"})
    assert "超過預定的" in gemini.prompts[-1]


def test_twist_is_foreshadowed_then_revealed_in_the_third_act():
    """前兩幕只給真相與伏筆、叫 AI 不要說破；第三幕要揭露；最後一幕當作已知。"""
    prompts = {}
    for act in range(4):
        engine, gemini = make_engine(beat())
        engine.act(solo(premise="x", turn=8, minutes=0, arc=ARC, act=act), {HERO: "a"})
        prompts[act] = gemini.prompts[-1]
    for act in (0, 1):
        assert "在那之前不要說破" in prompts[act] and "- 鑰匙上刻著你的生日" in prompts[act]
    assert "本幕要揭露隱藏的真相：鑰匙的主人就是失憶前的你" in prompts[2] and "呼應之前埋下的伏筆" in prompts[2]
    assert "已揭露的真相" in prompts[3] and "伏筆" not in prompts[3]


def test_old_save_gets_arc_and_jumps_to_matching_act():
    engine, gemini = make_engine(beat())
    state = solo(premise="舊存檔", turn=109, minutes=0, summary="主角把證據交給媒體")
    engine.act(state, {HERO: "a"})
    assert state.arc == ARC and state.act == 3
    assert "已經進行了 109 回合" in gemini.prompts[0]


# ---------- 提示詞與記憶 ----------


def test_prompt_includes_the_history_and_no_duplicate_action():
    engine, gemini = make_engine(beat())
    state = solo(premise="x", turn=10, minutes=0, current_narration="上一段劇情", recent=[Turn(narration="最近的回合", action="近行動")])
    engine.act(state, {HERO: "推開門"})
    prompt = gemini.prompts[-1]
    assert "最近的回合" in prompt and "上一段劇情" in prompt
    assert prompt.count("推開門") == 1


def test_compaction_folds_old_events_and_flags_into_summary():
    engine, gemini = make_engine(summary="壓縮後的摘要")
    turns = [Turn(narration=f"第{i}回合", action="a") for i in range(4)]
    state = solo(
        premise="x",
        recent=list(turns),
        key_events=[f"事件{i}" for i in range(16)],
        flags=[f"事實{i}" for i in range(30)],
    )
    assert engine.needs_compaction(state)
    engine.compact_memory(state)
    assert state.summary == "壓縮後的摘要"
    assert state.recent == turns  # 劇情紀錄沒有超過預算：原文全部保留
    assert state.key_events == [f"事件{i}" for i in range(10, 16)]
    assert state.flags == [f"事實{i}" for i in range(18, 30)]
    assert "事件0" in gemini.prompts[-1] and "事件15" not in gemini.prompts[-1]


def test_every_turn_is_kept_in_the_history():
    state, *_ = play(*[beat() for _ in range(7)])
    assert len(state.recent) == 6  # 開場之後的 6 回合全部保留原文


def test_history_over_budget_compacts_the_oldest_half(monkeypatch):
    import story.core.rules as rules

    monkeypatch.setattr(rules, "HISTORY_BUDGET", 100)
    engine, gemini = make_engine(summary="早期劇情的摘要")
    turns = [Turn(narration=f"第{i}回合" + "字" * 16, action="a") for i in range(6)]  # 每回合 21 字，共 126 字
    state = solo(premise="x", recent=list(turns))
    assert engine.needs_compaction(state)
    engine.compact_memory(state)
    assert state.summary == "早期劇情的摘要"
    assert state.recent == turns[-2:]  # 壓到剩預算的一半以內（42 字）
    assert "第0回合" in gemini.prompts[-1] and "第5回合" not in gemini.prompts[-1]
    assert not engine.needs_compaction(state)


def test_prompt_keeps_changing_sections_after_the_history():
    """會隨劇情改變的區塊（重大事件、故事進度、狀態）放在劇情紀錄後面，前面的部分每回合都一樣，快取才命中得到。"""
    engine, gemini = make_engine(beat())
    state = solo(
        premise="燈塔", turn=3, minutes=0, arc=ARC, summary="早期的摘要", key_events=["找到鑰匙"],
        current_narration="上一段", recent=[Turn(narration="第一段", action="開門")],
    )
    engine.act(state, {HERO: "往上爬"})
    prompt = gemini.prompts[-1]
    order = ["# 故事前提", "# 先前劇情摘要", "# 劇情紀錄", "# 重大事件", "# 故事進度", "# 遊戲狀態", "# 本回合每位角色的行動"]
    positions = [prompt.index(title) for title in order]
    assert positions == sorted(positions)


def test_turn_log_is_written(isolated):
    engine, _ = make_engine(beat(), beat(conditions_changed=[cond("擦傷", "輕")]))
    engine.log_path = isolated / "log.jsonl"
    state = solo(premise="x")
    engine.start(state)
    engine.act(state, {HERO: "a"})
    lines = engine.log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and "擦傷(light)" in lines[-1]


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
    state = solo(premise="x")
    engine.start(state)
    engine.act(state, {HERO: "a"})  # AI 太早寫出結局：請它重寫一次
    opening, turn = [json.loads(line) for line in engine.log_path.read_text(encoding="utf-8").splitlines()]
    assert [c["kind"] for c in opening["calls"]] == ["arc", "turn"]
    assert [c["kind"] for c in turn["calls"]] == ["turn", "rewrite"]
    call = turn["calls"][0]
    assert call["seconds"] >= 0
    assert (call["prompt"], call["cached"], call["output"], call["thinking"]) == (1200, 800, 300, 50)


def test_overall_level_words_are_not_conditions():
    """AI 偶爾把狀態列的評語（良好、重傷……）當成傷勢名稱回報：直接忽略。"""
    from story.core.models import ConditionChange

    state = solo(premise="x")
    changes = [ConditionChange(**cond(name, "重")) for name in ("良好", "重傷", "右臂撕裂傷")]
    apply_condition_changes(hero(state), changes, [], 0)
    assert [c.name for c in hero(state).conditions] == ["右臂撕裂傷"]


# ---------- 串流 ----------


def test_partial_json_fields_while_streaming():
    from story.core.ai import partial_bool, partial_string

    text = '{"game_over": false, "narration": "你在\\n燈塔\\u9192'
    assert partial_bool(text, "game_over") is False
    assert partial_string(text, "narration") == "你在\n燈塔醒"
    assert partial_string(text[:-3], "narration") == "你在\n燈塔"  # \\u 還沒收完整：先不顯示
    assert partial_string('{"game_over": tr', "narration") is None and partial_bool('{"game_over": tr', "game_over") is None


def test_draft_follows_the_narration_as_it_streams():
    engine, gemini = make_engine(beat(narration="風雨中，你推開了燈塔的門。" * 3))
    stream, drafts = gemini.generate_content_stream, []

    def watching(**request):
        for chunk in stream(**request, chunk_size=10):
            yield chunk
            drafts.append(engine.draft)  # 收下這一段之後，draft 已經更新

    gemini.models.generate_content_stream = watching
    state = solo(premise="x", turn=1, minutes=0, arc=ARC)
    engine.act(state, {HERO: "a"})
    shown = [d for d in drafts if d]
    assert len(shown) > 3 and all(b.startswith(a) for a, b in zip(shown, shown[1:]))  # 一路變長
    assert shown[-1] == state.current_narration
    assert engine.draft == ""  # 寫完就清空


def test_early_ending_stops_before_any_narration_is_shown():
    engine, gemini = make_engine(beat(game_over=True, narration="全劇終"), beat(narration="新的發展"))
    stream, drafts = gemini.generate_content_stream, []

    def watching(**request):
        for chunk in stream(**request, chunk_size=5):
            yield chunk
            drafts.append(engine.draft)

    gemini.models.generate_content_stream = watching
    state = solo(premise="x", turn=5, minutes=0, arc=ARC, act=1)
    engine.act(state, {HERO: "a"})
    assert "全劇終" not in "".join(drafts)  # game_over 在劇情前面：還沒出現劇情就中斷重寫
    assert state.current_narration == "新的發展"


def test_requests_time_out_and_retry():
    """Gemini 偶爾卡住一兩分鐘：每次請求有逾時，逾時或伺服器忙時自動重送。"""
    from story.core.ai import REQUEST_ATTEMPTS, REQUEST_TIMEOUT, new_client

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
        engine.act(solo(premise="x", arc=ARC), {HERO: "a"})
    assert engine.calls[0]["kind"] == "turn" and "timed out" in engine.calls[0]["error"]


def test_is_key_error():
    assert is_key_error(InvalidKeyError())
    assert not is_key_error(RuntimeError("網路斷線"))
