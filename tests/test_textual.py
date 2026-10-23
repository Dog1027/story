"""Textual 外殼：用 Textual 的測試工具模擬按鍵，確認畫面流程正確。核心用真的 StoryCore，engine 用假的。"""

import asyncio
import io
import time
from pathlib import Path

import pytest
from rich.text import Text
from conftest import FakeEngine
from textual.widgets import Button, Checkbox, Input, Static

import story.shells.client as client_module
from story.shells.client import status_line
import story.shells.textual.app as app_module
from story.core import StoryCore
from story.core.records import DEFAULT_PREMISE
from story.shells.textual import StoryApp
from story.shells.textual.prose import Prose
from story.shells.textual.dialogs import ApiKeyDialog, ConfirmDialog, EndingDialog, InfoDialog, NameDialog, PremiseDialog

SIZE = (100, 28)


@pytest.fixture(autouse=True)
def fast_and_fake(monkeypatch):
    """打字效果幾乎不等待；StoryApp 建立核心時換上假的 engine；預設有 API key。"""
    monkeypatch.setattr(app_module, "CHAR_DELAY", 0.001)
    monkeypatch.setattr(app_module, "PAUSE_AFTER", {})
    monkeypatch.setattr(client_module, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=FakeEngine(), **kw))
    monkeypatch.setenv("GEMINI_API_KEY", "test")


def log_lines(app):
    return [w.text if isinstance(w, Prose) else str(w.content) for w in app.query("#log Static")]


def status_text(app):
    """狀態列的純文字（多人模式是表格，要實際排版才拿得到文字）。"""
    from rich.console import Console

    console = Console(width=app.size.width, record=True, file=io.StringIO())
    console.print(app.query_one("#status", Static).content)
    return console.export_text()


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
        assert log_lines(app) == [f"故事前提：{DEFAULT_PREMISE}", "你在燈塔醒來。"]  # 前提先顯示，等 AI 寫開場時可以先讀
        assert "回合 1" in status_text(app)
        await pilot.press("1", "enter")
        await wait_until(pilot, lambda: app.choices == ["點亮油燈", "躲起來"])
        lines = log_lines(app)
        assert "› 往上爬" in lines and "你選擇了「往上爬」。" in lines
        assert any("新增 小腿挫傷（中）" in line for line in lines)
        assert "回合 2" in status_text(app) and "小腿挫傷" in status_text(app)
        assert "受傷" not in status_text(app) and "背包" not in status_text(app)  # 直接列出狀態，不加評語；背包不放在狀態列


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
        assert "限時模式" in status_text(app).splitlines()[0]  # 跟回合同一排
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
        await wait_until(pilot, lambda: app.continue_event is not None)  # 先讀完最後的劇情
        assert "─── 燈塔守望者 ───" not in log_lines(app)
        assert app.query_one("#cmd").placeholder == "按 Enter 看尾聲"
        await pilot.press("enter")
        await wait_until(pilot, lambda: "─── 燈塔守望者 ───" in log_lines(app) and app.continue_event is not None and not app.typing)
        assert not isinstance(app.screen, EndingDialog)
        await pilot.press("enter")
        await wait_until(pilot, lambda: isinstance(app.screen, EndingDialog))
        app.screen.query_one("#yes", Button).press()
        await wait_until(pilot, lambda: isinstance(app.screen, PremiseDialog))


async def test_scrolling_up_while_typing_stops_following():
    """文字還在打的時候往上捲：不會被拉回最底，可以往回看；捲回最底就繼續跟著新內容。"""
    app = StoryApp()
    async with app.run_test(size=(60, 14)) as pilot:
        await start_game(pilot, app)
        log = app.query_one("#log")
        for _ in range(6):  # 故事長到可以捲動
            app.log_message("很長的一段劇情。" * 6, "narration")
        await pilot.pause()
        pulled = []
        log.scroll_end = lambda **kw: pulled.append(1)  # 記下程式把故事區捲到最底的次數

        app.follow_log(0)  # 玩家往上捲
        assert not app.follow
        await app.typewrite("新的劇情" * 5)
        assert pulled == []  # 打字時不會把玩家拉回最底

        app.follow_log(log.max_scroll_y)  # 玩家捲回最底
        await app.typewrite("新的劇情" * 5)
        assert pulled

        app.follow_log(0)
        app.log_message(Text("› 往上爬"), "action", follow=True)  # 自己行動了：一定捲到最底
        assert app.follow


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


