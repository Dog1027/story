"""Calling a local model through Ollama instead of Gemini: a client with the same two calls as a Gemini client's models (a GeminiClient),
so the games and the rest of the core don't know the difference. Chosen by ai = "ollama" in config.toml (story/settings.py).

The request's system_instruction becomes the system message, response_schema (a pydantic model) becomes Ollama's format (output constrained to that JSON schema),
and the answer comes back as a Gemini response (text, parsed, finish_reason, token usage). thinking_config is ignored: local models answer without thinking, which is faster.

Inkling models (family inkling*) ship a chat template Ollama can't use (it stops before the first word), so for them the prompt is written in their own format
and sent raw, starting the answer directly (no thinking). Other models go through Ollama's normal chat.
"""

import json
from collections.abc import Iterator
from functools import cached_property
from typing import Any

import httpx
from google.genai import types
from pydantic import BaseModel

from story.core.ai import AIFailed

DEFAULT_URL = "http://localhost:11434"
DEFAULT_NUM_CTX = 16384  # Ollama's default context is only a few thousand tokens: a long story's prompt would be cut off silently
# Waiting for the first chunk includes loading the model and reading the whole prompt, which on a home computer can take a while; after that chunks come quickly
TIMEOUT = httpx.Timeout(connect=10, read=300, write=30, pool=None)
FINISH = {"stop": types.FinishReason.STOP, "length": types.FinishReason.MAX_TOKENS}


class OllamaClient:
    def __init__(self, model: str, url: str = DEFAULT_URL, num_ctx: int = DEFAULT_NUM_CTX, transport: httpx.BaseTransport | None = None):
        """transport: for tests (httpx.MockTransport)."""
        self.model, self.num_ctx = model, num_ctx
        self.http = httpx.Client(base_url=url.rstrip("/"), timeout=TIMEOUT, transport=transport)
        self.models = OllamaModels(self)

    @cached_property
    def inkling(self) -> bool:
        """Whether the model is an Inkling (its prompt is written by hand, see the module docstring). Asked once; if Ollama can't say, assume not."""
        try:
            response = self.http.post("/api/show", json={"model": self.model})
            family = response.json().get("details", {}).get("family", "") if response.is_success else ""
        except (httpx.HTTPError, ValueError):
            return False
        return family.startswith("inkling")

    def request(self, contents: Any, config: types.GenerateContentConfig | None) -> tuple[str, dict]:
        """(Ollama API path, request body) for one call."""
        system = str(config.system_instruction) if config and config.system_instruction else ""
        user = contents if isinstance(contents, str) else str(contents)
        body: dict[str, Any] = {"model": self.model, "stream": True, "options": {"num_ctx": self.num_ctx}}
        if config and config.temperature is not None:
            body["options"]["temperature"] = config.temperature
        if (fmt := json_schema(config)) is not None:
            body["format"] = fmt
        if self.inkling:
            return "/api/generate", body | {"raw": True, "prompt": inkling_prompt(system, user)}
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
        return "/api/chat", body | {"messages": messages}

    def chunks(self, contents: Any, config: types.GenerateContentConfig | None) -> Iterator[dict]:
        """Ollama's streamed answer, one JSON object per line. Connection trouble and timeouts raise httpx errors (ai.raise_friendly turns them into AIFailed)."""
        path, body = self.request(contents, config)
        with self.http.stream("POST", path, json=body) as response:
            if not response.is_success:
                response.read()
                raise AIFailed(f"Ollama ({self.model}): {error_text(response)}", code=response.status_code)
            for line in response.iter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if error := chunk.get("error"):
                    raise AIFailed(f"Ollama ({self.model}): {error}")
                yield chunk


class OllamaModels:
    """OllamaClient.models: the two calls the program makes on a Gemini client's models. The model argument is ignored (the configured model is used)."""

    def __init__(self, owner: OllamaClient):
        self.owner = owner

    def generate_content_stream(self, *, model: str = "", contents: Any, config: types.GenerateContentConfig | None = None) -> Iterator[types.GenerateContentResponse]:
        for chunk in self.owner.chunks(contents, config):
            yield to_response(chunk)

    def generate_content(self, *, model: str = "", contents: Any, config: types.GenerateContentConfig | None = None) -> types.GenerateContentResponse:
        text, last = "", {}
        for chunk in self.owner.chunks(contents, config):
            text += piece(chunk)
            last = chunk
        response = to_response(last | {"response": text, "message": None})
        schema = config.response_schema if config else None
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            try:
                response.parsed = schema.model_validate_json(text)
            except ValueError:
                response.parsed = None  # Like Gemini: unparsable leaves parsed empty, and the caller decides what to do
        return response


def json_schema(config: types.GenerateContentConfig | None) -> dict | str | None:
    """Ollama's format for the request: the response_schema as a JSON schema, "json" for JSON without a schema, or None for plain text."""
    if config is None:
        return None
    schema = config.response_schema or config.response_json_schema
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_json_schema()
    if isinstance(schema, dict):
        return schema
    return "json" if config.response_mime_type == "application/json" else None


def inkling_prompt(system: str, user: str) -> str:
    """An Inkling prompt that starts the model's answer directly, with thinking off. Strips the model's control-token markers from the text, so player input can't forge them."""

    def message(role: str, text: str) -> str:
        return f"<|message_{role}|><|content_text|>{text.replace('<|', '<')}<|end_message|>"

    head = message("system", system) if system else ""
    return head + message("system", "Thinking effort level: 0") + message("user", user) + "<|message_model|><|content_text|>"


def piece(chunk: dict) -> str:
    """The text in one streamed chunk (/api/generate puts it in response, /api/chat in message.content)."""
    return chunk.get("response") or (chunk.get("message") or {}).get("content") or ""


def to_response(chunk: dict) -> types.GenerateContentResponse:
    """One Ollama chunk as a Gemini response: the text, plus the finish reason and token usage on the last chunk."""
    done = chunk.get("done", False)
    candidate = types.Candidate(
        content=types.Content(role="model", parts=[types.Part(text=piece(chunk))]),
        finish_reason=FINISH.get(chunk.get("done_reason", ""), types.FinishReason.OTHER) if done else None,
    )
    usage = None
    if done:
        usage = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=chunk.get("prompt_eval_count"),
            cached_content_token_count=chunk.get("prompt_eval_cached_count"),
            candidates_token_count=chunk.get("eval_count"),
        )
    return types.GenerateContentResponse(candidates=[candidate], usage_metadata=usage)


def error_text(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error") or response.text)
    except ValueError:
        return response.text or str(response.status_code)
