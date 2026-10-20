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
