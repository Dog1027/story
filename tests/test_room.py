"""The web lobby and rooms: connect to the lobby with connect(), open or join rooms, and simulate several players playing together. The core is a real AdventureCore and the engine is fake."""

import asyncio

import pytest
from conftest import PUZZLE, FakeGroupEngine, FakeJudge

import story.shells.rooms.lobby as lobby_module
from story.core import Reply
from story.games import AdventureCore, SoupCore
from story.games.adventure.prompting import AWAY_ACTION
from story.shells.connection import Connection
from story.shells.rooms.lobby import Lobby
from story.shells.web.hosting import game_choices


class Player:
    """A player connected to a room: keeps every message received, for checking."""

    def __init__(self, conn: Connection):
        self.conn = conn
        self.messages: list[dict] = []

    async def send(self, text: str) -> None:
        await self.conn.send({"type": "send", "text": text})

    async def expect(self, condition, timeout: float = 3.0) -> dict:
        """Wait for a message matching the condition (including ones received earlier and not yet waited for), then return and remove it."""
        async def wait():
            seen = 0
            while True:
                for message in self.messages[seen:]:
                    if condition(message):
                        self.messages.remove(message)
                        return message
                seen = len(self.messages)
                message = await self.conn.receive()
                assert message is not None, "連線被關閉了"
                self.messages.append(message)

        return await asyncio.wait_for(wait(), timeout)

    async def reply(self, condition=lambda r: True) -> Reply:
        message = await self.expect(lambda m: m["type"] == "reply" and condition(Reply.from_dict(m["reply"])))
        return Reply.from_dict(message["reply"])


def make_lobby(isolated, engine=None) -> Lobby:
    """Every game's core uses the same fake engine (lobby.engine), to check what the AI received."""
    engine = engine or FakeGroupEngine()
    def make_core(players, on_queue, game="adventure"):
        if game == "soup":
            return SoupCore("test", players, save_path=isolated / "soup.json", judge=FakeJudge(), puzzles=[PUZZLE])
        return AdventureCore("test", players, save_path=isolated / "team.json", log_path=isolated / "team.log.jsonl", engine=engine)

    lobby = Lobby(game_choices(), make_core)
    lobby.engine = engine
    return lobby


@pytest.fixture
async def lobby(isolated):
    lobby = make_lobby(isolated)
    yield lobby
    await lobby.stop()


def room_of(lobby) -> object:
    return lobby.rooms[0]


async def join(lobby, name: str, token: str = "") -> Player:
    """Connect to the lobby and enter with this name. token is the ID the browser remembers."""
    conn = lobby.connect()
    await conn.send({"type": "join", "name": name, "token": token})
    answer = await conn.receive()
    assert answer == {"type": "joined"}, answer
    return Player(conn)


def is_lobby(title: str = "大廳"):
    return lambda m: m["type"] == "lobby" and m["title"] == title


async def open_room(player: Player) -> None:
    """Choose "open a new room" in the lobby (the first option)."""
    screen = await player.expect(is_lobby())
    assert screen["choices"][0] == "開一個新房間"
    await player.send("1")


async def enter_room(player: Player, host: str) -> None:
    """Choose "join host's room" in the lobby."""
    screen = await player.expect(lambda m: is_lobby()(m) and any(host in c for c in m["choices"]))
    await player.send(str(next(i for i, c in enumerate(screen["choices"], 1) if host in c)))


async def gather(lobby, *names: str) -> list[Player]:
    """The first person opens a room and the others join; everyone is on the room's waiting screen."""
    players = [await join(lobby, names[0])]
    await open_room(players[0])
    await players[0].expect(is_lobby(f"{names[0]} 的房間"))
    for name in names[1:]:
        player = await join(lobby, name)
        await enter_room(player, names[0])
        await player.expect(is_lobby(f"{names[0]} 的房間"))
        players.append(player)
    return players


async def start_story(lobby) -> tuple[Player, Player]:
    host, guest = await gather(lobby, "阿明", "小華")
    await host.expect(lambda m: is_lobby("阿明 的房間")(m) and m["members"] == ["阿明", "小華"] and m["host"] == "阿明")
    await host.send("1")  # Start the adventure
    assert (await host.reply()).phase == "setup"
    await guest.expect(lambda m: m["type"] == "notice" and "房主正在準備這一局" in m["text"])
    await host.send("燈塔")
    return host, guest


