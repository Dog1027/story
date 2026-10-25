"""網頁版的大廳與房間：用 connect() 連進大廳、開房間或加入房間，模擬好幾位玩家一起玩。核心用真的 PartyCore，engine 用假的。"""

import asyncio

import pytest
from conftest import FakePartyEngine

import story.shells.lobby as lobby_module
from story.core import PartyCore, Reply
from story.core.party import AWAY_ACTION
from story.shells.lobby import Lobby
from story.shells.room import Connection


class Player:
    """一位連到房間的玩家：收到的訊息都留著，方便檢查。"""

    def __init__(self, conn: Connection):
        self.conn = conn
        self.messages: list[dict] = []

    async def send(self, text: str) -> None:
        await self.conn.send({"type": "send", "text": text})

    async def expect(self, condition, timeout: float = 3.0) -> dict:
        """等到收到符合條件的訊息（之前收過、還沒被等過的也算），回傳並移除那則訊息。"""
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
    """每局的核心都用同一個假 engine（lobby.engine），方便檢查 AI 收到了什麼。"""
    engine = engine or FakePartyEngine()
    lobby = Lobby(lambda players, on_queue: PartyCore(
        "test", players, save_path=isolated / "party.json", log_path=isolated / "party.log.jsonl", engine=engine))
    lobby.engine = engine
    return lobby


@pytest.fixture
async def lobby(isolated):
    lobby = make_lobby(isolated)
    yield lobby
    await lobby.stop()


def room_of(lobby) -> object:
    return lobby.rooms[0]


async def join(lobby, name: str) -> Player:
    """連進大廳，用這個名字進來。"""
    conn = lobby.connect()
    await conn.send({"type": "join", "name": name})
    answer = await conn.receive()
    assert answer == {"type": "joined"}, answer
    return Player(conn)


def is_lobby(title: str = "大廳"):
    return lambda m: m["type"] == "lobby" and m["title"] == title


async def open_room(player: Player) -> None:
    """在大廳選「開一個新房間」（第一個選項）。"""
    screen = await player.expect(is_lobby())
    assert screen["choices"][0] == "開一個新房間"
    await player.send("1")


async def enter_room(player: Player, host: str) -> None:
    """在大廳選「加入 host 的房間」。"""
    screen = await player.expect(lambda m: is_lobby()(m) and any(host in c for c in m["choices"]))
    await player.send(str(next(i for i, c in enumerate(screen["choices"], 1) if host in c)))


async def gather(lobby, *names: str) -> list[Player]:
    """第一個人開房間，其他人加入，大家都在房間的等人畫面。"""
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
    await host.expect(lambda m: is_lobby("阿明 的房間")(m) and m["members"] == ["阿明（房主）", "小華"])
    await host.send("1")  # 開始遊戲
    assert (await host.reply()).phase == "ask_premise"
    await guest.expect(lambda m: m["type"] == "notice" and "房主正在設定故事" in m["text"])
    await host.send("燈塔")
    return host, guest


async def test_two_players_play_a_round_in_any_order(lobby):
    host, guest = await start_story(lobby)
    await guest.expect(lambda m: m["type"] == "new_story" and m["premise"] == "燈塔")  # 其他人也先看到故事前提
    mine, theirs = await host.reply(), await guest.reply()
    assert mine.narration == theirs.narration == "兩人在燈塔醒來。"
    assert mine.actor == "阿明" and mine.choices == ["阿明往上爬", "阿明躲起來"]
    assert theirs.actor == "小華" and theirs.choices == ["小華往上爬", "小華躲起來"]

    await guest.send("2")  # 小華先行動
    acted = await guest.reply()
    assert acted.choices == [] and "已記下 小華 的行動" in acted.notice
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
    await conn.send({"type": "join", "name": "小華"})  # 被拒絕後可以換名字再試
    assert await conn.receive() == {"type": "joined"}

    await open_room(first)
    for name in ("小華", "小美", "阿華"):  # 加到第 4 人
        player = Player(conn) if name == "小華" else await join(lobby, name)
        await enter_room(player, "阿明")
    fifth = await join(lobby, "阿強")
    screen = await fifth.expect(is_lobby())
    assert screen["choices"] == ["開一個新房間"]  # 滿了的房間不會列出來


async def test_only_party_members_can_rejoin_after_start(lobby):
    host, guest = await start_story(lobby)
    await guest.reply()
    stranger = await join(lobby, "路人")
    screen = await stranger.expect(is_lobby())
    assert screen["choices"] == ["開一個新房間"] and "1 個房間正在遊戲中" in screen["hint"]


