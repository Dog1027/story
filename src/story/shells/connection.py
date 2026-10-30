"""The connection between a player and the server (lobby, rooms): a pair of Connections passing messages in memory.

The lobby, the rooms and every browser tab's shared layer all live in the web server process, so no network connection is needed;
every message goes to JSON and back, so the two ends share no objects and the message format is the only contract.
"""

import asyncio
import json
from collections.abc import Coroutine
from typing import Any

from story.shells.messages import Message, PlayerMessage, ServerMessage


class Connection[In: Message, Out: Message]:
    """One end of a connection between a player and the server: messages from send() arrive at the other end's receive().
    Once either end calls close(), the other end's receive() returns None and send() raises ConnectionError.
    In is what this end receives and Out what it sends: see PlayerEnd and ServerEnd below."""

    def __init__(self, inbox: asyncio.Queue, outbox: asyncio.Queue):
        self.inbox: asyncio.Queue[In | None] = inbox
        self.outbox: asyncio.Queue[Out | None] = outbox
        self.peer: Connection[Out, In] | None = None
        self.closed = False

    @staticmethod
    def pair() -> tuple[PlayerEnd, ServerEnd]:
        """(the player's end, the server's end)."""
        to_player: asyncio.Queue = asyncio.Queue()
        to_server: asyncio.Queue = asyncio.Queue()
        player: PlayerEnd = Connection(to_player, to_server)
        server: ServerEnd = Connection(to_server, to_player)
        player.peer, server.peer = server, player
        return player, server

    @property
    def open(self) -> bool:
        """Neither end has called close()."""
        return not self.closed and not (self.peer is not None and self.peer.closed)

    async def send(self, message: Out) -> None:
        if not self.open:
            raise ConnectionError("connection closed")
        # To JSON and back: the two ends never share an object and only get JSON types (tuples become lists), so the message format is the only contract
        self.outbox.put_nowait(json.loads(json.dumps(message, ensure_ascii=False)))

    async def send_if_open(self, message: Out) -> None:
        """send(), but a closed connection is fine: the receiver already left, and whoever handles their leaving deals with it."""
        try:
            await self.send(message)
        except ConnectionError:
            pass

    async def receive(self) -> In | None:
        """Receive the next message; None once the connection is over."""
        if self.closed:
            return None
        return await self.inbox.get()

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.outbox.put_nowait(None)  # Ends the other end's receive()
            self.inbox.put_nowait(None)  # Also ends a receive() still waiting on this end


type PlayerEnd = Connection[ServerMessage, PlayerMessage]  # A player's Client: receives what the server sends
type ServerEnd = Connection[PlayerMessage, ServerMessage]  # The lobby's and rooms' end


class BackgroundTasks:
    """Work started in the background and cancelled together (e.g. when a room closes). Keeps each task referenced until it ends,
    since asyncio only keeps a weak reference to a running task."""

    def __init__(self) -> None:
        self._running: set[asyncio.Task] = set()

    def spawn(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coroutine)
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    def cancel(self) -> None:
        for task in list(self._running):
            task.cancel()

    def __len__(self) -> int:
        return len(self._running)