async def test_two_players_play_a_round_in_any_order(lobby):
    host, guest = await start_story(lobby)
    await guest.expect(lambda m: m["type"] == "new_story" and m["premise"] == "燈塔")  # The others see the premise first too
    mine, theirs = await host.reply(), await guest.reply()
    assert mine.narration == theirs.narration == "兩人在燈塔醒來。"
    assert mine.actor == "阿明" and mine.choices == ["阿明往上爬", "阿明躲起來"]
    assert theirs.actor == "小華" and theirs.choices == ["小華往上爬", "小華躲起來"]

    await guest.send("2")  # Hua acts first
    acted = await guest.reply()
    assert acted.choices == [] and acted.notice == ""
    await host.expect(lambda m: m["type"] == "waiting" and m["names"] == ["阿明"])

    await host.send("1")
    await guest.expect(lambda m: m["type"] == "busy" and m["on"])
    assert (await guest.reply(lambda r: bool(r.narration))).narration == "阿明阿明往上爬；小華小華躲起來"
    assert lobby.engine.rounds == [{"阿明": "阿明往上爬", "小華": "小華躲起來"}]


async def test_names_are_unique_on_the_whole_server_and_rooms_have_a_limit(lobby):
    first = await join(lobby, "阿明")
    conn = lobby.connect()
    await conn.send({"type": "join", "name": "阿明"})
    assert "已經有人在用" in (await conn.receive())["reason"]
    await conn.send({"type": "join", "name": "../x"})
    assert "只能包含" in (await conn.receive())["reason"]
    await conn.send({"type": "join", "name": "小華"})  # After being refused, you can try another name
    assert await conn.receive() == {"type": "joined"}

    await open_room(first)
    for name in ("小華", "小美", "阿華"):  # Up to the 4th person
        player = Player(conn) if name == "小華" else await join(lobby, name)
        await enter_room(player, "阿明")
    fifth = await join(lobby, "阿強")
    screen = await fifth.expect(is_lobby())
    assert screen["choices"] == ["開一個新房間"]  # Full rooms aren't listed


async def test_only_team_members_can_rejoin_after_start(lobby):
    host, guest = await start_story(lobby)
    await guest.reply()
    stranger = await join(lobby, "路人")
    screen = await stranger.expect(is_lobby())
    assert screen["choices"] == ["開一個新房間"] and [r["state"] for r in screen["rooms"]] == ["playing"]


async def test_only_host_answers_dialogs_and_restarts(lobby):
    host, guest = await start_story(lobby)
    await guest.reply()
    await guest.send("/restart")
    await guest.expect(lambda m: m["type"] == "notice" and "只有房主" in m["text"])
    await guest.send("/timeout")  # Players can't call time for everyone
    await guest.send("/state")
    assert (await guest.reply(lambda r: r.info is not None)).info[0] == "程式記住的東西"
    assert lobby.engine.rounds == []


async def test_disconnected_players_rejoin_or_are_skipped(lobby):
    host, guest = await start_story(lobby)
    await host.reply()
    await guest.reply()
    guest.conn.close()
    await host.expect(lambda m: m["type"] == "notice" and "小華 離線了" in m["text"])

    back = await join(lobby, "小華")  # Back with the same name: straight to the original room, seeing the current turn
    view = await back.reply()
    assert view.resumed and view.narration == "兩人在燈塔醒來。" and view.actor == "小華"

    back.conn.close()
    await host.expect(lambda m: m["type"] == "notice" and "小華 離線了" in m["text"])
    await host.send("1")  # Everyone online has acted: send "away" for Hua, who's offline
    await host.reply(lambda r: bool(r.narration))
    assert lobby.engine.rounds == [{"阿明": "阿明往上爬", "小華": AWAY_ACTION}]


