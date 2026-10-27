"""測試共用的假物件與設定。所有測試都不會連到 Gemini，也不會動到你真的存檔或 API key。"""

import os
from types import SimpleNamespace

import pytest

# 語言在 import 時就決定了：測試一律用中文，不管你的設定檔或環境變數選了什麼
os.environ["STORY_LANG"] = "zh-TW"

from story.games.adventure.engine import Engine
from story.games.adventure.models import Character, Condition, GameState, GenrePick, StoryArc, StoryBeat, Turn
from story.games.adventure.prompting import format_actions
from story.games.soup.models import Puzzle


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """每個測試都在暫存資料夾裡執行（save.json、saves/ 都寫在那裡），並且看不到真的 API key。"""
    monkeypatch.chdir(tmp_path)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("story.settings.CONFIG_DIR", tmp_path)  # 看不到你的設定檔（config.toml）
    monkeypatch.setattr("story.settings.CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr("story.games.adventure.genres.PERSONAL_DIR", tmp_path / "genres")  # 看不到你個人的題材包
    return tmp_path


# ---------- 假的 AI 回覆 ----------


HERO = "主角"  # 一個人玩的測試裡，那位角色的名字
CHARACTER_FIELDS = {"choices", "conditions_changed", "conditions_removed", "items_gained", "items_lost"}


def beat(**fields) -> StoryBeat:
    """一個人玩的 AI 回覆：角色的變化（choices、conditions_changed……）直接寫在參數裡，沒指定的用「什麼都沒發生」的預設值。"""
    update = upd(HERO, **{"choices": ["繼續"], **{k: fields.pop(k) for k in CHARACTER_FIELDS & fields.keys()}})
    return pbeat(update, **{"narration": "什麼事也沒發生。", **fields})


def pbeat(*updates, **fields) -> StoryBeat:
    """好幾位角色的 AI 回覆。updates 用 upd() 建立。"""
    base = dict(
        narration="大家各自行動。", character_updates=list(updates), time_passed="片刻", start_time_of_day="傍晚",
        time_limit=0, milestone_reached=False, flags_set=[], key_event="", game_over=False,
    )
    return StoryBeat(**{**base, **fields})


def solo(**fields) -> GameState:
    """一個人玩的遊戲狀態：一位叫 HERO 的角色。角色的欄位（conditions、inventory）直接寫在參數裡。"""
    character = Character(name=HERO, **{k: fields.pop(k) for k in ("conditions", "inventory") if k in fields})
    return GameState(**{"premise": "x", **fields, "characters": [character]})


def hero(state: GameState) -> Character:
    return state.characters[0]


def upd(name: str, **fields) -> dict:
    """一位角色這回合的變化。"""
    base = dict(name=name, choices=["前進", "等待"], conditions_changed=[], conditions_removed=[], items_gained=[], items_lost=[])
    return {**base, **fields}


def cond(name: str, severity: str, kind: str = "身體") -> dict:
    """AI 回報狀態變化的格式。"""
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
    """假的 Gemini client：依照呼叫的 response_schema 回傳排好的結果，並記下送出的提示詞。"""

    def __init__(self, beats=(), arc=ARC, summary="新的摘要", premise="AI 想的開頭", genre=""):
        self.beats = list(beats)
        self.arc, self.summary, self.premise, self.genre = arc, summary, premise, genre
        self.prompts: list[str] = []
        self.models = SimpleNamespace(generate_content=self.generate_content, generate_content_stream=self.generate_content_stream)

    def generate_content_stream(self, model, contents, config, chunk_size=20):
        """串流版：把 generate_content 的結果轉成文字，切成小段依序送出（結構化的回傳就是 JSON）。"""
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
    """用假的 Gemini 建立真的 Engine，所以 engine 的規則都會實際執行。
    預設不載入題材包（結果才固定），要測題材時傳 genres。"""
    gemini = FakeGemini(beats, **kwargs)
    return Engine(client=gemini, genres=genres or {}), gemini


# ---------- 給核心與外殼用的假 engine（不跑規則，直接改狀態） ----------


class FakeEngine:
    """取代 Engine，讓核心與外殼的測試可以精準控制每回合的結果。一個人玩的燈塔故事。"""

    genres: dict = {}  # 子類別可以換成自己的題材包
    stage = draft = ""  # 跟 Engine 一樣：開場的進度、串流中的劇情

    def __init__(self):
        self.fail_with: Exception | None = None  # 下一次 act() 要拋出的錯誤
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
            state.turn += 99  # 模擬改了一半就失敗
            raise self.fail_with
        state.recent.append(Turn(narration=state.current_narration, action=format_actions(actions)))  # 跟真的 engine 一樣記下劇情紀錄
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
    """取代 Engine，精準控制每回合。阿明與小華兩個人的燈塔故事（一個人時就是阿明）。"""

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
    """模擬 Gemini 回報 API key 無效。"""

    code = 400

    def __str__(self):
        return "API key not valid. Please pass a valid API key."


# ---------- 海龜湯 ----------

PUZZLE = Puzzle(title="空號", surface="他每晚撥同一個空號。", truth="那是母親錄的語音。", key_points=["語音是母親錄的", "母親過世了", "他想聽母親的聲音"])
AI_PUZZLE = Puzzle(title="AI 的題目", surface="AI 的湯面", truth="AI 的湯底", key_points=["一", "二"])


class FakeJudge:
    """假的裁判：提問一律回答「是」；猜湯底時，文字裡有「全部」就說中所有關鍵點，否則說中一個。"""

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
