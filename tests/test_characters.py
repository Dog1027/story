"""好幾位角色的隊伍：每位角色各自套用規則，以及 StoryCore 收齊每位角色的行動（send_as）才推進的流程。"""

from pathlib import Path

import pytest
from conftest import ARC, FakeGroupEngine, InvalidKeyError, cond, make_engine, pbeat, upd

from story.core import StoryCore
from story.core.prompting import AWAY_ACTION
from story.core.prompting import TIMEOUT_ACTION
from story.core.models import Character, GameState
from story.core.records import ending_record, load

NAMES = ["阿明", "小華"]


def group_state(**kwargs) -> GameState:
    return GameState(premise="兩個人被困在燈塔。", characters=[Character(name=n) for n in NAMES], **kwargs)


def by_name(state):
    return {c.name: c for c in state.characters}


# ---------- engine ----------


def test_each_character_gets_own_conditions_items_and_choices():
    engine, _ = make_engine(pbeat(
        upd("阿明", choices=["往上爬", "點燈"], conditions_changed=[cond("擦傷", "輕")], items_gained=["油燈"]),
        upd("小華", choices=["躲起來"], conditions_changed=[cond("恐懼", "中", "精神")]),
    ))
    state = group_state()
    engine.start(state)
    a, b = by_name(state)["阿明"], by_name(state)["小華"]
    assert [(c.name, c.severity) for c in a.conditions] == [("擦傷", "light")] and a.inventory == ["油燈"]
    assert [(c.name, c.kind) for c in b.conditions] == [("恐懼", "mind")] and b.inventory == []
    assert a.choices == ["往上爬", "點燈"] and b.choices == ["躲起來"]


def test_shared_rules_apply_per_character():
    engine, _ = make_engine(
        pbeat(upd("阿明", conditions_changed=[cond("刀傷", "重")]), upd("小華", items_gained=["繩子"])),
        pbeat(upd("阿明", conditions_changed=[cond("刀傷", "輕")]), upd("小華", items_lost=["寶劍", "繩子"])),
    )
    state = group_state()
    engine.start(state)
    engine.act(state, {"阿明": "包紮", "小華": "丟掉繩子"})
    assert [(c.name, c.severity) for c in by_name(state)["阿明"].conditions] == [("刀傷", "moderate")]  # 好轉最多一級
    assert by_name(state)["小華"].inventory == []  # 不能失去沒有的東西


def test_unknown_names_are_ignored_and_missing_characters_get_no_choices():
    engine, _ = make_engine(pbeat(upd("阿明"), upd("路人甲", items_gained=["寶劍"])))
    state = group_state()
    engine.start(state)
    assert by_name(state)["小華"].choices == []
    assert all("寶劍" not in c.inventory for c in state.characters)


def test_one_character_dies_others_continue():
    engine, gemini = make_engine(
        pbeat(upd("阿明"), upd("小華")),
        pbeat(upd("阿明", conditions_changed=[cond("失血", "重"), cond("骨折", "重")]), upd("小華")),
    )
    state = group_state()
    engine.start(state)
    engine.act(state, {"阿明": "硬闖", "小華": "等待"})
    assert not by_name(state)["阿明"].alive and by_name(state)["阿明"].choices == []
    assert by_name(state)["小華"].alive and not state.game_over
    assert "（倒下的場景）" in state.current_narration
    assert "傷重倒下的場景" in gemini.prompts[-1]


def test_everyone_dead_ends_the_game():
    lethal = [cond("失血", "重"), cond("骨折", "重")]
    engine, _ = make_engine(pbeat(upd("阿明"), upd("小華")), pbeat(upd("阿明", conditions_changed=lethal), upd("小華", conditions_changed=lethal)))
    state = group_state()
    engine.start(state)
    engine.act(state, {"阿明": "a", "小華": "b"})
    assert state.game_over
    assert "隊伍全員都在這趟旅程中倒下了" in ending_record(state)


def test_dead_characters_get_no_updates():
    engine, _ = make_engine(pbeat(upd("小華"), upd("阿明", items_gained=["寶劍"])))
    state = group_state(turn=3, minutes=600)
    state.characters[0].alive = False
    engine.act(state, {"小華": "a"})
    assert by_name(state)["阿明"].inventory == []


