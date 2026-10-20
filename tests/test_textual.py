"""Textual 外殼：用 Textual 的測試工具模擬按鍵，確認畫面流程正確。核心用真的 StoryCore，engine 用假的。"""

import asyncio
import time

import pytest
from conftest import FakeEngine
from textual.widgets import Button, Checkbox, Input, Static

import story.shells.textual.app as app_module
from story.core import StoryCore
from story.shells.textual import StoryApp
from story.shells.textual.dialogs import ApiKeyDialog, ConfirmDialog, EndingDialog, InfoDialog, NameDialog, PremiseDialog

SIZE = (100, 28)


@pytest.fixture(autouse=True)
def fast_and_fake(monkeypatch):
    """打字效果幾乎不等待；StoryApp 建立核心時換上假的 engine；預設有 API key。"""
    monkeypatch.setattr(app_module, "CHAR_DELAY", 0.001)
    monkeypatch.setattr(app_module, "PAUSE_AFTER", {})
    monkeypatch.setattr(app_module, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=FakeEngine(), **kw))
    monkeypatch.setenv("GEMINI_API_KEY", "test")


def log_lines(app):
    return [str(w.render()) for w in app.query("#log Static")]


def status_text(app):
    return str(app.query_one("#status", Static).render())


async def wait_until(pilot, condition, timeout=5.0):
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "等待逾時"
        await pilot.pause(0.05)


async def start_game(pilot, app, timed=False):
    await wait_until(pilot, lambda: isinstance(app.screen, PremiseDialog))
    app.screen.query_one("#timed", Checkbox).value = timed
    app.screen.query_one("#ok", Button).press()
    await wait_until(pilot, lambda: app.choices and not app.typing)


async def test_new_game_turn_and_status_update():
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await start_game(pilot, app)
        assert log_lines(app) == ["你在燈塔醒來。"]
        assert "回合 1" in status_text(app)
        await pilot.press("1", "enter")
        await wait_until(pilot, lambda: app.choices == ["點亮油燈", "躲起來"])
        lines = log_lines(app)
        assert "› 往上爬" in lines and "你選擇了「往上爬」。" in lines
        assert any("新增 小腿挫傷（中）" in line for line in lines)
        assert "回合 2" in status_text(app) and "受傷" in status_text(app)


async def test_suggest_button_fills_premise():
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, PremiseDialog))
        app.screen.query_one("#suggest", Button).press()
        await wait_until(pilot, lambda: app.screen.query_one("#premise").text)
        assert app.screen.query_one("#premise").text == "你是月球礦坑的夜班工程師。"


async def test_status_bar_waits_until_text_is_typed(monkeypatch):
    monkeypatch.setattr(app_module, "CHAR_DELAY", 0.05)
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await start_game(pilot, app)
        await pilot.press("1", "enter")
        await wait_until(pilot, lambda: app.typing)
        assert "回合 1" in status_text(app)  # 打字中還沒更新
        await wait_until(pilot, lambda: not app.typing)
        assert "回合 2" in status_text(app)


async def test_enter_speeds_up_then_skips_typing(monkeypatch):
    monkeypatch.setattr(app_module, "CHAR_DELAY", 0.5)
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, PremiseDialog))
        app.screen.query_one("#ok", Button).press()
        await wait_until(pilot, lambda: app.typing)
        await pilot.press("enter", "enter")
        await wait_until(pilot, lambda: not app.typing, timeout=1)


async def test_timed_mode_counts_down_and_sends_timeout():
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await start_game(pilot, app, timed=True)
        assert "限時模式" in str(app.query_one("#mode").render())
        assert app.query_one("#timer").has_class("show")
        app.time_left = 0.2  # 不用真的等 10 秒
        await wait_until(pilot, lambda: any(line.startswith("› （時間到") for line in log_lines(app)))


async def test_countdown_pauses_while_dialog_is_open():
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await start_game(pilot, app, timed=True)
        await pilot.press("f1")
        await wait_until(pilot, lambda: isinstance(app.screen, InfoDialog))
        before = app.time_left
        await pilot.pause(0.5)
        assert app.time_left == before
        await pilot.press("escape")


async def test_state_and_restart_dialogs():
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await start_game(pilot, app)
        await pilot.press("ctrl+t")
        await wait_until(pilot, lambda: isinstance(app.screen, InfoDialog))
        await pilot.press("escape")
        await pilot.press("ctrl+r")
        await wait_until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.press("escape")  # 取消
        await wait_until(pilot, lambda: not isinstance(app.screen, ConfirmDialog))
        assert app.choices == ["往上爬", "檢查鑰匙"]


async def test_dialog_arrow_keys_stay_within_button_row():
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await start_game(pilot, app)
        await pilot.press("ctrl+r")
        await wait_until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        assert app.focused.id == "yes"
        await pilot.press("right")
        assert app.focused.id == "yes"  # 已在最右，不會繞回去
        await pilot.press("left", "left")
        assert app.focused.id == "no"


async def test_ending_flow():
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await start_game(pilot, app)
        await pilot.press("1", "enter")
        await wait_until(pilot, lambda: app.choices == ["點亮油燈", "躲起來"] and not app.typing)
        await pilot.press("2", "enter")
        await wait_until(pilot, lambda: app.continue_event is not None)
        assert "─── 燈塔守望者 ───" in log_lines(app)
        await pilot.press("enter")
        await wait_until(pilot, lambda: isinstance(app.screen, EndingDialog))
        app.screen.query_one("#yes", Button).press()
        await wait_until(pilot, lambda: isinstance(app.screen, PremiseDialog))


async def test_resume_from_save():
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await start_game(pilot, app)
        await pilot.press("1", "enter")
        await wait_until(pilot, lambda: app.choices == ["點亮油燈", "躲起來"] and not app.typing)
    await asyncio.sleep(0.2)  # 等背景壓縮記憶寫完存檔

    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.press("enter")  # 繼續
        await wait_until(pilot, lambda: app.choices == ["點亮油燈", "躲起來"])
        assert log_lines(app)[0].startswith("讀取存檔")


async def test_missing_key_asks_for_it_and_saves_it(monkeypatch, isolated):
    monkeypatch.delenv("GEMINI_API_KEY")
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, ApiKeyDialog))
        app.screen.query_one("#key", Input).value = "my-key"
        await pilot.press("enter")
        await wait_until(pilot, lambda: isinstance(app.screen, PremiseDialog))
    assert (isolated / "api_key").read_text() == "my-key"


async def test_web_mode_asks_name_and_never_stores_key(isolated):
    app = StoryApp(web=True)
    async with app.run_test(size=SIZE) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, NameDialog))
        app.screen.query_one("#name", Input).value = "../hack"
        await pilot.press("enter")
        assert "只能包含" in str(app.screen.query_one("#error").render())
        app.screen.query_one("#name", Input).value = "阿明"
        await pilot.press("enter")
        await wait_until(pilot, lambda: isinstance(app.screen, ApiKeyDialog))
        assert app.screen.query_one("#save", Checkbox).disabled
        app.screen.query_one("#key", Input).value = "player-key"
        await pilot.press("enter")
        await wait_until(pilot, lambda: isinstance(app.screen, PremiseDialog))
        assert str(app.core.save_path) == "saves/阿明.json"
        assert (isolated / "saves" / "阿明.lock").exists()
    assert not (isolated / "saves" / "阿明.lock").exists()  # 離開時釋放
    assert not (isolated / "api_key").exists()
