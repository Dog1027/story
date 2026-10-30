"""The adventure's data: the state the program controls (AdventureState) and the format the LLM returns (StoryBeat)."""

from typing import Literal

from pydantic import BaseModel, Field

from story.core.vocab import Vocab
from story.games.adventure.text import TEXT

SCHEMA = TEXT.sections("schema")  # Field descriptions (prompts/<lang>/schema.md), sent to the AI with the response format

# Game vocabulary: code and saves use codes; text shown to the AI, returned by the AI, or shown to players uses this language's words from prompts/<lang>/vocab.md
Severity = Literal["light", "moderate", "severe"]  # From light to severe
ConditionKind = Literal["body", "mind"]
TimeSpan = Literal["instant", "moment", "while", "hours", "night", "days"]
TimeOfDay = Literal["dawn", "morning", "noon", "afternoon", "dusk", "evening", "late_night"]
Level = Literal["healthy", "minor", "injured", "serious", "dying", "dead"]  # The body's overall condition, from best to worst
CODES = {"severity": Severity, "kind": ConditionKind, "time_span": TimeSpan, "time_of_day": TimeOfDay, "level": Level}
VOCAB = Vocab(TEXT.sections("vocab"), CODES)
word, code, words = VOCAB.word, VOCAB.code, VOCAB.words


class ConditionChange(BaseModel):
    """A condition the AI reports: a new one, or one whose severity changed."""

    name: str = Field(description=SCHEMA["ConditionChange.name"])
    kind: words("kind") = Field(description=SCHEMA["ConditionChange.kind"])
    severity: words("severity") = Field(description=SCHEMA["ConditionChange.severity"])


class Condition(BaseModel):
    """A condition on a character. The program also tracks how much in-game time has passed at the current severity, to work out healing."""

    name: str
    kind: ConditionKind = "body"
    severity: Severity
    minutes: int = 0


class CharacterUpdate(BaseModel):
    """What the AI reports for one character this turn: changes and the next choices."""

    name: str = Field(description=SCHEMA["CharacterUpdate.name"])
    choices: list[str] = Field(description=SCHEMA["CharacterUpdate.choices"])
    conditions_changed: list[ConditionChange] = Field(description=SCHEMA["CharacterUpdate.conditions_changed"])
    conditions_removed: list[str] = Field(description=SCHEMA["CharacterUpdate.conditions_removed"])
    items_gained: list[str] = Field(description=SCHEMA["CharacterUpdate.items_gained"])
    items_lost: list[str] = Field(description=SCHEMA["CharacterUpdate.items_lost"])


class StoryBeat(BaseModel):
    """What the AI must return each turn: one narration covering every character, plus each character's changes. The program checks them before applying them to the state.
    The field order is the AI's output order: decide whether it's the ending first, then the narration (shown as it streams in), and the other changes last, checked and applied by the program."""

    game_over: bool = Field(description=SCHEMA["StoryBeat.game_over"])
    narration: str = Field(description=SCHEMA["StoryBeat.narration"])
    character_updates: list[CharacterUpdate] = Field(description=SCHEMA["StoryBeat.character_updates"])
    time_passed: words("time_span") = Field(description=SCHEMA["StoryBeat.time_passed"])
    start_time_of_day: words("time_of_day") = Field(description=SCHEMA["StoryBeat.start_time_of_day"])
    time_limit: int = Field(description=SCHEMA["StoryBeat.time_limit"])
    milestone_reached: bool = Field(description=SCHEMA["StoryBeat.milestone_reached"])
    flags_set: list[str] = Field(description=SCHEMA["StoryBeat.flags_set"])
    key_event: str = Field(description=SCHEMA["StoryBeat.key_event"])


class Act(BaseModel):
    name: str = Field(description=SCHEMA["Act.name"])
    milestone: str = Field(description=SCHEMA["Act.milestone"])


class StoryArc(BaseModel):
    """The hidden story outline: the AI follows it to move the story on, and the program uses it to control pacing. Never shown to players."""

    goal: str = Field(description=SCHEMA["StoryArc.goal"])
    twist: str = Field(description=SCHEMA["StoryArc.twist"])
    clues: list[str] = Field(description=SCHEMA["StoryArc.clues"])
    acts: list[Act] = Field(description=SCHEMA["StoryArc.acts"])
    endings: list[str] = Field(description=SCHEMA["StoryArc.endings"])


class GenrePick(BaseModel):
    """When the players choose the "auto" genre, the AI picks one for the premise."""

    genre: str = Field(description=SCHEMA["GenrePick.genre"])


class Epilogue(BaseModel):
    """The epilogue after the story ends."""

    title: str = Field(description=SCHEMA["Epilogue.title"])
    text: str = Field(description=SCHEMA["Epilogue.text"])


class Turn(BaseModel):
    """One turn's verbatim record (the narration and the players' actions)."""

    narration: str
    action: str  # What the players did after reading narration (one line per character)


class Character(BaseModel):
    """One character on the team, played by one player."""

    name: str
    conditions: list[Condition] = Field(default_factory=list)  # Body and mind conditions; empty means fine
    inventory: list[str] = Field(default_factory=list)
    choices: list[str] = Field(default_factory=list)  # This character's current choices
    alive: bool = True


class AdventureState(BaseModel):
    """Everything the program remembers. A save is this serialized to JSON."""

    premise: str
    characters: list[Character]  # The team: one to four characters, one when playing alone
    turn: int = 0
    timed_mode: bool = False  # Timed mode: decide within a time limit in urgent moments
    genre: str = ""  # The genre pack's name (name in GENRE.md); empty means no genre
    genre_pending: bool = False  # The players chose "auto": when planning the outline, the AI picks one from the catalog for the premise
    arc: StoryArc | None = None  # The hidden story outline (planned before the opening; made next turn if that failed)
    act: int = 0  # The current act (0-3)
    act_turns: int = 0  # Turns spent in the current act so far
    minutes: int | None = None  # The in-game clock: minutes since day 1, 0:00; None means not decided yet (before the opening). For the AI only, never shown to players
    flags: list[str] = Field(default_factory=list)

    # Layered memory
    summary: str = ""  # Long-term: a compacted summary of earlier story
    key_events: list[str] = Field(default_factory=list)  # Long-term: the list of key events
    recent: list[Turn] = Field(default_factory=list)  # The story log: each turn verbatim, append only; only the oldest are compacted into the summary when it gets too long

    # The current screen (so it can be shown again after loading)
    current_narration: str = ""
    current_time_limit: int = 0  # This turn's reaction time (seconds); 0 means no limit
    game_over: bool = False
    ending_title: str = ""  # Only after the story ends: the ending's title and the epilogue
    epilogue: str = ""

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.characters]

    @property
    def solo(self) -> bool:
        """Only one character: prompts and the screen use the second person ("you") and list no names."""
        return len(self.characters) == 1