def test_group_early_ending_is_ignored():
    """好幾位角色也一樣：AI 太早宣告結局時請它重寫，重寫後還是結局就忽略。"""
    engine, gemini = make_engine(pbeat(upd("阿明"), upd("小華"), game_over=True), pbeat(upd("阿明"), upd("小華"), game_over=True))
    state = group_state(turn=5, minutes=0, arc=ARC, act=1)
    engine.act(state, {"阿明": "a", "小華": "b"})
    assert not state.game_over and len(gemini.prompts) == 2


def test_group_prompt_contents():
    engine, gemini = make_engine(pbeat(upd("阿明"), upd("小華")), pbeat(upd("阿明"), upd("小華")))
    state = group_state()
    engine.start(state)
    assert "# 主角" in gemini.prompts[0] and "阿明、小華" in gemini.prompts[0]  # 大綱知道有兩位主角
    engine.act(state, {"阿明": "推開門", "小華": "點燈"})
    prompt = gemini.prompts[-1]
    assert "阿明：推開門\n小華：點燈" in prompt
    assert '"名字":"阿明"' in prompt and '"名字":"小華"' in prompt
    assert "# 焦點" in prompt and "# 人稱" not in prompt  # 好幾位角色用名字，不用「你」


def test_spotlight_rotates_between_alive_characters():
    engine, _ = make_engine()
    state = group_state(turn=1, minutes=0)
    assert "「小華」" in engine.build.turn(state, {}).split("# 焦點")[1]
    state.turn = 2
    assert "「阿明」" in engine.build.turn(state, {}).split("# 焦點")[1]


def test_epilogue_looks_back_on_every_character():
    engine, gemini = make_engine()
    state = group_state(turn=10, minutes=600, arc=ARC, act=3, game_over=True)
    engine.write_epilogue(state)
    assert "回顧每位角色" in gemini.prompts[-1] and '"名字":"小華"' in gemini.prompts[-1]


def test_one_character_gets_no_focus_and_wrong_names_still_count():
    """只有一位角色：不用「焦點」、提醒 AI 用「你」；AI 把名字寫錯了，變化也算在他身上。"""
    engine, gemini = make_engine(pbeat(upd("別的名字", items_gained=["油燈"], choices=["點燈"])))
    state = GameState(premise="一個人在燈塔。", characters=[Character(name="阿明")])
    engine.start(state)
    assert "# 焦點" not in gemini.prompts[-1]
    assert "# 人稱" in gemini.prompts[-1] and "「阿明」" in gemini.prompts[-1]
    assert state.characters[0].inventory == ["油燈"] and state.characters[0].choices == ["點燈"]


# ---------- StoryCore：好幾位角色 ----------


@pytest.fixture
def engine():
    return FakeGroupEngine()


@pytest.fixture
def core(engine, isolated):
    return StoryCore("test", NAMES, save_path=isolated / "team.json", log_path=isolated / "team.log.jsonl", engine=engine)


def act(core, text: str):
    """替這回合還沒行動的第一位角色送出行動（房間裡是每個人各自用 send_as 送）。"""
    return core.send_as(core.waiting()[0], text)


def test_needs_one_to_four_unique_players():
    StoryCore("test", ["阿明"], save_path=Path("p.json"), log_path=Path("p.jsonl"), engine=FakeGroupEngine())  # 一個人也能開始
    for players in ([], ["阿明", "阿明"], ["a", "b", "c", "d", "e"]):
        with pytest.raises(ValueError):
            StoryCore("test", players, save_path=Path("p.json"), log_path=Path("p.jsonl"), engine=FakeGroupEngine())


def test_everyone_acts_before_the_round_resolves(core, engine):
    core.start()
    reply = core.send("")
    assert reply.phase == "playing" and reply.actor == "" and reply.choices == []  # 選項看 view() 或 send_as() 的回覆
    assert [s.name for s in reply.characters] == NAMES
    assert core.waiting() == NAMES

    reply = core.send_as("阿明", "1")
    assert reply.actor == "" and reply.narration == "" and reply.notice == ""
    assert engine.rounds == [] and core.waiting() == ["小華"]

    reply = core.send_as("小華", "自己想的行動")
    assert engine.rounds == [{"阿明": "阿明往上爬", "小華": "自己想的行動"}]
    assert reply.narration and reply.actor == "小華" and reply.choices == ["小華往上爬", "小華躲起來"]  # 新的一回合
    assert reply.changes == [("阿明", [("獲得", [("油燈", "plain")])])]


