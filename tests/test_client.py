"""The shells' shared layer: a fake interface that only records calls checks the "what to show when" flow. The rooms and lobby are real, the core is a real AdventureCore, and the engine is fake."""

import asyncio
from itertools import pairwise

import pytest
from conftest import FakeEngine, until

import story.shells.screen.client as client_module
from story.core import Reply, SetupForm, Status
from story.core.ai import AIFailed
from story.games import AdventureCore
from story.games.adventure.game import GENRE_AUTO, GENRE_NONE
from story.shells.connection import Connection
from story.shells.rooms.lobby import Lobby
from story.shells.screen.client import Client
from story.shells.screen.premise import PremiseFailed, PremiseForm
from story.shells.screen.view import View, status_line
from story.shells.web.hosting import game_choices


class RecordingView(View):
    """Records which methods Client called; dialogs answer with prearranged answers."""

    def __init__(self, premise="燈塔", timed=False, play_again=False):
        self.calls: list[tuple] = []
        self.premise, self.timed, self.play_again = premise, timed, play_again
        self.lobby_view = ""  # The view of the last lobby screen: lobby (the lobby) or room (a room's waiting screen)

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
        self.record("setup", form.default)
        return form.finish(self.premise, self.timed)

    async def ask_ending(self, title, record):
        self.record("ask_ending", title)
        return self.play_again

    async def ask_name(self, error, max_len):
        return "阿明"

    def exit(self):
        self.record("exit")


@pytest.fixture
async def play(isolated):
    """Connect to a real lobby (the core uses a fake engine), open your own room, start an adventure, and wait for the opening to show. Returns the Client."""
    lobbies, tasks = [], []

    async def start(view: RecordingView, engine=None) -> Client:
        engine = engine or FakeEngine()
        lobby = Lobby(game_choices(), lambda players, on_queue, game: AdventureCore(
            "test", players, save_path=isolated / "save.json", log_path=isolated / "log.jsonl", engine=engine))
        lobbies.append(lobby)
        client = Client(view, lobby.connect)
        tasks.append(asyncio.create_task(client.run()))
        await until(lambda: view.lobby_view == "lobby")
        await client.act("1")  # Open a new room
        await until(lambda: view.lobby_view == "room")
        await client.act("1")  # Start an adventure
        await until(lambda: ("show_choices", ["往上爬", "檢查鑰匙"]) in view.calls and "set_status" in view.names())
        if view.timed:
            await until(lambda: "start_timer" in view.names())
        await until(lambda: client.waiting)  # Also let the room's next message (who's still pending) be handled
        return client

    yield start
    for task in tasks:
        task.cancel()
    for lobby in lobbies:
        await lobby.stop()


def after(view: RecordingView, name: str) -> list[str]:
    """Which methods were called, in order, after a given call."""
    names = view.names()
    return names[len(names) - names[::-1].index(name) :]


async def test_new_story_shows_premise_then_the_opening(play):
    view = RecordingView()
    await play(view)
    assert "setup" in view.names()
    assert ("clear_story", "燈塔") in view.calls  # Show the premise first, then wait for the AI to write the opening
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
    # On sending, hide the choices and show the action first; changes, choices and status appear only after the narration, and the countdown starts once everyone has read it
    assert order == ["show_choices", "show_action", "prepare_choices", "show_narration", "show_changes", "show_choices", "set_status", "start_timer"]
    assert ("prepare_choices", ["點亮油燈", "躲起來"], True) in view.calls  # Timed: the interface can reserve room for the countdown bar
    status = [c[1] for c in view.calls if c[0] == "set_status"][-1]
    assert status.turn == 2 and status.mode == "限時模式"
    assert status.characters[0].items == [["小腿挫傷", "moderate"]]  # Through the room's JSON: tuples become lists


async def test_ending_appears_one_part_at_a_time(play):
    view = RecordingView()
    client = await play(view)
    await client.act("1")
    await until(lambda: ("show_choices", ["點亮油燈", "躲起來"]) in view.calls)
    view.calls.clear()
    await client.act("2")  # The story ends on turn 3
    await until(lambda: "exit" in view.names())
    order = after(view, "show_action")
    expected = ["wait_enter", "show_ending_title", "show_narration", "wait_enter", "ask_ending", "exit"]
    assert [n for n in order if n in expected][-6:] == expected
    hints = [c[1] for c in view.calls if c[0] == "wait_enter"]
    assert hints == ["按 Enter 看尾聲", "按 Enter 查看結局"]


