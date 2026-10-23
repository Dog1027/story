"""多人模式：engine 的隊伍規則，以及 PartyCore 的輪流輸入流程。"""

import pytest
from conftest import ARC, FakePartyEngine, InvalidKeyError, cond, make_engine, pbeat, upd

from story.core import PartyCore
from story.core.party import AWAY_ACTION, PartyEngine
from story.core.engine import TIMEOUT_ACTION
from story.core.models import Character, GameState
from story.core.records import ending_record, load

NAMES = ["阿明", "小華"]


def make_party_engine(*beats, **kwargs):
    return make_engine(*beats, engine_class=PartyEngine, **kwargs)


def party_state(**kwargs) -> GameState:
    return GameState(premise="兩個人被困在燈塔。", party=[Character(name=n) for n in NAMES], **kwargs)


def by_name(state):
    return {c.name: c for c in state.party}


# ---------- engine ----------


def test_each_character_gets_own_conditions_items_and_choices():
    engine, _ = make_party_engine(pbeat(
        upd("阿明", choices=["往上爬", "點燈"], conditions_changed=[cond("擦傷", "輕")], items_gained=["油燈"]),
        upd("小華", choices=["躲起來"], conditions_changed=[cond("恐懼", "中", "精神")]),
    ))
    state = party_state()
    engine.start(state)
    a, b = by_name(state)["阿明"], by_name(state)["小華"]
    assert [(c.name, c.severity) for c in a.conditions] == [("擦傷", "輕")] and a.inventory == ["油燈"]
    assert [(c.name, c.kind) for c in b.conditions] == [("恐懼", "精神")] and b.inventory == []
    assert a.choices == ["往上爬", "點燈"] and b.choices == ["躲起來"]


def test_shared_rules_apply_per_character():
    engine, _ = make_party_engine(
        pbeat(upd("阿明", conditions_changed=[cond("刀傷", "重")]), upd("小華", items_gained=["繩子"])),
        pbeat(upd("阿明", conditions_changed=[cond("刀傷", "輕")]), upd("小華", items_lost=["寶劍", "繩子"])),
    )
    state = party_state()
    engine.start(state)
    engine.act(state, {"阿明": "包紮", "小華": "丟掉繩子"})
    assert [(c.name, c.severity) for c in by_name(state)["阿明"].conditions] == [("刀傷", "中")]  # 好轉最多一級
    assert by_name(state)["小華"].inventory == []  # 不能失去沒有的東西


def test_unknown_names_are_ignored_and_missing_characters_get_no_choices():
    engine, _ = make_party_engine(pbeat(upd("阿明"), upd("路人甲", items_gained=["寶劍"])))
    state = party_state()
    engine.start(state)
    assert by_name(state)["小華"].choices == []
    assert all("寶劍" not in c.inventory for c in state.party)


def test_one_character_dies_others_continue():
    engine, gemini = make_party_engine(
        pbeat(upd("阿明"), upd("小華")),
        pbeat(upd("阿明", conditions_changed=[cond("失血", "重"), cond("骨折", "重")]), upd("小華")),
    )
    state = party_state()
    engine.start(state)
    engine.act(state, {"阿明": "硬闖", "小華": "等待"})
    assert not by_name(state)["阿明"].alive and by_name(state)["阿明"].choices == []
    assert by_name(state)["小華"].alive and not state.game_over
    assert "（倒下的場景）" in state.current_narration
    assert "傷重倒下的場景" in gemini.prompts[-1]


def test_everyone_dead_ends_the_game():
    lethal = [cond("失血", "重"), cond("骨折", "重")]
    engine, _ = make_party_engine(pbeat(upd("阿明"), upd("小華")), pbeat(upd("阿明", conditions_changed=lethal), upd("小華", conditions_changed=lethal)))
    state = party_state()
    engine.start(state)
    engine.act(state, {"阿明": "a", "小華": "b"})
    assert state.game_over
    assert "隊伍全員都在這趟旅程中倒下了" in ending_record(state)


def test_dead_characters_get_no_updates():
    engine, _ = make_party_engine(pbeat(upd("小華"), upd("阿明", items_gained=["寶劍"])))
    state = party_state(turn=3, minutes=600)
    state.party[0].alive = False
    engine.act(state, {"小華": "a"})
    assert by_name(state)["阿明"].inventory == []


