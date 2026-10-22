"""線上多人的房間：用真的 Unix socket 連線，模擬好幾位玩家一起玩同一局。核心用真的 PartyCore，engine 用假的。"""

import asyncio
import tempfile
from pathlib import Path

import pytest
from conftest import FakePartyEngine

import story.shells.room as room_module
from story.core import PartyCore, Reply
from story.shells.room import OFFLINE_ACTION, Room, RoomConnection


class Player:
    """一位連到房間的玩家：收到的訊息都留著，方便檢查。"""

    def __init__(self, conn: RoomConnection):
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


@pytest.fixture
async def room(isolated):
    engine = FakePartyEngine()
    room = Room(lambda players: PartyCore("test", players, save_path=isolated / "party.json", engine=engine))
    room.engine = engine
    path = str(Path(tempfile.mkdtemp(prefix="story-test-")) / "room.sock")  # socket 路徑有長度限制，不用 tmp_path
    await room.start(path)
    room.path = path
    yield room
    await room.stop()


async def join(room, name: str) -> Player:
    conn = await RoomConnection.open(room.path)
    await conn.send({"type": "join", "name": name})
    answer = await conn.receive()
    assert answer == {"type": "joined"}, answer
    return Player(conn)


async def start_story(room) -> tuple[Player, Player]:
    host, guest = await join(room, "阿明"), await join(room, "小華")
    await host.expect(lambda m: m["type"] == "lobby" and m["members"] == ["阿明", "小華"] and m["host"] == "阿明")
    await host.send("1")
    assert (await host.reply()).phase == "ask_premise"
    await guest.expect(lambda m: m["type"] == "notice" and "房主正在設定故事" in m["text"])
    await host.send("燈塔")
    return host, guest


async def test_two_players_play_a_round_in_any_order(room):
    host, guest = await start_story(room)
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
    assert room.engine.rounds == [{"阿明": "阿明往上爬", "小華": "小華躲起來"}]


async def test_names_are_checked_and_room_has_a_limit(room):
    players = [await join(room, "阿明")]
    conn = await RoomConnection.open(room.path)
    await conn.send({"type": "join", "name": "阿明"})
    assert "已經在房間裡" in (await conn.receive())["reason"]
    await conn.send({"type": "join", "name": "../x"})
    assert "只能包含" in (await conn.receive())["reason"]
    await conn.send({"type": "join", "name": "小華"})  # 被拒絕後可以換名字再試
    assert await conn.receive() == {"type": "joined"}

    players += [await join(room, "小美"), await join(room, "阿華")]  # 第 4 人
    fifth = await RoomConnection.open(room.path)
    await fifth.send({"type": "join", "name": "阿強"})
    assert "房間已滿" in (await fifth.receive())["reason"]


async def test_only_party_members_can_rejoin_after_start(room):
    host, guest = await start_story(room)
    await guest.reply()
    conn = await RoomConnection.open(room.path)
    await conn.send({"type": "join", "name": "路人"})
    assert "遊戲進行中" in (await conn.receive())["reason"]


async def test_only_host_answers_dialogs_and_restarts(room):
    host, guest = await start_story(room)
    await guest.reply()
    await guest.send("/restart")
    await guest.expect(lambda m: m["type"] == "notice" and "只有房主" in m["text"])
    await guest.send("/timeout")  # 玩家不能替大家按時間到
    await guest.send("/state")
    assert (await guest.reply(lambda r: r.info is not None)).info[0] == "程式記住的東西"
    assert room.engine.rounds == []


async def test_disconnected_players_rejoin_or_are_skipped(room):
    host, guest = await start_story(room)
    await host.reply()
    await guest.reply()
    guest.conn.close()
    await host.expect(lambda m: m["type"] == "notice" and "小華 離線了" in m["text"])

    back = await join(room, "小華")  # 用同一個名字回來，看到目前這回合
    view = await back.reply()
    assert view.resumed and view.narration == "兩人在燈塔醒來。" and view.actor == "小華"

    back.conn.close()
    await host.expect(lambda m: m["type"] == "notice" and "小華 離線了" in m["text"])
    await host.send("1")  # 在線的人都行動了：替離線的小華送出「暫時離開」
    await host.reply(lambda r: bool(r.narration))
    assert room.engine.rounds == [{"阿明": "阿明往上爬", "小華": OFFLINE_ACTION}]


async def test_host_leaving_passes_the_dialog_to_the_next_player(room):
    host = await join(room, "阿明")
    guest = await join(room, "小華")
    await host.send("1")
    await host.reply()  # 房主收到前提對話框
    host.conn.close()
    assert (await guest.reply()).phase == "ask_premise"  # 換小華當房主


