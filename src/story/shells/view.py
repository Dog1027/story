"""What an interface implements (View), and the display data the shared layer hands it (StatusLine): content and severity only, no colors or layout.

The shared layer (client.py) calls View's methods in the order of the game's flow; an interface (WebView in web/view.py) only draws them.
"""

from dataclasses import dataclass, field

from story.core import ChangeGroups, Status
from story.shells.premise import PremiseForm
from story.shells.text import ui_text

UI = ui_text("shells")  # The shells' shared text (story/shells/ui/<lang>/shells.md)


@dataclass
class StatusLine:
    turn: int
    mode: str  # "Timed mode" or "Normal mode", on the same line as the turn
    timed: bool
    characters: list[Status] = field(default_factory=list)  # One line per character; whether to warn and the words shown come from the game
    named: bool = False  # Several characters: one line per character, with names


def status_line(turn: int, characters: list[Status], timed: bool) -> StatusLine | None:
    """With one character, no names; with several, one line per character."""
    if not characters:
        return None
    mode = UI["mode_timed" if timed else "mode_normal"]
    return StatusLine(turn, mode, timed, list(characters), named=len(characters) > 1)


# ---------- Methods the interface implements ----------


class View:
    """What the interface provides. Client calls these methods as the game goes, and the interface only draws them.
    async methods return only once the player has finished reading or answering."""

    # The story area
    def clear_story(self, premise: str) -> None:
        """A new story starts: clear the story area, choices and status bar, and show the premise first (may be an empty string)."""
        raise NotImplementedError

    def show_action(self, text: str) -> None:
        """The action the player just took (scroll to the bottom to see the result when it's your own)."""
        raise NotImplementedError

    def show_note(self, text: str) -> None:
        """A line of explanation in the story area, e.g. "Loaded save: …" when loading."""
        raise NotImplementedError

    def start_narration(self) -> None:
        """Start showing a passage of narration (e.g. with a typing effect). The text arrives through extend_narration(); hide the waiting hint too."""
        raise NotImplementedError

    def extend_narration(self, text: str) -> None:
        """The full text of this narration received so far (the AI is still writing, so it keeps growing)."""
        raise NotImplementedError

    async def finish_narration(self, text: str) -> None:
        """The complete narration; returns once all of it is shown."""
        raise NotImplementedError

    def show_past_narration(self, text: str) -> None:
        """Earlier narration after loading or reconnecting: show the whole passage at once, without typing or scrolling."""
        raise NotImplementedError

    def discard_narration(self) -> None:
        """Take back this unfinished narration (the AI failed and the turn didn't advance)."""
        raise NotImplementedError

    def show_changes(self, groups: ChangeGroups, name: str = "") -> None:
        """Changes between turns (new, healed, gained…); has the character's name with several characters, empty when alone."""
        raise NotImplementedError

    def show_ending_title(self, title: str) -> None:
        raise NotImplementedError

    async def wait_enter(self, hint: str) -> None:
        """Stop and wait for the player to press Enter before going on."""
        raise NotImplementedError

    # Choices and input
    def prepare_choices(self, choices: list[str], timed: bool) -> None:
        """Place the choices while the narration is still showing, but keep them invisible (so the interface can reserve the space); with timed, the countdown bar too."""
        raise NotImplementedError

    def show_choices(self, choices: list[str]) -> None:
        """Show the choices (makes the ones placed by prepare_choices appear)."""
        raise NotImplementedError

    def mark_choice(self, index: int) -> None:
        """Mark the input mode currently picked (turtle soup's "ask" and "guess"; see Reply.inputs); -1 clears the mark. Interfaces that don't need it can skip it."""

    def set_hint(self, placeholder: str) -> None:
        """The input box hint, e.g. "Waiting for Hua to act…" after acting on the web."""
        raise NotImplementedError

    def set_status(self, status: StatusLine | None) -> None:
        raise NotImplementedError

    def show_lobby(self, screen: dict) -> None:
        """The web lobby or a room's waiting screen; the content is described at the top of lobby.py and room.py (view is lobby or room).
        Choices are drawn as buttons, which send client.act(number) when pressed."""
        raise NotImplementedError

    def set_busy(self, busy: bool) -> None:
        """The core is busy: don't accept input."""
        raise NotImplementedError

    def show_busy(self) -> None:
        """Show the waiting hint (the text from client.busy_text(), which changes with progress)."""
        raise NotImplementedError

    # Timed mode: the room keeps time and sends time's up; the interface only shows the countdown
    def start_timer(self, seconds: int) -> None:
        raise NotImplementedError

    def stop_timer(self) -> None:
        raise NotImplementedError

    # Notices and dialogs
    def notify(self, text: str, error: bool = False, lasting: bool = False) -> None:
        raise NotImplementedError

    def show_activity(self, text: str) -> None:
        """Brief activity that doesn't cover the story (e.g. "Hua acted" on the web) and disappears shortly. Interfaces that don't need it can skip it."""

    def show_info(self, title: str, body: str) -> None:
        raise NotImplementedError

    async def ask_confirm(self, question: str, yes: str, no: str) -> bool:
        raise NotImplementedError

    async def ask_premise(self, form: PremiseForm) -> tuple[str, bool, str] | None:
        """The new story dialog: draw the genre menu, the genre description, the default opening and timed mode from form; pass the player's actions to form
        and update the text box from what it returns. On start, return form.finish(text box, timed or not); None on leaving."""
        raise NotImplementedError

    async def ask_ending(self, title: str, record: str) -> bool:
        """Show the ending and the journey record; returns whether to play again."""
        raise NotImplementedError

    async def ask_name(self, hint: str, error: str) -> str | None:
        """Ask for a name; returns what the player typed (None if cancelled). error is why the last one couldn't be used, empty the first time; when hint is blank, the interface uses its own explanation."""
        raise NotImplementedError

    def exit(self) -> None:
        raise NotImplementedError