async def test_the_same_browser_takes_over_its_old_connection(lobby):
    """The old tab hasn't dropped (e.g. a phone in the background) and the same browser comes in again with the same name: the new connection takes the same seat."""
    first = await join(lobby, "阿明", token="browser-1")
    await open_room(first)
    await first.expect(is_lobby("阿明 的房間"))
    await first.send("1")  # Start the adventure
    assert (await first.reply()).phase == "setup"
    await first.send("燈塔")
    await first.reply(lambda r: bool(r.narration))

    second = await join(lobby, "阿明", token="browser-1")
    await first.expect(lambda m: m["type"] == "replaced")
    view = await second.reply()
    assert view.resumed and view.narration and view.actor == "阿明"
    await asyncio.sleep(0.05)  # The old connection ended
    assert len(lobby.rooms) == 1 and lobby.people["阿明"] is not first.conn  # The room didn't close when the old connection left
    await second.send("1")
    await second.reply(lambda r: bool(r.narration))
    assert lobby.engine.rounds == [{"阿明": "阿明往上爬"}]


async def test_other_browsers_cannot_take_a_name_in_use(lobby):
    await join(lobby, "阿明", token="browser-1")
    for token in ("browser-2", ""):
        conn = lobby.connect()
        await conn.send({"type": "join", "name": "阿明", "token": token})
        answer = await conn.receive()
        assert answer["type"] == "rejected" and "已經有人在用" in answer["reason"]
        conn.close()


async def test_host_leaving_passes_the_dialog_to_the_next_player(lobby):
    host, guest = await gather(lobby, "阿明", "小華")
    await host.send("1")
    await host.reply()  # The host gets the premise dialog
    host.conn.close()
    assert (await guest.reply()).phase == "setup"  # Hua becomes the host


class TimedEngine(FakeGroupEngine):
    def start(self, state):
        super().start(state)
        state.current_time_limit = 1


async def test_countdown_starts_after_everyone_has_read_then_times_out(isolated):
    lobby = make_lobby(isolated, TimedEngine())
    try:
        host, guest = await start_story(lobby)
        await host.reply()
        await guest.reply()
        await host.conn.send({"type": "ready"})
        await asyncio.sleep(0.1)
        assert not any(m["type"] == "timer" for m in host.messages)  # Hua hasn't finished reading
        await guest.conn.send({"type": "ready"})
        assert (await host.expect(lambda m: m["type"] == "timer"))["seconds"] == 1
        await host.reply(lambda r: bool(r.narration))  # Time's up; the room advances for everyone
        assert room_of(lobby).core.state.turn == 2
    finally:
        await lobby.stop()


async def test_game_end_returns_to_lobby(lobby, monkeypatch):
    host, guest = await start_story(lobby)
    await host.reply()
    for _ in range(3):  # Ming falls on turn 3, and it ends on turn 4
        if room_of(lobby).core.waiting() and "阿明" in room_of(lobby).core.waiting():
            await host.send("1")
        await guest.send("1")
        await guest.reply(lambda r: bool(r.narration) or r.phase == "ended")
    ended = await host.reply(lambda r: r.phase == "ended")
    assert ended.ending.title == "燈塔雙人行"
    await host.expect(is_lobby("阿明 的房間"))  # Back to the room's waiting screen, ready for another game
    assert room_of(lobby).core is None


async def test_failed_timeout_round_restarts_the_countdown(isolated):
    engine = TimedEngine()
    lobby = make_lobby(isolated, engine)
    try:
        host, guest = await start_story(lobby)
        await host.reply()
        await guest.reply()
        engine.fail_with = RuntimeError("503 UNAVAILABLE")
        for player in (host, guest):
            await player.conn.send({"type": "ready"})
        await host.expect(lambda m: m["type"] == "timer")
        failed = await guest.reply(lambda r: r.error == "api")  # Time's up, advancing fails
        assert failed.choices == ["小華往上爬", "小華躲起來"]  # Everyone must choose again
        await host.expect(lambda m: m["type"] == "timer")  # The countdown restarts
        engine.fail_with = None
        await host.send("1")
        await guest.send("2")
        await host.reply(lambda r: bool(r.narration))
        assert engine.rounds == [{"阿明": "阿明往上爬", "小華": "小華躲起來"}]
    finally:
        await lobby.stop()


