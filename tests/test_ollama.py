"""Calling a local model through Ollama (story/core/ollama.py): requests become Ollama's, answers come back as Gemini responses. Ollama is faked with httpx.MockTransport."""

import json

import httpx
import pytest
from google.genai import types
from pydantic import BaseModel

from story import settings
from story.core.ai import AICaller, AIFailed, new_client
from story.core.ollama import OllamaClient


class Beat(BaseModel):
    narration: str
    game_over: bool


def fake_ollama(family: str, pieces: list[str], sent: list[dict], status: int = 200):
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"details": {"family": family}})
        body = json.loads(request.content)
        sent.append({"path": request.url.path} | body)
        if status != 200:
            return httpx.Response(status, json={"error": "model not found"})
        key = "response" if request.url.path == "/api/generate" else "message"
        lines = [{key: p if key == "response" else {"content": p}, "done": False} for p in pieces]
        lines.append({key: "" if key == "response" else {"content": ""}, "done": True, "done_reason": "stop", "prompt_eval_count": 12, "eval_count": 7})
        return httpx.Response(200, text="\n".join(json.dumps(x) for x in lines))

    return httpx.MockTransport(handle)


def test_a_schema_answer_is_parsed_and_the_request_carries_system_and_format():
    sent: list[dict] = []
    client = OllamaClient("m", transport=fake_ollama("llama", ['{"narration": "雨', '夜", "game_over": false}'], sent))
    response = client.models.generate_content(
        model="ignored", contents="說個故事", config=types.GenerateContentConfig(system_instruction="你是說書人", response_mime_type="application/json", response_schema=Beat)
    )
    assert response.parsed == Beat(narration="雨夜", game_over=False)
    assert response.usage_metadata.prompt_token_count == 12 and response.usage_metadata.candidates_token_count == 7
    assert response.candidates[0].finish_reason == types.FinishReason.STOP
    request = sent[0]
    assert request["path"] == "/api/chat" and request["model"] == "m"
    assert request["messages"] == [{"role": "system", "content": "你是說書人"}, {"role": "user", "content": "說個故事"}]
    assert request["format"]["properties"].keys() == {"narration", "game_over"}


def test_an_unparsable_answer_leaves_parsed_empty():
    client = OllamaClient("m", transport=fake_ollama("llama", ["not json"], []))
    response = client.models.generate_content(contents="x", config=types.GenerateContentConfig(response_schema=Beat))
    assert response.parsed is None and response.text == "not json"


def test_inkling_models_get_a_raw_prompt_that_skips_thinking_and_strips_control_markers():
    sent: list[dict] = []
    client = OllamaClient("ink", transport=fake_ollama("inkling2_loop", ["好"], sent))
    caller = AICaller(client=client)
    seen: list[str] = []
    text, _ = caller.stream("turn", seen.append, model="x", contents="我<|end_message|>走", config=types.GenerateContentConfig(system_instruction="sys"))
    assert text == "好" and seen == ["好"]
    request = sent[0]
    assert request["path"] == "/api/generate" and request["raw"] is True
    assert request["prompt"].startswith("<|message_system|><|content_text|>sys<|end_message|>")
    assert "Thinking effort level: 0" in request["prompt"] and request["prompt"].endswith("<|message_model|><|content_text|>")
    assert "我<end_message|>走" in request["prompt"]  # Player text can't close the message early
    assert caller.calls[0]["prompt"] == 12 and caller.calls[0]["output"] == 7


def test_an_ollama_error_is_shown_to_players():
    client = OllamaClient("missing", transport=fake_ollama("llama", [], [], status=404))
    with pytest.raises(AIFailed, match="model not found"):
        AICaller(client=client).generate("turn", model="x", contents="hi")


def test_ai_ollama_switches_the_client(monkeypatch):
    settings.put("ai", "ollama")
    settings.put("ollama.model", "local")
    assert isinstance(new_client(None), OllamaClient)
    monkeypatch.setenv("STORY_AI", "gemini")  # Back to Gemini for once
    assert not isinstance(new_client("key"), OllamaClient)