async def test_only_host_answers_dialogs_and_restarts(lobby):
    host, guest = await start_story(lobby)
    await guest.reply()
    await guest.send("/restart")
    await guest.expect(lambda m: m["type"] == "notice" and "只有房主" in m["text"])
    await guest.send("/timeout")  # 玩家不能替大家按時間到
    await guest.send("/state")
    assert (await guest.reply(lambda r: r.info is not None)).info[0] == "程式記住的東西"
    assert lobby.engine.rounds == []


async def test_disconnected_players_rejoin_or_are_skipped(lobby):
    host, guest = await start_story(lobby)
    await host.reply()
    await guest.reply()
    guest.conn.close()
    await host.expect(lambda m: m["type"] == "notice" and "小華 離線了" in m["text"])

    back = await join(lobby, "小華")  # 用同一個名字回來：直接回到原本的房間，看到目前這回合
    view = await back.reply()
    assert view.resumed and view.narration == "兩人在燈塔醒來。" and view.actor == "小華"

    back.conn.close()
    await host.expect(lambda m: m["type"] == "notice" and "小華 離線了" in m["text"])
    await host.send("1")  # 在線的人都行動了：替離線的小華送出「暫時離開」
    await host.reply(lambda r: bool(r.narration))
    assert lobby.engine.rounds == [{"阿明": "阿明往上爬", "小華": AWAY_ACTION}]


async def test_host_leaving_passes_the_dialog_to_the_next_player(lobby):
    host, guest = await gather(lobby, "阿明", "小華")
    await host.send("1")
    await host.reply()  # 房主收到前提對話框
    host.conn.close()
    assert (await guest.reply()).phase == "ask_premise"  # 換小華當房主


class TimedEngine(FakePartyEngine):
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
        assert not any(m["type"] == "timer" for m in host.messages)  # 小華還沒看完
        await guest.conn.send({"type": "ready"})
        assert (await host.expect(lambda m: m["type"] == "timer"))["seconds"] == 1
        await host.reply(lambda r: bool(r.narration))  # 時間到，房間替大家推進
        assert room_of(lobby).core.state.turn == 2
    finally:
        await lobby.stop()


async def test_game_end_returns_to_lobby(lobby, monkeypatch):
    host, guest = await start_story(lobby)
    await host.reply()
    for _ in range(3):  # 第 3 回合阿明倒下，第 4 回合結束
        if room_of(lobby).core.waiting() and "阿明" in room_of(lobby).core.waiting():
            await host.send("1")
        await guest.send("1")
        await guest.reply(lambda r: bool(r.narration) or r.phase == "ended")
    ended = await host.reply(lambda r: r.phase == "ended")
    assert ended.ending.title == "燈塔雙人行"
    await host.expect(is_lobby("阿明 的房間"))  # 回到房間的等人畫面，可以再玩一局
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
        failed = await guest.reply(lambda r: r.error == "api")  # 時間到，推進失敗
        assert failed.choices == ["小華往上爬", "小華躲起來"]  # 大家都要重新選
        await host.expect(lambda m: m["type"] == "timer")  # 重新倒數
        engine.fail_with = None
        await host.send("1")
        await guest.send("2")
        await host.reply(lambda r: bool(r.narration))
        assert engine.rounds == [{"阿明": "阿明往上爬", "小華": "小華躲起來"}]
    finally:
        await lobby.stop()


class SlowOpeningEngine(FakePartyEngine):
    """開場分兩個階段、各花一點時間，模擬真的呼叫兩次 AI。"""

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
            await guest.expect(lambda m: m["type"] == "busy" and m.get("progress") == stage)
        await guest.reply(lambda r: bool(r.narration))
    finally:
        await lobby.stop()


async def test_host_genre_choice_reaches_the_core(isolated):
    from story.core.genres import Genre

    class GenreEngine(FakePartyEngine):
        genres = {"武俠": Genre(name="武俠", description="江湖恩怨", guide="用古白話。")}

    lobby = make_lobby(isolated, GenreEngine())
    try:
        host, guest = await gather(lobby, "阿明", "小華")
        await host.send("1")
        premise_reply = await host.reply()
        assert premise_reply.genres == [["武俠", "江湖恩怨"]]  # 經過 JSON，tuple 變成 list
        await host.send("/genre 武俠")  # 前提對話框裡的選擇：不需要回覆
        await host.send("鏢局")
        await guest.reply(lambda r: bool(r.narration))
        assert room_of(lobby).core.state.genre == "武俠"
    finally:
        await lobby.stop()