class SlowOpeningEngine(FakeGroupEngine):
    """The opening has two stages that each take a little time, simulating two real AI calls."""

    def start(self, state):
        import time

        for self.stage in ("規劃故事大綱", "寫開場"):
            time.sleep(0.5)
        self.stage = ""
        super().start(state)


async def test_everyone_sees_the_opening_progress(isolated):
    lobby = make_lobby(isolated, SlowOpeningEngine())
    try:
        host, guest = await start_story(lobby)
        for stage in ("規劃故事大綱", "寫開場"):
            await guest.expect(lambda m, stage=stage: m["type"] == "busy" and m.get("progress") == stage)
        await guest.reply(lambda r: bool(r.narration))
    finally:
        await lobby.stop()


async def test_host_genre_choice_reaches_the_core(isolated):
    from story.games.adventure.genres import Genre

    class GenreEngine(FakeGroupEngine):
        genres = {"武俠": Genre(name="武俠", description="江湖恩怨", guide="用古白話。")}

    lobby = make_lobby(isolated, GenreEngine())
    try:
        host, guest = await gather(lobby, "阿明", "小華")
        await host.send("1")
        premise_reply = await host.reply()
        assert premise_reply.genres[-1] == ["武俠", "題材：武俠", "江湖恩怨"]  # Through JSON, tuples become lists
        await host.send("/genre 武俠")  # Choices in the premise dialog: no reply needed
        await host.send("鏢局")
        await guest.reply(lambda r: bool(r.narration))
        assert room_of(lobby).core.state.genre == "武俠"
    finally:
        await lobby.stop()


async def test_only_commands_asking_for_an_answer_get_one(lobby):
    host, guest = await gather(lobby, "阿明", "小華")
    await host.send("1")
    await host.reply()
    await host.conn.send({"type": "send", "text": "/timed on", "form": True})  # An action in the dialog, with no reply requested
    await host.conn.send({"type": "send", "text": "/random", "form": True, "answer": True})
    answer = await host.expect(lambda m: m["type"] == "premise")
    assert Reply.from_dict(answer["reply"]).phase == "setup"
    assert not any(m["type"] == "premise" for m in host.messages)  # Only one reply


async def test_one_player_can_start_alone(lobby):
    host = await join(lobby, "阿明")
    await open_room(host)
    screen = await host.expect(is_lobby("阿明 的房間"))
    assert screen["members"] == ["阿明"] and screen["choices"] == ["開始冒險", "開始海龜湯", "離開房間"]
    await host.send("1")
    assert (await host.reply()).phase == "setup"
    await host.send("燈塔")
    assert (await host.reply(lambda r: bool(r.narration))).choices == ["阿明往上爬", "阿明躲起來"]


class StreamingGroupEngine(FakeGroupEngine):
    """Writes narration slowly while advancing a turn (updating draft), like a real AI streaming."""

    def act(self, state, actions):
        import time

        for i in range(1, 6):
            self.draft = "大家往上爬"[:i]
            time.sleep(0.15)
        self.draft = ""
        super().act(state, actions)


async def test_everyone_sees_the_narration_while_it_is_written(isolated):
    lobby = make_lobby(isolated, StreamingGroupEngine())
    try:
        host, guest = await start_story(lobby)
        await host.reply()
        await guest.reply()
        await guest.send("1")
        await host.send("1")
        draft = await guest.expect(lambda m: m["type"] == "draft")  # Received before the writing finishes
        assert "大家往上爬".startswith(draft["text"])
        await guest.reply(lambda r: bool(r.narration))
    finally:
        await lobby.stop()


class StuckEngine(FakeGroupEngine):
    """The AI takes its time with a turn until the test lets it go."""

    def __init__(self):
        import threading

        super().__init__()
        self.release = threading.Event()

    def act(self, state, actions):
        self.release.wait(5)
        super().act(state, actions)