def test_status_line_lists_conditions_and_the_core_warning():
    fine = status_line(3, [Status(items=[("疲勞", "moderate"), ("恐懼", "light")])], timed=False)
    assert fine.mode == "一般模式" and not fine.named
    assert fine.characters[0].warning == "" and fine.characters[0].items == [("疲勞", "moderate"), ("恐懼", "light")]
    danger = status_line(3, [Status(items=[("失血", "severe")], warning="dying", warning_text="瀕死")], timed=True)
    assert danger.characters[0].warning == "dying" and danger.characters[0].warning_text == "瀕死" and danger.mode == "限時模式"
    group = status_line(2, [Status(items=[], name="阿明", alive=False), Status(items=[], name="小華")], timed=False)
    assert group.named and group.characters[0].name == "阿明" and not group.characters[0].alive


class StreamingEngine(FakeEngine):
    """Writes narration slowly, a character at a time (updating draft), like a real AI streaming. With fail, errors out halfway."""

    def __init__(self, fail=False):
        super().__init__()
        self.draft, self.fail = "", fail

    def play_turn(self, state, actions):
        import time

        text = "風雨中，你推開了燈塔的門。"
        for i in range(1, len(text) + 1):
            self.draft = text[:i]
            time.sleep(0.03)
        self.draft = ""
        if self.fail:
            raise AIFailed("503 UNAVAILABLE")
        super().play_turn(state, actions)
        state.current_narration = text


async def test_narration_is_shown_while_the_ai_is_still_writing(play):
    view = RecordingView()
    client = await play(view, StreamingEngine())
    view.calls.clear()
    await client.act("1")
    await until(lambda: ("show_narration", "風雨中，你推開了燈塔的門。") in view.calls)
    names = view.names()
    assert names.index("start_narration") < names.index("prepare_choices")  # Starts showing before the reply arrives
    extended = [c[1] for c in view.calls if c[0] == "extend_narration"]
    assert len(extended) > 2 and all(b.startswith(a) for a, b in pairwise(extended))
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
    assert any(c[0] == "notify" and c[2] for c in view.calls)  # The error notice
    assert client.draft == ""


# ---------- The new story dialog's rules ----------


def premise_form(**replies):
    """A fake core: records the commands sent and replies by the last command."""
    sent = []

    async def request(*commands):
        sent.append(list(commands))
        await asyncio.sleep(0)
        return replies[commands[-1].split()[0]]

    menu = [(GENRE_AUTO, "自動", "AI 挑"), (GENRE_NONE, "不套用", "照一般的方式"), ("武俠", "題材：武俠", "江湖"), ("克蘇魯", "題材：克蘇魯", "不可名狀")]
    reply = Reply(phase="setup", form=SetupForm(default="燈塔", genres=menu))  # The game gives the menu
    return PremiseForm(reply, request), sent


async def test_premise_form_keeps_what_the_player_typed():
    form, sent = premise_form(**{"/genre": Reply(phase="setup", form=SetupForm(default="鏢局")), "/random": Reply(phase="setup", form=SetupForm(default="客棧"))})
    assert form.genre == GENRE_AUTO and [v for _, v in form.genre_options()][:3] == [GENRE_AUTO, GENRE_NONE, "武俠"]
    assert form.genre_hint("武俠") == "江湖"
    assert await form.change_genre("武俠", "燈塔") == "鏢局"  # Untouched: switch to the new genre's opening
    assert await form.change_genre("武俠", "我自己寫的") is None  # Edited: keep it
    assert await form.reroll("我自己寫的") == "客棧"  # Pressed "another one": always replace
    assert sent[-1] == ["/genre 武俠", "/random"]
    assert form.finish("  ", True) == ("客棧", True, "武俠")  # Blank uses the default opening
    assert form.finish(" 一個 \n人 ", False) == ("一個 人", False, "武俠")


def test_premise_form_builds_the_commands_that_apply_its_choices():
    """Before starting: the mode only if it changed, then the genre picked in the dialog."""
    form, _ = premise_form()
    assert form.setup_commands(True) == ["/timed on", f"/genre {GENRE_AUTO}"]
    assert form.setup_commands(False) == [f"/genre {GENRE_AUTO}"]


