"""What every game's evals (just eval) share: run the scenarios, tally the checks, print the report, save each run's result.

Each game writes its scenarios (Scenario) in its own evals.py: have the AI really run once, then record the checks with Trial.check().
story/evals.py gathers every game's scenarios and hands them to evaluate() here.
"""

import json
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from story import settings
from story.core.ratelimit import RateLimit

WORKERS = 8  # How many scenarios run at once


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Run:
    """The result of one run of a scenario. output is what's saved for comparing later (e.g. the adventure's narration and choices)."""

    output: dict = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    error: str = ""


class Trial:
    """One run of a scenario: records the check results and what to save. Each game subclasses it to add its own tools (e.g. the adventure's Engine and judge)."""

    def __init__(self, client, log_path: Path):
        self.client = client
        self.log_path = log_path  # This run's game log (in a temporary folder, deleted afterwards)
        self.checks: list[Check] = []
        self.output: dict = {}

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(name, bool(passed), detail))


@dataclass
class Scenario:
    description: str
    run: Callable[[Trial], None]
    trial: Callable[[object, Path], Trial] = Trial  # Builds the Trial for this scenario: (client, log path)


def attempt(scenario: Scenario, client, log_path: Path) -> Run:
    trial = scenario.trial(client, log_path)
    try:
        scenario.run(trial)
    except Exception as e:  # One failure doesn't affect the other runs; it's listed in the report
        return Run(trial.output, trial.checks, error=str(e)[:200])
    return Run(trial.output, trial.checks)


def report(found: dict[str, Scenario], results: dict[str, list[Run]]) -> None:
    total = passed = 0
    for name, runs in results.items():
        print(f"\n{name}: {found[name].description}")
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
    results_dir = settings.DATA_DIR / "eval_results"  # In the project folder, whatever folder this runs from
    results_dir.mkdir(exist_ok=True)
    path = results_dir / f"{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for name, runs in results.items():
            for i, run in enumerate(runs, 1):
                f.write(json.dumps({"scenario": name, "run": i} | asdict(run), ensure_ascii=False) + "\n")
    return path


def evaluate(found: dict[str, Scenario], names: list[str], runs: int, rpm: int, make_client: Callable[[], object]) -> None:
    """Run each scenario runs times (several at once, with AI calls limited to rpm a minute), print the report and save the results."""
    results: dict[str, list[Run]] = {name: [] for name in names}
    jobs = [(name, i) for name in names for i in range(runs)]
    limit = RateLimit(rpm)
    with tempfile.TemporaryDirectory() as logs, ThreadPoolExecutor(WORKERS) as pool:
        futures = {
            pool.submit(attempt, found[name], limit.wrap(make_client()), Path(logs) / f"{name}-{i}.jsonl"): name
            for name, i in jobs
        }
        for done, future in enumerate(as_completed(futures), 1):
            results[futures[future]].append(future.result())
            print(f"\rDone {done}/{len(jobs)}", end="", flush=True)
    print()
    report(found, results)
    print(f"Each run's output and the judge's reasons: {save_results(results)}")