def test_party_early_ending_is_ignored():
    """多人模式也一樣：AI 太早宣告結局時請它重寫，重寫後還是結局就忽略。"""
    engine, gemini = make_party_engine(pbeat(upd("阿明"), upd("小華"), game_over=True), pbeat(upd("阿明"), upd("小華"), game_over=True))
    state = party_state(turn=5, minutes=0, arc=ARC, act=1)
    engine.act(state, {"阿明": "a", "小華": "b"})
    assert not state.game_over and len(gemini.prompts) == 2


def test_party_prompt_contents():
    engine, gemini = make_party_engine(pbeat(upd("阿明"), upd("小華")), pbeat(upd("阿明"), upd("小華")))
    state = party_state()
    engine.start(state)
    assert "主角（多人" in gemini.prompts[0] and "阿明、小華" in gemini.prompts[0]  # 大綱知道有兩位主角
    engine.act(state, {"阿明": "推開門", "小華": "點燈"})
    prompt = gemini.prompts[-1]
    assert "阿明：推開門\n小華：點燈" in prompt
    assert '"名字":"阿明"' in prompt and '"名字":"小華"' in prompt
    assert "# 焦點" in prompt


def test_spotlight_rotates_between_alive_characters():
    engine, _ = make_party_engine()
    state = party_state(turn=1, minutes=0)
    assert "「小華」" in engine._build_prompt(state, {}).split("# 焦點")[1]
    state.turn = 2
    assert "「阿明」" in engine._build_prompt(state, {}).split("# 焦點")[1]


def test_party_epilogue_uses_party_prompt():
    engine, gemini = make_party_engine()
    state = party_state(turn=10, minutes=600, arc=ARC, act=3, game_over=True)
    engine.write_epilogue(state)
    assert "回顧每位角色" in gemini.prompts[-1] and "# 隊伍" in gemini.prompts[-1]


# ---------- PartyCore ----------


@pytest.fixture
def engine():
    return FakePartyEngine()


@pytest.fixture
def core(engine, isolated):
    return PartyCore("test", NAMES, save_path=isolated / "party.json", engine=engine)


def test_needs_one_to_four_unique_players():
    PartyCore("test", ["阿明"], engine=FakePartyEngine())  # 一個人也能開始
    for players in ([], ["阿明", "阿明"], ["a", "b", "c", "d", "e"]):
        with pytest.raises(ValueError):
            PartyCore("test", players, engine=FakePartyEngine())


def test_players_take_turns_before_the_round_resolves(core, engine):
    core.start()
    reply = core.send("")
    assert reply.phase == "playing" and reply.actor == "阿明"
    assert reply.choices == ["阿明往上爬", "阿明躲起來"]
    assert [s.name for s in reply.characters] == NAMES

    reply = core.send("1")
    assert reply.actor == "小華" and reply.narration == "" and "已記下 阿明 的行動" in reply.notice
    assert engine.rounds == []

    reply = core.send("自己想的行動")
    assert engine.rounds == [{"阿明": "阿明往上爬", "小華": "自己想的行動"}]
    assert reply.narration and reply.actor == "阿明"
    assert reply.changes == [("阿明", [("獲得", [("油燈", "plain")])])]
    assert "輪到 阿明 行動" in reply.text


def test_action_for_uses_the_current_actors_choices(core):
    core.start()
    core.send("")
    assert core.action_for("2") == "阿明躲起來"
    core.send("1")
    assert core.action_for("2") == "小華躲起來"


def test_timeout_fills_everyone_who_has_not_acted(core, engine):
    core.start()
    core.send("")
    core.send("1")
    core.send("/timeout")
    assert engine.rounds == [{"阿明": "阿明往上爬", "小華": TIMEOUT_ACTION}]


def test_dead_characters_are_skipped(core, engine):
    core.start()
    core.send("")
    core.send("1")
    core.send("1")  # 第 2 回合
    core.send("1")
    reply = core.send("1")  # 第 3 回合：阿明倒下
    assert reply.actor == "小華"
    assert [s.alive for s in reply.characters] == [False, True]
    core.send("1")
    assert engine.rounds[-1] == {"小華": "小華往上爬"}


def test_failed_round_lets_everyone_choose_again(core, engine):
    core.start()
    core.send("")
    core.send("1")
    engine.fail_with = InvalidKeyError()
    reply = core.send("2")
    assert reply.error == "api_key" and reply.actor == "阿明"  # 撤回所有人的行動，從第一位重新輸入
    assert core.state.turn == 1  # 已從存檔還原
    core.set_api_key("新的 key")
    core.send("2")
    core.send("2")
    assert engine.rounds == [{"阿明": "阿明躲起來", "小華": "小華躲起來"}]


