from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from agent.ollama_native_adapter import (
    AsyncOllamaNativeClient,
    OllamaNativeClient,
    build_ollama_native_payload,
    convert_openai_messages_to_ollama,
    normalize_ollama_native_base_url,
)


def test_normalize_native_base_accepts_pasted_openai_compat_url() -> None:
    assert (
        normalize_ollama_native_base_url("http://127.0.0.1:11434/v1/")
        == "http://127.0.0.1:11434"
    )
    assert (
        normalize_ollama_native_base_url("http://lab.internal/ollama/v1")
        == "http://lab.internal/ollama"
    )


@pytest.mark.parametrize(
    "value",
    (
        "file:///tmp/ollama",
        "http://user:secret@127.0.0.1:11434",
        "http://127.0.0.1:11434?token=secret",
        "http://127.0.0.1:11434#secret",
    ),
)
def test_normalize_native_base_rejects_unsafe_url_material(value: str) -> None:
    with pytest.raises(ValueError, match="invalid_ollama_native_base_url"):
        normalize_ollama_native_base_url(value)


def test_message_conversion_preserves_reasoning_and_binds_tool_result_name() -> None:
    converted = convert_openai_messages_to_ollama(
        [
            {"role": "developer", "content": "Be exact."},
            {"role": "user", "content": "List files"},
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "I should inspect the directory.",
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {
                            "name": "terminal",
                            "arguments": '{"command":"ls"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_abc",
                "content": "README.md",
            },
        ]
    )

    assert converted[0] == {"role": "system", "content": "Be exact."}
    assert converted[2]["thinking"] == "I should inspect the directory."
    assert converted[2]["tool_calls"][0]["function"] == {
        "index": 0,
        "name": "terminal",
        "arguments": {"command": "ls"},
    }
    assert converted[3] == {
        "role": "tool",
        "content": "README.md",
        "tool_name": "terminal",
    }


def test_message_conversion_never_fetches_remote_image_urls() -> None:
    converted = convert_openai_messages_to_ollama(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.test/private.png"},
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,aGVsbG8="},
                    },
                ],
            }
        ]
    )

    assert converted == [
        {"role": "user", "content": "Describe this", "images": ["aGVsbG8="]}
    ]


def test_payload_maps_openai_controls_to_native_options() -> None:
    payload = build_ollama_native_payload(
        {
            "model": "ollama/qwen3:latest",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "ping",
                        "description": "Ping",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            "max_tokens": 2048,
            "temperature": 0.2,
            "reasoning_effort": "high",
            "extra_body": {"options": {"num_ctx": 65536}},
        }
    )

    assert payload["model"] == "qwen3:latest"
    assert payload["stream"] is False
    assert payload["think"] == "high"
    assert payload["options"] == {
        "num_ctx": 65536,
        "num_predict": 2048,
        "temperature": 0.2,
    }
    assert payload["tools"][0]["function"]["name"] == "ping"


def test_non_streaming_native_response_normalizes_tool_calls_and_usage() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "qwen3:latest",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "thinking": "Need a tool.",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "ping",
                                "arguments": {"host": "127.0.0.1"},
                            }
                        }
                    ],
                },
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 12,
                "eval_count": 4,
            },
        )

    raw_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OllamaNativeClient(
        api_key="no-key-required",
        base_url="http://127.0.0.1:11434/v1",
        http_client=raw_client,
    )
    response = client.chat.completions.create(
        model="qwen3:latest",
        messages=[{"role": "user", "content": "ping"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "ping",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    assert seen["url"] == "http://127.0.0.1:11434/api/chat"
    assert seen["authorization"] is None
    assert seen["payload"]["stream"] is False
    assert response.choices[0].finish_reason == "tool_calls"
    assert response.choices[0].message.reasoning_content == "Need a tool."
    call = response.choices[0].message.tool_calls[0]
    assert call.id.startswith("call_")
    assert call.function.name == "ping"
    assert json.loads(call.function.arguments) == {"host": "127.0.0.1"}
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 4
    assert response.usage.total_tokens == 16


def test_native_client_uses_bearer_only_for_real_configured_key() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        return httpx.Response(
            200,
            json={
                "model": "qwen3",
                "message": {"role": "assistant", "content": "ok"},
                "done": True,
            },
        )

    client = OllamaNativeClient(
        api_key="private-proxy-token",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.chat.completions.create(
        model="qwen3", messages=[{"role": "user", "content": "hi"}]
    )
    assert seen == ["Bearer private-proxy-token"]


def test_streaming_native_response_emits_reasoning_text_tools_finish_and_usage() -> None:
    lines = [
        {
            "model": "qwen3",
            "message": {"role": "assistant", "thinking": "Check first."},
            "done": False,
        },
        {
            "model": "qwen3",
            "message": {"role": "assistant", "content": "Working"},
            "done": False,
        },
        {
            "model": "qwen3",
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {"function": {"name": "ping", "arguments": {"host": "local"}}}
                ],
            },
            "done": True,
            "prompt_eval_count": 9,
            "eval_count": 3,
        },
    ]
    body = "".join(json.dumps(line) + "\n" for line in lines)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body.encode(),
            headers={"content-type": "application/x-ndjson"},
        )

    client = OllamaNativeClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    chunks = list(
        client.chat.completions.create(
            model="qwen3",
            messages=[{"role": "user", "content": "ping"}],
            stream=True,
        )
    )

    assert chunks[0].choices[0].delta.reasoning_content == "Check first."
    assert chunks[1].choices[0].delta.content == "Working"
    assert chunks[2].choices[0].finish_reason == "tool_calls"
    assert chunks[2].choices[0].delta.tool_calls[0].function.name == "ping"
    assert chunks[3].choices == []
    assert chunks[3].usage.total_tokens == 12


@pytest.mark.asyncio
async def test_async_facade_returns_native_completion() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen3",
                "message": {"role": "assistant", "content": "ready"},
                "done": True,
            },
        )

    sync = OllamaNativeClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    client = AsyncOllamaNativeClient(sync)
    response = await client.chat.completions.create(
        model="qwen3", messages=[{"role": "user", "content": "hi"}]
    )
    assert response.choices[0].message.content == "ready"


