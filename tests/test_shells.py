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
    public = {"send", "start", "action_for", "watch", "progress", "busy_label", "draft", "phase", "players", "send_as", "view", "waiting"}
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


def test_rooms_and_screens_only_meet_through_a_connection():
    """Inside the shells: the lobby and rooms (rooms/) don't know which games exist, how things are shown, or the settings; each tab's flow
    (screen/) doesn't know about rooms. They only share connection.py, messages.py (the message types), players.py and text.py. Only web/ wires them to the games and settings."""
    from pathlib import Path

    import story.shells

    root = Path(story.shells.__file__).parent
    shared = ("story.core", "story.shells.connection", "story.shells.messages", "story.shells.players", "story.shells.text")
    allowed = {"rooms": (*shared, "story.shells.rooms"), "screen": (*shared, "story.shells.screen")}
    problems = []
    for part, ok in allowed.items():
        for path in sorted((root / part).rglob("*.py")):
            for module in re.findall(r"^\s*(?:from|import) (story[\w.]*)", path.read_text(encoding="utf-8"), re.M):
                if not module.startswith(ok):
                    problems.append(f"{path.relative_to(root)}: {module}")
    assert problems == []


def test_interfaces_go_through_the_shared_client_layer():
    """The interface (the web View) only handles looks: it never builds a core, connects to rooms directly, or calls core methods; the flow always goes to the shared layer (screen/client.py).
    The web server (web/server.py, web/hosting.py) opens rooms and connections and doesn't count as the interface."""
    from pathlib import Path

    import story.shells.web.view

    problems = []
    for path in [Path(story.shells.web.view.__file__)]:
        source = path.read_text(encoding="utf-8")
        for name in ("AdventureCore", "SoupCore", "Connection", "story.shells.rooms.room", "story.shells.players"):
            if re.search(rf"\b{re.escape(name)}\b", source):
                problems.append(f"{path.name}: uses {name} (should go through the shared layer)")
        if re.search(r"\bcore\.\w+", source):
            problems.append(f"{path.name}: calls the core directly")
    assert problems == []