def test_failed_timeout_round_does_not_get_stuck(core, engine):
    """時間到替大家填入的行動推進失敗：要撤回，不然每個人都「已行動」卻沒人能重送。"""
    core.start()
    core.send("")
    core.send("1")
    engine.fail_with = RuntimeError("503 UNAVAILABLE")
    reply = core.send("/timeout")
    assert reply.error == "api" and "請重新選擇行動" in reply.notice
    assert core.waiting() == ["阿明", "小華"]


def test_party_ending(core):
    core.start()
    core.send("")
    for _ in range(2):
        core.send("1")
        core.send("1")
    core.send("1")  # 第 3 回合阿明倒下，只剩小華行動，第 4 回合故事結束
    assert core.phase == "ending"
    reply = core.send("")
    assert reply.phase == "ended" and reply.ending.title == "燈塔雙人行"
    assert "阿明 在這趟旅程中倒下了" in reply.ending.record


def test_resume_party_save(engine, isolated):
    first = PartyCore("test", NAMES, save_path=isolated / "party.json", engine=engine)
    first.start()
    first.send("")
    first.send("1")
    first.send("1")
    assert load(isolated / "party.json").turn == 2

    same = PartyCore("test", NAMES, save_path=isolated / "party.json", engine=FakePartyEngine())
    assert same.start().phase == "ask_continue"
    reply = same.send("1")
    assert reply.resumed and reply.actor == "阿明"

    others = PartyCore("test", ["阿明", "小美"], save_path=isolated / "party.json", engine=FakePartyEngine())
    assert others.start().phase == "ask_premise"  # 玩家不同就開新局


def test_resume_ignores_player_order(engine, isolated):
    first = PartyCore("test", NAMES, save_path=isolated / "party.json", engine=engine)
    first.start()
    first.send("")
    reversed_order = PartyCore("test", NAMES[::-1], save_path=isolated / "party.json", engine=FakePartyEngine())
    assert reversed_order.start().phase == "ask_continue"  # 線上多人加入的順序不同也能接續


# ---------- 線上多人：send_as 與 view ----------


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
    assert "已記下 小華 的行動" in reply.notice and reply.actor == "" and reply.choices == []
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
        core.send("1")
        core.send("1")  # 第 3 回合阿明倒下
    assert "倒下" in core.send_as("阿明", "1").notice


def test_reply_survives_json_round_trip(core):
    import json

    from story.core import Reply

    core.start()
    core.send("")
    core.send("1")
    reply = core.send("1")
    back = Reply.from_dict(json.loads(json.dumps(reply.to_dict(), ensure_ascii=False)))
    assert back.characters[0].name == "阿明" and back.characters[0].alive and back.turn == reply.turn == 2
    assert back.changes[0][0] == "阿明"
    assert back.narration == reply.narration and back.choices == reply.choices


def test_party_core_with_real_engine(isolated):
    """PartyCore 接上真的 Engine（只有 Gemini 是假的），從開場一路玩到有人倒下。"""
    lethal = [cond("失血", "重"), cond("骨折", "重")]
    engine, gemini = make_party_engine(
        pbeat(upd("阿明", choices=["推門", "點燈"]), upd("小華", choices=["守門", "搜索"]), narration="兩人醒來。"),
        pbeat(upd("阿明", conditions_changed=lethal), upd("小華", items_gained=["鑰匙"], choices=["逃走"]), narration="惡犬撲來。"),
    )
    core = PartyCore("test", NAMES, save_path=isolated / "party.json", engine=engine)
    core.start()
    reply = core.send("")
    assert reply.narration == "兩人醒來。" and reply.actor == "阿明" and reply.choices == ["推門", "點燈"]
    core.send("1")
    reply = core.send("2")
    assert "阿明：推門\n小華：搜索" in gemini.prompts[-2]
    assert "惡犬撲來。" in reply.narration and "（倒下的場景）" in reply.narration
    assert reply.actor == "小華" and reply.choices == ["逃走"]  # 阿明倒下了，只剩小華
    assert [(s.name, s.alive) for s in reply.characters] == [("阿明", False), ("小華", True)]
    assert ("小華", [("獲得", [("鑰匙", "plain")])]) in reply.changes
    assert load(isolated / "party.json").party[0].alive is False
