"""Calling Gemini: build the client, send requests, pull out the narration while streaming, and record each call's time and token usage.

Each game's AI-calling class inherits AICaller (the adventure's Engine, turtle soup's SoupJudge) and calls the AI with generate() and stream();
this module knows nothing about game rules or what the prompts say.
"""

import json
import re
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NoReturn

import httpx
from google import genai
from google.genai import types

from story.core.prompts import UI  # Error messages shown to players (story/core/ui/<lang>/core.md)

MODEL = "gemini-3.5-flash-lite"
REQUEST_TIMEOUT = 40  # Seconds to wait for one AI request; Gemini sometimes hangs a minute or two, and resending is usually faster
REQUEST_ATTEMPTS = 3  # How many times to send on a timeout or a busy server (429, 5xx), including the first


def new_client(api_key: str | None) -> genai.Client:
    """Resends automatically on a timeout or a busy server (about 1 and 2 seconds apart), so players don't wait on a stuck request."""
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT * 1000,  # Milliseconds
            retry_options=types.HttpRetryOptions(attempts=REQUEST_ATTEMPTS),
        ),
    )


def is_key_error(e: Exception) -> bool:
    """Whether a Gemini error comes from an invalid API key or missing permission."""
    code = getattr(e, "code", None)
    text = str(e)
    return code in (400, 401, 403) and ("API key" in text or "API_KEY" in text)


class AIFailed(RuntimeError):
    """Calling the AI didn't give a usable result (timed out, cut off, unparsable, left something out); the message is shown to players.
    Games raise it for their own checks too. The core treats it as retryable; any other RuntimeError is a bug."""


def raise_friendly(e: Exception) -> NoReturn:
    """Still timing out, unreachable or cut off mid-answer after the resends: turn it into an error the core handles; re-raise anything else as is."""
    if isinstance(e, httpx.TransportError):  # Timeouts, failed connections, connections reset partway through a stream…
        raise AIFailed(UI["timeout"]) from e
    raise e


class StopStream(Exception):
    """Raised from stream()'s on_text when there's no point receiving more (e.g. the adventure's AI declared the ending too early): stops the stream and propagates."""

    reason = "stopped"  # The reason written to the log


def close(chunks: Iterator[types.GenerateContentResponse] | None) -> None:
    """Stop receiving a stream (if it has started)."""
    if chunks is not None and hasattr(chunks, "close"):
        chunks.close()


def partial_string(text: str, key: str) -> str | None:
    """What a string field (e.g. narration while streaming) holds so far in JSON that isn't finished yet. None if the field hasn't appeared."""
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"', text)
    if not match:
        return None
    out, i = [], match.end()
    while i < len(text) and text[i] != '"':
        if text[i] != "\\":
            out.append(text[i])
            i += 1
            continue
        if i + 1 >= len(text) or (text[i + 1] == "u" and i + 6 > len(text)):
            break  # The escape sequence isn't complete yet; wait for the next chunk
        escaped = text[i + 1]
        if escaped == "u":
            out.append(chr(int(text[i + 2 : i + 6], 16)))
            i += 6
        else:
            out.append({"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}.get(escaped, escaped))
            i += 2
    return "".join(out)


def partial_bool(text: str, key: str) -> bool | None:
    """A boolean field from JSON that isn't finished yet; None if it hasn't appeared."""
    match = re.search(rf'"{re.escape(key)}"\s*:\s*(true|false)', text)
    return None if match is None else match.group(1) == "true"


class AICaller:
    """Every AI call goes through here: records the kind, the seconds it took, and the token usage Gemini reports (prompt, cached, output, thinking)
    into each turn's log, to find out where waiting time goes."""

    def __init__(self, api_key: str | None = None, client: Any = None, log_path: Path | None = None):
        """client: a Gemini client, or anything with the same models.generate_content(_stream) (a RateLimit's LimitedClient, the tests' fakes)."""
        self.client = client or new_client(api_key)
        self.log_path = log_path  # One log per team; None writes nothing (e.g. just prompts)
        self.calls: list[dict] = []  # AI calls since the last log line (cleared once written)
        self.on_change: Callable[[], None] = lambda: None  # Called (from the worker thread) whenever progress or draft changes
        self._progress_text = ""
        self._draft_text = ""

    @property
    def progress(self) -> str:
        """What's happening now during a long job (e.g. "planning the story outline"), shown on the waiting screen; empty otherwise."""
        return self._progress_text

    @progress.setter
    def progress(self, value: str) -> None:
        if value != self._progress_text:
            self._progress_text = value
            self.on_change()

    @property
    def draft(self) -> str:
        """The narration the AI is writing (what has streamed in so far), which shells can show early; empty when not writing."""
        return self._draft_text

    @draft.setter
    def draft(self, value: str) -> None:
        if value != self._draft_text:
            self._draft_text = value
            self.on_change()

    def generate(self, kind: str, **request: Any) -> types.GenerateContentResponse:
        """A call that returns the whole result at once."""
        started = time.monotonic()
        try:
            response = self.client.models.generate_content(**request)
        except Exception as e:  # Failed even after the resends: record the failed call too, written with the next turn's log line
            self.record(kind, started, None, error=str(e)[:200])
            raise_friendly(e)
        self.record(kind, started, response)
        return response

    def stream(self, kind: str, on_text: Callable[[str], None], **request: Any) -> tuple[str, types.GenerateContentResponse | None]:
        """A streaming call: on each chunk, calls on_text with the full text so far. Returns (full text, last chunk). If on_text raises StopStream, stops and propagates."""
        started, text, last, extra = time.monotonic(), "", None, {}
        chunks = None
        try:
            chunks = self.client.models.generate_content_stream(**request)
            for chunk in chunks:
                last = chunk
                if piece := chunk.text:
                    text += piece
                    on_text(text)
        except StopStream as e:
            extra["stopped"] = e.reason
            raise
        except Exception as e:
            extra["error"] = str(e)[:200]
            raise_friendly(e)
        finally:
            close(chunks)  # Stop receiving the rest when interrupted
            self.record(kind, started, last, **extra)
        return text, last

    def record(self, kind: str, started: float, response: types.GenerateContentResponse | None, **extra: str) -> None:
        call = {"kind": kind, "seconds": round(time.monotonic() - started, 2)}
        usage = getattr(response, "usage_metadata", None)
        for field, name in (
            ("prompt_token_count", "prompt"),
            ("cached_content_token_count", "cached"),
            ("candidates_token_count", "output"),
            ("thoughts_token_count", "thinking"),
        ):
            if (value := getattr(usage, field, None)) is not None:
                call[name] = value
        self.calls.append(call | extra)

    def write_log(self, record: dict) -> None:
        """Write one log line, with the AI calls made since the last one."""
        record["calls"], self.calls = self.calls, []
        if self.log_path is None:
            return
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # A log that can't be written doesn't affect the game
