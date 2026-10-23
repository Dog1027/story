"""網頁版：用 aiohttp 的測試工具連上 WebSocket，扮演瀏覽器走完流程。核心用真的 StoryCore／PartyCore，engine 用假的。"""

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer
from conftest import FakeEngine, FakePartyEngine

import story.shells.client as client_module
import story.shells.web as web
from story.core import PartyCore, StoryCore
from story.shells.room import Room


@pytest.fixture(autouse=True)
def fake_core(monkeypatch):
    monkeypatch.setattr(client_module, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=FakeEngine(), **kw))


class Browser:
    """一個瀏覽器分頁：收到的訊息都留著；劇情一律當作立刻顯示完。"""

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


async def enter_single_game(client) -> Browser:
    browser = Browser(await client.ws_connect("/ws"))
    name = await browser.expect("name")
    await browser.answer(name["id"], "阿明")
    key = await browser.expect("api_key")
    await browser.answer(key["id"], "test")
    premise = await browser.expect("premise")
    await browser.answer(premise["id"], ["燈塔", False, "自動"])
    await browser.expect("choices", lambda m: m["choices"] == ["往上爬", "檢查鑰匙"])
    return browser


async def test_page_is_served_with_phone_support():
    async with TestClient(TestServer(web.make_app())) as client:
        page = await (await client.get("/")).text()
        assert '<meta name="viewport" content="width=device-width' in page and "/static/app.js" in page
        script = await client.get("/static/app.js")
        assert script.status == 200 and script.headers["Cache-Control"] == "no-cache"  # 更新後不會用到快取的舊檔


async def test_single_player_plays_a_turn(isolated):
    async with TestClient(TestServer(web.make_app())) as client:
        browser = await enter_single_game(client)
        assert any(m["t"] == "clear" and m["premise"] == "燈塔" for m in browser.seen)  # 先顯示前提，再寫開場
        await browser.send("act", text="1")
        assert (await browser.expect("action"))["text"] == "往上爬"
        await browser.expect("changes", lambda m: m["name"] == "" and m["groups"][0][0] == "新增")
        status = (await browser.expect("status", lambda m: m["status"] and m["status"]["turn"] == 2))["status"]
        assert status["characters"][0]["items"] == [["小腿挫傷", "中"]] and not status["party"]
        assert (Path("saves") / "阿明.json").exists()  # 依名字分開存檔


async def test_name_problems_are_shown_and_asked_again(isolated):
    async with TestClient(TestServer(web.make_app())) as client:
        first = await enter_single_game(client)
        second = Browser(await client.ws_connect("/ws"))
        name = await second.expect("name")
        await second.answer(name["id"], "../x")
        assert "只能包含" in (await second.expect("name"))["error"]
        name = second.seen[-1]
        await second.answer(name["id"], "阿明")  # 有人正在用這個名字
        assert "正在遊戲中" in (await second.expect("name"))["error"]
        await first.ws.close()


async def test_premise_dialog_can_ask_the_core_while_open(isolated):
    async with TestClient(TestServer(web.make_app())) as client:
        browser = Browser(await client.ws_connect("/ws"))
        await browser.answer((await browser.expect("name"))["id"], "阿明")
        await browser.answer((await browser.expect("api_key"))["id"], "test")
        premise = await browser.expect("premise")
        await browser.send("premise_ask", req=1, commands=["/suggest"])
        update = await browser.expect("premise_update")
        assert update["req"] == 1 and update["suggestion"] == "你是月球礦坑的夜班工程師。"
        await browser.answer(premise["id"], ["", True, "自動"])  # 留白：用預設的前提
        assert (await browser.expect("status", lambda m: m["status"]))["status"]["mode"] == "限時模式"


async def test_leaving_from_the_name_dialog_ends_the_session(isolated):
    async with TestClient(TestServer(web.make_app())) as client:
        browser = Browser(await client.ws_connect("/ws"))
        await browser.answer((await browser.expect("name"))["id"], None)
        await browser.expect("exit")


async def test_sessions_are_limited(isolated, monkeypatch):
    monkeypatch.setattr(web, "MAX_SESSIONS", 1)
    async with TestClient(TestServer(web.make_app())) as client:
        first = Browser(await client.ws_connect("/ws"))
        await first.expect("name")
        second = Browser(await client.ws_connect("/ws"))
        assert "在線人數已滿" in (await second.expect("fatal"))["text"]


async def test_party_mode_puts_every_tab_in_one_lobby(isolated):
    room = Room(lambda players: PartyCore("test", players, save_path=isolated / "party.json", engine=FakePartyEngine()))
    async with TestClient(TestServer(web.make_app(room))) as client:
        host, guest = Browser(await client.ws_connect("/ws")), Browser(await client.ws_connect("/ws"))
        await host.answer((await host.expect("name"))["id"], "阿明")
        await host.expect("lobby")  # 阿明先進房間（第一個進來的是房主），小華才送出名字
        await guest.answer((await guest.expect("name"))["id"], "小華")
        await host.expect("lobby", lambda m: m["members"] == ["阿明（房主）", "小華"])
        await host.expect("choices", lambda m: m["choices"] == ["開始遊戲"])
        await host.send("act", text="1")
        premise = await host.expect("premise")
        await host.answer(premise["id"], ["燈塔", False, "自動"])
        await guest.expect("clear", lambda m: m["premise"] == "燈塔")
        await guest.expect("choices", lambda m: m["choices"] == ["小華往上爬", "小華躲起來"])
        status = (await guest.expect("status", lambda m: m["status"]))["status"]
        assert status["party"] and [c["name"] for c in status["characters"]] == ["阿明", "小華"]
        # 線上多人沒有輪流的順序：選項區不標「輪到誰」
        assert all(m["title"] == "接下來" for m in guest.seen if m["t"] == "hint")
