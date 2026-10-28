"""Turtle soup's eval scenarios (just eval soup): check the judge's rulings with guesses from real games (soup_cases in samples/<lang>.md).

How to run it is in story/evals.py; running scenarios, reporting and saving results are shared, in story/core/evals.py.
"""

from pathlib import Path

from story.core import prompts
from story.core.evals import Scenario, Trial
from story.games.soup.judge import SoupJudge
from story.games.soup.models import Move, SoupState
from story.games.soup.puzzles import load_puzzles

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"


def judge_cases(t: Trial) -> None:
    """Each puzzle's guesses are judged together in one turn (as in the game); the key points hit must fall in range.
    An incomplete guess (e.g. not naming the illness) can't get full marks; guesses that mean the same must get the same score."""
    samples = prompts.sections(prompts.LANGUAGE, SAMPLES_DIR)
    judge = SoupJudge(client=t.client, log_path=t.log_path)
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


def scenarios() -> dict[str, Scenario]:
    return {"soup": Scenario("The turtle soup judge: incomplete guesses don't get full marks, and guesses meaning the same score the same", judge_cases)}
