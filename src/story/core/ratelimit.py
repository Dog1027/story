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


class RateLimit:
    """Called from background threads (the core calls the AI in a background thread), so it uses a threading lock."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.sent: deque[float] = deque()  # When calls went out in the last minute
        self.lock = threading.Lock()

    def wait(self, on_queue: Callable[[bool], None] | None = None) -> None:
        """Wait until a call may go out. Calls on_queue(True) before queuing and on_queue(False) when it's our turn, so the page can show "queued"."""
        queued = False
        while True:
            with self.lock:
                now = time.monotonic()
                while self.sent and now - self.sent[0] >= WINDOW:
                    self.sent.popleft()
                if len(self.sent) < self.per_minute:
                    self.sent.append(now)
                    break
                delay = self.sent[0] + WINDOW - now
            if on_queue and not queued:
                on_queue(True)
            queued = True
            time.sleep(delay)
        if on_queue and queued:
            on_queue(False)

    def call(self, send, on_queue=None):
        for attempt in range(RETRIES + 1):
            self.wait(on_queue)
            try:
                return send()
            except errors.ClientError as e:
                if e.code != 429 or attempt == RETRIES:
                    raise
                delay = re.search(r"retry in ([\d.]+)s", str(e))
                time.sleep(float(delay.group(1)) if delay else 30)

    def wrap(self, client, on_queue: Callable[[bool], None] | None = None):
        """Wrap a Gemini client so every call through it is limited. A streaming request is only sent when the first chunk is read, so reading the first chunk is wrapped too."""
        models = client.models

        def stream(**request):
            def first():
                chunks = models.generate_content_stream(**request)
                return chunks, next(chunks, None)

            chunks, head = self.call(first, on_queue)
            if head is not None:
                yield head
                yield from chunks

        return SimpleNamespace(client=client, models=SimpleNamespace(  # Keep client: when it's collected, it closes the connection
            generate_content=lambda **request: self.call(lambda: models.generate_content(**request), on_queue),
            generate_content_stream=stream,
        ))
