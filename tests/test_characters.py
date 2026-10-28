"""Teams of several characters: rules applied to each character separately, and StoryCore advancing only once every character's action is in (send_as)."""

from pathlib import Path

import pytest
from conftest import ARC, FakeGroupEngine, InvalidKeyError, cond, make_engine, pbeat, upd

from story.games import StoryCore
from story.games.adventure.prompting import AWAY_ACTION
from story.games.adventure.prompting import TIMEOUT_ACTION
from story.games.adventure.models import Character, GameState
from story.core.saves import load
from story.games.adventure.records import ending_record

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
    assert [(c.name, c.severity) for c in by_name(state)["阿明"].conditions] == [("刀傷", "moderate")]  # At most one level better
    assert by_name(state)["小華"].inventory == []  # Can't lose what you don't have


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
    """The same with several characters: when the AI declares the ending too early, have it rewrite; if the rewrite still ends, ignore it."""
    engine, gemini = make_engine(pbeat(upd("阿明"), upd("小華"), game_over=True), pbeat(upd("阿明"), upd("小華"), game_over=True))
    state = group_state(turn=5, minutes=0, arc=ARC, act=1)
    engine.act(state, {"阿明": "a", "小華": "b"})
    assert not state.game_over and len(gemini.prompts) == 2


def test_group_prompt_contents():
    engine, gemini = make_engine(pbeat(upd("阿明"), upd("小華")), pbeat(upd("阿明"), upd("小華")))
    state = group_state()
    engine.start(state)
    assert "# 主角" in gemini.prompts[0] and "阿明、小華" in gemini.prompts[0]  # The outline knows there are two leads
    engine.act(state, {"阿明": "推開門", "小華": "點燈"})
    prompt = gemini.prompts[-1]
    assert "阿明：推開門\n小華：點燈" in prompt
    assert '"名字":"阿明"' in prompt and '"名字":"小華"' in prompt
    assert "# 焦點" in prompt and "# 人稱" not in prompt  # Several characters use names, not 「你」 ("you")


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
    """Only one character: no "focus", the AI is reminded to use 「你」 ("you"), and changes count for them even when the AI gets the name wrong."""
    engine, gemini = make_engine(pbeat(upd("別的名字", items_gained=["油燈"], choices=["點燈"])))
    state = GameState(premise="一個人在燈塔。", characters=[Character(name="阿明")])
    engine.start(state)
    assert "# 焦點" not in gemini.prompts[-1]
    assert "# 人稱" in gemini.prompts[-1] and "「阿明」" in gemini.prompts[-1]
    assert state.characters[0].inventory == ["油燈"] and state.characters[0].choices == ["點燈"]


# ---------- StoryCore: several characters ----------


@pytest.fixture
def engine():
    return FakeGroupEngine()


@pytest.fixture
def core(engine, isolated):
    return StoryCore("test", NAMES, save_path=isolated / "team.json", log_path=isolated / "team.log.jsonl", engine=engine)


def act(core, text: str):
    """Send an action for the first character who hasn't acted this turn (in a room, each person sends their own with send_as)."""
    return core.send_as(core.waiting()[0], text)


def test_needs_one_to_four_unique_players():
    StoryCore("test", ["阿明"], save_path=Path("p.json"), log_path=Path("p.jsonl"), engine=FakeGroupEngine())  # One person can start too
    for players in ([], ["阿明", "阿明"], ["a", "b", "c", "d", "e"]):
        with pytest.raises(ValueError):
            StoryCore("test", players, save_path=Path("p.json"), log_path=Path("p.jsonl"), engine=FakeGroupEngine())


def test_everyone_acts_before_the_round_resolves(core, engine):
    core.start()
    reply = core.send("")
    assert reply.phase == "playing" and reply.actor == "" and reply.choices == []  # Choices come from view() or the send_as() reply
    assert [s.name for s in reply.characters] == NAMES
    assert core.waiting() == NAMES

    reply = core.send_as("阿明", "1")
    assert reply.actor == "" and reply.narration == "" and reply.notice == ""
    assert engine.rounds == [] and core.waiting() == ["小華"]

    reply = core.send_as("小華", "自己想的行動")
    assert engine.rounds == [{"阿明": "阿明往上爬", "小華": "自己想的行動"}]
    assert reply.narration and reply.actor == "小華" and reply.choices == ["小華往上爬", "小華躲起來"]  # A new turn
    assert reply.changes == [("阿明", [("獲得", [("油燈", "plain")])])]


