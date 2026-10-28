"""The adventure's eval scenarios (just eval): have the AI really write a turn in fixed scenarios, then have the program and a judge (another AI call) check whether it got it right.

The sample story is shared with just prompts (samples.py, with its text in samples/<lang>.md); the judge's criteria are in prompts/<lang>/eval.md.
How to run it is in story/evals.py; running scenarios, reporting and saving results are shared, in story/core/evals.py.
"""

import json
import re
from collections.abc import Callable
from pathlib import Path

from google.genai import types
from pydantic import BaseModel, Field

from story.core import prompts
from story.core.ai import MODEL
from story.core.evals import Scenario, Trial
from story.games.adventure.engine import Engine
from story.games.adventure.genres import Genre, load_genres
from story.games.adventure.models import SCHEMA, Character, GameState
from story.games.adventure.rules import ACT_TURNS, body_level, body_score
from story.games.adventure.samples import ARC, PREMISE, SAMPLE, conditions, listed, sample_actions, sample_state
from story.games.adventure.text import TEXT

EVAL = TEXT.sections("eval")
# The judge uses the same model as the game but thinks more. The free tier's gemini-3.5-flash allows only 5 calls a minute; with a paid plan, switching to it makes judging more reliable
JUDGE_MODEL = MODEL


def schema_range(text: str) -> tuple[int, int]:
    """The "150-300 characters" and "2-4" in schema.md: change them there and these checks follow."""
    low, high = re.search(r"(\d+)-(\d+)", text).groups()
    return int(low), int(high)


NARRATION_LEN = schema_range(SCHEMA["StoryBeat.narration"])
CHOICE_COUNT = schema_range(SCHEMA["CharacterUpdate.choices"])


class Verdict(BaseModel):
    reason: str = Field(description=EVAL["Verdict.reason"])
    passed: bool = Field(description=EVAL["Verdict.passed"])


class AdventureTrial(Trial):
    """One run of an adventure scenario: a real Engine, plus the judge and the checks every scenario needs."""

    def __init__(self, client, log_path: Path, genres: dict[str, Genre]):
        super().__init__(client, log_path)
        self.engine = Engine(client=client, genres=genres, log_path=log_path)

    def judge(self, name: str, section: str, expect: bool = True, **values) -> None:
        """Ask the judge to decide by eval.md's criteria. expect=False is for deliberately bad samples: the check passes only if the judge fails them."""
        response = self.client.models.generate_content(
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


def opening(t: AdventureTrial) -> GameState:
    state = GameState(premise=PREMISE, characters=[hero()])
    t.engine.start(state)
    arc = state.arc
    t.check("the outline has a hidden truth and clues", arc is not None and arc.twist and arc.clues)
    t.basics(state)
    if arc is not None and arc.twist:
        t.judge("the opening doesn't give away the truth", "twist_hidden", twist=arc.twist, narration=state.current_narration)
    return state


def early(t: AdventureTrial) -> GameState:
    state = sample_state(1, "", act=1, act_turns=3, turn=12, current_narration=SAMPLE["early_narration"])
    action = SAMPLE["early_action"]
    t.engine.act(state, mine(action))
    t.check("didn't try to write an ending", not t.tried_ending(), "the AI started writing an ending and was asked to rewrite")
    t.basics(state)
    t.judge("the narration isn't written as an ending", "no_ending", action=action, narration=state.current_narration,
            choices="\n".join(state.characters[0].choices))
    return state


def reveal(t: AdventureTrial) -> GameState:
    state = sample_state(1, "", act=2, act_turns=ACT_TURNS, turn=18, current_narration=SAMPLE["reveal_narration"])
    t.engine.act(state, mine(SAMPLE["reveal_action"]))
    t.basics(state)
    t.judge("revealed the hidden truth", "reveal", twist=ARC.twist, clues="\n".join(f"- {c}" for c in ARC.clues),
            narration=state.current_narration)
    return state


def agency(t: AdventureTrial) -> GameState:
    state = sample_state(1, "")
    action = first_action()
    t.engine.act(state, mine(action))
    t.basics(state)
    t.judge("doesn't decide for the player", "agency", action=action, narration=state.current_narration)
    return state


def reckless(t: AdventureTrial) -> GameState:
    state = sample_state(1, "", current_narration=SAMPLE["armed"])
    before = body_score(state.characters[0])
    t.engine.act(state, mine(SAMPLE["reckless_action"]))
    after = body_score(state.characters[0])
    t.check("a reckless action caused wounds (wound total up by at least 2)", after - before >= 2, f"wound total {before} → {after}")
    t.basics(state, may_end=True)
    return state


def dying(t: AdventureTrial) -> GameState:
    state = sample_state(1, "", current_narration=SAMPLE["armed"])
    state.characters[0].conditions = conditions("dying_wounds")
    t.engine.act(state, mine(SAMPLE["dying_action"]))
    level = body_level(state.characters[0])
    t.check("taking risks while dying is fatal", level == "dead", f"overall condition: {level}")
    return state


def tone(genre: Genre) -> Callable[[AdventureTrial], GameState]:
    def run(t: AdventureTrial) -> GameState:
        state = GameState(premise=genre.premises[0] if genre.premises else PREMISE, characters=[hero()], genre=genre.name)
        t.engine.start(state)
        t.basics(state)
        t.judge("the style fits the genre", "tone", genre=genre.name, guide=genre.guide, narration=state.current_narration)
        return state

    return run


# Samples for the judge (samples/<lang>.md): deliberately bad ones (must fail) and fine ones (must pass). If the judge lets the bad ones through, the other scenarios' passes can't be trusted


def calibration(genres: dict[str, Genre]) -> Callable[[AdventureTrial], None]:
    def run(t: AdventureTrial) -> None:
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


def keep(scenario: Callable[[AdventureTrial], GameState | None]) -> Callable[[AdventureTrial], None]:
    """Save the narration and choices afterwards, to compare before and after a prompt change (scenarios that only check the judge write none)."""

    def run(t: AdventureTrial) -> None:
        if (state := scenario(t)) is not None:
            t.output = {"narration": state.current_narration, "choices": state.characters[0].choices}

    return run


def scenarios(genres: dict[str, Genre] | None = None) -> dict[str, Scenario]:
    """{code: scenario}. Each genre pack has its own scenario, coded by the genre's name."""
    genres = load_genres()[0] if genres is None else genres
    found = {
        "opening": ("Opening: plan the outline; the opening doesn't give away the truth", opening),
        "early": ("Act two, the player wants to leave: don't write the ending too early", early),
        "reveal": ("Act three, walking into the secret room: reveal the hidden truth", reveal),
        "agency": ("A normal turn: don't decide the player's actions or feelings", agency),
        "reckless": ("A reckless action: it must cost something", reckless),
        "dying": ("Taking risks while dying: fatal", dying),
        "judge": ("The judge: deliberately bad narration must fail and fine narration must pass", calibration(genres)),
    }
    for name, genre in genres.items():
        found[name] = (f"The opening for genre {name!r}: the style follows the genre guide", tone(genre))

    def trial(client, log_path: Path) -> AdventureTrial:
        return AdventureTrial(client, log_path, genres)

    return {name: Scenario(description, keep(run), trial) for name, (description, run) in found.items()}
