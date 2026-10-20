"""Textual 外殼：用 Textual 的測試工具模擬按鍵，確認畫面流程正確。核心用真的 StoryCore，engine 用假的。"""

import asyncio
import time

import pytest
from conftest import FakeEngine
from textual.widgets import Button, Checkbox, Input, Static

import story.shells.textual.app as app_module
from story.core import StoryCore
from story.shells.textual import StoryApp
from story.shells.textual.prose import Prose
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
    return [w.text if isinstance(w, Prose) else str(w.render()) for w in app.query("#log Static")]


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
        await wait_until(pilot, lambda: app.choices == ["點亮油燈", "躲起來"] and not app.typing)


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


async def test_party_mode_takes_turns(monkeypatch):
    from conftest import FakePartyEngine
    from story.core import PartyCore
    from story.shells.textual.dialogs import PartyNamesDialog

    monkeypatch.setattr(app_module, "PartyCore", lambda api_key, players: PartyCore(api_key, players, engine=FakePartyEngine()))
    app = StoryApp(party=True)
    async with app.run_test(size=(110, 32)) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, PartyNamesDialog))
        app.screen.query_one("#names", Input).value = "阿明"
        await pilot.press("enter")
        assert "2 到" in str(app.screen.query_one("#error").render())
        app.screen.query_one("#names", Input).value = "阿明，小華"
        await pilot.press("enter")
        await start_game(pilot, app)
        assert app.actor == "阿明" and app.choices == ["阿明往上爬", "阿明躲起來"]
        assert "阿明" in status_text(app) and "小華" in status_text(app)
        assert app.query_one("#choices").border_title == "輪到 阿明"

        await pilot.press("1", "enter")
        await wait_until(pilot, lambda: app.actor == "小華")
        assert "› 阿明：阿明往上爬" in log_lines(app)
        await pilot.press("2", "enter")
        await wait_until(pilot, lambda: app.actor == "阿明" and not app.typing and app.core.state.turn == 2)
        lines = log_lines(app)
        assert "› 小華：小華躲起來" in lines
        assert any(line.startswith("阿明　獲得 油燈") for line in lines)


async def test_narration_uses_chinese_line_breaking(monkeypatch):
    class EnglishNameEngine(FakeEngine):
        def start(self, state):
            super().start(state)
            state.current_narration = "阿明轉頭看向 Bob，發現他的手臂正在流血，鮮血順著指尖一滴一滴落在冰冷的石地上。"

    monkeypatch.setattr(app_module, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=EnglishNameEngine(), **kw))
    app = StoryApp()
    async with app.run_test(size=(48, 28)) as pilot:  # 故事區扣掉邊距後寬 41
        await start_game(pilot, app)
        narration = app.query_one(".narration", Prose)
        lines = str(narration.render()).splitlines()
        assert lines[0].startswith("阿明轉頭看向 Bob，")


async def test_online_party_through_a_room(isolated):
    """線上多人：畫面沒有自己的核心，透過房間和另一位玩家（直接用連線模擬）一起玩。"""
    import tempfile
    from pathlib import Path

    from conftest import FakePartyEngine
    from story.core import PartyCore
    from story.shells.room import Room, RoomConnection
    from story.shells.textual.dialogs import NameDialog

    engine = FakePartyEngine()
    room = Room(lambda players: PartyCore("test", players, save_path=isolated / "party.json", engine=engine))
    path = str(Path(tempfile.mkdtemp(prefix="story-test-")) / "room.sock")
    await room.start(path)
    try:
        app = StoryApp(web=True, party=True, room=path)
        async with app.run_test(size=(110, 32)) as pilot:
            await wait_until(pilot, lambda: isinstance(app.screen, NameDialog) and app.screen.query("#name"))
            app.screen.query_one("#name", Input).value = "阿明"
            await pilot.press("enter")
            await wait_until(pilot, lambda: "阿明（房主）" in status_text(app))
            assert app.core is None and app.choices == []  # 只有一個人，還不能開始

            guest = await RoomConnection.open(path)
            await guest.send({"type": "join", "name": "小華"})
            await wait_until(pilot, lambda: app.choices == ["開始遊戲"])
            await pilot.press("1", "enter")
            await start_game(pilot, app)
            await wait_until(pilot, lambda: app.actor == "阿明" and not app.typing)
            assert app.choices == ["阿明往上爬", "阿明躲起來"]
            assert log_lines(app) == ["兩人在燈塔醒來。"]

            await pilot.press("2", "enter")
            await wait_until(pilot, lambda: app.waiting == ["小華"])
            assert "› 阿明：阿明躲起來" in log_lines(app)
            assert "等待 小華" in app.query_one("#cmd", Input).placeholder

            await guest.send({"type": "send", "text": "1"})
            await wait_until(pilot, lambda: app.actor == "阿明" and not app.typing and len(log_lines(app)) > 2)
            assert "阿明阿明躲起來；小華小華往上爬" in log_lines(app)

            # 第二回合小華先行動：阿明這邊跳出通知，選項不重建（以前會整個重畫、閃一下）
            rebuilt = []
            original = app.set_choices
            app.set_choices = lambda choices: (rebuilt.append(choices), original(choices))
            await guest.send({"type": "send", "text": "1"})
            await wait_until(pilot, lambda: any("小華 已行動" in str(n.message) for n in app._notifications))
            assert rebuilt == [] and app.choices == ["阿明往上爬", "阿明躲起來"]
            guest.close()
    finally:
        await room.stop()


async def test_narrow_screen_uses_smaller_margins(isolated):
    """手機直式（60 格以下）縮小邊距；電腦的寬畫面維持原樣。"""
    for width, narrow in ((40, True), (100, False)):
        (isolated / "save.json").unlink(missing_ok=True)  # 每次都從新故事開始
        app = StoryApp()
        async with app.run_test(size=(width, 30)) as pilot:
            await start_game(pilot, app)
            assert app.screen.has_class("-narrow") is narrow
            assert app.query_one("#log").styles.padding.left == (1 if narrow else 3)


async def test_busy_line_shows_opening_progress(monkeypatch):
    class SlowOpening(FakeEngine):
        def start(self, state):
            self.stage = "規劃故事大綱"
            time.sleep(0.6)
            self.stage = ""
            super().start(state)

    monkeypatch.setattr(app_module, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=SlowOpening(), **kw))
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, PremiseDialog))
        app.screen.query_one("#ok", Button).press()
        await wait_until(pilot, lambda: app.busy_line is not None and "規劃故事大綱" in str(app.busy_line.render()))
        await wait_until(pilot, lambda: app.choices and not app.typing)
