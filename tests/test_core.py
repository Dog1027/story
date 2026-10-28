"""The core's text protocol: send text in and check the replies. FakeEngine controls each turn's result exactly."""

import pytest
from conftest import HERO, FakeEngine, InvalidKeyError

from story.games import StoryCore
from story.games.adventure.prompting import TIMEOUT_ACTION
from story.core.saves import load
from story.games.adventure.models import GameState
from story.games.adventure.records import DEFAULT_PREMISE


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def core(engine, isolated):
    return StoryCore("test", [HERO], engine=engine, save_path=isolated / "save.json")


def new_game(core, *inputs):
    core.start()
    for text in inputs:
        core.send(text)
    return core.send("")  # Start with the default premise


# ---------- New game ----------


def test_first_reply_asks_for_premise(core):
    reply = core.start()
    assert reply.phase == "setup"
    assert reply.premise_default == DEFAULT_PREMISE


def test_blank_premise_uses_default(core):
    reply = new_game(core)
    assert reply.phase == "playing"
    assert core.state.premise == DEFAULT_PREMISE
    assert reply.narration == "你在燈塔醒來。"
    assert reply.choices == ["往上爬", "檢查鑰匙"]


def test_suggestion_becomes_the_default(core):
    core.start()
    reply = core.send("/suggest")
    assert reply.suggestion == reply.premise_default == "你是月球礦坑的夜班工程師。"
    core.send("")
    assert core.state.premise == "你是月球礦坑的夜班工程師。"


def test_custom_premise_whitespace_is_normalized(core):
    core.start()
    core.send("  你是一名\n郵差  ")
    assert core.state.premise == "你是一名 郵差"


def test_timed_toggle(core):
    core.start()
    assert core.send("/timed on").timed
    assert not core.send("/timed off").timed
    assert core.send("/timed").timed  # No argument toggles it
    reply = core.send("")
    assert reply.timed and core.state.timed_mode and reply.time_limit == 10


def test_unknown_command_while_asking_premise(core):
    core.start()
    reply = core.send("/xyz")
    assert reply.phase == "setup" and "沒有 /xyz" in reply.notice


# ---------- In a game ----------


def test_choosing_by_number_and_reply_fields(core):
    new_game(core)
    reply = core.send("1")
    assert reply.narration == "你選擇了「往上爬」。"
    assert reply.turn == 2 and reply.characters[0].items == [("小腿挫傷", "moderate")]
    assert reply.changes == [(HERO, [("新增", [("小腿挫傷（中）", "moderate")]), ("獲得", [("油燈", "plain")])])]


def test_free_text_action(core, engine):
    new_game(core)
    assert core.send("躲到桌子底下").narration == "你選擇了「躲到桌子底下」。"


@pytest.mark.parametrize("text, action", [
    ("1", "往上爬"), (" 2 ", "檢查鑰匙"), ("3", "3"), ("自由行動", "自由行動"),
    ("/timeout", TIMEOUT_ACTION), ("/state", None), ("", None),
])
def test_action_for(core, text, action):
    new_game(core)
    assert core.action_for(text) == action


def test_action_for_outside_game_is_none(core):
    core.start()
    assert core.action_for("1") is None


def test_timeout_sends_timeout_action(core):
    new_game(core)
    assert TIMEOUT_ACTION in core.send("/timeout").narration


def test_info_commands_do_not_advance_the_story(core):
    new_game(core)
    reply = core.send("/state")
    assert reply.info[0] == "程式記住的東西" and reply.narration == ""
    assert "[背包]\n  鑰匙" in reply.info[1]  # The status bar doesn't show the bag; the full contents are here
    assert reply.choices == ["往上爬", "檢查鑰匙"]
    assert core.send("/help").info[0] == "說明"
    assert core.state.turn == 1


def test_status_warns_only_when_the_next_wound_could_kill(core):
    """Which severities to warn about is a game rule (defined in the adventure along with the death threshold); shells use Status.warning and its word directly."""
    from story.games.adventure.models import Condition

    new_game(core)
    fine = core.send("/state").characters[0]
    assert fine.warning == "" and fine.items == [("良好", "healthy")]  # The word shown with no conditions also comes from the game
    core.state.characters[0].conditions = [Condition(name="失血", kind="body", severity="severe")]
    reply = core.send("/state")
    assert reply.characters[0].warning == "serious" and reply.characters[0].warning_text == "重傷"
    core.state.characters[0].conditions = [Condition(name="疲勞", kind="body", severity="moderate"), Condition(name="恐懼", kind="mind", severity="severe")]
    assert core.send("/state").characters[0].warning == ""  # Moderate fatigue and mind conditions are never fatal


