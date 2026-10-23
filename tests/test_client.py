"""外殼共用層：用一個只記錄呼叫的假介面，確認「什麼時候顯示什麼」的流程。不需要 Textual，任何介面都適用。"""

import pytest
from conftest import FakeEngine, FakePartyEngine, InvalidKeyError

import story.shells.client as client_module
from story.core import GENRE_AUTO, PartyCore, StoryCore
from story.core.session import Status
from story.shells.client import Client, View, status_line


class RecordingView(View):
    """記下 Client 呼叫了哪些方法；對話框照預先排好的答案回答。"""

    def __init__(self, premise="燈塔", timed=False, keys=(), play_again=False):
        self.calls: list[tuple] = []
        self.premise, self.timed, self.keys, self.play_again = premise, timed, list(keys), play_again

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]

    def record(self, *call):
        self.calls.append(call)

    def clear_story(self, premise):
        self.record("clear_story", premise)

    def show_action(self, text):
        self.record("show_action", text)

    def show_note(self, text):
        self.record("show_note", text)

    def start_narration(self):
        self.record("start_narration")

    def extend_narration(self, text):
        self.record("extend_narration", text)

    async def finish_narration(self, text):
        self.record("show_narration", text)

    def discard_narration(self):
        self.record("discard_narration")

    def show_changes(self, groups, name=""):
        self.record("show_changes", name)

    def show_ending_title(self, title):
        self.record("show_ending_title", title)

    async def wait_enter(self, hint):
        self.record("wait_enter", hint)

    def prepare_choices(self, choices, timed):
        self.record("prepare_choices", choices, timed)

    def show_choices(self, choices):
        self.record("show_choices", choices)

    def set_hint(self, title, placeholder):
        self.record("set_hint", title, placeholder)

    def set_status(self, status):
        self.record("set_status", status)

    def show_lobby(self, members):
        self.record("show_lobby", members)

    def set_busy(self, busy):
        self.record("set_busy", busy)

    def show_busy(self):
        self.record("show_busy")

    def start_timer(self, seconds):
        self.record("start_timer", seconds)

    def stop_timer(self):
        self.record("stop_timer")

    def notify(self, text, error=False, lasting=False):
        self.record("notify", text, error)

    def show_info(self, title, body):
        self.record("show_info", title)

    def show_fatal(self, text):
        self.record("show_fatal", text)

    async def ask_confirm(self, question, yes="確定", no="取消"):
        self.record("ask_confirm", question)
        return True

    async def ask_premise(self, reply, ask):
        self.record("ask_premise", reply.premise_default)
        return self.premise, self.timed, GENRE_AUTO

    async def ask_ending(self, title, record):
        self.record("ask_ending", title)
        return self.play_again

    async def ask_name(self, hint, error):
        return None

    async def ask_api_key(self, reason, can_save):
        self.record("ask_api_key", reason)
        return (self.keys.pop(0), False) if self.keys else None

    async def ask_party_names(self):
        return ["阿明", "小華"]

    def exit(self):
        self.record("exit")


@pytest.fixture
def engine(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(client_module, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=engine, **kw))
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    return engine


def after(view: RecordingView, name: str) -> list[str]:
    """某個呼叫之後依序呼叫了哪些方法。"""
    names = view.names()
    return names[len(names) - names[::-1].index(name) :]


async def test_new_story_shows_premise_then_the_opening(engine):
    view = RecordingView()
    client = Client(view)
    await client.run()
    assert "ask_premise" in view.names()
    assert ("clear_story", "燈塔") in view.calls  # 先顯示前提，再等 AI 寫開場
    assert view.names().index("clear_story") < view.names().index("show_narration")
    assert ("show_choices", ["往上爬", "檢查鑰匙"]) in view.calls


async def test_a_turn_reveals_choices_and_status_only_after_the_narration(engine):
    view = RecordingView(timed=True)
    client = Client(view)
    await client.run()
    view.calls.clear()
    await client.act("1")
    assert ("show_action", "你選擇了「往上爬」。") not in view.calls and ("show_action", "往上爬") in view.calls
    order = [n for n in view.names() if n in ("show_action", "prepare_choices", "show_narration", "show_changes", "show_choices", "set_status", "start_timer")]
    # 送出時先收起選項、顯示行動；劇情顯示完才出現變化、選項、狀態，最後才開始倒數
    assert order == ["show_choices", "show_action", "prepare_choices", "show_narration", "show_changes", "show_choices", "set_status", "start_timer"]
    assert ("prepare_choices", ["點亮油燈", "躲起來"], True) in view.calls  # 限時：介面可以先空出倒數條
    status = [c[1] for c in view.calls if c[0] == "set_status"][-1]
    assert status.turn == 2 and status.mode == "限時模式"
    assert status.characters[0].items == [("小腿挫傷", "中")]


