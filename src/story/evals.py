"""Evals: have the AI really run fixed scenarios, then have the program and a judge (another AI call) check whether it got it right.

Calls the real Gemini (costs a little and takes a few minutes), so it isn't part of just test. Run it by hand after changing the prompts (story/games/*/prompts/):

    just eval                  every scenario, 3 runs each
    just eval reveal agency    only these two scenarios
    just eval judge            only check the adventure's judge: can it tell when narration was deliberately written badly
    just eval soup             only check the turtle soup judge
    just eval --runs 5         5 runs each (the AI writes differently every time, so more runs are more accurate)
    just eval --rpm 60         at most 60 calls a minute (raise it on a paid plan to run faster)

Scenarios live in each game's own evals.py next to its game.py (games/adventure/evals.py, games/soup/evals.py): every game in GAMES that has one
is gathered automatically, so a new game's scenarios need no change here.
Each run's output and the judge's reasons are saved to eval_results/, to compare before and after a prompt change. Saves and game logs are never touched.
"""

import importlib
import sys

from story import settings
from story.core import new_client
from story.core.ai import MODEL
from story.core.evals import Scenario, evaluate
from story.games import GAMES

RUNS = 3
RPM = 14  # Most AI calls per minute: the free tier's flash-lite limit is 15. Every scenario 3 times is about 90 calls, six or seven minutes


def scenarios() -> dict[str, Scenario]:
    """Every game's scenarios: from the evals module next to each game in GAMES (games without one have none)."""
    found: dict[str, Scenario] = {}
    for game in GAMES.values():
        name = game.__module__.rpartition(".")[0] + ".evals"
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as e:
            if e.name != name:
                raise
            continue
        found |= module.scenarios()
    return found


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    options = {"--runs": RUNS, "--rpm": RPM}
    for option in options:
        if option in args:
            i = args.index(option)
            options[option] = int(args[i + 1])
            del args[i : i + 2]
    runs, rpm = options["--runs"], options["--rpm"]
    found = scenarios()
    unknown = [n for n in args if n not in found]
    if unknown:
        sys.exit(f"No such scenario: {', '.join(unknown)}. Available: {', '.join(found)}")
    key = settings.api_key()
    if not key:
        sys.exit("No Gemini API key found: run uv run story once to enter one, or set the GEMINI_API_KEY environment variable.")

    names = args or list(found)
    print(f"Evaluating {len(names)} scenario(s), {runs} run(s) each (model: {MODEL}, at most {rpm} calls a minute)")
    evaluate(found, names, runs, rpm, lambda: new_client(key))


if __name__ == "__main__":
    main()
