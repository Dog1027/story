"""評估（evals）：用固定的情境讓 AI 真的寫一回合，再由程式與評審（另一次 AI 呼叫）檢查寫得對不對。

會呼叫真的 Gemini（花一點錢，跑一兩分鐘），所以不在 just test 裡。改了 story/prompts/ 之後手動執行：

    just eval                  全部情境，各跑 3 次
    just eval reveal agency    只跑這兩個情境
    just eval --runs 5         各跑 5 次（AI 每次寫的不一樣，次數多比較準）
    just eval --rpm 60         每分鐘最多呼叫 60 次（付費方案可以調高，跑比較快）

情境寫在這裡（範例故事跟 just prompts 共用），評審的標準在 story/prompts/語言/eval.md。
每次的劇情、選項、評審理由都存到 eval_results/，方便比較改提示詞之前與之後。不會動到存檔與遊戲紀錄。
"""

import json
import re
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from google.genai import errors, types
from pydantic import BaseModel, Field

from story.core import prompts
from story.core.engine import ACT_TURNS, MODEL, Engine, body_level, body_score, new_client
from story.core.genres import Genre, load_genres
from story.core.models import SCHEMA, Condition, GameState
from story.preview import ARC, PREMISE, sample_state
from story.shells.apikey import get_saved_api_key

EVAL = prompts.sections("eval")
# 評審跟遊戲用同一個模型，但多想一點。免費方案的 gemini-3.5-flash 每分鐘只能呼叫 5 次，有付費的話換成它判斷會更可靠
JUDGE_MODEL = MODEL
RUNS = 3
WORKERS = 8  # 同時跑幾個情境
RPM = 14  # 每分鐘最多呼叫幾次 AI：免費方案的 flash-lite 上限是 15。全部情境跑 3 次約 90 次呼叫，要六、七分鐘
RATE_LIMIT_RETRIES = 3  # 還是超過上限（429）時，等 Gemini 說的秒數再送，最多幾次
RESULTS_DIR = Path("eval_results")
ARMED = "樓下的門被撞開，一個持刀的黑衣人衝上樓梯，堵住了唯一的出口。"


def schema_range(text: str) -> tuple[int, int]:
    """schema.md 裡的「150-300 字」「2-4 個」：改了那裡，這裡的檢查跟著變。"""
    low, high = re.search(r"(\d+)-(\d+)", text).groups()
    return int(low), int(high)


NARRATION_LEN = schema_range(SCHEMA["StoryBeat.narration"])
CHOICE_COUNT = schema_range(SCHEMA["StoryBeat.choices"])


class Throttle:
    """所有情境共用：AI 呼叫排隊，平均分散在每分鐘的上限內，超過上限時等一下再送。"""

    def __init__(self, rpm: int):
        self.interval = 60 / rpm
        self.next = time.monotonic()
        self.lock = threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            start, self.next = max(now, self.next), max(now, self.next) + self.interval
        time.sleep(start - now)

    def call(self, send):
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            self.wait()
            try:
                return send()
            except errors.ClientError as e:
                if e.code != 429 or attempt == RATE_LIMIT_RETRIES:
                    raise
                delay = re.search(r"retry in ([\d.]+)s", str(e))
                time.sleep(float(delay.group(1)) if delay else 30)

    def wrap(self, client):
        """包住 Gemini client，讓 Engine 和評審的呼叫都經過這裡。串流的請求在讀第一段時才送出，所以把讀第一段也包進來。"""
        models = client.models

        def stream(**request):
            def first():
                chunks = models.generate_content_stream(**request)
                return chunks, next(chunks, None)

            chunks, head = self.call(first)
            if head is not None:
                yield head
                yield from chunks

        return SimpleNamespace(client=client, models=SimpleNamespace(  # client 要留著，被回收時會關掉連線
            generate_content=lambda **request: self.call(lambda: models.generate_content(**request)),
            generate_content_stream=stream,
        ))


class Verdict(BaseModel):
    reason: str = Field(description=EVAL["Verdict.reason"])
    passed: bool = Field(description=EVAL["Verdict.passed"])


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Run:
    """一個情境跑一次的結果。"""

    narration: str = ""
    choices: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    error: str = ""