async def test_party_mode_takes_turns(monkeypatch):
    from conftest import FakePartyEngine
    from story.core import PartyCore
    from story.shells.textual.dialogs import PartyNamesDialog

    monkeypatch.setattr(client_module, "PartyCore", lambda api_key, players: PartyCore(api_key, players, engine=FakePartyEngine()))
    app = StoryApp(party=True)
    async with app.run_test(size=(110, 32)) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, PartyNamesDialog))
        app.screen.query_one("#names", Input).value = "甲 乙 丙 丁 戊"
        await pilot.press("enter")
        assert "1 到 4" in str(app.screen.query_one("#error").render())
        app.screen.query_one("#names", Input).value = "阿明，小華"
        await pilot.press("enter")
        await start_game(pilot, app)
        assert app.client.actor == "阿明" and app.choices == ["阿明往上爬", "阿明躲起來"]
        assert "阿明" in status_text(app) and "小華" in status_text(app)
        assert app.query_one("#choices").border_title == "輪到 阿明"

        await pilot.press("1", "enter")
        await wait_until(pilot, lambda: app.client.actor == "小華")
        assert "› 阿明：阿明往上爬" in log_lines(app)
        await pilot.press("2", "enter")
        await wait_until(pilot, lambda: app.client.actor == "阿明" and not app.typing and app.client.core.state.turn == 2)
        lines = log_lines(app)
        assert "› 小華：小華躲起來" in lines
        assert any(line.startswith("阿明　獲得 油燈") for line in lines)


async def test_narration_uses_chinese_line_breaking(monkeypatch):
    class EnglishNameEngine(FakeEngine):
        def start(self, state):
            super().start(state)
            state.current_narration = "阿明轉頭看向 Bob，發現他的手臂正在流血，鮮血順著指尖一滴一滴落在冰冷的石地上。"

    monkeypatch.setattr(client_module, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=EnglishNameEngine(), **kw))
    app = StoryApp()
    async with app.run_test(size=(48, 28)) as pilot:  # 故事區扣掉邊距後寬 41
        await start_game(pilot, app)
        narration = app.query_one(".narration", Prose)
        lines = str(narration.render()).splitlines()
        assert lines[0].startswith("阿明轉頭看向 Bob，")


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

    monkeypatch.setattr(client_module, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=SlowOpening(), **kw))
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, PremiseDialog))
        app.screen.query_one("#ok", Button).press()
        await wait_until(pilot, lambda: app.busy_line is not None and "規劃故事大綱" in str(app.busy_line.render()))
        await wait_until(pilot, lambda: app.choices and not app.typing)


async def test_story_does_not_jump_when_choices_appear(monkeypatch):
    """選項框在打字前就佔好位置（看不見），打完字時故事區的高度不變，文字才不會突然往上跳。"""
    monkeypatch.setattr(app_module, "CHAR_DELAY", 0.1)
    app = StoryApp()
    async with app.run_test(size=(40, 30)) as pilot:
        await start_game(pilot, app)
        await pilot.press("1", "enter")
        await wait_until(pilot, lambda: app.typing)
        options = app.query_one("#choices")
        assert options.styles.opacity == 0.0 and not options.has_class("-empty")  # 已佔位、還看不見
        height_while_typing = app.query_one("#log").size.height
        await wait_until(pilot, lambda: not app.typing)
        await pilot.pause(0.5)
        assert app.query_one("#log").size.height == height_while_typing
        assert options.styles.opacity == 1.0


