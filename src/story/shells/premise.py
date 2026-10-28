"""The new story dialog (the adventure's premise form): its rules live here, so the interface only draws it."""

import asyncio
from collections.abc import Awaitable, Callable

from story.core import Reply


class PremiseForm:
    """The rules of the new story dialog: the interface only draws it, passes the player's actions here, and updates the text box from what comes back.
    None means leave the text box as is (the player edited it, or a later action has superseded this result)."""

    def __init__(self, reply: Reply, request: Callable[..., Awaitable[Reply]]):
        self.default = reply.premise_default  # The current default opening: used when the text box is blank or untouched
        self.timed = reply.timed
        self.genres = [(value, label) for value, label, _ in reply.genres]  # The genre menu: empty without genre packs, and then the interface doesn't show it
        self.hints = {value: hint for value, _, hint in reply.genres}
        self.genre = reply.genre if not self.genres or reply.genre in self.hints else self.genres[0][0]
        self.request = request  # Sends commands to the core; see Client.ask_room()
        self.asking = asyncio.Lock()  # One at a time: the core can't handle two requests at once
        self.latest = 0  # The number of the latest action

    def genre_options(self) -> list[tuple[str, str]]:
        """The genre menu: (text shown, genre), in the order the game gives."""
        return [(label, value) for value, label in self.genres]

    def genre_hint(self, choice: str) -> str:
        """The genre description under the menu."""
        return self.hints.get(choice, "")

    async def change_genre(self, choice: str, text: str) -> str | None:
        """Change the genre: the randomly drawn opening switches to the new genre's too (not if the player edited the text box). text is the text box's current content."""
        self.genre = choice
        reply = await self._ask(f"/genre {choice}")
        return None if reply is None or reply.error else self._new_default(reply.premise_default, text)

    async def reroll(self, text: str) -> str | None:
        """Another one: redraw from the genre packs' opening ideas without waiting for the AI. Pressing it always replaces the text box."""
        reply = await self._ask(f"/genre {self.genre}", "/random")
        return None if reply is None or reply.error else self._new_default(reply.premise_default, text, replace=True)

    async def suggest(self, text: str) -> str:
        """Suggest one: have the AI think of an opening, always replacing the text box. Raises RuntimeError on failure (the interface just shows a notice; starting a game isn't interrupted)."""
        reply = await self._ask(f"/genre {self.genre}", "/suggest", latest_only=False)
        if reply.error:
            raise RuntimeError(reply.notice)
        return self._new_default(reply.suggestion, text, replace=True)

    def finish(self, text: str, timed: bool) -> tuple[str, bool, str]:
        """Start pressed: (premise, timed or not, genre). A blank text box uses the default opening."""
        return " ".join(text.split()) or self.default, timed, self.genre

    async def _ask(self, *commands: str, latest_only: bool = True) -> Reply | None:
        """With latest_only, returns None if another action came in while waiting (e.g. switching genres quickly); the old result isn't used."""
        self.latest += 1
        mine = self.latest
        async with self.asking:
            reply = await self.request(*commands)
        return reply if not latest_only or mine == self.latest else None

    def _new_default(self, premise: str, text: str, replace: bool = False) -> str | None:
        edited = " ".join(text.split()) not in ("", " ".join(self.default.split()))
        self.default = premise
        return None if edited and not replace else premise
