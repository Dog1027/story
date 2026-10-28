"""Evals: have the AI really write a turn in fixed scenarios, then have the program and a judge (another AI call) check whether it got it right.

Calls the real Gemini (costs a little and takes a minute or two), so it isn't part of just test. Run it by hand after changing the prompts (story/games/*/prompts/):

    just eval                  every scenario, 3 runs each
    just eval reveal agency    only these two scenarios
    just eval judge            only check the judge: can it tell when narration was deliberately written badly
    just eval --runs 5         5 runs each (the AI writes differently every time, so more runs are more accurate)
    just eval --rpm 60         at most 60 calls a minute (raise it on a paid plan to run faster)

Scenarios are defined here (the sample story is shared with just prompts); the judge's criteria are in story/games/adventure/prompts/<lang>/eval.md.
Each run's narration, choices and the judge's reasons are saved to eval_results/, to compare before and after a prompt change. Saves and game logs are never touched.
"""

import json
import re
import sys
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from google.genai import types
from pydantic import BaseModel, Field

from story.core import RateLimit, prompts
from story.core.ai import MODEL, new_client
from story.games.adventure.engine import Engine
from story.games.adventure.genres import Genre, load_genres
from story.games.adventure.models import SCHEMA, Character, GameState
from story.games.adventure.rules import ACT_TURNS, body_level, body_score
from story.games.adventure.text import TEXT
from story.preview import ARC, PREMISE, SAMPLE, conditions, items, listed, sample_actions, sample_state
from story import settings

EVAL = TEXT.sections("eval")
# The judge uses the same model as the game but thinks more. The free tier's gemini-3.5-flash allows only 5 calls a minute; with a paid plan, switching to it makes judging more reliable
JUDGE_MODEL = MODEL
RUNS = 3
WORKERS = 8  # How many scenarios run at once
RPM = 14  # Most AI calls per minute (RateLimit): the free tier's flash-lite limit is 15. Every scenario 3 times is about 90 calls, six or seven minutes
RESULTS_DIR = Path("eval_results")


def schema_range(text: str) -> tuple[int, int]:
    """The "150-300 characters" and "2-4" in schema.md: change them there and these checks follow."""
    low, high = re.search(r"(\d+)-(\d+)", text).groups()
    return int(low), int(high)


NARRATION_LEN = schema_range(SCHEMA["StoryBeat.narration"])
CHOICE_COUNT = schema_range(SCHEMA["CharacterUpdate.choices"])


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
    """The result of one run of a scenario."""

    narration: str = ""
    choices: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    error: str = ""


class Trial:
    """One run of a scenario: a real Engine, plus tools that record the check results."""

    def __init__(self, client, genres: dict[str, Genre], log_path: Path):
        self.engine = Engine(client=client, genres=genres, log_path=log_path)
        self.log_path = log_path
        self.checks: list[Check] = []

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(name, bool(passed), detail))

    def judge(self, name: str, section: str, expect: bool = True, **values) -> None:
        """Ask the judge to decide by eval.md's criteria. expect=False is for deliberately bad samples: the check passes only if the judge fails them."""
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
            self.check(name, verdict.passed == expect, verdict.reason)
        else:
            self.check(name, False, "the judge returned no result")

    def basics(self, state: GameState, may_end: bool = False) -> None:
        """What every scenario must meet: length, number of choices, and the story not having ended."""
        length = prompts.text_length(state.current_narration)
        low, high = NARRATION_LEN
        self.check(f"narration length {low}-{high}", low <= length <= high, f"length {length}")
        if not state.game_over:
            count, (low, high) = len(state.characters[0].choices), CHOICE_COUNT
            self.check(f"{low}-{high} choices", low <= count <= high, f"{count} choices")
        if not may_end:
            self.check("the story hasn't ended", not state.game_over)

    def tried_ending(self) -> bool:
        """The AI started writing an ending and the program stopped it and asked for a rewrite (see Engine._next_beat)."""
        if not self.log_path.exists():
            return False
        records = [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]
        return any("stopped" in call for record in records for call in record["calls"])


# ---------- Scenarios: each returns the finished state. All are solo (one character): the sample story's first character ----------


def hero() -> Character:
    return sample_state(1, "").characters[0].model_copy(update={"conditions": [], "inventory": []})


def mine(action: str) -> dict[str, str]:
    """The action this turn when playing alone: {character name: action}."""
    return {hero().name: action}


def first_action() -> str:
    return next(iter(sample_actions(1).values()))