async def test_status_lists_conditions_and_warns_only_when_in_danger():
    from story.core.session import Status

    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.set_status(status_line(3, [Status(conditions=[("疲勞", "中"), ("恐懼", "輕")])], timed=False))
        line = status_text(app)
        assert "疲勞 · 恐懼" in line and "受傷" not in line and "⚠" not in line and "鑰匙" not in line
        app.set_status(status_line(3, [Status(conditions=[("失血", "重")], warning="瀕死")], timed=False))
        assert "⚠ 瀕死 · 失血" in status_text(app)
        app.set_status(status_line(3, [Status(conditions=[])], timed=False))
        assert "狀態 良好" in status_text(app)


async def test_theme_command_changes_colors_and_is_remembered(isolated):
    from textual.command import CommandPalette

    from story.shells.textual.style import palette

    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await start_game(pilot, app)
        await pilot.press("f2")
        await wait_until(pilot, lambda: isinstance(app.screen, CommandPalette))  # Textual 內建的主題選擇器
        await pilot.press("escape")
        app.theme = "solarized-light"
        await pilot.pause()
        assert app.colors == palette(app.current_theme)
        assert app.colors["良好"] != palette(app.get_theme("tokyo-night"))["良好"]
    assert (isolated / "theme").read_text() == "solarized-light"

    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, ConfirmDialog))  # 有存檔，問要不要繼續
        assert app.theme == "solarized-light"  # 下次開啟沿用


def test_every_builtin_theme_gives_valid_status_colors():
    """ansi 主題的顏色是 ansi_red 這種名稱，要轉成 Rich 認得的寫法，否則狀態列會出錯。"""
    from rich.style import Style
    from textual.theme import BUILTIN_THEMES

    from story.shells.textual.style import palette

    for theme in BUILTIN_THEMES.values():
        for color in palette(theme).values():
            Style.parse(f"bold {color}")  # 認不得會拋出錯誤


async def test_party_status_columns_line_up():
    """多人模式的狀態列：名字長短、狀態多寡不同，狀態欄仍然對齊；手機上「⚠ 重傷」這類小區塊不會被拆開。"""
    from rich.cells import cell_len

    from story.core.session import Status

    party = [
        Status(conditions=[("右臂撕裂傷", "重"), ("小腿挫傷", "中"), ("恐懼", "中"), ("失眠", "輕")], warning="重傷", name="阿民"),
        Status(conditions=[], name="10快快俠"),
    ]

    def column(line: str, word: str) -> int:  # 在畫面上的第幾格（中文字佔兩格）
        return cell_len(line[: line.index(word)])

    for width in (100, 40):
        app = StoryApp()
        async with app.run_test(size=(width, 30)) as pilot:
            await pilot.pause()
            app.set_status(status_line(7, party, timed=False))
            await pilot.pause()
            lines = status_text(app).splitlines()
            first, second = lines[1], next(line for line in lines[2:] if line.startswith("10快快俠"))
            assert "限時模式" not in lines[0] and "一般模式" in lines[0]
            assert column(first, "⚠ 重傷") == column(second, "良好")  # 狀態欄對齊
            if width < 60:
                assert len(lines) > 3  # 窄畫面放不下就換行，但每個狀態都完整
            for word in ("右臂撕裂傷", "小腿挫傷", "恐懼", "失眠"):
                assert any(word in line for line in lines)


async def test_premise_dialog_lets_you_pick_a_genre(monkeypatch):
    from textual.widgets import Select

    from story.core.genres import Genre

    class GenreEngine(FakeEngine):
        genres = {"武俠": Genre(name="武俠", description="江湖恩怨", guide="用古白話。")}

    monkeypatch.setattr(client_module, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=GenreEngine(), **kw))
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, PremiseDialog) and app.screen.query("#genre"))
        app.screen.query_one("#genre", Select).value = "武俠"
        await pilot.pause()
        assert "江湖恩怨" in str(app.screen.query_one("#genre-hint").render())  # 選了題材就顯示它的描述
        app.screen.query_one("#ok", Button).press()
        await wait_until(pilot, lambda: app.choices and not app.typing)
        assert app.client.core.state.genre == "武俠"


