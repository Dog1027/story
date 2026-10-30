"""Evals: have the AI really run fixed scenarios, then have the program and a judge (another AI call) check whether it got it right.

Calls the real Gemini (costs a little and takes a few minutes), so it isn't part of just test. Run it by hand after changing the prompts (story/games/*/prompts/):

    just eval                  every scenario, 3 runs each
    just eval reveal agency    only these two scenarios
    just eval judge            only check the adventure's judge: can it tell when narration was deliberately written badly
    just eval soup             only check the turtle soup judge
    just eval --runs 5         5 runs each (the AI writes differently every time, so more runs are more accurate)
    just eval --rpm 60         at most 60 calls a minute (raise it on a paid plan to run faster)

Scenarios live in each game's own evals.py next to its game.py (games/adventure/evals.py, games/soup/evals.py), listed in SCENARIOS below;
a test checks every game in GAMES is listed there. Running scenarios, reporting and saving results are in story/core/evals.py.
Each run's output and the judge's reasons are saved to eval_results/, to compare before and after a prompt change. Saves and game logs are never touched.
"""

import sys
from collections.abc import Callable

from story import settings
from story.core import new_client
from story.core.ai import MODEL
from story.core.evals import Scenario, evaluate
from story.games.adventure import evals as adventure
from story.games.soup import evals as soup

RUNS = 3
RPM = 14  # Most AI calls per minute: the free tier's flash-lite limit is 15. Every scenario 3 times is about 90 calls, six or seven minutes


# Each game's scenarios, by its code in GAMES
SCENARIOS: dict[str, Callable[[], dict[str, Scenario]]] = {"adventure": adventure.scenarios, "soup": soup.scenarios}


def scenarios() -> dict[str, Scenario]:
    """Every game's scenarios, by scenario name."""
    found: dict[str, Scenario] = {}
    for game_scenarios in SCENARIOS.values():
        found |= game_scenarios()
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