async def test_coming_back_while_the_room_stands_in_for_you_still_gets_the_turn(isolated):
    """Someone drops while the room is idle, so the room sends "away" for them and the AI writes the turn; they come back meanwhile.
    They must still get the current screen once the AI is done (catching up happens after standing in, not before)."""
    engine = StuckEngine()
    lobby = make_lobby(isolated, engine)
    try:
        host, guest = await start_story(lobby)
        await host.reply()
        await guest.reply()
        await host.send("1")
        await host.reply(lambda r: not r.actor)  # Ming has acted and the room is idle again
        guest.conn.close()  # Hua drops: the room stands in for them and the AI starts writing
        await host.expect(lambda m: m["type"] == "notice" and "小華 離線了" in m["text"])
        await host.expect(lambda m: m["type"] == "busy" and m["on"])
        back = await join(lobby, "小華")
        await back.expect(lambda m: m["type"] == "busy" and m["on"], timeout=1)
        engine.release.set()
        view = await back.reply(lambda r: bool(r.narration))
        assert view.actor == "小華" and view.choices
    finally:
        engine.release.set()
        await lobby.stop()


async def test_leaving_and_coming_back_do_not_wait_for_the_ai(isolated):
    """While the AI writes a turn, someone leaving is handled at once, and someone coming back sees "writing the story" right away,
    then the current screen once it's done."""
    engine = StuckEngine()
    lobby = make_lobby(isolated, engine)
    try:
        host, guest = await start_story(lobby)
        await host.reply()
        await guest.reply()
        host.messages.clear()  # Only wait for what comes after this
        await guest.send("1")
        await host.send("1")
        await host.expect(lambda m: m["type"] == "busy" and m["on"])
        guest.conn.close()
        await host.expect(lambda m: m["type"] == "notice" and "小華 離線了" in m["text"], timeout=1)  # Not held up by the AI
        back = await join(lobby, "小華")
        await back.expect(lambda m: m["type"] == "busy" and m["on"], timeout=1)
        engine.release.set()
        view = await back.reply()
        assert view.resumed and view.narration == "阿明阿明往上爬；小華小華往上爬" and view.actor == "小華"
        assert not [m for m in back.messages if m["type"] == "reply"]  # Only the whole current screen, not the turn's reply as well
    finally:
        engine.release.set()
        await lobby.stop()


async def test_two_rooms_play_at_the_same_time(lobby):
    """Different people form their own teams: two rooms play separately, and the lobby lists rooms still waiting for players."""
    a = await join(lobby, "阿明")
    await open_room(a)
    b = await join(lobby, "小華")
    await open_room(b)
    watcher = await join(lobby, "路人")
    screen = await watcher.expect(lambda m: is_lobby()(m) and len(m["choices"]) == 3)
    assert screen["choices"][1:] == ["加入 阿明 的房間（1/4 人）", "加入 小華 的房間（1/4 人）"]
    for player, premise in ((a, "燈塔"), (b, "古堡")):
        await player.send("1")  # Start the adventure
        await player.reply(lambda r: r.phase == "setup")
        await player.send(premise)
    for player in (a, b):
        await player.reply(lambda r: bool(r.narration))
    assert [r.core.state.premise for r in lobby.rooms] == ["燈塔", "古堡"]
    assert [r.core.players for r in lobby.rooms] == [["阿明"], ["小華"]]


async def test_leaving_a_room_goes_back_to_the_lobby_and_empty_rooms_close(lobby):
    host, guest = await gather(lobby, "阿明", "小華")
    await guest.send("1")  # Hua's only option is "leave room"
    await guest.expect(lambda m: is_lobby()(m) and m["clear"])
    await host.expect(lambda m: is_lobby("阿明 的房間")(m) and m["members"] == ["阿明"])
    await host.send("/leave")
    await host.expect(lambda m: is_lobby()(m) and m["choices"] == ["開一個新房間"])
    assert lobby.rooms == []  # No one left, so the room closes


async def test_rooms_are_limited(lobby, monkeypatch):
    monkeypatch.setattr(lobby_module, "MAX_ROOMS", 1)
    await open_room(await join(lobby, "阿明"))
    late = await join(lobby, "小華")
    await late.expect(lambda m: is_lobby()(m) and len(m["choices"]) == 2)
    await late.send("1")  # Open a new room
    await late.expect(lambda m: m["type"] == "notice" and "最多 1 間" in m["text"])