def test_primary_client_factory_selects_native_adapter(monkeypatch) -> None:
    from agent import agent_runtime_helpers as runtime_helpers

    raw_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "model": "qwen3",
                    "message": {"role": "assistant", "content": "native"},
                    "done": True,
                },
            )
        )
    )
    agent = SimpleNamespace(
        provider="ollama",
        api_mode="chat_completions",
        _disable_environment_proxy=True,
        _client_log_context=lambda: "test",
        _build_keepalive_http_client=lambda *_args, **_kwargs: raw_client,
    )
    monkeypatch.setattr(
        runtime_helpers,
        "authorize_primary_base_url",
        lambda _agent, base_url: base_url,
    )

    client = runtime_helpers.create_openai_client(
        agent,
        {"api_key": "ollama-local", "base_url": "http://127.0.0.1:11434/v1"},
        reason="test",
        shared=False,
    )

    assert isinstance(client, OllamaNativeClient)
    assert client.base_url == "http://127.0.0.1:11434"
    response = client.chat.completions.create(
        model="qwen3", messages=[{"role": "user", "content": "hello"}]
    )
    assert response.choices[0].message.content == "native"


def test_auxiliary_router_preserves_first_class_native_ollama(monkeypatch) -> None:
    from agent import auxiliary_client
    from agent.egress_policy import EgressMode, EgressPolicy

    monkeypatch.setattr(
        auxiliary_client,
        "_load_auxiliary_egress_context",
        lambda: (EgressPolicy(EgressMode.ONLINE), {}),
    )

    client, model = auxiliary_client.resolve_provider_client(
        "ollama",
        model="qwen3:latest",
        explicit_base_url="http://127.0.0.1:11434/v1",
    )

    assert isinstance(client, OllamaNativeClient)
    assert client.base_url == "http://127.0.0.1:11434"
    assert client.api_key == "ollama-local"
    assert model == "qwen3:latest"
    client.close()


@pytest.mark.asyncio
async def test_auxiliary_router_builds_async_native_ollama(monkeypatch) -> None:
    from agent import auxiliary_client
    from agent.egress_policy import EgressMode, EgressPolicy

    monkeypatch.setattr(
        auxiliary_client,
        "_load_auxiliary_egress_context",
        lambda: (EgressPolicy(EgressMode.ONLINE), {}),
    )

    client, model = auxiliary_client.resolve_provider_client(
        "ollama",
        model="qwen3:latest",
        async_mode=True,
        explicit_base_url="http://127.0.0.1:11434",
    )

    assert isinstance(client, AsyncOllamaNativeClient)
    assert model == "qwen3:latest"
    client.close()


def test_local_ai_auxiliary_route_stays_native_and_proxy_free(monkeypatch) -> None:
    from agent import auxiliary_client
    from agent.egress_policy import EgressMode, EgressPolicy

    route_config = {
        "model": {
            "provider": "ollama",
            "default": "qwen3:latest",
            "base_url": "http://127.0.0.1:11434",
        },
        "security": {"egress_mode": "local_ai"},
    }
    monkeypatch.setattr(
        auxiliary_client,
        "_load_auxiliary_egress_context",
        lambda: (EgressPolicy(EgressMode.LOCAL_AI), route_config),
    )

    client, model = auxiliary_client.resolve_provider_client(
        "ollama",
        model="qwen3:latest",
        explicit_base_url="http://127.0.0.1:11434",
    )

    assert isinstance(client, OllamaNativeClient)
    assert client.base_url == "http://127.0.0.1:11434"
    assert client.api_key == "ollama-local"
    assert client._fabric_disable_environment_proxy is True
    assert model == "qwen3:latest"
    client.close()
