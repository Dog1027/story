"""測試共用的假物件與設定。所有測試都不會連到 Gemini，也不會動到你真的存檔或 API key。"""

from types import SimpleNamespace

import pytest

from story.core.engine import Engine
from story.core.models import Condition, StoryArc, StoryBeat


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """每個測試都在暫存資料夾裡執行（save.json、saves/ 都寫在那裡），並且看不到真的 API key。"""
    monkeypatch.chdir(tmp_path)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("story.shells.apikey.KEY_PATH", tmp_path / "api_key")
    return tmp_path


# ---------- 假的 AI 回覆 ----------


def beat(**fields) -> StoryBeat:
    """建立一個 StoryBeat，沒指定的欄位用「什麼都沒發生」的預設值。"""
    base = dict(
        narration="什麼事也沒發生。", choices=["繼續"], conditions_changed=[], conditions_removed=[],
        time_passed="片刻", start_time_of_day="傍晚", time_limit=0, milestone_reached=False,
        items_gained=[], items_lost=[], flags_set=[], key_event="", game_over=False,
    )
    return StoryBeat(**{**base, **fields})


def cond(name: str, severity: str, kind: str = "身體") -> dict:
    """AI 回報狀態變化的格式。"""
    return {"name": name, "kind": kind, "severity": severity}


ARC = StoryArc(
    goal="查出鑰匙的主人",
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

    def __init__(self, beats=(), arc=ARC, summary="新的摘要", premise="AI 想的開頭"):
        self.beats = list(beats)
        self.arc, self.summary, self.premise = arc, summary, premise
        self.prompts: list[str] = []
        self.models = SimpleNamespace(generate_content=self.generate_content)

    def generate_content(self, model, contents, config):
        self.prompts.append(contents)
        schema = getattr(config, "response_schema", None)
        if schema is StoryBeat:
            return SimpleNamespace(parsed=self.beats.pop(0), candidates=[])
        if schema is StoryArc:
            return SimpleNamespace(parsed=self.arc)
        if schema is not None:  # Epilogue
            return SimpleNamespace(parsed=schema(title="燈塔守望者", text="多年以後，燈塔仍會亮起。"))
        if "故事前提" in contents and "題材" in contents:
            return SimpleNamespace(text=self.premise)
        return SimpleNamespace(text=self.summary)


def make_engine(*beats, **kwargs) -> tuple[Engine, FakeGemini]:
    """用假的 Gemini 建立真的 Engine，所以 engine 的規則都會實際執行。"""
    gemini = FakeGemini(beats, **kwargs)
    return Engine(client=gemini), gemini


# ---------- 給核心與外殼用的假 engine（不跑規則，直接改狀態） ----------


class FakeEngine:
    """取代 Engine，讓核心與外殼的測試可以精準控制每回合的結果。"""

    def __init__(self):
        self.fail_with: Exception | None = None  # 下一次 act() 要拋出的錯誤
        self.compacted = 0
        self.keys: list[str] = []

    def set_api_key(self, key):
        self.keys.append(key)
        self.fail_with = None

    def suggest_premise(self, avoid=""):
        return "你是月球礦坑的夜班工程師。"

    def needs_compaction(self, state):
        return state.turn == 2

    def compact_memory(self, state):
        self.compacted += 1

    def start(self, state):
        state.turn, state.minutes, state.inventory = 1, 18 * 60, ["鑰匙"]
        state.current_narration = "你在燈塔醒來。"
        state.current_choices = ["往上爬", "檢查鑰匙"]
        state.current_time_limit = 10 if state.timed_mode else 0

    def act(self, state, action):
        if self.fail_with:
            state.turn += 99  # 模擬改了一半就失敗
            raise self.fail_with
        state.turn += 1
        state.current_narration = f"你選擇了「{action}」。"
        if state.turn == 2:
            state.inventory.append("油燈")
            state.conditions = [Condition(name="小腿挫傷", kind="身體", severity="中")]
            state.current_choices = ["點亮油燈", "躲起來"]
            state.current_time_limit = 10 if state.timed_mode else 0
        else:
            state.current_choices, state.current_time_limit, state.game_over = [], 0, True

    def write_epilogue(self, state):
        state.ending_title, state.epilogue = "燈塔守望者", "多年以後，燈塔仍會亮起。"


class InvalidKeyError(RuntimeError):
    """模擬 Gemini 回報 API key 無效。"""

    code = 400

    def __str__(self):
        return "API key not valid. Please pass a valid API key."