class Trial:
    """跑一次情境：一個真的 Engine，加上記下檢查結果的工具。"""

    def __init__(self, client, genres: dict[str, Genre], log_path: Path):
        self.engine = Engine(client=client, genres=genres, log_path=log_path)
        self.log_path = log_path
        self.checks: list[Check] = []

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(name, bool(passed), detail))

    def judge(self, name: str, section: str, **values) -> None:
        response = self.engine.client.models.generate_content(
            model=JUDGE_MODEL,
            contents=EVAL[section].format(**values),
            config=types.GenerateContentConfig(
                system_instruction=EVAL["system"],
                response_mime_type="application/json",
                response_schema=Verdict,
                thinking_config=types.ThinkingConfig(thinking_level="medium"),
            ),
        )
        verdict = response.parsed
        if isinstance(verdict, Verdict):
            self.check(name, verdict.passed, verdict.reason)
        else:
            self.check(name, False, "評審沒有回傳結果")

    def basics(self, state: GameState, may_end: bool = False) -> None:
        """每個情境都要符合的：字數、選項個數，以及故事還沒結束。"""
        length = len(re.sub(r"\s", "", state.current_narration))
        low, high = NARRATION_LEN
        self.check(f"劇情 {low}-{high} 字", low <= length <= high, f"{length} 字")
        if not state.game_over:
            count, (low, high) = len(state.current_choices), CHOICE_COUNT
            self.check(f"選項 {low}-{high} 個", low <= count <= high, f"{count} 個")
        if not may_end:
            self.check("故事沒有結束", not state.game_over)

    def tried_ending(self) -> bool:
        """AI 一開始寫了結局、被程式中斷要求重寫（見 Engine._next_beat）。"""
        if not self.log_path.exists():
            return False
        records = [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]
        return any("stopped" in call for record in records for call in record["calls"])


# ---------- 情境：每個都回傳跑完的狀態 ----------


def opening(t: Trial) -> GameState:
    state = GameState(premise=PREMISE)
    t.engine.start(state)
    arc = state.arc
    t.check("大綱有隱藏的真相與伏筆", arc is not None and arc.twist and arc.clues)
    t.basics(state)
    if arc is not None and arc.twist:
        t.judge("開場沒有說破真相", "twist_hidden", twist=arc.twist, narration=state.current_narration)
    return state


def early(t: Trial) -> GameState:
    state = sample_state(False, "", act=1, act_turns=3, turn=12,
                         current_narration="日誌最後一頁寫著：「別再追查下去。」暴風雨停了，岸邊繫著一艘小船。")
    action = "把日誌丟進海裡，搭上岸邊的小船離開這座島，從此不再回來"
    t.engine.act(state, action)
    t.check("沒有試圖寫出結局", not t.tried_ending(), "AI 一開始寫了結局，被要求重寫")
    t.basics(state)
    t.judge("劇情沒有寫成結局", "no_ending", action=action, narration=state.current_narration,
            choices="\n".join(state.current_choices))
    return state


def reveal(t: Trial) -> GameState:
    state = sample_state(False, "", act=2, act_turns=ACT_TURNS, turn=18,
                         current_narration="你撬開燈塔底層的地板，底下是通往密室的石階，深處透出微弱的燈光，還有人在咳嗽。")
    t.engine.act(state, "走下石階，進入密室")
    t.basics(state)
    t.judge("揭露了隱藏的真相", "reveal", twist=ARC.twist, clues="\n".join(f"- {c}" for c in ARC.clues),
            narration=state.current_narration)
    return state


def agency(t: Trial) -> GameState:
    state = sample_state(False, "")
    action = "照著日誌打出燈號回應"
    t.engine.act(state, action)
    t.basics(state)
    t.judge("沒有替玩家做決定", "agency", action=action, narration=state.current_narration)
    return state


def reckless(t: Trial) -> GameState:
    state = sample_state(False, "", current_narration=ARMED)
    before = body_score(state)
    t.engine.act(state, "不管右臂的傷，赤手空拳撲向持刀的黑衣人")
    after = body_score(state)
    t.check("魯莽的行動受了傷（傷勢總分至少加 2）", after - before >= 2, f"傷勢總分 {before} → {after}")
    t.basics(state, may_end=True)
    return state


def dying(t: Trial) -> GameState:
    wounds = [Condition(name="右臂撕裂傷", kind="身體", severity="重"), Condition(name="失血", kind="身體", severity="中")]
    state = sample_state(False, "", conditions=wounds, current_narration=ARMED)
    t.engine.act(state, "不管身上的傷，赤手空拳撲向持刀的黑衣人")
    t.check("瀕死還冒險就喪命", body_level(state) == "死亡", f"整體狀態：{body_level(state)}")
    return state