async def test_ending_appears_one_part_at_a_time(engine):
    view = RecordingView()
    client = Client(view)
    await client.run()
    await client.act("1")
    view.calls.clear()
    await client.act("2")  # 第 3 回合故事結束
    order = after(view, "show_action")
    expected = ["wait_enter", "show_ending_title", "show_narration", "wait_enter", "ask_ending", "exit"]
    assert [n for n in order if n in expected][-6:] == expected
    hints = [c[1] for c in view.calls if c[0] == "wait_enter"]
    assert hints == ["按 Enter 看尾聲", "按 Enter 查看結局"]


async def test_invalid_key_asks_for_a_new_one_and_retries(engine):
    view = RecordingView(keys=["新的 key"])
    client = Client(view)
    await client.run()
    engine.fail_with = InvalidKeyError()
    await client.act("1")
    assert any(c[0] == "ask_api_key" and "無效" in c[1] for c in view.calls)
    assert engine.keys == ["新的 key"] and client.core.phase == "playing"
    assert ("show_choices", ["點亮油燈", "躲起來"]) in view.calls  # 換了 key 之後重送成功


async def test_local_party_shows_whose_action_it_is(engine, monkeypatch):
    monkeypatch.setattr(client_module, "PartyCore", lambda api_key, players: PartyCore(api_key, players, engine=FakePartyEngine()))
    view = RecordingView()
    client = Client(view, party=True)
    await client.run()
    assert client.actor == "阿明"
    assert ("set_hint", "輪到 阿明", "輪到 阿明：↑↓ 選擇，或寫下行動") in view.calls
    view.calls.clear()
    await client.act("1")
    assert ("show_action", "阿明：阿明往上爬") in view.calls
    assert "stop_timer" not in view.names()  # 多人的倒數以整回合為單位，換人時繼續跑


def test_status_line_lists_conditions_and_the_core_warning():
    fine = status_line(3, [Status(conditions=[("疲勞", "中"), ("恐懼", "輕")])], timed=False)
    assert fine.mode == "一般模式" and not fine.party
    assert fine.characters[0].warning == "" and fine.characters[0].items == [("疲勞", "中"), ("恐懼", "輕")]
    danger = status_line(3, [Status(conditions=[("失血", "重")], warning="瀕死")], timed=True)
    assert danger.characters[0].warning == "瀕死" and danger.mode == "限時模式"
    empty = status_line(1, [Status(conditions=[])], timed=False)
    assert empty.characters[0].items == [("良好", "良好")]
    party = status_line(2, [Status(conditions=[], name="阿明", alive=False)], timed=False)
    assert party.party and party.characters[0].name == "阿明" and not party.characters[0].alive


class StreamingEngine(FakeEngine):
    """一個字一個字慢慢寫劇情（更新 draft），像真的 AI 在串流。fail 時寫到一半出錯。"""

    def __init__(self, fail=False):
        super().__init__()
        self.draft, self.fail = "", fail

    def act(self, state, action):
        import time

        text = "風雨中，你推開了燈塔的門。"
        for i in range(1, len(text) + 1):
            self.draft = text[:i]
            time.sleep(0.03)
        self.draft = ""
        if self.fail:
            raise RuntimeError("503 UNAVAILABLE")
        super().act(state, action)
        state.current_narration = text


async def test_narration_is_shown_while_the_ai_is_still_writing(monkeypatch):
    engine = StreamingEngine()
    monkeypatch.setattr(client_module, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=engine, **kw))
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    view = RecordingView()
    client = Client(view)
    await client.run()
    view.calls.clear()
    await client.act("1")
    names = view.names()
    assert names.index("start_narration") < names.index("prepare_choices")  # 回覆到之前就開始顯示
    extended = [c[1] for c in view.calls if c[0] == "extend_narration"]
    assert len(extended) > 2 and all(b.startswith(a) for a, b in zip(extended, extended[1:]))
    assert ("show_narration", "風雨中，你推開了燈塔的門。") in view.calls
    assert names.count("start_narration") == 1 and "show_busy" not in names[names.index("start_narration"):]


async def test_half_written_narration_is_taken_back_when_the_turn_fails(monkeypatch):
    engine = StreamingEngine(fail=True)
    monkeypatch.setattr(client_module, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=engine, **kw))
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    view = RecordingView()
    client = Client(view)
    await client.run()
    view.calls.clear()
    await client.act("1")
    names = view.names()
    assert "start_narration" in names and "discard_narration" in names and "show_narration" not in names
    assert any(c[0] == "notify" and c[2] for c in view.calls)  # 出錯的通知
    assert client.draft == ""