def opening(t: Trial) -> GameState:
    state = GameState(premise=PREMISE, characters=[hero()])
    t.engine.start(state)
    arc = state.arc
    t.check("the outline has a hidden truth and clues", arc is not None and arc.twist and arc.clues)
    t.basics(state)
    if arc is not None and arc.twist:
        t.judge("the opening doesn't give away the truth", "twist_hidden", twist=arc.twist, narration=state.current_narration)
    return state


def early(t: Trial) -> GameState:
    state = sample_state(1, "", act=1, act_turns=3, turn=12, current_narration=SAMPLE["early_narration"])
    action = SAMPLE["early_action"]
    t.engine.act(state, mine(action))
    t.check("didn't try to write an ending", not t.tried_ending(), "the AI started writing an ending and was asked to rewrite")
    t.basics(state)
    t.judge("the narration isn't written as an ending", "no_ending", action=action, narration=state.current_narration,
            choices="\n".join(state.characters[0].choices))
    return state


def reveal(t: Trial) -> GameState:
    state = sample_state(1, "", act=2, act_turns=ACT_TURNS, turn=18, current_narration=SAMPLE["reveal_narration"])
    t.engine.act(state, mine(SAMPLE["reveal_action"]))
    t.basics(state)
    t.judge("revealed the hidden truth", "reveal", twist=ARC.twist, clues="\n".join(f"- {c}" for c in ARC.clues),
            narration=state.current_narration)
    return state


def agency(t: Trial) -> GameState:
    state = sample_state(1, "")
    action = first_action()
    t.engine.act(state, mine(action))
    t.basics(state)
    t.judge("doesn't decide for the player", "agency", action=action, narration=state.current_narration)
    return state


def reckless(t: Trial) -> GameState:
    state = sample_state(1, "", current_narration=SAMPLE["armed"])
    before = body_score(state.characters[0])
    t.engine.act(state, mine(SAMPLE["reckless_action"]))
    after = body_score(state.characters[0])
    t.check("a reckless action caused wounds (wound total up by at least 2)", after - before >= 2, f"wound total {before} → {after}")
    t.basics(state, may_end=True)
    return state


def dying(t: Trial) -> GameState:
    state = sample_state(1, "", current_narration=SAMPLE["armed"])
    state.characters[0].conditions = conditions("dying_wounds")
    t.engine.act(state, mine(SAMPLE["dying_action"]))
    level = body_level(state.characters[0])
    t.check("taking risks while dying is fatal", level == "dead", f"overall condition: {level}")
    return state


def tone(genre: Genre) -> Callable[[Trial], GameState]:
    def run(t: Trial) -> GameState:
        state = GameState(premise=genre.premises[0] if genre.premises else PREMISE, characters=[hero()], genre=genre.name)
        t.engine.start(state)
        t.basics(state)
        t.judge("the style fits the genre", "tone", genre=genre.name, guide=genre.guide, narration=state.current_narration)
        return state

    return run


# Samples for the judge (story/games/adventure/samples/<lang>.md): deliberately bad ones (must fail) and fine ones (must pass). If the judge lets the bad ones through, the other scenarios' passes can't be trusted


def calibration(genres: dict[str, Genre]) -> Callable[[Trial], None]:
    def run(t: Trial) -> None:
        clues = "\n".join(f"- {c}" for c in ARC.clues)
        agency, early = first_action(), SAMPLE["early_action"]
        t.judge("catches deciding for the player", "agency", expect=False, action=agency, narration=SAMPLE["agency_bad"])
        t.judge("passes fine narration (doesn't decide for the player)", "agency", action=agency, narration=SAMPLE["agency_good"])
        t.judge("catches narration written as an ending", "no_ending", expect=False, action=early, narration=SAMPLE["early_bad"], choices="")
        t.judge("passes fine narration (the story goes on)", "no_ending", action=early, narration=SAMPLE["early_good"],
                choices="\n".join(listed("early_good_choices")))
        t.judge("catches an opening that gives away the truth", "twist_hidden", expect=False, twist=ARC.twist, narration=SAMPLE["opening_bad"])
        t.judge("catches only hinting instead of revealing", "reveal", expect=False, twist=ARC.twist, clues=clues, narration=SAMPLE["reveal_bad"])
        if wuxia := next((g for g in genres.values() if g.path and g.path.name == "wuxia"), None):
            t.judge("catches a style that doesn't fit the genre", "tone", expect=False, genre=wuxia.name, guide=wuxia.guide, narration=SAMPLE["tone_bad"])

    return run


