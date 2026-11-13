"""The settings file (config.toml in the project folder): reading and writing, environment variables winning, moving old files in. In tests the config lives in a temp folder."""

import stat

from story import settings


def test_put_and_get_and_remove(isolated):
    settings.put("language", "en")
    settings.put("api_key", 'k"ey')
    assert settings.get("language") == "en" and settings.get("api_key") == 'k"ey'
    settings.put("api_key", None)
    assert settings.get("api_key") is None and settings.get("language") == "en"
    assert stat.S_IMODE((isolated / "config.toml").stat().st_mode) == 0o600  # It may hold the API key


def test_environment_variables_win(monkeypatch):
    settings.put("api_key", "from-file")
    settings.put("language", "en")
    assert settings.api_key() == "from-file"
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert settings.api_key() == "from-env"
    assert settings.language() == "zh-TW"  # conftest pins STORY_LANG to Chinese
    monkeypatch.delenv("STORY_LANG")
    assert settings.language() == "en"


def test_old_files_move_into_the_config(isolated):
    old = settings.CONFIG_DIR
    old.mkdir()
    (old / "api_key").write_text("old-key\n")
    assert settings.api_key() is None  # Reading never changes files: setup moves them on launch
    settings.migrate()
    assert settings.api_key() == "old-key"
    assert not (old / "api_key").exists()
    assert 'api_key = "old-key"' in (isolated / "config.toml").read_text()


def test_the_old_config_moves_into_the_project_folder(isolated):
    old = settings.CONFIG_DIR
    old.mkdir()
    (old / "config.toml").write_text('language = "en"\napi_key = "k"\n')
    assert settings.language() == "zh-TW"  # conftest pins STORY_LANG
    assert settings.get("language") == "en"  # Read from the old place until moved: the core reads the language before setup runs
    settings.migrate()
    assert not (old / "config.toml").exists()
    assert settings.get("language") == "en" and settings.get("api_key") == "k"
    assert stat.S_IMODE((isolated / "config.toml").stat().st_mode) == 0o600


def test_the_example_config_is_valid_and_ignored_by_git():
    import tomllib
    from pathlib import Path

    project = Path(__file__).resolve().parents[1]
    example = tomllib.loads((project / "config.example.toml").read_text(encoding="utf-8"))
    assert set(example) <= {"language", "api_key"}
    assert "/config.toml" in (project / ".gitignore").read_text().splitlines()


def test_sections_are_kept_as_tables(isolated):
    (isolated / "config.toml").write_text('[terminal]\ntheme = "nord"\n')
    settings.put("language", "en")
    assert (isolated / "config.toml").read_text() == 'language = "en"\n\n[terminal]\ntheme = "nord"\n'
    assert settings.get("terminal.theme") == "nord" and settings.get("language") == "en"


def test_first_launch_asks_only_for_what_is_missing(monkeypatch):
    """First launch: ask for the language and API key and save them; nothing already in the config is asked again."""
    from story.shells import setup

    monkeypatch.delenv("STORY_LANG")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["2"])  # Pick the second language (English)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(setup, "getpass", lambda prompt="": "my-key")
    setup.run()
    assert settings.get("language") == "en" and settings.get("api_key") == "my-key"

    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(AssertionError("should not ask again")))
    setup.run()  # Everything is set: asks nothing


def test_no_questions_when_not_in_a_terminal(monkeypatch):
    from story.shells import setup

    monkeypatch.delenv("STORY_LANG")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)  # E.g. just start in the background
    setup.run()
    assert settings.load() == {}


def test_a_broken_config_raises_an_error_naming_the_file(isolated):
    import pytest

    (isolated / "config.toml").write_text("language = \n")
    with pytest.raises(settings.InvalidConfig, match="config.toml"):
        settings.load()