def test_actions_without_a_name_are_refused(core):
    """遊戲中的行動要說是誰的：用 send() 送行動是用錯了（以前同一台電腦輪流輸入時才會這樣用）。"""
    core.start()
    core.send("")
    with pytest.raises(ValueError, match="send_as"):
        core.send("1")
    assert core.send("/state").info  # 指令照常可以用 send()


def test_timeout_fills_everyone_who_has_not_acted(core, engine):
    core.start()
    core.send("")
    act(core, "1")
    core.send("/timeout")
    assert engine.rounds == [{"阿明": "阿明往上爬", "小華": TIMEOUT_ACTION}]


def test_dead_characters_are_skipped(core, engine):
    core.start()
    core.send("")
    act(core, "1")
    act(core, "1")  # 第 2 回合
    act(core, "1")
    reply = act(core, "1")  # 第 3 回合：阿明倒下
    assert core.waiting() == ["小華"]
    assert [s.alive for s in reply.characters] == [False, True]
    act(core, "1")
    assert engine.rounds[-1] == {"小華": "小華往上爬"}


def test_failed_round_lets_everyone_choose_again(core, engine):
    core.start()
    core.send("")
    act(core, "1")
    engine.fail_with = InvalidKeyError()
    reply = act(core, "2")
    assert reply.error == "api_key" and core.waiting() == NAMES  # 撤回所有人的行動，大家重新選
    assert core.state.turn == 1  # 已從存檔還原
    core.set_api_key("新的 key")
    act(core, "2")
    act(core, "2")
    assert engine.rounds == [{"阿明": "阿明躲起來", "小華": "小華躲起來"}]


def test_failed_timeout_round_does_not_get_stuck(core, engine):
    """時間到替大家填入的行動推進失敗：要撤回，不然每個人都「已行動」卻沒人能重送。"""
    core.start()
    core.send("")
    act(core, "1")
    engine.fail_with = RuntimeError("503 UNAVAILABLE")
    reply = core.send("/timeout")
    assert reply.error == "api" and "請重新選擇行動" in reply.notice
    assert core.waiting() == ["阿明", "小華"]


def test_group_ending(core):
    core.start()
    core.send("")
    for _ in range(2):
        act(core, "1")
        act(core, "1")
    act(core, "1")  # 第 3 回合阿明倒下，只剩小華行動，第 4 回合故事結束
    assert core.phase == "ending"
    reply = core.send("")
    assert reply.phase == "ended" and reply.ending.title == "燈塔雙人行"
    assert "阿明 在這趟旅程中倒下了" in reply.ending.record


def test_resume_team_save(engine, isolated):
    first = StoryCore("test", NAMES, save_path=isolated / "team.json", log_path=isolated / "team.log.jsonl", engine=engine)
    first.start()
    first.send("")
    act(first, "1")
    act(first, "1")
    assert load(isolated / "team.json").turn == 2

    same = StoryCore("test", NAMES, save_path=isolated / "team.json", log_path=isolated / "team.log.jsonl", engine=FakeGroupEngine())
    assert same.start().phase == "ask_continue"
    reply = same.send("1")
    assert reply.resumed and same.view("阿明", reply).choices == ["阿明往上爬", "阿明躲起來"]

    others = StoryCore("test", ["阿明", "小美"], save_path=isolated / "team.json", log_path=isolated / "team.log.jsonl", engine=FakeGroupEngine())
    assert others.start().phase == "ask_premise"  # 玩家不同就開新局


def test_resume_ignores_player_order(engine, isolated):
    first = StoryCore("test", NAMES, save_path=isolated / "team.json", log_path=isolated / "team.log.jsonl", engine=engine)
    first.start()
    first.send("")
    reversed_order = StoryCore("test", NAMES[::-1], save_path=isolated / "team.json", log_path=isolated / "team.log.jsonl", engine=FakeGroupEngine())
    assert reversed_order.start().phase == "ask_continue"  # 房間裡加入的順序不同也能接續