def soup(t: Trial) -> None:
    """The turtle soup judge: guesses from real games, each puzzle's guesses judged together in one turn (as in the game); the key points hit must fall in range.
    An incomplete guess (e.g. not naming the illness) can't get full marks; guesses that mean the same must get the same score."""
    from story.games.soup.judge import SoupJudge
    from story.games.soup.models import Move, SoupState
    from story.games.soup.puzzles import load_puzzles

    samples = prompts.sections(prompts.LANGUAGE, Path(__file__).resolve().parent / "games" / "soup" / "samples")

    judge = SoupJudge(client=t.engine.client, log_path=t.log_path)
    bank = {p.title: p for p in load_puzzles()[0]}
    cases: dict[str, list[tuple[str, int, int]]] = {}
    for title, guess, low, high in ([f.strip() for f in item.split("|")] for item in prompts.items(samples["soup_cases"])):
        cases.setdefault(title, []).append((guess, int(low), int(high)))
    for title, guesses in cases.items():
        state = SoupState(puzzle=bank[title], players=[f"P{i}" for i in range(len(guesses))])
        moves = [Move(name=f"P{i}", kind="guess", text=g) for i, (g, _, _) in enumerate(guesses)]
        judge.judge(state, moves)
        for move, (guess, low, high) in zip(moves, guesses):
            t.check(f"{title}: {prompts.clip(guess, 12)}… hits {low}-{high}", low <= move.hit <= high, f"hit {move.hit}")


def scenarios(genres: dict[str, Genre]) -> dict[str, tuple[str, Callable[[Trial], GameState | None]]]:
    """{code: (description, scenario)}. Each genre pack has its own scenario, coded by the genre's name."""
    found = {
        "opening": ("Opening: plan the outline; the opening doesn't give away the truth", opening),
        "early": ("Act two, the player wants to leave: don't write the ending too early", early),
        "reveal": ("Act three, walking into the secret room: reveal the hidden truth", reveal),
        "agency": ("A normal turn: don't decide the player's actions or feelings", agency),
        "reckless": ("A reckless action: it must cost something", reckless),
        "dying": ("Taking risks while dying: fatal", dying),
        "judge": ("The judge: deliberately bad narration must fail and fine narration must pass", calibration(genres)),
        "soup": ("The turtle soup judge: incomplete guesses don't get full marks, and guesses meaning the same score the same", soup),
    }
    for name, genre in genres.items():
        found[name] = (f"The opening for genre {name!r}: the style follows the genre guide", tone(genre))
    return found


# ---------- Running and reporting ----------


def attempt(scenario: Callable[[Trial], GameState | None], client, genres: dict[str, Genre], log_path: Path) -> Run:
    trial = Trial(client, genres, log_path)
    try:
        state = scenario(trial)
    except Exception as e:  # One failure doesn't affect the other runs; it's listed in the report
        return Run(checks=trial.checks, error=str(e)[:200])
    if state is None:  # Only checks the judge; no narration written
        return Run(checks=trial.checks)
    return Run(state.current_narration, state.characters[0].choices, trial.checks)


def report(found: dict, results: dict[str, list[Run]]) -> None:
    total = passed = 0
    for name, runs in results.items():
        print(f"\n{name}: {found[name][0]}")
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
                print(f"  ! Error: {run.error}")
    print(f"\nPassed {passed}/{total} checks")


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
        sys.exit(f"No such scenario: {', '.join(unknown)}. Available: {', '.join(found)}")
    key = settings.api_key()
    if not key:
        sys.exit("No Gemini API key found: run uv run story once to enter one, or set the GEMINI_API_KEY environment variable.")

    names = args or list(found)
    print(f"Evaluating {len(names)} scenario(s), {runs} run(s) each (game: {MODEL}, judge: {JUDGE_MODEL}, at most {rpm} calls a minute)")
    results: dict[str, list[Run]] = {name: [] for name in names}
    jobs = [(name, i) for name in names for i in range(runs)]
    limit = RateLimit(rpm)
    with tempfile.TemporaryDirectory() as logs, ThreadPoolExecutor(WORKERS) as pool:
        futures = {
            pool.submit(attempt, found[name][1], limit.wrap(new_client(key)), genres, Path(logs) / f"{name}-{i}.jsonl"): name
            for name, i in jobs
        }
        for done, future in enumerate(as_completed(futures), 1):
            results[futures[future]].append(future.result())
            print(f"\rDone {done}/{len(jobs)}", end="", flush=True)
    print()
    report(found, results)
    print(f"Each run's narration and the judge's reasons: {save_results(results)}")


if __name__ == "__main__":
    main()
