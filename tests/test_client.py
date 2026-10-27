"""外殼共用層：用一個只記錄呼叫的假介面，確認「什麼時候顯示什麼」的流程。房間與大廳是真的，核心用真的 StoryCore，engine 用假的。"""

import asyncio

import pytest
from conftest import FakeEngine

import story.shells.client as client_module
from story.core import Reply
from story.games import GENRE_AUTO, GENRE_NONE, StoryCore
from story.core import Status
from story.shells.client import PremiseForm, View, status_line
from story.shells.connection import Connection
from story.shells.lobby import Lobby
from story.shells.room_client import RoomClient


class RecordingView(View):
    """記下 Client 呼叫了哪些方法；對話框照預先排好的答案回答。"""

    def __init__(self, premise="燈塔", timed=False, play_again=False):
        self.calls: list[tuple] = []
        self.premise, self.timed, self.play_again = premise, timed, play_again
        self.lobby_view = ""  # 最後一次大廳畫面的 view：lobby（大廳）或 room（房間的等人畫面）

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

    def mark_choice(self, index):
        self.record("mark_choice", index)

    def show_choices(self, choices):
        self.record("show_choices", choices)

    def set_hint(self, placeholder):
        self.record("set_hint", placeholder)

    def set_status(self, status):
        self.record("set_status", status)

    def show_lobby(self, screen):
        self.record("show_lobby", screen)
        self.lobby_view = screen["view"]

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


    async def ask_confirm(self, question, yes="確定", no="取消"):
        self.record("ask_confirm", question)
        return True

    async def ask_premise(self, form):
        self.record("ask_premise", form.default)
        return form.finish(self.premise, self.timed)

    async def ask_ending(self, title, record):
        self.record("ask_ending", title)
        return self.play_again

    async def ask_name(self, hint, error):
        return "阿明"

    def exit(self):
        self.record("exit")


async def until(condition, timeout: float = 3.0) -> None:
    """等到 condition() 成立（房間的回覆是非同步推來的）。"""
    async def wait():
        while not condition():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout)


@pytest.fixture
async def play(isolated):
    """連進真的大廳（核心用假的 engine）、開一個自己的房間、開始冒險，等開場顯示完。回傳 RoomClient。"""
    lobbies, tasks = [], []

    async def start(view: "RecordingView", engine=None) -> RoomClient:
        engine = engine or FakeEngine()
        lobby = Lobby(lambda players, on_queue, game: StoryCore(
            "test", players, save_path=isolated / "save.json", log_path=isolated / "log.jsonl", engine=engine))
        lobbies.append(lobby)
        client = RoomClient(view, lobby)
        tasks.append(asyncio.create_task(client.run()))
        await until(lambda: view.lobby_view == "lobby")
        await client.act("1")  # 開一個新房間
        await until(lambda: view.lobby_view == "room")
        await client.act("1")  # 開始冒險
        await until(lambda: ("show_choices", ["往上爬", "檢查鑰匙"]) in view.calls and "set_status" in view.names())
        if view.timed:
            await until(lambda: "start_timer" in view.names())
        await asyncio.sleep(0.05)  # 房間接著推來的訊息（還在等誰）也處理完
        return client

    yield start
    for task in tasks:
        task.cancel()
    for lobby in lobbies:
        await lobby.stop()


def after(view: RecordingView, name: str) -> list[str]:
    """某個呼叫之後依序呼叫了哪些方法。"""
    names = view.names()
    return names[len(names) - names[::-1].index(name) :]


async def test_new_story_shows_premise_then_the_opening(play):
    view = RecordingView()
    await play(view)
    assert "ask_premise" in view.names()
    assert ("clear_story", "燈塔") in view.calls  # 先顯示前提，再等 AI 寫開場
    assert view.names().index("clear_story") < view.names().index("show_narration")
    assert ("show_choices", ["往上爬", "檢查鑰匙"]) in view.calls


