import asyncio
import json

import httpx
import pytest

from app.services import assistant_provider


@pytest.mark.parametrize("host,deepseek", [("api.deepseek.com", True), ("model.example", False)])
def test_provider_bounds_protocol_and_records_usage(monkeypatch, host, deepseek):
    sent = []

    def respond(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={
            "model": "returned-build", "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            "choices": [{"message": {"content": "状态待核实"}}],
        })

    client = httpx.AsyncClient
    monkeypatch.setattr(assistant_provider.httpx, "AsyncClient",
                        lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    provider = assistant_provider.ChatCompletionsProvider("https://" + host, "fixture", "fixture-secret")
    assert asyncio.run(provider.complete([{"role": "user", "content": "在哪里"}], []))["content"] == "状态待核实"
    assert sent[0].get("thinking") == ({"type": "disabled"} if deepseek else None)
    assert sent[0]["max_tokens"] == 1500
    assert provider.last_response == {
        "model": "returned-build", "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}


def test_provider_error_contains_no_credentials_or_upstream_body(monkeypatch):
    client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _: httpx.Response(401, text="private-upstream-body"))
    monkeypatch.setattr(assistant_provider.httpx, "AsyncClient", lambda **kw: client(transport=transport, **kw))
    provider = assistant_provider.ChatCompletionsProvider("https://api.deepseek.com", "fixture", "private-key")
    with pytest.raises(assistant_provider.ProviderUnavailable) as error:
        asyncio.run(provider.complete([], []))
    assert "private" not in str(error.value)
    assert provider.last_response == {}


def test_stream_emits_text_before_finish_and_reassembles_tool_arguments(monkeypatch):
    deltas = []

    def frame(delta):
        return ("data: " + json.dumps({"choices": [{"delta": delta}]}, ensure_ascii=False) + "\r\n\r\n").encode()

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            first = frame({"content": "流式回复"})
            split = first.index("流".encode()) + 1
            yield first[:split]
            yield first[split:]
            assert deltas == ["流式回复"]
            yield frame({"tool_calls": [{"index": 0, "id": "tool", "function": {
                "name": "get_robot_context", "arguments": "{"}}]})
            yield frame({"tool_calls": [{"index": 0, "function": {"arguments": "}"}}]})
            yield b"data: [DONE]\r\n\r\n"

    def respond(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, stream=Chunks(), headers={"Content-Type": "text/event-stream"})

    client = httpx.AsyncClient
    monkeypatch.setattr(assistant_provider.httpx, "AsyncClient",
                        lambda **kw: client(transport=httpx.MockTransport(respond), **kw))
    provider = assistant_provider.ChatCompletionsProvider("https://model.example", "fixture", "fixture-secret")
    assert asyncio.run(provider.complete_stream([], [], deltas.append)) == {
        "tool_calls": [{"id": "tool", "function": {"name": "get_robot_context", "arguments": "{}"}}],
    }