class TimedEngine(FakePartyEngine):
    def start(self, state):
        super().start(state)
        state.current_time_limit = 1


async def test_countdown_starts_after_everyone_has_read_then_times_out(isolated):
    room = Room(lambda players: PartyCore("test", players, save_path=isolated / "party.json", engine=TimedEngine()))
    room.path = str(Path(tempfile.mkdtemp(prefix="story-test-")) / "room.sock")
    await room.start(room.path)
    try:
        host, guest = await start_story(room)
        await host.reply()
        await guest.reply()
        await host.conn.send({"type": "ready"})
        await asyncio.sleep(0.1)
        assert not any(m["type"] == "timer" for m in host.messages)  # 小華還沒看完
        await guest.conn.send({"type": "ready"})
        assert (await host.expect(lambda m: m["type"] == "timer"))["seconds"] == 1
        await host.reply(lambda r: bool(r.narration))  # 時間到，房間替大家推進
        assert room.core.state.turn == 2
    finally:
        await room.stop()


async def test_game_end_returns_to_lobby(room, monkeypatch):
    host, guest = await start_story(room)
    await host.reply()
    for _ in range(3):  # 第 3 回合阿明倒下，第 4 回合結束
        if room.core.waiting() and "阿明" in room.core.waiting():
            await host.send("1")
        await guest.send("1")
        await guest.reply(lambda r: bool(r.narration) or r.phase == "ended")
    ended = await host.reply(lambda r: r.phase == "ended")
    assert ended.ending.title == "燈塔雙人行"
    await host.expect(lambda m: m["type"] == "lobby" and m["host"] == "阿明")
    assert room.core is None


async def test_failed_timeout_round_restarts_the_countdown(isolated):
    engine = TimedEngine()
    room = Room(lambda players: PartyCore("test", players, save_path=isolated / "party.json", engine=engine))
    room.path = str(Path(tempfile.mkdtemp(prefix="story-test-")) / "room.sock")
    await room.start(room.path)
    try:
        host, guest = await start_story(room)
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
        await room.stop()


class SlowOpeningEngine(FakePartyEngine):
    """開場分兩個階段、各花一點時間，模擬真的呼叫兩次 AI。"""

    def start(self, state):
        import time

        for self.stage in ("規劃故事大綱", "寫開場"):
            time.sleep(0.5)
        self.stage = ""
        super().start(state)


async def test_everyone_sees_the_opening_progress(isolated):
    room = Room(lambda players: PartyCore("test", players, save_path=isolated / "party.json", engine=SlowOpeningEngine()))
    room.path = str(Path(tempfile.mkdtemp(prefix="story-test-")) / "room.sock")
    await room.start(room.path)
    try:
        host, guest = await start_story(room)
        for stage in ("規劃故事大綱", "寫開場"):
            await guest.expect(lambda m: m["type"] == "busy" and m.get("progress") == stage)
        await guest.reply(lambda r: bool(r.narration))
    finally:
        await room.stop()


async def test_host_genre_choice_reaches_the_core(isolated):
    from story.core.genres import Genre

    class GenreEngine(FakePartyEngine):
        genres = {"武俠": Genre(name="武俠", description="江湖恩怨", guide="用古白話。")}

    room = Room(lambda players: PartyCore("test", players, save_path=isolated / "party.json", engine=GenreEngine()))
    room.path = str(Path(tempfile.mkdtemp(prefix="story-test-")) / "room.sock")
    await room.start(room.path)
    try:
        host, guest = await join(room, "阿明"), await join(room, "小華")
        await host.send("1")
        premise_reply = await host.reply()
        assert premise_reply.genres == [["武俠", "江湖恩怨"]]  # 經過 JSON，tuple 變成 list
        await host.send("/genre 武俠")  # 前提對話框裡的選擇：不需要回覆
        await host.send("鏢局")
        await guest.reply(lambda r: bool(r.narration))
        assert room.core.state.genre == "武俠"
    finally:
        await room.stop()


async def test_only_commands_asking_for_an_answer_get_one(room):
    host, guest = await join(room, "阿明"), await join(room, "小華")
    await host.send("1")
    await host.reply()
    await host.send("/timed on")  # 沒有要求回覆
    await host.conn.send({"type": "send", "text": "/random", "answer": True})
    answer = await host.expect(lambda m: m["type"] == "premise")
    assert Reply.from_dict(answer["reply"]).phase == "ask_premise"
    assert not any(m["type"] == "premise" for m in host.messages)  # 只有一個回覆
