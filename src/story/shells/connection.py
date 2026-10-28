"""The connection between a player and the server (lobby, rooms): a pair of Connections passing messages in memory.

The lobby, the rooms and every browser tab's shared layer all live in the web server process, so no network connection is needed;
every message goes to JSON and back, so the two ends share no objects and the message format is the only contract.
"""

import asyncio
import json


class Connection:
    """One end of a connection between a player and the server: messages from send() arrive at the other end's receive().
    Once either end calls close(), the other end's receive() returns None and send() raises ConnectionError."""

    def __init__(self, inbox: asyncio.Queue, outbox: asyncio.Queue):
        self.inbox, self.outbox = inbox, outbox
        self.peer: Connection | None = None
        self.closed = False

    @staticmethod
    def pair() -> tuple[Connection, Connection]:
        a, b = asyncio.Queue(), asyncio.Queue()
        one, other = Connection(a, b), Connection(b, a)
        one.peer, other.peer = other, one
        return one, other

    @property
    def open(self) -> bool:
        """Neither end has called close()."""
        return not self.closed and not self.peer.closed

    async def send(self, message: dict) -> None:
        if not self.open:
            raise ConnectionError("connection closed")
        # To JSON and back: the two ends never share an object and only get JSON types (tuples become lists), so the message format is the only contract
        self.outbox.put_nowait(json.loads(json.dumps(message, ensure_ascii=False)))

    async def receive(self) -> dict | None:
        """Receive the next message; None once the connection is over."""
        if self.closed:
            return None
        return await self.inbox.get()

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.outbox.put_nowait(None)  # Ends the other end's receive()
            self.inbox.put_nowait(None)  # Also ends a receive() still waiting on this end