async def test_premise_dialog_works_with_arrow_keys_only(monkeypatch):
    """只用方向鍵：從前提輸入框一路往下走到「開始」，題材選單不會把上下鍵攔走；左右鍵可以切換題材。"""
    from textual.widgets import Select

    from story.core.genres import Genre

    class GenreEngine(FakeEngine):
        genres = {"武俠": Genre(name="武俠", description="江湖恩怨", guide="用古白話。")}

    monkeypatch.setattr(client_module, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=GenreEngine(), **kw))
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, PremiseDialog) and app.screen.query("#genre"))
        await pilot.press("down", "down")  # 前提輸入框 → 限時模式 → 題材選單
        assert app.focused.id == "genre"
        await pilot.press("right", "right")  # 自動 → 不套用 → 武俠
        assert app.screen.query_one("#genre", Select).value == "武俠"
        await pilot.press("down")  # 題材選單 → 按鈕列（停在「開始」）
        assert app.focused.id == "ok"
        await pilot.press("enter")
        await wait_until(pilot, lambda: app.choices and not app.typing)
        assert app.client.core.state.genre == "武俠"


async def test_premise_dialog_reroll_and_genre_change_update_the_default(monkeypatch):
    from textual.widgets import Select

    from story.core.genres import Genre

    class PackEngine(FakeEngine):
        genres = {
            "武俠": Genre(name="武俠", description="江湖", guide="古白話。", premises=["你是鏢師。", "你是捕快。"]),
            "克蘇魯": Genre(name="克蘇魯", description="恐怖", guide="暗示。", premises=["你收到舅舅的包裹。"]),
        }

    monkeypatch.setattr(client_module, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=PackEngine(), **kw))
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, PremiseDialog) and app.screen.query("#genre"))
        dialog = app.screen
        dialog.query_one("#genre", Select).value = "克蘇魯"
        await wait_until(pilot, lambda: dialog.default == "你收到舅舅的包裹。")
        assert "你收到舅舅的包裹。" in str(dialog.query_one("#default-hint").render())
        dialog.query_one("#genre", Select).value = "武俠"
        await wait_until(pilot, lambda: dialog.default in ("你是鏢師。", "你是捕快。"))
        before = dialog.default
        dialog.query_one("#reroll", Button).press()
        await wait_until(pilot, lambda: dialog.default != before)  # 換一個
        chosen = dialog.default
        dialog.query_one("#ok", Button).press()
        await wait_until(pilot, lambda: app.choices and not app.typing)
        assert app.client.core.state.premise == chosen and app.client.core.state.genre == "武俠"


async def test_rapid_genre_switching_shows_the_last_genres_premise(monkeypatch):
    """用左右鍵快速連續切換題材：請求排隊、舊的結果丟掉，最後顯示的前提一定屬於最後選的題材。"""
    from story.core.genres import Genre

    class PackEngine(FakeEngine):
        genres = {
            "武俠": Genre(name="武俠", description="江湖", guide="古白話。", premises=["你是鏢師。", "你是捕快。"]),
            "克蘇魯": Genre(name="克蘇魯", description="恐怖", guide="暗示。", premises=["你收到舅舅的包裹。"]),
        }

    monkeypatch.setattr(client_module, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=PackEngine(), **kw))
    app = StoryApp()
    async with app.run_test(size=SIZE) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, PremiseDialog) and app.screen.query("#genre"))
        dialog = app.screen
        dialog.query_one("#genre").focus()
        # 選項順序：自動、不套用、武俠、克蘇魯（循環）。右 5 次停在「不套用」，再左 3 次停在「武俠」
        await pilot.press("right", "right", "right", "right", "right")
        await pilot.press("left", "left", "left")
        await wait_until(pilot, lambda: not dialog.asking.locked())
        await pilot.pause(0.3)
        assert dialog.chosen_genre() == "武俠"
        assert dialog.default in ("你是鏢師。", "你是捕快。")
