"""Preview the full prompts sent to the AI: build the prompt for each kind of AI call from sample scenarios and print them, without calling the AI or spending anything.

After changing the adventure's prompts (story/games/adventure/prompts/), use this to see how they fit together:

    just prompts              every scenario
    just prompts turn         only "a normal turn"
    just prompts --players 2  a team of two characters (one by default)
    just prompts --genre <genre name> opening   use a genre pack (names are in the current language)

The sample story is in samples.py, with its text in samples/<lang>.md (not a prompt, just so the preview looks like a real game).
"""

import random
import sys
from types import SimpleNamespace

from story.games.adventure.engine import AdventureEngine
from story.games.adventure.genres import load_genres
from story.games.adventure.models import SCHEMA, AdventureState
from story.games.adventure.prompting import SYSTEM_PROMPT
from story.games.adventure.rules import ACT_TURNS, MIN_ACT_TURNS, TARGET_TURNS
from story.games.adventure.tools.samples import HISTORY, SAMPLE, sample_actions, sample_state


def scenarios(engine: AdventureEngine, players: int, genre: str) -> dict[str, tuple[str, str]]:
    """{code: (description, prompt)}"""
    def state(**fields) -> AdventureState:
        return sample_state(players, genre, **fields)

    build, action = engine.build, sample_actions(players)
    opening = state(turn=0, minutes=None, story_log=[], key_events=[], facts=[], act=0, act_turns=0)
    dying = state(current_narration=SAMPLE["fall" if players == 1 else "fall_named"])
    events = [f"{SAMPLE['event']} {i}" for i in range(10)]
    long_story = state(turn=40, story_log=HISTORY * 40, key_events=events, summary=SAMPLE["summary"])
    return {
        "system": ("Writing and game rules (the system prompt, sent every time narration is written)", SYSTEM_PROMPT),
        "schema": ("Field descriptions for the response format (sent with the format)", "\n".join(f"{key}: {text}" for key, text in SCHEMA.items())),
        "genre": ("Picking a genre when it's set to auto", build.pick_genre(opening)),
        "arc": ("Planning the hidden outline", build.arc(opening)),
        "opening": ("The opening", build.turn(opening, None)),
        "turn": ("A normal turn (act two)", build.turn(state(), action)),
        "early": (f"An act just started (fewer than {MIN_ACT_TURNS} turns in)", build.turn(state(act_turns=0), action)),
        "dragging": (f"An act dragging on (over {ACT_TURNS} turns)", build.turn(state(act_turns=ACT_TURNS), action)),
        "reveal": ("Act three: revealing the hidden truth", build.turn(state(act=2, turn=16), action)),
        "final": (f"The last act, past the planned {TARGET_TURNS} turns", build.turn(state(act=3, turn=TARGET_TURNS), action)),
        "timed": ("Timed mode", build.turn(state(timed_mode=True), action)),
        "death": ("Falling from wounds", build.death(dying, [dying.characters[0].name])),
        "epilogue": ("The epilogue", build.epilogue(state(act=3, turn=26))),
        "premise": ("Suggest one", build.premise(genre=genre)),
        "compaction": ("Memory compaction (when the story log gets too long)", build.compaction(long_story)),
    }


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    players = 1
    if "--players" in args:  # How many characters on the team (one by default, i.e. playing alone)
        players = int(args.pop(args.index("--players") + 1))
        args.remove("--players")
    genres = load_genres()[0]
    genre = ""  # No genre by default, which keeps the output shorter; add --genre to see a genre pack's guidance
    if "--genre" in args:
        genre = args[args.index("--genre") + 1]
        if genre not in genres:
            sys.exit(f"No genre pack named {genre!r}. Available: {', '.join(genres)}")
    names = [a for a in args if not a.startswith("--") and a != genre]
    random.seed(0)  # The random twist ideas and suggested genre are the same every time, to compare before and after a change
    engine = AdventureEngine(client=SimpleNamespace(), genres=genres)
    found = scenarios(engine, players, genre)
    unknown = [n for n in names if n not in found]
    if unknown:
        sys.exit(f"No such scenario: {', '.join(unknown)}. Available: {', '.join(found)}")
    mode = f"{players} character(s)"
    for name in names or found:
        title, text = found[name]
        print(f"\n{'═' * 60}\n{name}: {title} ({mode}, genre: {genre or 'none'})\n{'═' * 60}\n{text}")


if __name__ == "__main__":
    main()
