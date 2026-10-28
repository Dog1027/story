"""The sample story: a lighthouse adventure at turn 8 (act two), with its outline, wounds and story log, plus sample narration for the evals.

Not part of the game: just prompts (preview.py) prints the prompts for it, and just eval (evals.py) runs scenarios on it.
The text is in samples/<lang>.md, one per language with the same sections.
"""

from pathlib import Path

from story.core import prompts
from story.games.adventure.models import Act, Character, Condition, GameState, StoryArc, Turn

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
SAMPLE = prompts.sections(prompts.LANGUAGE, SAMPLES_DIR)  # This language's sample story (samples/<lang>.md)


def items(name: str) -> list[list[str]]:
    """A sample section with one item per line; each item splits into fields on |."""
    return [[field.strip() for field in item.split("|")] for item in prompts.items(SAMPLE[name])]


def listed(name: str) -> list[str]:
    return [item[0] for item in items(name)]


def conditions(name: str) -> list[Condition]:
    return [Condition(name=n, kind=kind, severity=severity) for n, kind, severity in items(name)]


ARC = StoryArc(
    goal=SAMPLE["goal"],
    twist=SAMPLE["twist"],
    clues=listed("clues"),
    acts=[Act(name=name, milestone=milestone) for name, milestone in items("acts")],
    endings=listed("endings"),
)
HISTORY = [Turn(narration=narration, action=action) for narration, action in items("history")]
PREMISE = SAMPLE["premise"]


def sample_state(players: int, genre: str, **fields) -> GameState:
    """Turn 8 of the sample story (act two); players is how many characters are on the team. The first character carries the sample wounds."""
    characters = [Character(name=name, inventory=[item]) for name, item in items("players")[:players]]
    characters[0].conditions = conditions("wounds")
    if players == 1:
        characters[0].inventory = listed("inventory")
    state = GameState(
        premise=PREMISE,
        characters=characters,
        genre=genre,
        turn=8,
        minutes=22 * 60,
        arc=ARC,
        act=1,
        act_turns=3,
        recent=list(HISTORY),
        key_events=listed("key_events"),
        flags=listed("flags"),
        current_narration=SAMPLE["narration"],
    )
    for key, value in fields.items():
        setattr(state, key, value)
    return state


def sample_actions(players: int) -> dict[str, str]:
    """Each character's action this turn."""
    return dict(items("actions")[:players])
