"""The web version: connect to the WebSocket with aiohttp's test tools and play the browser's part. The lobby and rooms are real, the core is a real AdventureCore, and the engine is fake."""

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer
from conftest import FakeGroupEngine

import story.shells.lobby as lobby_module
import story.shells.web as web
from story.games import AdventureCore
from story.shells.lobby import Lobby


@pytest.fixture(autouse=True)
def fake_core(monkeypatch) -> list[str]:
    """Swap in a fake engine when the lobby builds a core; returns the API key each core got."""
    keys: list[str] = []

    def make(api_key, players, *, save_path, log_path, client=None):
        keys.append(api_key)
        return AdventureCore(api_key, players, save_path=save_path, log_path=log_path, engine=FakeGroupEngine())

    monkeypatch.setitem(lobby_module.GAMES, "adventure", make)
    return keys


def app():
    return web.make_app(Lobby.for_server("server-key"))


class Browser:
    """One browser tab: keeps every message received; narration always counts as shown at once."""

    def __init__(self, ws):
        self.ws = ws
        self.seen: list[dict] = []

    async def expect(self, kind: str, condition=lambda m: True, timeout: float = 3.0) -> dict:
        while True:
            message = await self.ws.receive_json(timeout=timeout)
            self.seen.append(message)
            if message["t"] == "narration_end":
                await self.answer(message["id"])
            if message["t"] == kind and condition(message):
                return message

    async def answer(self, id, value=None):
        await self.ws.send_json({"t": "answer", "id": id, "value": value})

    async def send(self, kind: str, **fields):
        await self.ws.send_json({"t": kind, **fields})


async def enter_name(client, name: str) -> Browser:
    browser = Browser(await client.ws_connect("/ws"))
    await browser.answer((await browser.expect("name"))["id"], name)  # Players don't enter an API key: the host's is used
    return browser


async def enter_own_room(client) -> Browser:
    """Playing alone: open your own room in the lobby, press start, and enter a premise."""
    browser = await enter_name(client, "阿明")
    await browser.expect("lobby", lambda m: m["screen"]["title"] == "大廳" and m["screen"]["choices"] == ["開一個新房間"])
    await browser.send("act", text="1")
    await browser.expect("lobby", lambda m: m["screen"]["title"] == "阿明 的房間" and m["screen"]["choices"] == ["開始冒險", "開始海龜湯", "離開房間"])
    await browser.send("act", text="1")
    premise = await browser.expect("premise")
    await browser.answer(premise["id"], ["燈塔", False])
    await browser.expect("choices", lambda m: m["choices"] == ["阿明往上爬", "阿明躲起來"])
    return browser


async def test_page_is_served_with_phone_support():
    async with TestClient(TestServer(app())) as client:
        page = await (await client.get("/")).text()
        assert '<meta name="viewport" content="width=device-width' in page and "/static/app.js" in page
        script = await client.get("/static/app.js")
        assert script.status == 200 and script.headers["Cache-Control"] == "no-cache"  # After an update, no stale cached file is used


async def test_page_has_the_logo():
    async with TestClient(TestServer(app())) as client:
        page = await (await client.get("/")).text()
        assert 'rel="icon" href="/static/logo.svg' in page and 'class="logo"' in page  # The favicon and the header mark
        logo = await client.get("/static/logo.svg")
        assert logo.status == 200 and logo.content_type == "image/svg+xml"


async def test_playing_alone_in_own_room(isolated, fake_core):
    async with TestClient(TestServer(app())) as client:
        browser = await enter_own_room(client)
        assert fake_core == ["server-key"]  # Uses the host's key; players don't enter one
        assert any(m["t"] == "clear" and m["premise"] == "燈塔" for m in browser.seen)  # Show the premise first, then write the opening
        await browser.send("act", text="1")
        assert (await browser.expect("action"))["text"] == "阿明往上爬"
        await browser.expect("changes", lambda m: m["name"] == "" and m["groups"][0][0] == "獲得")  # No name when playing alone
        status = (await browser.expect("status", lambda m: m["status"] and m["status"]["turn"] == 2))["status"]
        assert [c["name"] for c in status["characters"]] == ["阿明"]
        assert (Path("saves") / "team-阿明.adventure.json").exists()  # The save follows the team (one person is a team too)


