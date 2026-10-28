"""Architecture rules every shell follows. The web version's tests are in test_web.py."""

import re


def test_shells_only_use_the_public_core_interface():
    """Shells talk to the core only through the public interface of the core and games: they only import names exported by story.core and story.games, and only use public methods and read-only attributes.
    Reading core internals directly (core.state, core.engine…) fails here, so the core's internals can change without breaking the shells."""
    from pathlib import Path

    import story.core
    import story.games
    import story.shells

    exported = {"story.core": story.core.__all__, "story.games": story.games.__all__}
    public = {"send", "start", "action_for", "watch", "progress", "draft", "phase", "players", "send_as", "view", "waiting"}
    problems = []
    for path in sorted(Path(story.shells.__file__).parent.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for module, names in re.findall(r"^\s*from (story\.(?:core|games)[\w.]*) import ([^\n]+)", source, re.M):
            if module not in exported:
                problems.append(f"{path.name}: from {module} import … (only import from story.core, story.games)")
                continue
            for name in (n.strip() for n in names.split(",")):
                if name not in exported[module]:
                    problems.append(f"{path.name}: {name} is not exported by {module}")
        for attribute in set(re.findall(r"\bcore\.(\w+)", source)):
            if attribute not in public:
                problems.append(f"{path.name}: core.{attribute} is not part of the public interface")
    assert problems == []


def test_layers_only_depend_outward():
    """Layers stack outward: the core imports no games or shells; each game imports only the core and itself, games don't depend on each other, and no game imports the shells.
    Follow this when adding a game and the core and other games stay untouched."""
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
    """The interface (the web View) only handles looks: it never builds a core, connects to rooms directly, or calls core methods; the flow always goes to the shared layer (client.py).
    The web server (web/__init__.py) opens rooms and connections and doesn't count as the interface."""
    from pathlib import Path

    import story.shells.web.view

    problems = []
    for path in [Path(story.shells.web.view.__file__)]:
        source = path.read_text(encoding="utf-8")
        for name in ("AdventureCore", "SoupCore", "Connection", "story.shells.room", "story.shells.players"):
            if name in source:
                problems.append(f"{path.name}: uses {name} (should go through the shared layer)")
        if re.search(r"\bcore\.\w+", source):
            problems.append(f"{path.name}: calls the core directly")
    assert problems == []
