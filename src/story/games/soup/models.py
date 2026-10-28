"""Turtle soup's data: puzzles, the rulings and puzzles the AI returns, and the state the program saves."""

from typing import Literal

from pydantic import BaseModel, Field

from story.core.vocab import Vocab
from story.games.soup.text import TEXT

SCHEMA = TEXT.sections("schema")  # Field descriptions (prompts/<lang>/schema.md), sent to the AI with the response format
SoupAnswer = Literal["yes", "no", "irrelevant", "partly", "not_question"]  # The judge's answer to a question; the words are in prompts/<lang>/vocab.md
VOCAB = Vocab(TEXT.sections("vocab"), {"soup_answer": SoupAnswer})
word, code, words = VOCAB.word, VOCAB.code, VOCAB.words

MoveKind = Literal["ask", "guess", "give_up", "away"]  # Ask, guess, give up, away (sent by the room for someone who disconnected)


class Puzzle(BaseModel):
    """One turtle soup puzzle. key_points are the facts a guess must state; stating all of them solves it."""

    title: str
    surface: str  # The scenario: the strange situation everyone sees at the start
    truth: str  # The truth behind it, which only the judge (the AI) knows
    key_points: list[str]


# ---------- Formats the AI returns ----------


class PointCheck(BaseModel):
    """The judge's ruling on one key point for a guess: first quote the guess, then decide whether it was hit."""

    point: int = Field(description=SCHEMA["PointCheck.point"])
    quote: str = Field(description=SCHEMA["PointCheck.quote"])
    stated: bool = Field(description=SCHEMA["PointCheck.stated"])


class Ruling(BaseModel):
    """The judge's ruling on one action."""

    move: int = Field(description=SCHEMA["Ruling.move"])
    answer: words("soup_answer") = Field(description=SCHEMA["Ruling.answer"])
    points: list[PointCheck] = Field(description=SCHEMA["Ruling.points"])


class Judgement(BaseModel):
    rulings: list[Ruling] = Field(description=SCHEMA["Judgement.rulings"])


class PuzzleDraft(BaseModel):
    """A puzzle the AI wrote."""

    title: str = Field(description=SCHEMA["PuzzleDraft.title"])
    surface: str = Field(description=SCHEMA["PuzzleDraft.surface"])
    truth: str = Field(description=SCHEMA["PuzzleDraft.truth"])
    key_points: list[str] = Field(description=SCHEMA["PuzzleDraft.key_points"])


class PuzzleCheck(BaseModel):
    ok: bool = Field(description=SCHEMA["PuzzleCheck.ok"])
    problem: str = Field(description=SCHEMA["PuzzleCheck.problem"])


# ---------- State the program saves ----------


class Move(BaseModel):
    """One player's action in a turn, and the judge's ruling."""

    name: str
    kind: MoveKind
    text: str = ""
    answer: str = ""  # A question: the answer's code (soup_answer in vocab.md)
    hit: int = 0  # A guess: how many key points were hit


class SoupState(BaseModel):
    """One turtle soup game's state; a save is this converted to JSON."""

    puzzle: Puzzle
    from_ai: bool = False  # The AI wrote the puzzle (it's not from the bank)
    players: list[str]
    turn: int = 0  # Turns played so far
    rounds: list[list[Move]] = Field(default_factory=list)  # Each person's action each turn
    winners: list[str] = Field(default_factory=list)  # Who solved it (people stating every key point in the same turn win together)
    game_over: bool = False

    @property
    def names(self) -> list[str]:
        return list(self.players)

    @property
    def premise(self) -> str:
        """Which game this is, when a save is found or loaded (the story premise in the adventure, the puzzle title here)."""
        return self.puzzle.title

    def questions(self, name: str) -> int:
        return sum(1 for r in self.rounds for m in r if m.name == name and m.kind == "ask")

    def best(self, name: str) -> int:
        """The most key points this person has hit in a guess."""
        return max((m.hit for r in self.rounds for m in r if m.name == name and m.kind == "guess"), default=0)