def tone(genre: Genre) -> Callable[[Trial], GameState]:
    def run(t: Trial) -> GameState:
        state = GameState(premise=genre.premises[0] if genre.premises else PREMISE, genre=genre.name)
        t.engine.start(state)
        t.basics(state)
        t.judge("符合題材的文風", "tone", genre=genre.name, guide=genre.guide, narration=state.current_narration)
        return state

    return run


def scenarios(genres: dict[str, Genre]) -> dict[str, tuple[str, Callable[[Trial], GameState]]]:
    """{代號: (說明, 情境)}。每個題材包各有一個情境，代號就是題材名稱。"""
    found = {
        "opening": ("開場：規劃大綱，開場不說破真相", opening),
        "early": ("第二幕玩家想離開：不能太早寫出結局", early),
        "reveal": ("第三幕走進密室：揭露隱藏的真相", reveal),
        "agency": ("一般回合：不替玩家決定行動或感受", agency),
        "reckless": ("魯莽的行動：要付出代價", reckless),
        "dying": ("瀕死還冒險：會死", dying),
    }
    for name, genre in genres.items():
        found[name] = (f"題材「{name}」的開場：文風符合題材指引", tone(genre))
    return found


# ---------- 執行與報告 ----------


def attempt(scenario: Callable[[Trial], GameState], client, genres: dict[str, Genre], log_path: Path) -> Run:
    trial = Trial(client, genres, log_path)
    try:
        state = scenario(trial)
    except Exception as e:  # 一次失敗不影響其他次，報告裡列出來
        return Run(checks=trial.checks, error=str(e)[:200])
    return Run(state.current_narration, state.current_choices, trial.checks)


def report(found: dict, results: dict[str, list[Run]]) -> None:
    total = passed = 0
    for name, runs in results.items():
        print(f"\n{name}：{found[name][0]}")
        by_check: dict[str, list[Check]] = {}
        for run in runs:
            for check in run.checks:
                by_check.setdefault(check.name, []).append(check)
        for check_name, checks in by_check.items():
            ok = sum(c.passed for c in checks)
            total, passed = total + len(checks), passed + ok
            print(f"  {'✓' if ok == len(checks) else '✗'} {check_name}  {ok}/{len(checks)}")
            for c in checks:
                if not c.passed and c.detail:
                    print(f"      - {c.detail}")
        for run in runs:
            if run.error:
                print(f"  ! 出錯：{run.error}")
    print(f"\n通過 {passed}/{total} 項檢查")


def save_results(results: dict[str, list[Run]]) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for name, runs in results.items():
            for i, run in enumerate(runs, 1):
                f.write(json.dumps({"scenario": name, "run": i} | asdict(run), ensure_ascii=False) + "\n")
    return path


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    options = {"--runs": RUNS, "--rpm": RPM}
    for option in options:
        if option in args:
            i = args.index(option)
            options[option] = int(args[i + 1])
            del args[i : i + 2]
    runs, rpm = options["--runs"], options["--rpm"]
    genres = load_genres()[0]
    found = scenarios(genres)
    unknown = [n for n in args if n not in found]
    if unknown:
        sys.exit(f"沒有這個情境：{'、'.join(unknown)}。可以用：{'、'.join(found)}")
    key = get_saved_api_key()
    if not key:
        sys.exit("找不到 Gemini API key：先玩一次遊戲輸入 key，或設定環境變數 GEMINI_API_KEY。")

    names = args or list(found)
    print(f"評估 {len(names)} 個情境，各跑 {runs} 次（遊戲：{MODEL}，評審：{JUDGE_MODEL}，每分鐘最多 {rpm} 次）")
    results: dict[str, list[Run]] = {name: [] for name in names}
    jobs = [(name, i) for name in names for i in range(runs)]
    throttle = Throttle(rpm)
    with tempfile.TemporaryDirectory() as logs, ThreadPoolExecutor(WORKERS) as pool:
        futures = {
            pool.submit(attempt, found[name][1], throttle.wrap(new_client(key)), genres, Path(logs) / f"{name}-{i}.jsonl"): name
            for name, i in jobs
        }
        for done, future in enumerate(as_completed(futures), 1):
            results[futures[future]].append(future.result())
            print(f"\r完成 {done}/{len(jobs)}", end="", flush=True)
    print()
    report(found, results)
    print(f"每次的劇情與評審理由：{save_results(results)}")


if __name__ == "__main__":
    main()
