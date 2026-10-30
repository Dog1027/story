"""What the core sends back to the shells: Reply and the Status, Ending and InputMode inside it. Every game uses the same reply,
so shells don't need to know which game is being played."""

from dataclasses import asdict, dataclass, field
from typing import Literal

from story.core.prompts import UI  # Text shown to players (story/core/ui/<lang>/core.md)

Phase = Literal[
    "ask_continue",  # Found a save; asking whether to continue (like confirm_restart: choices are the two options, notice is the question)
    "setup",  # New game: with choices, pick one (games other than the adventure, e.g. how turtle soup gets its puzzle); without, the story premise form (the adventure)
    "playing",  # In a game
    "confirm_restart",  # Confirming whether to give up the current progress
    "ending",  # Just ended; the next input wraps up the ending (the adventure has the AI write an epilogue)
    "ended",  # The ending is ready; can play again
]

MAX_PLAYERS = 4

# Changes between turns (Reply.changes). Each item carries a tone, and shells decide how to present it (e.g. which color):
# light/moderate/severe = how bad a new condition is; good = better or healed; bad = worse; plain = ordinary (an item gained); muted = minor (an item lost)
Tone = Literal["light", "moderate", "severe", "good", "bad", "plain", "muted"]
ChangeGroups = list[tuple[str, list[tuple[str, Tone]]]]  # [(label, [(text, tone)])]


def join(items) -> str:
    return UI["list_sep"].join(items)


def pick_choice(raw: str, options: list[str]) -> str | None:
    """Match "2" or an option's own text to an option; None if nothing matches. The web also uses it to show what was picked."""
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    return raw if raw in options else None


@dataclass
class Status:
    """One player on the status bar (in the adventure, their character). The bag isn't here: changes are in changes, the full content via /state."""

    items: list[tuple[str, str]]  # Items to list: (text, tone code). Conditions and severities in the adventure (body first, then mind; "fine" when there are none); question count and points hit in turtle soup
    warning: str = ""  # The overall condition code to warn the player about (serious, dying: another wound could kill); empty when not in danger
    name: str = ""
    alive: bool = True  # Whether the character is still alive
    warning_text: str = ""  # The word shown for the warning, e.g. "badly hurt"


@dataclass
class Ending:
    title: str
    epilogue: str  # The epilogue in the adventure, the truth in turtle soup
    record: str  # The journey record: turns, days, key events…
    reveal: str = ""  # The prompt to press Enter before the epilogue; when empty, shells use their own ("Press Enter for the epilogue")


@dataclass
class InputMode:
    """A way to give input (turtle soup's "ask", "guess", "give up"). When present, choices switch modes rather than being actions:
    picking a mode that needs text sends what's typed next with it (command plus the text); one that doesn't sends command right away."""

    label: str  # The text on the choice, also the label in front of the action (e.g. "Ask")
    command: str  # The command sent to the core, e.g. /ask
    hint: str = ""  # The input box hint once this mode is picked
    needs_text: bool = True
    confirm: tuple[str, str, str] | None = None  # Ask before sending (a mode that doesn't need text): (question, yes, no)


@dataclass
class Reply:
    phase: Phase
    turn: int = 0  # The current turn; 0 before the game starts
    timed: bool = False  # Whether timed mode is on (in a game, this game's mode; while waiting for a premise, the mode a new game will use)
    narration: str = ""  # Narration produced this time (or shown again after loading); empty when there's none
    choices: list[str] = field(default_factory=list)
    characters: list[Status] = field(default_factory=list)  # Each player's status (only one when playing alone)
    changes: list[tuple[str, ChangeGroups]] = field(default_factory=list)  # Characters who changed this turn: (name, new, healed, gained…)
    time_limit: int = 0  # Time limit in seconds; 0 means none
    notice: str = ""  # A short system message, e.g. "Loaded save" or "No such command"
    resumed: bool = False  # This is a loaded save, showing the last narration again
    history: list[tuple[str, str]] = field(default_factory=list)  # resumed: earlier narration, per turn (narration, the actions taken after it, one per line per player)
    history_trimmed: bool = False  # resumed: older narration was compacted into a summary, so history starts partway
    info: tuple[str, str] | None = None  # Content to show separately: (title, body), e.g. memory or help
    premise_default: str = ""  # The story premise form: the premise used if left blank
    genre: str = ""  # The story premise form: the genre a new game will use (one of the values in genres)
    genres: list[tuple[str, str, str]] = field(default_factory=list)  # The story premise form: the genre menu (value, text shown, description); no menu when empty
    suggestion: str = ""  # The story premise form: the premise /suggest came up with
    ending: Ending | None = None  # ended: the epilogue and journey record
    error: Literal["api"] | None = None  # Calling the AI failed (notice says why): stays in the same phase and can be retried
    actor: str = ""  # The player who sent the input (the subject of send_as and view; the only player when alone): their name while they haven't acted this turn, and choices are theirs
    inputs: list[InputMode] = field(default_factory=list)  # When present, choices are input modes (see InputMode), not actions

    def to_dict(self) -> dict:
        """Convert to a dict that can be saved as JSON (used by web rooms to send replies)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Reply:
        """The reverse of to_dict(). JSON has no tuples, so tuples become lists, which makes no difference to shells unpacking them."""
        data = dict(data)
        if data.get("ending"):
            data["ending"] = Ending(**data["ending"])
        data["characters"] = [Status(**s) for s in data.get("characters", [])]
        data["inputs"] = [InputMode(**m) for m in data.get("inputs", [])]
        return cls(**data)
