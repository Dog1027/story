"""玩家的設定檔（~/.config/story/config.toml）：讀寫、環境變數優先、舊檔案搬進來。測試裡的設定檔在暫存資料夾。"""

import stat

from story import settings


def test_put_and_get_and_remove(isolated):
    settings.put("language", "en")
    settings.put("api_key", 'k"ey')
    assert settings.get("language") == "en" and settings.get("api_key") == 'k"ey'
    settings.put("api_key", None)
    assert settings.get("api_key") is None and settings.get("language") == "en"
    assert stat.S_IMODE((isolated / "config.toml").stat().st_mode) == 0o600  # 裡面可能有 API key


def test_environment_variables_win(monkeypatch):
    settings.put("api_key", "from-file")
    settings.put("language", "en")
    assert settings.api_key() == "from-file"
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert settings.api_key() == "from-env"
    assert settings.language() == "zh-TW"  # conftest 用 STORY_LANG 固定成中文
    monkeypatch.delenv("STORY_LANG")
    assert settings.language() == "en"


def test_old_files_move_into_the_config(isolated):
    (isolated / "api_key").write_text("old-key\n")
    assert settings.api_key() == "old-key"
    assert not (isolated / "api_key").exists()
    assert 'api_key = "old-key"' in (isolated / "config.toml").read_text()


def test_sections_are_kept_as_tables(isolated):
    (isolated / "config.toml").write_text('[terminal]\ntheme = "nord"\n')
    settings.put("language", "en")
    assert (isolated / "config.toml").read_text() == 'language = "en"\n\n[terminal]\ntheme = "nord"\n'
    assert settings.get("terminal.theme") == "nord" and settings.get("language") == "en"


def test_first_launch_asks_only_for_what_is_missing(monkeypatch):
    """第一次啟動：問語言與 API key，存進設定檔；設定檔裡有的就不再問。"""
    from story import setup

    monkeypatch.delenv("STORY_LANG")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["2"])  # 語言選第二個（English）
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(setup, "getpass", lambda prompt="": "my-key")
    setup.run()
    assert settings.get("language") == "en" and settings.get("api_key") == "my-key"

    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(AssertionError("不該再問")))
    setup.run()  # 都有了：什麼都不問


def test_no_questions_when_not_in_a_terminal(monkeypatch):
    from story import setup

    monkeypatch.delenv("STORY_LANG")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)  # 例如 just start 在背景啟動
    setup.run()
    assert settings.load() == {}