async def test_continuing_a_save_starts_from_a_clean_screen(isolated):
    """When loading, clear the room's waiting screen first, then show the last story."""
    async with TestClient(TestServer(app())) as client:
        browser = await enter_own_room(client)
        await browser.send("act", text="1")
        await browser.expect("status", lambda m: m["status"] and m["status"]["turn"] == 2)
        await browser.ws.close()  # Leaving: the room closes, but the save stays
        browser = await enter_name(client, "阿明")
        await browser.expect("lobby", lambda m: m["screen"]["title"] == "大廳")
        await browser.send("act", text="1")
        await browser.expect("lobby", lambda m: m["screen"]["view"] == "room")
        await browser.send("act", text="1")  # Start the adventure: a save is found
        await browser.answer((await browser.expect("confirm"))["id"], True)
        await browser.expect("choices", lambda m: m["choices"])
        kinds = [m["t"] for m in browser.seen]
        after = kinds[kinds.index("confirm"):]
        past = [m["text"] for m in browser.seen if m["t"] == "past_narration"]
        assert past == ["兩人在燈塔醒來。", "阿明阿明往上爬"]  # The earlier story and the current passage are both shown at once, without typing again
        assert "clear" in after and after.index("clear") < after.index("past_narration") and "narration_start" not in after


async def test_name_problems_are_shown_and_asked_again(isolated):
    async with TestClient(TestServer(app())) as client:
        first = await enter_own_room(client)
        second = Browser(await client.ws_connect("/ws"))
        name = await second.expect("name")
        await second.answer(name["id"], "../x")
        assert "只能包含" in (await second.expect("name"))["error"]
        name = second.seen[-1]
        await second.answer(name["id"], "阿明")  # Someone is already using this name
        assert "已經有人在用" in (await second.expect("name"))["error"]
        await first.ws.close()


async def test_premise_dialog_can_ask_the_core_while_open(isolated):
    async with TestClient(TestServer(app())) as client:
        browser = await enter_name(client, "阿明")
        for _ in range(2):  # Open a room, start the game
            await browser.expect("lobby", lambda m: m["screen"]["choices"][0] in ("開一個新房間", "開始冒險"))
            await browser.send("act", text="1")
        premise = await browser.expect("premise")
        assert premise["default"] and "options" in premise and "hints" in premise  # The menu and descriptions come from the shared layer
        await browser.send("premise_event", req=1, action="suggest", text="")
        update = await browser.expect("premise_update")
        assert update["req"] == 1 and update["text"] == "AI 想的開頭"
        await browser.answer(premise["id"], ["", True])  # Blank: use the default premise
        assert (await browser.expect("status", lambda m: m["status"]))["status"]["mode"] == "限時模式"


async def test_leaving_from_the_name_dialog_ends_the_session(isolated):
    async with TestClient(TestServer(app())) as client:
        browser = Browser(await client.ws_connect("/ws"))
        await browser.answer((await browser.expect("name"))["id"], None)
        await browser.expect("exit")


async def test_sessions_are_limited(isolated, monkeypatch):
    monkeypatch.setattr(web, "MAX_SESSIONS", 1)
    async with TestClient(TestServer(app())) as client:
        first = Browser(await client.ws_connect("/ws"))
        await first.expect("name")
        second = Browser(await client.ws_connect("/ws"))
        assert "在線人數已滿" in (await second.expect("fatal"))["text"]


async def test_friends_join_the_same_room(isolated):
    async with TestClient(TestServer(app())) as client:
        host = await enter_name(client, "阿明")
        await host.expect("lobby", lambda m: m["screen"]["choices"] == ["開一個新房間"] and m["screen"]["rooms"] == [])
        await host.send("act", text="1")
        await host.expect("lobby", lambda m: m["screen"]["title"] == "阿明 的房間")
        guest = await enter_name(client, "小華")
        lobby = (await guest.expect("lobby", lambda m: m["screen"]["view"] == "lobby"))["screen"]
        assert lobby["choices"] == ["開一個新房間", "加入 阿明 的房間（1/4 人）"]  # Typing a number in the input box works too
        assert lobby["rooms"] == [{"title": "阿明 的房間", "host": "阿明", "members": ["阿明"], "state": "open", "game": "", "choice": "2"}]
        assert {p["name"]: p["room"] for p in lobby["people"]} == {"阿明": "阿明", "小華": ""}  # Who is where
        await guest.send("act", text="2")
        await host.expect("lobby", lambda m: m["screen"]["members"] == ["阿明", "小華"] and m["screen"]["host"] == "阿明")
        await guest.expect("lobby", lambda m: m["screen"]["view"] == "room" and m["screen"]["choices"] == ["離開房間"])
        await host.send("act", text="1")
        premise = await host.expect("premise")
        await host.answer(premise["id"], ["燈塔", False])
        await guest.expect("clear", lambda m: m["premise"] == "燈塔")
        await guest.expect("choices", lambda m: m["choices"] == ["小華往上爬", "小華躲起來"])
        status = (await guest.expect("status", lambda m: m["status"]))["status"]
        assert status["named"] and [c["name"] for c in status["characters"]] == ["阿明", "小華"]
        await guest.send("act", text="2")
        await host.expect("activity", lambda m: m["text"] == "小華 已行動")  # Someone else acted: a brief notice that doesn't cover the story
        assert not any(m["t"] == "activity" for m in guest.seen)  # Your own action doesn't notify yourself