def test_unknown_command_and_empty_input_while_playing(core):
    new_game(core)
    assert "沒有 /xyz" in core.send("/xyz").notice
    assert "請輸入行動" in core.send("").notice
    assert core.state.turn == 1


def test_each_turn_is_saved(core, isolated):
    new_game(core)
    core.send("1")
    assert load(isolated / "save.json", GameState).turn == 2


def test_compaction_runs_in_background_and_is_awaited(core, engine):
    new_game(core)
    core.send("1")  # FakeEngine asks for compaction on turn 2
    core.send("2")  # The next turn waits for compaction to finish first
    assert engine.compacted == 1


# ---------- Errors ----------


def test_invalid_key_keeps_state_and_can_retry(core, engine, isolated):
    new_game(core)
    engine.fail_with = InvalidKeyError()
    reply = core.send("1")
    assert reply.error == "api" and reply.phase == "playing" and "架站的人" in reply.notice  # Players can't change the server's key
    assert core.state.turn == 1  # The half-changed state was restored from the save
    engine.fail_with = None
    assert core.send("1").narration == "你選擇了「往上爬」。"


def test_other_api_error(core, engine):
    new_game(core)
    engine.fail_with = RuntimeError("模型輸出無法解析")
    reply = core.send("1")
    assert reply.error == "api" and "模型輸出無法解析" in reply.notice


# ---------- Restart, ending, loading ----------


def test_restart_asks_for_confirmation(core):
    new_game(core)
    reply = core.send("/restart")
    assert reply.phase == "confirm_restart" and reply.choices == ["確定", "取消"]
    reply = core.send("2")
    assert reply.phase == "playing" and reply.choices == ["往上爬", "檢查鑰匙"]
    core.send("/restart")
    reply = core.send("1")
    assert reply.phase == "setup" and reply.premise_default == DEFAULT_PREMISE


def test_ending_epilogue_and_play_again(core):
    new_game(core)
    core.send("1")
    reply = core.send("2")
    assert reply.phase == "ending"
    reply = core.send("")
    assert reply.phase == "ended"
    assert reply.ending.title == "燈塔守望者" and "共 3 回合" in reply.ending.record
    reply = core.send("1")
    assert reply.phase == "setup"


def test_resume_from_save(engine, isolated):
    first = StoryCore("test", [HERO], engine=engine, save_path=isolated / "save.json")
    new_game(first)
    first.send("1")

    second = StoryCore("test", [HERO], engine=FakeEngine(), save_path=isolated / "save.json")
    reply = second.start()
    assert reply.phase == "ask_continue" and "第 2 回合" in reply.notice
    reply = second.send("1")
    assert reply.resumed and reply.narration == "你選擇了「往上爬」。"
    assert reply.choices == ["點亮油燈", "躲起來"]
    (opening, action), = reply.history  # The earlier story comes back too; playing alone, actions have no name in front
    assert opening and action == "往上爬" and not reply.history_trimmed
    assert not second.send("1").resumed


def test_finished_save_starts_new_story(engine, isolated):
    core = StoryCore("test", [HERO], engine=engine, save_path=isolated / "save.json")
    new_game(core)
    core.send("1")
    core.send("2")
    assert StoryCore("test", [HERO], engine=FakeEngine(), save_path=isolated / "save.json").start().phase == "setup"


def test_new_game_from_continue_prompt_reuses_premise(engine, isolated):
    core = StoryCore("test", [HERO], engine=engine, save_path=isolated / "save.json")
    core.start()
    core.send("自訂的前提")
    reply = StoryCore("test", [HERO], engine=FakeEngine(), save_path=isolated / "save.json")
    reply.start()
    assert reply.send("2").premise_default == "自訂的前提"


def test_progress_tells_what_the_opening_is_doing(isolated):
    """Starting a new story calls the AI twice: progress is "planning the story outline", then "writing the opening", and is cleared afterwards."""
    from conftest import beat, make_engine

    engine, gemini = make_engine(beat(narration="燈塔的門吱呀一聲打開。"))
    core = StoryCore("test", [HERO], engine=engine, save_path=isolated / "save.json")
    seen = []
    generate = gemini.generate_content
    gemini.models.generate_content = lambda **kw: (seen.append(core.progress), generate(**kw))[1]
    core.start()
    core.send("")
    assert seen == ["規劃故事大綱", "寫開場"]
    assert core.progress == ""
