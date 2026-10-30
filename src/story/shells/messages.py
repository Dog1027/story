"""The messages between each player's Client and the server (lobby, rooms), as types. They travel over a Connection as JSON;
what each one means is described in rooms/lobby.py and rooms/room.py. Keys marked NotRequired may be missing: read them with .get()."""

from typing import Literal, NotRequired, TypedDict

# ---------- Player → server ----------


class JoinMessage(TypedDict):
    type: Literal["join"]
    name: str
    token: str  # An ID the browser remembers (may be empty)


class SendMessage(TypedDict):
    type: Literal["send"]
    text: str
    form: NotRequired[bool]  # An action in the new game dialog: goes only to the core
    answer: NotRequired[int]  # The id of the dialog request waiting for this command's result


class ReadyMessage(TypedDict):
    type: Literal["ready"]  # New narration finished showing


PlayerMessage = JoinMessage | SendMessage | ReadyMessage


# ---------- Server → player ----------


class JoinedMessage(TypedDict):
    type: Literal["joined"]


class RejectedMessage(TypedDict):
    type: Literal["rejected"]
    reason: str


class ReplacedMessage(TypedDict):
    type: Literal["replaced"]


class RoomCard(TypedDict):
    """One room in the lobby's list."""

    title: str
    host: str
    members: list[str]
    state: Literal["open", "full", "playing"]
    game: str  # The name of the game being played; empty while waiting
    choice: str  # The option that joins it; empty if it can't be joined


class Person(TypedDict):
    name: str
    room: str  # The host's name of the room they're in; empty in the lobby
    playing: bool


class GameCard(TypedDict):
    """One game in the host's game picker."""

    code: str
    title: str
    description: str
    choice: str  # The option that starts it


class LobbyScreen(TypedDict):
    """The lobby (view "lobby") or a room's waiting screen (view "room")."""

    type: Literal["lobby"]
    view: Literal["lobby", "room"]
    title: str
    you: str
    choices: list[str]
    hint: str
    clear: bool
    seats: int
    rooms: NotRequired[list[RoomCard]]  # Lobby only
    people: NotRequired[list[Person]]  # Lobby only
    max_rooms: NotRequired[int]  # Lobby only
    host: NotRequired[str]  # Room only
    members: NotRequired[list[str]]  # Room only
    games: NotRequired[list[GameCard]]  # Room only: the host's game picker (empty for everyone else)


class ReplyMessage(TypedDict):
    type: Literal["reply"]
    reply: dict  # Reply.to_dict()


class PremiseMessage(TypedDict):
    type: Literal["premise"]
    id: int  # The request id the Client sent as answer
    reply: dict  # Reply.to_dict()


class NewStoryMessage(TypedDict):
    type: Literal["new_story"]
    premise: str  # Empty when the game started from a choice, not a written premise


class BusyMessage(TypedDict):
    type: Literal["busy"]
    on: bool
    progress: NotRequired[str]  # Only while on
    label: NotRequired[str]  # Only while on


class DraftMessage(TypedDict):
    type: Literal["draft"]
    text: str


class WaitingMessage(TypedDict):
    type: Literal["waiting"]
    names: list[str]


class TimerMessage(TypedDict):
    type: Literal["timer"]
    seconds: int


class NoticeMessage(TypedDict):
    type: Literal["notice"]
    text: str


ServerMessage = (
    JoinedMessage | RejectedMessage | ReplacedMessage | LobbyScreen | ReplyMessage | PremiseMessage
    | NewStoryMessage | BusyMessage | DraftMessage | WaitingMessage | TimerMessage | NoticeMessage
)
Message = PlayerMessage | ServerMessage