def test_rate_limit_queues_calls_beyond_the_limit_and_retries(monkeypatch):
    """The AI call limit shared by all rooms: calls over it within a minute wait; when Gemini refuses (429), wait the seconds it asks for and resend."""
    from google.genai import errors

    import story.core.ratelimit as ratelimit

    clock = [0.0]
    slept = []
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(ratelimit.time, "sleep", lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s)))
    limit, queued = ratelimit.RateLimit(2), []
    for _ in range(3):
        limit.wait(queued.append)
    assert slept == [60] and queued == [True, False]  # The third waits until the first is a minute old

    calls = []

    def send():
        calls.append(1)
        if len(calls) == 1:
            raise errors.ClientError(429, {"error": {"message": "Please retry in 12.5s."}})
        return "ok"

    assert limit.call(send) == "ok" and 12.5 in slept


async def test_a_room_plays_turtle_soup_together(lobby):
    """The host picks turtle soup and draws from the bank; each turn everyone asks or guesses at once and sees everyone's questions and answers; stating every key point wins."""
    host, guest = await gather(lobby, "阿明", "小華")
    await host.expect(lambda m: is_lobby("阿明 的房間")(m) and m["members"] == ["阿明", "小華"])
    await host.send("2")  # Start turtle soup
    ask = await host.reply()
    assert ask.phase == "setup" and ask.choices == ["從題庫抽一題", "請 AI 出一題"]
    await guest.expect(lambda m: m["type"] == "notice" and "房主正在準備這一局" in m["text"])
    await host.send("1")
    await guest.expect(lambda m: m["type"] == "new_story" and m["premise"] == "")  # Clear the screen first; the scenario waits until the puzzle is drawn
    mine, theirs = await host.reply(), await guest.reply()
    assert "【空號】" in mine.narration and mine.narration == theirs.narration
    assert theirs.actor == "小華" and [m.label for m in theirs.inputs] == ["提問", "猜湯底", "放棄"]
    assert lobby.rooms[0].game == "海龜湯"  # The name shown on the room card

    await guest.send("/guess 全部都說出來")
    await host.send("/ask 是電話嗎")
    result = await guest.reply(lambda r: bool(r.narration))
    assert "阿明 問：是電話嗎\n→ 是" in result.narration and "小華 說中了所有關鍵點" in result.narration
    ended = await guest.reply(lambda r: r.phase == "ended")
    assert ended.ending.title == "小華 解開了謎題" and ended.ending.epilogue == PUZZLE.truth
    await host.expect(is_lobby("阿明 的房間"))  # Afterwards back to the waiting screen, where the game can be chosen again


async def test_an_unexpected_error_in_the_room_keeps_everyone_connected(lobby, caplog):
    """The last line of defence: if handling a message fails in a way nobody expected, the room and connections stay, and everyone gets their screen back."""
    host, guest = await start_story(lobby)
    await host.reply(lambda r: bool(r.narration))
    await guest.reply(lambda r: bool(r.narration))
    core = room_of(lobby).core
    send_as = core.send_as
    core.send_as = lambda name, text: {}["bug"]
    await guest.send("2")
    assert "伺服器出了點問題" in (await guest.expect(lambda m: m["type"] == "notice"))["text"]
    assert (await host.reply(lambda r: r.actor == "阿明")).choices == ["阿明往上爬", "阿明躲起來"]  # Screens are put back
    assert "unexpected error" in caplog.text and len(lobby.rooms) == 1
    core.send_as = send_as
    await guest.send("2")  # The connection still works
    assert (await guest.reply(lambda r: not r.actor)).choices == []  # Acted: no choices left


