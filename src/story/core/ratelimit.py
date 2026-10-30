"""A limit on AI calls: how many calls a minute when several games (web rooms, just eval scenarios) share one API key.

Gemini's free tier limits calls per model per minute (15 for flash-lite). Calls over the limit queue here until the oldest one is a minute old;
under the limit they go out at once, so playing alone is never slower. If Gemini still refuses (429), wait the seconds it asks for and resend.
"""

import re
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

from google.genai import errors, types

Chunks = Iterator[types.GenerateContentResponse]

WINDOW = 60  # Seconds
RETRIES = 3  # How many times to resend when Gemini refuses (429)


class RateLimit:
    """Called from background threads (the core calls the AI in a background thread), so it uses a threading lock."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.sent: deque[float] = deque()  # When calls went out in the last minute
        self.lock = threading.Lock()

    def take(self) -> float:
        """Take a slot if one is free: 0. Otherwise take nothing and return how many seconds until the next one frees up."""
        with self.lock:
            now = time.monotonic()
            while self.sent and now - self.sent[0] >= WINDOW:
                self.sent.popleft()
            if len(self.sent) < self.per_minute:
                self.sent.append(now)
                return 0
            return self.sent[0] + WINDOW - now

    def wait(self, on_queue: Callable[[bool], None] | None = None) -> None:
        """Wait until a call may go out. Calls on_queue(True) before queuing and on_queue(False) when it's our turn, so the page can show "queued"."""
        queued = False
        while delay := self.take():
            if on_queue and not queued:
                on_queue(True)
            queued = True
            time.sleep(delay)
        if on_queue and queued:
            on_queue(False)

    def call[T](self, send: Callable[[], T], on_queue: Callable[[bool], None] | None = None) -> T:
        """Send once there's a slot, resending on 429."""
        attempt = 0
        while True:
            self.wait(on_queue)
            try:
                return send()
            except errors.ClientError as e:
                if e.code != 429 or attempt == RETRIES:
                    raise
                attempt += 1
                delay = re.search(r"retry in ([\d.]+)s", str(e))
                time.sleep(float(delay.group(1)) if delay else 30)

    def wrap(self, client: Any, on_queue: Callable[[bool], None] | None = None) -> LimitedClient:
        """Wrap a Gemini client so every call through it is limited."""
        return LimitedClient(self, client, on_queue)


class LimitedClient:
    """A Gemini client whose calls go through a RateLimit: models has the same methods as a Gemini client's."""

    def __init__(self, limit: RateLimit, client: Any, on_queue: Callable[[bool], None] | None = None):
        self.limit, self.client, self.on_queue = limit, client, on_queue  # Keep client: when it's collected, it closes the connection

        def stream(**request: Any) -> Chunks:
            chunks, head = self.open_stream(request)
            if head is not None:
                yield head
                yield from chunks

        self.models = SimpleNamespace(generate_content=lambda **request: self.generate(request), generate_content_stream=stream)

    def generate(self, request: dict[str, Any]) -> types.GenerateContentResponse:
        return self.limit.call(lambda: self.client.models.generate_content(**request), self.on_queue)

    def open_stream(self, request: dict[str, Any]) -> tuple[Chunks, types.GenerateContentResponse | None]:
        """A streaming request is only sent when the first chunk is read, so reading the first chunk counts as the call. Returns (chunks, first chunk)."""

        def first() -> tuple[Chunks, types.GenerateContentResponse | None]:
            chunks = self.client.models.generate_content_stream(**request)
            return chunks, next(chunks, None)

        return self.limit.call(first, self.on_queue)
