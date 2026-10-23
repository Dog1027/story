"""純文字外殼，以及所有外殼都要遵守的架構規則。網頁版的測試在 test_web.py。"""

import re

from conftest import FakeEngine

import story.shells.plain as plain
from story.core import StoryCore


def test_plain_shell_plays_a_whole_story(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(plain, "StoryCore", lambda api_key, **kw: StoryCore(api_key, engine=FakeEngine(), **kw))
    inputs = iter(["", "1", "2", "", "/quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    plain.main()
    out = capsys.readouterr().out
    assert "你在燈塔醒來。" in out
    assert "回合 2｜狀態 小腿挫傷（中）" in out
    assert "─── 燈塔守望者 ───" in out
    assert "已存檔，下次見。" in out


def test_plain_shell_party_mode(monkeypatch, capsys):
    from conftest import FakePartyEngine
    from story.core import PartyCore

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(plain, "PartyCore", lambda api_key, players: PartyCore(api_key, players, engine=FakePartyEngine()))
    inputs = iter(["阿明,阿明", "阿明,小華", "", "1", "2", "/quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    plain.main(party=True)
    out = capsys.readouterr().out
    assert "多人模式需要 1 到" in out  # 名字重複
    assert "輪到 阿明 行動" in out and "輪到 小華 行動" in out
    assert "阿明　獲得 油燈" in out


def test_shells_only_use_the_public_core_interface():
    """外殼只能透過核心的公開介面溝通：只 import story.core 匯出的名稱，只用公開的方法與唯讀屬性。
    直接讀核心內部（core.state、core.engine……）時這裡會失敗，核心內部怎麼改才不會弄壞外殼。"""
    from pathlib import Path

    import story.core
    import story.shells

    public = {"send", "start", "action_for", "set_api_key", "progress", "draft", "phase", "players", "send_as", "view", "waiting"}
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


def test_interfaces_go_through_the_shared_client_layer():
    """介面（Textual、網頁的 View）只負責長相：不自己建立核心、不直接連房間、不呼叫核心的方法，流程一律交給共用層（client.py）。
    這樣新增其他介面時，流程不用再寫一次。網頁伺服器（web/__init__.py）負責開房間與連線，不算介面。"""
    from pathlib import Path

    import story.shells.textual
    import story.shells.web.view

    problems = []
    interfaces = [*Path(story.shells.textual.__file__).parent.rglob("*.py"), Path(story.shells.web.view.__file__)]
    for path in sorted(interfaces):
        source = path.read_text(encoding="utf-8")
        for name in ("StoryCore", "PartyCore", "RoomConnection", "story.shells.room", "story.shells.apikey", "story.shells.players"):
            if name in source:
                problems.append(f"{path.name}: 用到 {name}（應該交給共用層）")
        if re.search(r"\bcore\.\w+", source):
            problems.append(f"{path.name}: 直接呼叫核心")
    assert problems == []
