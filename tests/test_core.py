"""核心的文字協定：送文字進去、檢查回覆。用 FakeEngine 精準控制每回合的結果。"""

import pytest
from conftest import FakeEngine, InvalidKeyError

from story.core import StoryCore
from story.core.engine import TIMEOUT_ACTION
from story.core.records import DEFAULT_PREMISE, load


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def core(engine, isolated):
    return StoryCore(api_key="test", engine=engine, save_path=isolated / "save.json")


def new_game(core, *inputs):
    core.start()
    for text in inputs:
        core.send(text)
    return core.send("")  # 用預設前提開始


# ---------- 開新局 ----------


def test_first_reply_asks_for_premise(core):
    reply = core.start()
    assert reply.phase == "ask_premise"
    assert reply.premise_default == DEFAULT_PREMISE
    assert DEFAULT_PREMISE in reply.text


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
    assert core.send("/timed").timed  # 沒有參數就切換
    reply = core.send("")
    assert reply.timed and core.state.timed_mode and reply.time_limit == 10


def test_unknown_command_while_asking_premise(core):
    core.start()
    reply = core.send("/xyz")
    assert reply.phase == "ask_premise" and "沒有 /xyz" in reply.notice


# ---------- 遊戲中 ----------


def test_choosing_by_number_and_reply_fields(core):
    new_game(core)
    reply = core.send("1")
    assert reply.narration == "你選擇了「往上爬」。"
    assert reply.status.turn == 2 and reply.status.level == "受傷"
    assert reply.status.body == [("小腿挫傷", "中")]
    assert reply.changes == [("新增", [("小腿挫傷（中）", "中")]), ("獲得", [("油燈", "plain")])]
    assert "回合 2｜狀態 受傷：小腿挫傷（中）" in reply.text


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
    assert reply.choices == ["往上爬", "檢查鑰匙"]
    assert core.send("/help").info[0] == "說明"
    assert core.state.turn == 1


def test_unknown_command_and_empty_input_while_playing(core):
    new_game(core)
    assert "沒有 /xyz" in core.send("/xyz").notice
    assert "請輸入行動" in core.send("").notice
    assert core.state.turn == 1


def test_each_turn_is_saved(core, isolated):
    new_game(core)
    core.send("1")
    assert load(isolated / "save.json").turn == 2


def test_compaction_runs_in_background_and_is_awaited(core, engine):
    new_game(core)
    core.send("1")  # FakeEngine 在第 2 回合要求壓縮
    core.send("2")  # 下一回合前會先等壓縮完成
    assert engine.compacted == 1


# ---------- 錯誤 ----------


def test_invalid_key_keeps_state_and_can_retry(core, engine, isolated):
    new_game(core)
    engine.fail_with = InvalidKeyError()
    reply = core.send("1")
    assert reply.error == "api_key" and reply.phase == "playing"
    assert core.state.turn == 1  # 改了一半的狀態已從存檔還原
    core.set_api_key("新的 key")
    assert core.send("1").narration == "你選擇了「往上爬」。"
    assert engine.keys == ["新的 key"]


def test_other_api_error(core, engine):
    new_game(core)
    engine.fail_with = RuntimeError("模型輸出無法解析")
    reply = core.send("1")
    assert reply.error == "api" and "模型輸出無法解析" in reply.notice


# ---------- 重新開始、結局、讀檔 ----------


def test_restart_asks_for_confirmation(core):
    new_game(core)
    reply = core.send("/restart")
    assert reply.phase == "confirm_restart" and reply.choices == ["確定", "取消"]
    reply = core.send("2")
    assert reply.phase == "playing" and reply.choices == ["往上爬", "檢查鑰匙"]
    core.send("/restart")
    reply = core.send("1")
    assert reply.phase == "ask_premise" and reply.premise_default == DEFAULT_PREMISE


def test_ending_epilogue_and_play_again(core):
    new_game(core)
    core.send("1")
    reply = core.send("2")
    assert reply.phase == "ending" and "送出任何文字查看尾聲" in reply.text
    reply = core.send("")
    assert reply.phase == "ended"
    assert reply.ending.title == "燈塔守望者" and "共 3 回合" in reply.ending.record
    reply = core.send("1")
    assert reply.phase == "ask_premise"


def test_resume_from_save(engine, isolated):
    first = StoryCore(api_key="test", engine=engine, save_path=isolated / "save.json")
    new_game(first)
    first.send("1")

    second = StoryCore(api_key="test", engine=FakeEngine(), save_path=isolated / "save.json")
    reply = second.start()
    assert reply.phase == "ask_continue" and "第 2 回合" in reply.notice
    reply = second.send("1")
    assert reply.resumed and reply.narration == "你選擇了「往上爬」。"
    assert reply.choices == ["點亮油燈", "躲起來"]
    assert not second.send("1").resumed


def test_finished_save_starts_new_story(engine, isolated):
    core = StoryCore(api_key="test", engine=engine, save_path=isolated / "save.json")
    new_game(core)
    core.send("1")
    core.send("2")
    assert StoryCore(api_key="test", engine=FakeEngine(), save_path=isolated / "save.json").start().phase == "ask_premise"


def test_new_game_from_continue_prompt_reuses_premise(engine, isolated):
    core = StoryCore(api_key="test", engine=engine, save_path=isolated / "save.json")
    core.start()
    core.send("自訂的前提")
    reply = StoryCore(api_key="test", engine=FakeEngine(), save_path=isolated / "save.json")
    reply.start()
    assert reply.send("2").premise_default == "自訂的前提"