async def test_a_bug_while_wrapping_up_the_ending_is_not_retried_endlessly(lobby, monkeypatch):
    """If wrapping up the ending fails, the room doesn't keep asking again on its own (the same error would repeat forever,
    and an adventure's epilogue would call the AI every time); anyone can send something to try again."""
    calls = []
    wrap_up = SoupCore._on_ending

    def broken(self, raw):
        calls.append(raw)
        if len(calls) == 1:
            raise KeyError("bug in the ending")
        return wrap_up(self, raw)

    monkeypatch.setattr(SoupCore, "_on_ending", broken)
    host, guest = await gather(lobby, "阿明", "小華")
    await host.send("2")  # Start turtle soup
    await host.reply(lambda r: r.phase == "setup")
    await host.send("1")  # Draw from the bank
    await guest.reply(lambda r: bool(r.narration))
    await host.send("/guess 全部")
    await guest.send("/give_up")
    failed = await guest.reply(lambda r: r.phase == "ending" and r.error is not None)
    assert "送出任何文字可以再試一次" in failed.notice
    await asyncio.sleep(0.2)
    assert len(calls) == 1  # Not retried on its own
    await guest.send("再試一次")  # Not just the host: anyone can retry
    assert (await host.reply(lambda r: r.phase == "ended")).ending.epilogue == PUZZLE.truth
    assert len(calls) == 2


async def test_a_bug_answering_the_premise_dialog_does_not_leave_it_waiting(lobby, caplog):
    """The premise dialog waits for the answer to "suggest one" and the like: if the room fails, it still gets one, with the error."""
    host, guest = await gather(lobby, "阿明", "小華")
    await host.send("1")  # Start the adventure
    await host.reply(lambda r: r.phase == "setup")
    room_of(lobby).core.send = lambda text: {}["bug"]
    await host.conn.send({"type": "send", "text": "/suggest", "form": True, "answer": True})
    answer = await host.expect(lambda m: m["type"] == "premise")
    assert Reply.from_dict(answer["reply"]).error == "api"


async def test_a_bug_after_the_host_answers_shows_the_dialog_again(lobby, caplog):
    """The host's dialog closes when they answer: if the room then fails, the host gets the dialog again instead of being stuck."""
    host, guest = await gather(lobby, "阿明", "小華")
    await host.send("1")  # Start the adventure
    await host.reply(lambda r: r.phase == "setup")
    core = room_of(lobby).core
    send = core.send
    core.send = lambda text: {}["bug"]
    await host.send("燈塔")
    await host.expect(lambda m: m["type"] == "notice" and "伺服器出了點問題" in m["text"])
    await host.reply(lambda r: r.phase == "setup")  # The dialog again
    core.send = send
    await host.send("燈塔")
    assert (await guest.reply(lambda r: bool(r.narration))).narration == "兩人在燈塔醒來。"


async def test_the_host_picks_a_game_from_the_menu(lobby):
    """The waiting screen gives the host a menu of every game in GAMES, with its name and a line about it; picking one starts that game.
    Adding a game to GAMES is enough for it to show up here."""
    from story.games import GAMES

    host, guest = await gather(lobby, "阿明", "小華")
    screen = await host.expect(lambda m: is_lobby("阿明 的房間")(m) and m["members"] == ["阿明", "小華"])
    menu = screen["games"]
    assert [g["code"] for g in menu] == list(GAMES) and [g["title"] for g in menu] == ["冒險", "海龜湯"]
    assert all(g["description"] for g in menu)
    assert [screen["choices"][int(g["choice"]) - 1] for g in menu] == ["開始冒險", "開始海龜湯"]  # Each game's option starts it
    third = await join(lobby, "小美")
    await enter_room(third, "阿明")
    assert (await guest.expect(lambda m: is_lobby("阿明 的房間")(m) and len(m["members"]) == 3))["games"] == []  # Only the host picks
    await host.send(next(g["choice"] for g in menu if g["code"] == "soup"))
    assert (await host.reply()).choices == ["從題庫抽一題", "請 AI 出一題"]


async def test_input_from_someone_who_left_right_after_is_ignored(lobby, caplog):
    """Input is handled in the background, so its sender may have left the room by then: nothing breaks and no one sees an error."""
    host, guest = await gather(lobby, "阿明", "小華")
    await guest.send("開始吧")  # A guest typing on the waiting screen gets "wait for the host"…
    await guest.conn.send({"type": "send", "text": "/leave"})  # …but leaves before that's handled
    await host.expect(lambda m: m["type"] == "lobby" and m["members"] == ["阿明"])
    await asyncio.sleep(0.05)
    assert "unexpected error" not in caplog.text
    assert not [m for m in host.messages if m["type"] == "notice" and "伺服器出了點問題" in m["text"]]
