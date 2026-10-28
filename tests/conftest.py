"""Fakes and setup shared by the tests. No test connects to Gemini or touches your real saves or API key."""

import os
from types import SimpleNamespace

import pytest

# The language is fixed at import time: tests always use Chinese, whatever your config or environment chooses
os.environ["STORY_LANG"] = "zh-TW"

from story.games.adventure.engine import Engine
from story.games.adventure.models import Character, Condition, GameState, GenrePick, StoryArc, StoryBeat, Turn
from story.games.adventure.prompting import format_actions
from story.games.soup.models import Puzzle


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test runs in a temp folder (saves/ and anything else are written there) and can't see the real API key."""
    monkeypatch.chdir(tmp_path)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("story.settings.CONFIG_DIR", tmp_path)  # Can't see your config (config.toml)
    monkeypatch.setattr("story.settings.CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr("story.games.adventure.genres.PERSONAL_DIR", tmp_path / "genres")  # Can't see your personal genre packs
    return tmp_path


# ---------- Fake AI replies ----------


HERO = "主角"  # The character's name in solo tests
CHARACTER_FIELDS = {"choices", "conditions_changed", "conditions_removed", "items_gained", "items_lost"}


def beat(**fields) -> StoryBeat:
    """A solo AI reply: the character's changes (choices, conditions_changed…) go straight in the arguments; anything unspecified defaults to "nothing happened"."""
    update = upd(HERO, **{"choices": ["繼續"], **{k: fields.pop(k) for k in CHARACTER_FIELDS & fields.keys()}})
    return pbeat(update, **{"narration": "什麼事也沒發生。", **fields})


def pbeat(*updates, **fields) -> StoryBeat:
    """An AI reply for several characters. Build updates with upd()."""
    base = dict(
        narration="大家各自行動。", character_updates=list(updates), time_passed="片刻", start_time_of_day="傍晚",
        time_limit=0, milestone_reached=False, flags_set=[], key_event="", game_over=False,
    )
    return StoryBeat(**{**base, **fields})


def solo(**fields) -> GameState:
    """A solo game state: one character named HERO. The character's fields (conditions, inventory) go straight in the arguments."""
    character = Character(name=HERO, **{k: fields.pop(k) for k in ("conditions", "inventory") if k in fields})
    return GameState(**{"premise": "x", **fields, "characters": [character]})


def hero(state: GameState) -> Character:
    return state.characters[0]


def upd(name: str, **fields) -> dict:
    """One character's changes this turn."""
    base = dict(name=name, choices=["前進", "等待"], conditions_changed=[], conditions_removed=[], items_gained=[], items_lost=[])
    return {**base, **fields}


def cond(name: str, severity: str, kind: str = "身體") -> dict:
    """The format the AI reports condition changes in."""
    return {"name": name, "kind": kind, "severity": severity}


ARC = StoryArc(
    goal="查出鑰匙的主人",
    twist="鑰匙的主人就是失憶前的你",
    clues=["鑰匙上刻著你的生日", "管理員看到你時愣了一下"],
    acts=[
        {"name": "第一幕", "milestone": "找到地下室"},
        {"name": "第二幕", "milestone": "發現實驗紀錄"},
        {"name": "第三幕", "milestone": "揭發真相"},
        {"name": "第四幕", "milestone": "做出最後的選擇"},
    ],
    endings=["找回記憶", "放下過去"],
)


class FakeGemini:
    """A fake Gemini client: returns the queued results by the call's response_schema and records the prompts sent."""

    def __init__(self, beats=(), arc=ARC, summary="新的摘要", premise="AI 想的開頭", genre=""):
        self.beats = list(beats)
        self.arc, self.summary, self.premise, self.genre = arc, summary, premise, genre
        self.prompts: list[str] = []
        self.models = SimpleNamespace(generate_content=self.generate_content, generate_content_stream=self.generate_content_stream)

    def generate_content_stream(self, model, contents, config, chunk_size=20):
        """The streaming version: turns generate_content's result into text and sends it in small chunks (a structured response is JSON)."""
        response = self.models.generate_content(model=model, contents=contents, config=config)
        parsed = getattr(response, "parsed", None)
        text = parsed.model_dump_json() if parsed is not None else response.text
        usage = getattr(response, "usage_metadata", None)
        for i in range(0, len(text), chunk_size):
            yield SimpleNamespace(text=text[i : i + chunk_size], candidates=[], usage_metadata=usage)

    def generate_content(self, model, contents, config):
        self.prompts.append(contents)
        schema = getattr(config, "response_schema", None)
        if schema is StoryBeat:
            return SimpleNamespace(parsed=self.beats.pop(0), candidates=[])
        if schema is StoryArc:
            return SimpleNamespace(parsed=self.arc)
        if schema is GenrePick:
            return SimpleNamespace(parsed=GenrePick(genre=self.genre))
        if schema is not None:  # Epilogue
            return SimpleNamespace(parsed=schema(title="燈塔守望者", text="多年以後，燈塔仍會亮起。"))
        if "傷重倒下的場景" in contents:
            return SimpleNamespace(text="（倒下的場景）")
        if "故事前提" in contents and "題材" in contents:
            return SimpleNamespace(text=self.premise)
        return SimpleNamespace(text=self.summary)


def make_engine(*beats, genres=None, **kwargs) -> tuple[Engine, FakeGemini]:
    """Builds a real Engine on a fake Gemini, so the engine's rules really run.
    No genre packs by default (so results are fixed); pass genres to test genres."""
    gemini = FakeGemini(beats, **kwargs)
    return Engine(client=gemini, genres=genres or {}), gemini


# ---------- Fake engines for the core and shells (no rules; change the state directly) ----------


class FakeEngine:
    """Stands in for Engine so core and shell tests can control each turn exactly. A solo lighthouse story."""

    genres: dict = {}  # Subclasses can swap in their own genre packs
    stage = draft = ""  # Like Engine: the opening's progress, narration while streaming

    def __init__(self):
        self.fail_with: Exception | None = None  # The error the next act() raises
        self.compacted = 0

    def suggest_premise(self, avoid="", genre=""):
        return "你是月球礦坑的夜班工程師。"

    def needs_compaction(self, state):
        return state.turn == 2

    def compact_memory(self, state):
        self.compacted += 1

    def start(self, state):
        me = state.characters[0]
        state.turn, state.minutes, me.inventory = 1, 18 * 60, ["鑰匙"]
        state.current_narration = "你在燈塔醒來。"
        me.choices = ["往上爬", "檢查鑰匙"]
        state.current_time_limit = 10 if state.timed_mode else 0

    def act(self, state, actions):
        if self.fail_with:
            state.turn += 99  # Simulates failing halfway through changes
            raise self.fail_with
        state.recent.append(Turn(narration=state.current_narration, action=format_actions(actions)))  # Records the story log like the real engine
        me, action = state.characters[0], next(iter(actions.values()))
        state.turn += 1
        state.current_narration = f"你選擇了「{action}」。"
        if state.turn == 2:
            me.inventory.append("油燈")
            me.conditions = [Condition(name="小腿挫傷", kind="body", severity="moderate")]
            me.choices = ["點亮油燈", "躲起來"]
            state.current_time_limit = 10 if state.timed_mode else 0
        else:
            me.choices, state.current_time_limit, state.game_over = [], 0, True

    def write_epilogue(self, state):
        state.ending_title, state.epilogue = "燈塔守望者", "多年以後，燈塔仍會亮起。"


class FakeGroupEngine:
    """Stands in for Engine to control each turn exactly. A lighthouse story for Ming and Hua (just Ming when alone)."""

    genres: dict = {}
    stage = draft = ""

    def __init__(self):
        self.rounds: list[dict] = []
        self.fail_with: Exception | None = None

    def needs_compaction(self, state):
        return False

    def suggest_premise(self, avoid="", genre=""):
        return "AI 想的開頭"

    def start(self, state):
        state.turn, state.minutes = 1, 600
        state.current_narration = "兩人在燈塔醒來。"
        for c in state.characters:
            c.choices = [f"{c.name}往上爬", f"{c.name}躲起來"]

    def act(self, state, actions):
        if self.fail_with:
            state.turn += 99
            raise self.fail_with
        self.rounds.append(dict(actions))
        state.recent.append(Turn(narration=state.current_narration, action=format_actions(actions)))
        state.turn += 1
        state.current_narration = "；".join(f"{k}{v}" for k, v in actions.items())
        if state.turn == 2:
            state.characters[0].inventory.append("油燈")
        if state.turn >= 3:
            state.characters[0].alive, state.characters[0].choices = False, []
        if state.turn >= 4:
            state.game_over = True

    def write_epilogue(self, state):
        state.ending_title, state.epilogue = "燈塔雙人行", "兩人的故事結束了。"


class InvalidKeyError(RuntimeError):
    """Simulates Gemini reporting an invalid API key."""

    code = 400

    def __str__(self):
        return "API key not valid. Please pass a valid API key."


# ---------- Turtle soup ----------

PUZZLE = Puzzle(title="空號", surface="他每晚撥同一個空號。", truth="那是母親錄的語音。", key_points=["語音是母親錄的", "母親過世了", "他想聽母親的聲音"])
AI_PUZZLE = Puzzle(title="AI 的題目", surface="AI 的湯面", truth="AI 的湯底", key_points=["一", "二"])


class FakeJudge:
    """A fake judge: questions are always answered "yes"; a guess containing 「全部」 ("all") hits every key point, otherwise one."""

    def __init__(self, puzzle=None, fail_with=None):
        self.stage = ""
        self.puzzle, self.fail_with = puzzle, fail_with
        self.rounds: list[list[tuple[str, str, str]]] = []
        self.avoided: list[str] = []

    def judge(self, state, moves):
        if self.fail_with:
            raise self.fail_with
        self.rounds.append([(m.name, m.kind, m.text) for m in moves])
        for m in moves:
            if m.kind == "ask":
                m.answer = "yes"
            else:
                m.hit = len(state.puzzle.key_points) if "全部" in m.text else 1

    def make_puzzle(self, avoid):
        self.avoided = avoid
        if isinstance(self.puzzle, Exception):
            raise self.puzzle
        return self.puzzle