async def test_a_turn_reveals_choices_and_status_only_after_the_narration(play):
    view = RecordingView(timed=True)
    client = await play(view)
    view.calls.clear()
    await client.act("1")
    await until(lambda: "start_timer" in view.names())
    assert ("show_action", "你選擇了「往上爬」。") not in view.calls and ("show_action", "往上爬") in view.calls
    order = [n for n in view.names() if n in ("show_action", "prepare_choices", "show_narration", "show_changes", "show_choices", "set_status", "start_timer")]
    # 送出時先收起選項、顯示行動；劇情顯示完才出現變化、選項、狀態，大家看完才開始倒數
    assert order == ["show_choices", "show_action", "prepare_choices", "show_narration", "show_changes", "show_choices", "set_status", "start_timer"]
    assert ("prepare_choices", ["點亮油燈", "躲起來"], True) in view.calls  # 限時：介面可以先空出倒數條
    status = [c[1] for c in view.calls if c[0] == "set_status"][-1]
    assert status.turn == 2 and status.mode == "限時模式"
    assert status.characters[0].items == [["小腿挫傷", "moderate"]]  # 經過房間的 JSON：tuple 變成 list


async def test_ending_appears_one_part_at_a_time(play):
    view = RecordingView()
    client = await play(view)
    await client.act("1")
    await until(lambda: ("show_choices", ["點亮油燈", "躲起來"]) in view.calls)
    view.calls.clear()
    await client.act("2")  # 第 3 回合故事結束
    await until(lambda: "exit" in view.names())
    order = after(view, "show_action")
    expected = ["wait_enter", "show_ending_title", "show_narration", "wait_enter", "ask_ending", "exit"]
    assert [n for n in order if n in expected][-6:] == expected
    hints = [c[1] for c in view.calls if c[0] == "wait_enter"]
    assert hints == ["按 Enter 看尾聲", "按 Enter 查看結局"]


def test_status_line_lists_conditions_and_the_core_warning():
    fine = status_line(3, [Status(conditions=[("疲勞", "moderate"), ("恐懼", "light")])], timed=False)
    assert fine.mode == "一般模式" and not fine.named
    assert fine.characters[0].warning == "" and fine.characters[0].items == [("疲勞", "moderate"), ("恐懼", "light")]
    danger = status_line(3, [Status(conditions=[("失血", "severe")], warning="dying", warning_text="瀕死")], timed=True)
    assert danger.characters[0].warning == "dying" and danger.characters[0].warning_text == "瀕死" and danger.mode == "限時模式"
    empty = status_line(1, [Status(conditions=[], fine="良好")], timed=False)  # 顯示的詞由玩法給
    assert empty.characters[0].items == [("良好", "healthy")]
    group = status_line(2, [Status(conditions=[], name="阿明", alive=False), Status(conditions=[], name="小華")], timed=False)
    assert group.named and group.characters[0].name == "阿明" and not group.characters[0].alive


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


async def test_narration_is_shown_while_the_ai_is_still_writing(play):
    view = RecordingView()
    client = await play(view, StreamingEngine())
    view.calls.clear()
    await client.act("1")
    await until(lambda: ("show_narration", "風雨中，你推開了燈塔的門。") in view.calls)
    names = view.names()
    assert names.index("start_narration") < names.index("prepare_choices")  # 回覆到之前就開始顯示
    extended = [c[1] for c in view.calls if c[0] == "extend_narration"]
    assert len(extended) > 2 and all(b.startswith(a) for a, b in zip(extended, extended[1:]))
    assert ("show_narration", "風雨中，你推開了燈塔的門。") in view.calls
    assert names.count("start_narration") == 1 and "show_busy" not in names[names.index("start_narration"):]


async def test_half_written_narration_is_taken_back_when_the_turn_fails(play):
    view = RecordingView()
    client = await play(view, StreamingEngine(fail=True))
    view.calls.clear()
    await client.act("1")
    await until(lambda: "discard_narration" in view.names() and "notify" in view.names())
    names = view.names()
    assert "start_narration" in names and "discard_narration" in names and "show_narration" not in names
    assert any(c[0] == "notify" and c[2] for c in view.calls)  # 出錯的通知
    assert client.draft == ""


# ---------- 新故事的對話框的規則 ----------


def premise_form(**replies):
    """假的核心：記下送出的指令，依最後一個指令回覆。"""
    sent = []

    async def request(*commands):
        sent.append(list(commands))
        await asyncio.sleep(0)
        return replies[commands[-1].split()[0]]

    reply = Reply(phase="ask_premise", premise_default="燈塔", genre="", genres=[("武俠", "江湖"), ("克蘇魯", "不可名狀")])
    return PremiseForm(reply, request), sent


