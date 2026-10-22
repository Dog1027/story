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

    async def show_narration(self, text):
        self.record("show_narration", text)

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

    async def ask_name(self, claim, hint=""):
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


def test_status_line_warns_only_when_in_danger_and_hides_the_inventory():
    fine = status_line(Status(turn=3, level="受傷", body=[("疲勞", "中")], mind=[("恐懼", "輕")], inventory=["鑰匙"]), [], timed=False)
    assert fine.mode == "一般模式" and not fine.party
    assert fine.characters[0].warning == "" and fine.characters[0].items == [("疲勞", "中"), ("恐懼", "輕")]
    danger = status_line(Status(turn=3, level="瀕死", body=[("失血", "重")], mind=[], inventory=[], warning="瀕死"), [], timed=True)
    assert danger.characters[0].warning == "瀕死" and danger.mode == "限時模式"
    empty = status_line(Status(turn=1, level="良好", body=[], mind=[], inventory=[]), [], timed=False)
    assert empty.characters[0].items == [("良好", "良好")]
    party = status_line(None, [Status(turn=2, level="良好", body=[], mind=[], inventory=[], name="阿明", alive=False)], timed=False)
    assert party.party and party.characters[0].name == "阿明" and not party.characters[0].alive