async def test_premise_form_drops_results_overtaken_by_a_newer_action():
    form, _ = premise_form(**{"/genre": Reply(phase="setup", form=SetupForm(default="新的"))})
    first = asyncio.create_task(form.change_genre("武俠", ""))
    second = asyncio.create_task(form.change_genre("克蘇魯", ""))
    assert await first is None and await second == "新的"
    assert form.genre == "克蘇魯"


async def test_premise_form_errors_are_raised_for_the_interface_to_show():
    failed = Reply(phase="setup", error="api", notice="額度用完了")
    form, _ = premise_form(**{"/suggest": failed, "/random": failed, "/genre": failed})
    for action in (form.suggest(""), form.reroll(""), form.change_genre("武俠", "")):
        with pytest.raises(PremiseFailed, match="額度用完了"):
            await action


# ---------- The connection to the room ----------


async def test_room_hint_stops_waiting_once_the_story_ends():
    """After the last turn, the hint no longer says "waiting for X" (the room stops sending who's pending at the ending)."""
    view = RecordingView()
    client = Client(view, connect=None)
    client.waiting = ["小華"]
    await client.show_reply(Reply(phase="ending"))
    hints = [c[1] for c in view.calls if c[0] == "set_hint"]
    assert hints[-1] == client_module.UI["hint_input"]


async def test_long_input_is_cut_before_it_reaches_the_room():
    """Whatever a browser sends, at most MAX_INPUT_LEN characters go on to the core (and into prompts on the host's key)."""
    client = Client(RecordingView(), connect=None)
    client.conn, server = Connection.pair()
    await client.send("長" * (client_module.MAX_INPUT_LEN + 50))
    assert len((await server.receive())["text"]) == client_module.MAX_INPUT_LEN


async def test_client_stops_taking_input_when_the_connection_closes():
    client = Client(RecordingView(), connect=None)
    client.conn, server = Connection.pair()
    assert client.ready
    server.close()
    assert not client.ready  # Sending again would raise ConnectionError


async def test_premise_dialog_request_fails_instead_of_waiting_forever_when_the_room_is_gone():
    client = Client(RecordingView(), connect=None)
    client.conn, server = Connection.pair()
    request = asyncio.create_task(client.ask_room("/genre 武俠", "/random"))
    await asyncio.sleep(0)
    server.close()
    await client.listen()
    with pytest.raises(ConnectionError):
        await asyncio.wait_for(request, 2)  # Without the fix it waits forever: a timeout means failure


async def test_premise_dialog_replies_are_matched_to_their_request_by_id():
    """Two requests in flight: each reply goes to the request with the same id, whatever order they come back in."""
    client = Client(RecordingView(), connect=None)
    client.conn, server = Connection.pair()
    listening = asyncio.create_task(client.listen())
    first = asyncio.create_task(client.ask_room("/genre 武俠"))
    second = asyncio.create_task(client.ask_room("/random"))
    sent = [await server.receive(), await server.receive()]
    ids = {m["text"]: m["answer"] for m in sent}
    for text, premise in (("/random", "客棧"), ("/genre 武俠", "鏢局")):  # Answered in the other order
        reply = Reply(phase="setup", form=SetupForm(default=premise))
        await server.send({"type": "premise", "id": ids[text], "reply": reply.to_dict()})
    assert (await first).form.default == "鏢局" and (await second).form.default == "客棧"
    server.close()
    await listening


async def test_input_modes_switch_what_typing_does():
    """Turtle soup: picking "guess" only switches modes (marked, with a new hint), and what's typed next is sent with /guess; "give up" needs no text and is sent at once."""
    from story.games.soup.game import INPUTS

    view = RecordingView()
    client = Client(view, connect=None)
    sent = []

    async def send(text, echo=""):
        sent.append((text, echo))

    client.send = send
    client.actor, client.inputs = "阿明", list(INPUTS)
    await client.act("他死了嗎")
    assert sent[-1] == ("/ask 他死了嗎", "提問：他死了嗎")  # Not picking a mode means asking
    await client.act("2")
    assert len(sent) == 1 and ("mark_choice", 1) in view.calls and view.calls[-1] == ("set_hint", INPUTS[1].hint)
    await client.act("母親錄的語音")
    assert sent[-1] == ("/guess 母親錄的語音", "猜湯底：母親錄的語音")
    await client.act("放棄")
    assert sent[-1] == ("/give_up", "放棄")