async def test_premise_form_keeps_what_the_player_typed():
    form, sent = premise_form(**{"/genre": Reply(phase="ask_premise", premise_default="鏢局"), "/random": Reply(phase="ask_premise", premise_default="客棧")})
    assert form.genre == GENRE_AUTO and [v for _, v in form.genre_options()][:3] == [GENRE_AUTO, GENRE_NONE, "武俠"]
    assert form.genre_hint("武俠") == "江湖"
    assert await form.change_genre("武俠", "燈塔") == "鏢局"  # 沒改過：換成新題材的開頭
    assert await form.change_genre("武俠", "我自己寫的") is None  # 改過：保留
    assert await form.reroll("我自己寫的") == "客棧"  # 按了「換一個」：一定換
    assert sent[-1] == ["/genre 武俠", "/random"]
    assert form.finish("  ", True) == ("客棧", True, "武俠")  # 留白用預設的開頭
    assert form.finish(" 一個 \n人 ", False) == ("一個 人", False, "武俠")


async def test_premise_form_drops_results_overtaken_by_a_newer_action():
    form, _ = premise_form(**{"/genre": Reply(phase="ask_premise", premise_default="新的")})
    first = asyncio.create_task(form.change_genre("武俠", ""))
    second = asyncio.create_task(form.change_genre("克蘇魯", ""))
    assert await first is None and await second == "新的"
    assert form.genre == "克蘇魯"


async def test_premise_form_suggest_errors_are_raised_for_the_interface_to_show():
    form, _ = premise_form(**{"/suggest": Reply(phase="ask_premise", error="api", notice="額度用完了")})
    with pytest.raises(RuntimeError, match="額度用完了"):
        await form.suggest("")


# ---------- RoomClient 與房間的連線 ----------


async def test_room_hint_stops_waiting_once_the_story_ends():
    """最後一回合結束後，提示不再寫「等待 X 行動」（房間在結局時不會再送還在等誰）。"""
    view = RecordingView()
    client = RoomClient(view, lobby=None)
    client.waiting = ["小華"]
    await client.handle(Reply(phase="ending"))
    hints = [c[1] for c in view.calls if c[0] == "set_hint"]
    assert hints[-1] == client_module.UI["hint_input"]


async def test_room_client_stops_taking_input_when_the_connection_closes():
    client = RoomClient(RecordingView(), lobby=None)
    client.room, server = Connection.pair()
    assert client.ready
    server.close()
    assert not client.ready  # 再送會丟出 ConnectionError


async def test_premise_request_fails_instead_of_waiting_forever_when_the_room_is_gone():
    client = RoomClient(RecordingView(), lobby=None)
    client.room, server = Connection.pair()
    request = asyncio.create_task(client.premise_request("/genre 武俠", "/random"))
    await asyncio.sleep(0)
    server.close()
    await client.listen()
    with pytest.raises(ConnectionError):
        await asyncio.wait_for(request, 2)  # 沒修好時會一直等：逾時就是失敗


async def test_input_modes_switch_what_typing_does():
    """海龜湯：選「猜湯底」只切換方式（標出來、換提示），接著打的字用 /guess 送出；「放棄」不用打字，直接送出。"""
    from story.games.soup.game import INPUTS

    view = RecordingView()
    client = RoomClient(view, lobby=None)
    sent = []

    async def send(text, echo=""):
        sent.append((text, echo))

    client.send = send
    client.actor, client.inputs = "阿明", list(INPUTS)
    await client.act("他死了嗎")
    assert sent[-1] == ("/ask 他死了嗎", "提問：他死了嗎")  # 沒選就是提問
    await client.act("2")
    assert len(sent) == 1 and ("mark_choice", 1) in view.calls and view.calls[-1] == ("set_hint", INPUTS[1].hint)
    await client.act("母親錄的語音")
    assert sent[-1] == ("/guess 母親錄的語音", "猜湯底：母親錄的語音")
    await client.act("放棄")
    assert sent[-1] == ("/give_up", "放棄")