def test_actions_without_a_name_are_refused(core):
    """In-game actions must say whose they are: sending an action with send() is a mistake (it was only used that way when people took turns typing on one computer)."""
    core.start()
    core.send("")
    with pytest.raises(ValueError, match="send_as"):
        core.send("1")
    assert core.send("/state").info  # Commands can still use send()


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
    act(core, "1")  # Turn 2
    act(core, "1")
    reply = act(core, "1")  # Turn 3: Ming falls
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
    assert reply.error == "api" and core.waiting() == NAMES  # Take back everyone's actions; everyone chooses again
    assert core.state.turn == 1  # Restored from the save
    engine.fail_with = None
    act(core, "2")
    act(core, "2")
    assert engine.rounds == [{"阿明": "阿明躲起來", "小華": "小華躲起來"}]


def test_failed_timeout_round_does_not_get_stuck(core, engine):
    """Actions filled in for everyone when time ran out fail to advance: they must be taken back, or everyone counts as having acted and no one can resend."""
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
    act(core, "1")  # Ming falls on turn 3, leaving only Hua to act, and the story ends on turn 4
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
    assert load(isolated / "team.json", GameState).turn == 2

    same = StoryCore("test", NAMES, save_path=isolated / "team.json", log_path=isolated / "team.log.jsonl", engine=FakeGroupEngine())
    assert same.start().phase == "ask_continue"
    reply = same.send("1")
    assert reply.resumed and same.view("阿明", reply).choices == ["阿明往上爬", "阿明躲起來"]
    assert reply.history == [("兩人在燈塔醒來。", "阿明：阿明往上爬\n小華：小華往上爬")]  # Several characters: one action per line, with names

    others = StoryCore("test", ["阿明", "小美"], save_path=isolated / "team.json", log_path=isolated / "team.log.jsonl", engine=FakeGroupEngine())
    assert others.start().phase == "setup"  # Different players start a new game


def test_resume_ignores_player_order(engine, isolated):
    first = StoryCore("test", NAMES, save_path=isolated / "team.json", log_path=isolated / "team.log.jsonl", engine=engine)
    first.start()
    first.send("")
    reversed_order = StoryCore("test", NAMES[::-1], save_path=isolated / "team.json", log_path=isolated / "team.log.jsonl", engine=FakeGroupEngine())
    assert reversed_order.start().phase == "ask_continue"  # Joining a room in a different order still continues


# ---------- Web rooms: send_as and view ----------


def test_away_is_an_action_whose_text_the_core_decides(core, engine):
    """The room sends /away for someone who disconnected: the core decides the text for the AI, and it can't overwrite the action of someone who has acted or fallen."""
    core.start()
    core.send("")
    assert core.action_for("/away") == AWAY_ACTION
    core.send_as("阿明", "1")
    assert "已經行動" in core.send_as("阿明", "/away").notice
    core.send_as("小華", "/away")
    assert engine.rounds == [{"阿明": "阿明往上爬", "小華": AWAY_ACTION}]
    assert "[背包]\n  阿明：" in core.send("/state").info[1]  # Each person's bag


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
    me = core.view("阿明")  # Reconnecting: the current turn's screen
    assert me.actor == "" and me.choices == [] and me.resumed and me.narration == "兩人在燈塔醒來。"
    assert me.history == []  # Still on the first turn, no earlier story
    assert core.view("小華").choices == ["小華往上爬", "小華躲起來"]


def test_send_as_rejects_fallen_characters(core):
    core.start()
    core.send("")
    for _ in range(2):
        act(core, "1")
        act(core, "1")  # Ming falls on turn 3
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
    """StoryCore with a real Engine (only Gemini is fake), played from the opening until someone falls."""
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
    assert core.waiting() == ["小華"] and reply.choices == ["逃走"]  # Ming has fallen; only Hua is left
    assert [(s.name, s.alive) for s in reply.characters] == [("阿明", False), ("小華", True)]
    assert ("小華", [("獲得", [("鑰匙", "plain")])]) in reply.changes
    assert load(isolated / "team.json", GameState).characters[0].alive is False
