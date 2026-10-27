"""所有外殼都要遵守的架構規則。網頁版的測試在 test_web.py。"""

import re


def test_shells_only_use_the_public_core_interface():
    """外殼只能透過核心與玩法的公開介面溝通：只 import story.core、story.games 匯出的名稱，只用公開的方法與唯讀屬性。
    直接讀核心內部（core.state、core.engine……）時這裡會失敗，核心內部怎麼改才不會弄壞外殼。"""
    from pathlib import Path

    import story.core
    import story.games
    import story.shells

    exported = {"story.core": story.core.__all__, "story.games": story.games.__all__}
    public = {"send", "start", "action_for", "set_api_key", "progress", "draft", "phase", "players", "send_as", "view", "waiting"}
    problems = []
    for path in sorted(Path(story.shells.__file__).parent.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for module, names in re.findall(r"^\s*from (story\.(?:core|games)[\w.]*) import ([^\n]+)", source, re.M):
            if module not in exported:
                problems.append(f"{path.name}: from {module} import …（只能從 story.core、story.games import）")
                continue
            for name in (n.strip() for n in names.split(",")):
                if name not in exported[module]:
                    problems.append(f"{path.name}: {name} 不是 {module} 匯出的名稱")
        for attribute in set(re.findall(r"\bcore\.(\w+)", source)):
            if attribute not in public:
                problems.append(f"{path.name}: core.{attribute} 不是公開介面")
    assert problems == []


def test_layers_only_depend_outward():
    """一層一層往外疊：核心不 import 玩法與外殼；每種玩法只 import 核心與自己，玩法之間互不相依、也不 import 外殼。
    新增玩法時照著做，就不會動到核心與其他玩法。"""
    from pathlib import Path

    import story

    root = Path(story.__file__).parent
    problems = []
    for path in sorted(root.rglob("*.py")):
        layer = path.relative_to(root).parts
        if layer[0] == "core":
            allowed = ("story.core", "story.settings", "story import settings")
        elif layer[0] == "games" and len(layer) > 2:
            allowed = ("story.core", f"story.games.{layer[1]}", "story import settings")
        else:
            continue
        for module in re.findall(r"^\s*(?:from|import) (story[\w.]*(?: import settings)?)", path.read_text(encoding="utf-8"), re.M):
            if not module.startswith(allowed):
                problems.append(f"{path.relative_to(root)}: {module}")
    assert problems == []


def test_interfaces_go_through_the_shared_client_layer():
    """介面（網頁的 View）只負責長相：不自己建立核心、不直接連房間、不呼叫核心的方法，流程一律交給共用層（client.py）。
    網頁伺服器（web/__init__.py）負責開房間與連線，不算介面。"""
    from pathlib import Path

    import story.shells.web.view

    problems = []
    for path in [Path(story.shells.web.view.__file__)]:
        source = path.read_text(encoding="utf-8")
        for name in ("StoryCore", "Connection", "story.shells.room", "story.shells.players"):
            if name in source:
                problems.append(f"{path.name}: 用到 {name}（應該交給共用層）")
        if re.search(r"\bcore\.\w+", source):
            problems.append(f"{path.name}: 直接呼叫核心")
    assert problems == []