async def test_only_commands_asking_for_an_answer_get_one(lobby):
    host, guest = await gather(lobby, "阿明", "小華")
    await host.send("1")
    await host.reply()
    await host.send("/timed on")  # 沒有要求回覆
    await host.conn.send({"type": "send", "text": "/random", "answer": True})
    answer = await host.expect(lambda m: m["type"] == "premise")
    assert Reply.from_dict(answer["reply"]).phase == "ask_premise"
    assert not any(m["type"] == "premise" for m in host.messages)  # 只有一個回覆


async def test_one_player_can_start_alone(lobby):
    host = await join(lobby, "阿明")
    await open_room(host)
    screen = await host.expect(is_lobby("阿明 的房間"))
    assert screen["members"] == ["阿明（房主）"] and screen["choices"] == ["開始遊戲", "離開房間"]
    await host.send("1")
    assert (await host.reply()).phase == "ask_premise"
    await host.send("燈塔")
    assert (await host.reply(lambda r: bool(r.narration))).choices == ["阿明往上爬", "阿明躲起來"]


class StreamingPartyEngine(FakePartyEngine):
    """推進回合時慢慢寫劇情（更新 draft），像真的 AI 在串流。"""

    def act(self, state, actions):
        import time

        for i in range(1, 6):
            self.draft = "大家往上爬"[:i]
            time.sleep(0.15)
        self.draft = ""
        super().act(state, actions)


async def test_everyone_sees_the_narration_while_it_is_written(isolated):
    lobby = make_lobby(isolated, StreamingPartyEngine())
    try:
        host, guest = await start_story(lobby)
        await host.reply()
        await guest.reply()
        await guest.send("1")
        await host.send("1")
        draft = await guest.expect(lambda m: m["type"] == "draft")  # 寫完之前就收到
        assert "大家往上爬".startswith(draft["text"])
        await guest.reply(lambda r: bool(r.narration))
    finally:
        await lobby.stop()


async def test_two_rooms_play_at_the_same_time(lobby):
    """不同的人各自組隊：兩個房間各玩各的，大廳列出還在等人的房間。"""
    a = await join(lobby, "阿明")
    await open_room(a)
    b = await join(lobby, "小華")
    await open_room(b)
    watcher = await join(lobby, "路人")
    screen = await watcher.expect(lambda m: is_lobby()(m) and len(m["choices"]) == 3)
    assert screen["choices"][1:] == ["加入 阿明 的房間（1/4 人）", "加入 小華 的房間（1/4 人）"]
    for player, premise in ((a, "燈塔"), (b, "古堡")):
        await player.send("1")  # 開始遊戲
        await player.reply(lambda r: r.phase == "ask_premise")
        await player.send(premise)
    for player in (a, b):
        await player.reply(lambda r: bool(r.narration))
    assert [r.core.state.premise for r in lobby.rooms] == ["燈塔", "古堡"]
    assert [r.core.players for r in lobby.rooms] == [["阿明"], ["小華"]]


async def test_leaving_a_room_goes_back_to_the_lobby_and_empty_rooms_close(lobby):
    host, guest = await gather(lobby, "阿明", "小華")
    await guest.send("1")  # 小華的選項只有「離開房間」
    await guest.expect(lambda m: is_lobby()(m) and m["clear"])
    await host.expect(lambda m: is_lobby("阿明 的房間")(m) and m["members"] == ["阿明（房主）"])
    await host.send("/leave")
    await host.expect(lambda m: is_lobby()(m) and m["choices"] == ["開一個新房間"])
    assert lobby.rooms == []  # 沒有人了，房間關閉


async def test_rooms_are_limited(lobby, monkeypatch):
    monkeypatch.setattr(lobby_module, "MAX_ROOMS", 1)
    await open_room(await join(lobby, "阿明"))
    late = await join(lobby, "小華")
    await late.expect(lambda m: is_lobby()(m) and len(m["choices"]) == 2)
    await late.send("1")  # 開新房間
    await late.expect(lambda m: m["type"] == "notice" and "最多 1 間" in m["text"])


def test_rate_limit_queues_calls_beyond_the_limit_and_retries(monkeypatch):
    """所有房間共用的 AI 次數限制：一分鐘內超過的要等；被 Gemini 擋下（429）時等它說的秒數再送。"""
    from google.genai import errors

    import story.core.ratelimit as ratelimit

    clock = [0.0]
    slept = []
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(ratelimit.time, "sleep", lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s)))
    limit, queued = ratelimit.RateLimit(2), []
    for _ in range(3):
        limit.wait(queued.append)
    assert slept == [60] and queued == [True, False]  # 第三次排隊等到第一次滿一分鐘

    calls = []

    def send():
        calls.append(1)
        if len(calls) == 1:
            raise errors.ClientError(429, {"error": {"message": "Please retry in 12.5s."}})
        return "ok"

    assert limit.call(send) == "ok" and 12.5 in slept
