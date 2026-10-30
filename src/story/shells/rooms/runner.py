"""Running a room's core: in a background thread (a call can take tens of seconds while the AI writes), telling everyone
how it's going while they wait. It knows nothing about the room's members; it only gets a way to tell everyone."""

import asyncio
from collections.abc import Awaitable, Callable

from story.core import Reply, TeamGame
from story.shells.text import UI


class CoreRunner:
    def __init__(self, broadcast: Callable[[dict], Awaitable[None]]):
        """broadcast(message) sends a message to everyone in the room."""
        self.broadcast = broadcast
        self.core: TeamGame | None = None
        self.busy = False  # Everyone sees "writing the story" (a call made with busy=True is running)
        self.queued = False  # An AI call is queued (all rooms share one key's call limit)
        self.reported = ("", "")  # The progress and draft everyone was last told about during this call
        self.loop: asyncio.AbstractEventLoop | None = None  # For news from the thread running the core (see changed)
        self.tasks: set[asyncio.Task] = set()  # Progress reports on their way

    def attach(self, core: TeamGame | None) -> None:
        """The core to run (None once the game is over). Hears about its progress from now on."""
        self.core = core
        if core is not None:
            self.loop = asyncio.get_running_loop()
            core.watch(self.changed)

    def progress(self) -> str:
        """What the waiting screen says: queued for the shared call limit, or what the core is doing."""
        return UI["queued"] if self.queued else (self.core.progress if self.core else "")

    def label(self) -> str:
        """What the waiting screen calls the wait: the game's own words ("writing the story", "the judge is thinking")."""
        return self.core.busy_label if self.core else ""

    def busy_message(self, progress: str | None = None) -> dict:
        """The "waiting for the AI" message: with the current progress unless one is given."""
        return {"type": "busy", "on": True, "progress": self.progress() if progress is None else progress, "label": self.label()}

    def set_queued(self, queued: bool) -> None:
        """Passed to make_core as on_queue: an AI call started or stopped waiting in line (called from the core's thread)."""
        self.queued = queued
        self.changed()

    def changed(self) -> None:
        """Called from the thread running the core when its progress or draft changes, or an AI call starts or stops queuing:
        hand it to the event loop, which tells everyone (_report)."""
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self._spawn_report)

    async def call(self, fn: Callable[[], Reply], busy: bool = False) -> Reply:
        """Call the core in a background thread. With busy, everyone sees "writing the story" and how it's going."""
        if busy:
            self.busy, self.reported = True, ("", "")
            await self.broadcast(self.busy_message(progress=""))
        try:
            return await asyncio.to_thread(fn)  # Progress and narration so far arrive through changed() meanwhile
        finally:
            if busy:
                self.busy = False
                await self.broadcast({"type": "busy", "on": False})

    def close(self) -> None:
        for task in list(self.tasks):
            task.cancel()

    def _spawn_report(self) -> None:
        task = asyncio.create_task(self._report())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _report(self) -> None:
        """Tell everyone the progress (a new story calls the AI several times) and the narration so far, if they changed."""
        if not self.busy or self.core is None:
            return  # Only while everyone sees "writing the story"; news arriving after the call ended is dropped
        progress, draft = self.progress(), self.core.draft
        if progress != self.reported[0]:
            await self.broadcast(self.busy_message(progress))
        if draft and draft != self.reported[1]:
            await self.broadcast({"type": "draft", "text": draft})
        self.reported = (progress, draft or self.reported[1])