# ---------- 網頁版的房間：send_as 與 view ----------


def test_away_is_an_action_whose_text_the_core_decides(core, engine):
    """斷線的人由房間送出 /away：給 AI 的文字由核心決定，已經行動或倒下的人不能用它蓋掉行動。"""
    core.start()
    core.send("")
    assert core.action_for("/away") == AWAY_ACTION
    core.send_as("阿明", "1")
    assert "已經行動" in core.send_as("阿明", "/away").notice
    core.send_as("小華", "/away")
    assert engine.rounds == [{"阿明": "阿明往上爬", "小華": AWAY_ACTION}]
    assert "[背包]\n  阿明：" in core.send("/state").info[1]  # 每個人的背包


def test_send_as_accepts_actions_in_any_order(core, engine):
    core.start()
    core.send("")
    reply = core.send_as("小華", "2")
    assert reply.notice == "" and reply.actor == "" and reply.choices == []
    assert core.waiting() == ["阿明"]
    assert "已經行動" in core.send_as("小華", "1").notice
    core.send_as("阿明", "1")
    assert engine.rounds == [{"阿明": "阿明往上爬", "小華": "小華躲起來"}]


def test_view_gives_each_player_their_own_choices(core):
    core.start()
    opening = core.send("")
    assert core.view("小華", opening).choices == ["小華往上爬", "小華躲起來"]
    assert core.view("小華", opening).actor == "小華"
    assert core.view("小華", opening).narration == opening.narration
    core.send_as("阿明", "1")
    me = core.view("阿明")  # 重新連線：目前這回合的畫面
    assert me.actor == "" and me.choices == [] and me.resumed and me.narration == "兩人在燈塔醒來。"
    assert core.view("小華").choices == ["小華往上爬", "小華躲起來"]


def test_send_as_rejects_fallen_characters(core):
    core.start()
    core.send("")
    for _ in range(2):
        act(core, "1")
        act(core, "1")  # 第 3 回合阿明倒下
    assert "倒下" in core.send_as("阿明", "1").notice


def test_reply_survives_json_round_trip(core):
    import json

    from story.core import Reply

    core.start()
    core.send("")
    act(core, "1")
    reply = act(core, "1")
    back = Reply.from_dict(json.loads(json.dumps(reply.to_dict(), ensure_ascii=False)))
    assert back.characters[0].name == "阿明" and back.characters[0].alive and back.turn == reply.turn == 2
    assert back.changes[0][0] == "阿明"
    assert back.narration == reply.narration and back.choices == reply.choices


def test_group_core_with_real_engine(isolated):
    """StoryCore 接上真的 Engine（只有 Gemini 是假的），從開場一路玩到有人倒下。"""
    lethal = [cond("失血", "重"), cond("骨折", "重")]
    engine, gemini = make_engine(
        pbeat(upd("阿明", choices=["推門", "點燈"]), upd("小華", choices=["守門", "搜索"]), narration="兩人醒來。"),
        pbeat(upd("阿明", conditions_changed=lethal), upd("小華", items_gained=["鑰匙"], choices=["逃走"]), narration="惡犬撲來。"),
    )
    core = StoryCore("test", NAMES, save_path=isolated / "team.json", log_path=isolated / "team.log.jsonl", engine=engine)
    core.start()
    reply = core.send("")
    assert reply.narration == "兩人醒來。" and core.view("阿明", reply).choices == ["推門", "點燈"]
    core.send_as("阿明", "1")
    reply = core.send_as("小華", "2")
    assert "阿明：推門\n小華：搜索" in gemini.prompts[-2]
    assert "惡犬撲來。" in reply.narration and "（倒下的場景）" in reply.narration
    assert core.waiting() == ["小華"] and reply.choices == ["逃走"]  # 阿明倒下了，只剩小華
    assert [(s.name, s.alive) for s in reply.characters] == [("阿明", False), ("小華", True)]
    assert ("小華", [("獲得", [("鑰匙", "plain")])]) in reply.changes
    assert load(isolated / "team.json").characters[0].alive is False
