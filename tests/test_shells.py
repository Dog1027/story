"""純文字外殼與網頁殼。"""

import asyncio
import json
import re

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer
from conftest import FakeEngine

import story.shells.plain as plain
import story.shells.web as web
from story.core import StoryCore


def test_plain_shell_plays_a_whole_story(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(plain, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=FakeEngine(), **kw))
    inputs = iter(["", "1", "2", "", "/quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    plain.main()
    out = capsys.readouterr().out
    assert "你在燈塔醒來。" in out
    assert "回合 2｜狀態 受傷：小腿挫傷（中）" in out
    assert "─── 燈塔守望者 ───" in out
    assert "已存檔，下次見。" in out


# ---------- 網頁殼：啟動真的 textual-serve 伺服器，每個連線會跑一個真的遊戲子程序 ----------

ANSI = re.compile(r"\x1b\[[0-9;?<>=]*[a-zA-Z]|\x1b[\]P][^\x07\x1b]*(\x07|\x1b\\)|\x1b.")


async def read_screen(ws, seconds):
    """收一段時間的終端機輸出，去掉控制碼後回傳純文字。"""
    text = ""
    loop = asyncio.get_running_loop()
    end = loop.time() + seconds
    while (left := end - loop.time()) > 0:
        try:
            msg = await asyncio.wait_for(ws.receive(), left)
        except TimeoutError:
            break
        if msg.type == aiohttp.WSMsgType.BINARY:
            text += msg.data.decode("utf-8", "ignore")
        elif msg.type == aiohttp.WSMsgType.TEXT:
            text += msg.data
        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
            break
    return ANSI.sub("", text)


@pytest.mark.slow
async def test_web_shell_runs_separate_games_and_limits_sessions(monkeypatch):
    monkeypatch.setattr(web, "MAX_SESSIONS", 1)
    monkeypatch.setattr(web.LimitedServer, "sessions", 0)
    server = web.LimitedServer(web.game_command(), host="127.0.0.1", port=0, title="Story")
    async with TestClient(TestServer(await server._make_app())) as client:
        first = await client.ws_connect("/ws?width=90&height=26")
        screen = await read_screen(first, 10)
        assert "你的名字" in screen  # 網頁模式的遊戲：先問名字

        second = await client.ws_connect("/ws?width=90&height=26")
        assert "在線人數已滿" in await read_screen(second, 3)

        await first.close()
        await asyncio.sleep(1)
        third = await client.ws_connect("/ws?width=90&height=26")
        assert "你的名字" in await read_screen(third, 10)
        await third.send_str(json.dumps(["stdin", "\x1b"]))
        await third.close()


@pytest.mark.slow
async def test_web_party_mode_puts_phone_and_desktop_tabs_in_one_lobby():
    """線上多人：每個分頁都進到同一個大廳。第一個分頁是手機，用手機輸入列的送法輸入名字
    （終端機失焦後，送 focus、用「貼上」送整段文字、再送 Enter），中文不會重複；第二個分頁照一般方式打字。"""
    import tempfile
    from pathlib import Path

    from story.shells.room import Room

    room_path = str(Path(tempfile.mkdtemp(prefix="story-test-")) / "room.sock")
    server = web.LimitedServer(web.game_command(room_path), host="127.0.0.1", port=0, title="Story", room=Room.for_server("test"), room_path=room_path)
    async with TestClient(TestServer(await server._make_app())) as client:
        phone = await client.ws_connect("/ws?width=40&height=30")
        assert "你的名字" in await read_screen(phone, 10)
        await phone.send_str(json.dumps(["blur"]))  # 點了頁面下方的輸入列
        for message in (["focus"], ["stdin", "\x1b[200~阿明\x1b[201~"], ["stdin", "\r"]):
            await phone.send_str(json.dumps(message))

        desktop = await client.ws_connect("/ws?width=100&height=30")
        assert "大家在同一局裡" in await read_screen(desktop, 10)
        await desktop.send_str(json.dumps(["stdin", "小華\r"]))

        screen = await read_screen(desktop, 5)
        assert "阿明（房主）" in screen and "小華" in screen
        assert "阿明阿明" not in await read_screen(phone, 1) + screen
        for ws in (phone, desktop):
            await ws.close()


async def test_web_page_supports_phones():
    server = web.LimitedServer(web.game_command(), host="127.0.0.1", port=0, title="Story")
    async with TestClient(TestServer(await server._make_app())) as client:
        page = await (await client.get("/")).text()
    assert '<meta name="viewport" content="width=device-width' in page
    assert 'id="mobile-input"' in page
    assert 'data-session-websocket-url="ws://' in page  # 模板的變數照常填入


async def test_web_page_urls_follow_the_browser_address():
    # 監聽 0.0.0.0 時，頁面裡的網址不能寫成 0.0.0.0，要跟著瀏覽器連進來的網址
    server = web.LimitedServer(web.game_command(), host="0.0.0.0", port=8080, title="Story")
    async with TestClient(TestServer(await server._make_app())) as client:
        page = await (await client.get("/", headers={"Host": "192.168.1.5:8080"})).text()
    assert "0.0.0.0" not in page
    assert 'src="http://192.168.1.5:8080/static/js/textual.js"' in page
    assert 'data-session-websocket-url="ws://192.168.1.5:8080/ws"' in page

    fixed = web.LimitedServer(web.game_command(), host="0.0.0.0", port=8080, public_url="https://story.example")
    async with TestClient(TestServer(await fixed._make_app())) as client:
        page = await (await client.get("/")).text()
    assert 'data-session-websocket-url="wss://story.example/ws"' in page


def test_plain_shell_party_mode(monkeypatch, capsys):
    from conftest import FakePartyEngine
    from story.core import PartyCore

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(plain, "PartyCore", lambda api_key, players: PartyCore(api_key, players, engine=FakePartyEngine()))
    inputs = iter(["阿明", "阿明,小華", "", "1", "2", "/quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    plain.main(party=True)
    out = capsys.readouterr().out
    assert "多人模式需要 2 到" in out
    assert "輪到 阿明 行動" in out and "輪到 小華 行動" in out
    assert "阿明　獲得 油燈" in out


def test_shells_only_use_the_public_core_interface():
    """外殼只能透過核心的公開介面溝通：只 import story.core 匯出的名稱，只用公開的方法與唯讀屬性。
    直接讀核心內部（core.state、core.engine……）時這裡會失敗，核心內部怎麼改才不會弄壞外殼。"""
    from pathlib import Path

    import story.core
    import story.shells

    public = {"send", "start", "action_for", "set_api_key", "progress", "phase", "players", "send_as", "view", "waiting"}
    problems = []
    for path in sorted(Path(story.shells.__file__).parent.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for module, names in re.findall(r"^\s*from (story\.core[\w.]*) import ([^\n]+)", source, re.M):
            if module != "story.core":
                problems.append(f"{path.name}: from {module} import …（只能從 story.core import）")
            for name in (n.strip() for n in names.split(",")):
                if name not in story.core.__all__:
                    problems.append(f"{path.name}: {name} 不是 story.core 匯出的名稱")
        for attribute in set(re.findall(r"\bcore\.(\w+)", source)):
            if attribute not in public:
                problems.append(f"{path.name}: core.{attribute} 不是公開介面")
    assert problems == []
