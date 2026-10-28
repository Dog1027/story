"""A limit on AI calls: how many calls a minute when several games (web rooms, just eval scenarios) share one API key.

Gemini's free tier limits calls per model per minute (15 for flash-lite). Calls over the limit queue here until the oldest one is a minute old;
under the limit they go out at once, so playing alone is never slower. If Gemini still refuses (429), wait the seconds it asks for and resend.
"""

import re
import threading
import time
from collections import deque
from collections.abc import Callable
from types import SimpleNamespace

from google.genai import errors

WINDOW = 60  # Seconds
RETRIES = 3  # How many times to resend when Gemini refuses (429)


class NoSlot(Exception):
    """A spare copy of a slow request (see ai.first_of) found the limit full: it isn't sent, so it never makes the queue longer."""


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

    def call(self, send, on_queue=None, spare: bool = False, on_sent: Callable[[], None] | None = None):
        """Send once there's a slot, resending on 429. on_sent() is called when the request actually goes out, after any queuing.
        spare: a second copy of a slow request; sent only if a slot is free right now and never resent, otherwise raises NoSlot."""
        for attempt in range(RETRIES + 1):
            if not spare:
                self.wait(on_queue)
            elif self.take():
                raise NoSlot
            if on_sent:
                on_sent()
            try:
                return send()
            except errors.ClientError as e:
                if spare or e.code != 429 or attempt == RETRIES:
                    raise
                delay = re.search(r"retry in ([\d.]+)s", str(e))
                time.sleep(float(delay.group(1)) if delay else 30)

    def wrap(self, client, on_queue: Callable[[bool], None] | None = None) -> LimitedClient:
        """Wrap a Gemini client so every call through it is limited."""
        return LimitedClient(self, client, on_queue)


class LimitedClient:
    """A Gemini client whose calls go through a RateLimit. AICaller uses generate() and open_stream() directly, so that a slow request's
    second copy only counts its wait from when the first actually went out, and is only sent if a slot is free (see ai.first_of).
    models has the same methods as a Gemini client's, for code that just makes calls."""

    def __init__(self, limit: RateLimit, client, on_queue: Callable[[bool], None] | None = None):
        self.limit, self.client, self.on_queue = limit, client, on_queue  # Keep client: when it's collected, it closes the connection

        def stream(**request):
            chunks, head = self.open_stream(request)
            if head is not None:
                yield head
                yield from chunks

        self.models = SimpleNamespace(generate_content=lambda **request: self.generate(request), generate_content_stream=stream)

    def generate(self, request: dict, spare: bool = False, on_sent: Callable[[], None] | None = None):
        return self.limit.call(lambda: self.client.models.generate_content(**request), self.on_queue, spare, on_sent)

    def open_stream(self, request: dict, spare: bool = False, on_sent: Callable[[], None] | None = None):
        """A streaming request is only sent when the first chunk is read, so reading the first chunk counts as the call. Returns (chunks, first chunk)."""

        def first():
            chunks = self.client.models.generate_content_stream(**request)
            return chunks, next(chunks, None)

        return self.limit.call(first, self.on_queue, spare, on_sent)
