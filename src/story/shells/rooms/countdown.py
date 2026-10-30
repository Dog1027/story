"""The timed mode's countdown for one room: it starts once everyone has finished reading the new narration (or after READY_WAIT anyway),
tells everyone how long they have, and calls time_up() when it runs out. It knows nothing about the game; the room says when to start and stop."""

import asyncio
from collections.abc import Awaitable, Callable

READY_WAIT = 90  # Most seconds to wait for everyone to finish reading; after that the countdown starts anyway
TIMEOUT_GRACE = 1  # Wait a little after the countdown ends to make up for network lag


class Countdown:
    def __init__(self, announce: Callable[[int], Awaitable[None]], time_up: Callable[[], Awaitable[None]]):
        """announce(seconds) tells everyone the countdown started; time_up() is awaited when it runs out (the room sends /timeout).
        time_up() should call detach() once it may act, i.e. once it has the core: until then stop() still cancels it."""
        self.announce, self.time_up = announce, time_up
        self.task: asyncio.Task | None = None
        self.reading = False  # Started, but still waiting for everyone to finish reading
        self.read_by: set[str] = set()  # Who finished reading this turn's narration
        self.seconds = 0  # This turn's time limit
        self.deadline = 0.0  # When it runs out (loop.time()), so people who connect midway can pick it up

    def after_reading(self, seconds: int) -> None:
        """New narration with a time limit: start once everyone has read it (see read()), or after READY_WAIT."""
        self.stop()
        self.read_by, self.reading, self.seconds = set(), True, seconds
        self.task = asyncio.create_task(self._run(seconds, wait_first=True))

    def start_now(self, seconds: int) -> None:
        """Start right away (e.g. everyone chooses again after a turn failed)."""
        self.stop()
        self.task = asyncio.create_task(self._run(seconds, wait_first=False))

    def finished_reading(self, name: str, online: list[str]) -> None:
        """name finished reading the narration: start if everyone online has."""
        self.read_by.add(name)
        self._start_if_all_read(online)

    def left_room(self, name: str, online: list[str]) -> None:
        """name left: the rest may all have read already."""
        self.read_by.discard(name)
        self._start_if_all_read(online)

    def remaining(self) -> int:
        """Seconds left while it's running, for someone who just connected; 0 when it isn't running (or still waiting for readers)."""
        if self.task is None or self.reading:
            return 0
        return max(0, round(self.deadline - asyncio.get_running_loop().time()))

    def stop(self) -> None:
        if self.task and self.task is not asyncio.current_task():
            self.task.cancel()
        self.task, self.reading = None, False

    def detach(self) -> None:
        """Called by time_up() once it may act: from now on stop() no longer cancels it (it may even start the next countdown)."""
        if self.task is asyncio.current_task():
            self.task = None

    def _start_if_all_read(self, online: list[str]) -> None:
        if self.reading and self.read_by >= set(online):
            self.start_now(self.seconds)

    async def _run(self, seconds: int, wait_first: bool) -> None:
        if wait_first:  # Waiting for everyone to finish reading (read() switches to the real countdown early)
            await asyncio.sleep(READY_WAIT)
        self.reading = False
        self.deadline = asyncio.get_running_loop().time() + seconds
        await self.announce(seconds)
        await asyncio.sleep(seconds + TIMEOUT_GRACE)
        await self.time_up()
