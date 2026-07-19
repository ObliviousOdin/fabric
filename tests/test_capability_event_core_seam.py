"""Privacy and behavior contracts for the closed core capability seam."""

from __future__ import annotations

import json

import pytest

import model_tools
from fabric_cli import plugins as plugin_runtime
from plugins.achievements.events import Provider, normalize_provider


def test_capability_event_accepts_only_closed_optional_metadata(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        plugin_runtime, "has_hook", lambda name: name == "capability_event"
    )
    monkeypatch.setattr(
        plugin_runtime,
        "invoke_hook",
        lambda name, **payload: calls.append((name, payload)) or [],
    )

    assert plugin_runtime.emit_capability_event(
        capability="provider",
        action="request_succeeded",
        outcome="success",
        subject_id="model-family",
        session_id="session-1",
        turn_id="turn-1",
        surface="Desktop App",
        provider="openai/codex",
        event_id="request-1",
        duration_ms=42,
        count=1,
        occurred_at=1.0,
    )

    assert calls == [
        (
            "capability_event",
            {
                "capability": "provider",
                "action": "request_succeeded",
                "outcome": "success",
                "occurred_at": 1.0,
                "subject_id": "model-family",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "event_id": "request-1",
                "surface": "desktop-app",
                "provider": "openai-codex",
                "duration_ms": 42,
                "count": 1,
            },
        )
    ]


def test_grok_oauth_provider_alias_is_counted_as_xai():
    assert normalize_provider("xai-oauth") is Provider.XAI


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session_id", "bad\nidentifier"),
        ("turn_id", object()),
        ("surface", "not\na\nsurface"),
        ("provider", "provider-☃"),
        ("event_id", "x" * 257),
    ],
)
def test_capability_event_rejects_invalid_optional_metadata(monkeypatch, field, value):
    monkeypatch.setattr(plugin_runtime, "has_hook", lambda _name: True)
    monkeypatch.setattr(
        plugin_runtime,
        "invoke_hook",
        lambda *_args, **_kwargs: pytest.fail("invalid event must not dispatch"),
    )
    kwargs = {
        "capability": "conversation",
        "action": "turn_started",
        "outcome": "success",
        field: value,
    }
    assert plugin_runtime.emit_capability_event(**kwargs) is False


def test_tool_capability_event_is_closed_and_explicit_false_is_failure(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        plugin_runtime, "has_hook", lambda name: name == "capability_event"
    )
    monkeypatch.setattr(
        plugin_runtime,
        "invoke_hook",
        lambda name, **payload: calls.append((name, payload)) or [],
    )

    secret = "PRIVATE-TOOL-CONTENT"
    model_tools._emit_post_tool_call_hook(
        function_name="browser_navigate",
        function_args={"url": secret},
        result=json.dumps({"success": False, "message": secret}),
        session_id="session-1",
        turn_id="turn-1",
        tool_call_id="tool-1",
        duration_ms=9,
    )

    assert len(calls) == 1
    name, payload = calls[0]
    assert name == "capability_event"
    assert payload["capability"] == "tool"
    assert payload["action"] == "browser_navigate"
    assert payload["outcome"] == "failed"
    assert "subject_id" not in payload
    assert payload["session_id"] == "session-1"
    assert payload["turn_id"] == "turn-1"
    assert payload["event_id"] == "tool-1"
    assert payload["duration_ms"] == 9
    assert secret not in repr(payload)
    assert "args" not in payload
    assert "result" not in payload
    assert "error" not in payload


def test_tool_observation_does_not_parse_result_without_any_listener(monkeypatch):
    monkeypatch.setattr(plugin_runtime, "has_hook", lambda _name: False)
    monkeypatch.setattr(
        model_tools,
        "_tool_result_observer_fields",
        lambda _result: pytest.fail("result should not be inspected"),
    )

    model_tools._emit_post_tool_call_hook(
        function_name="read_file",
        function_args={"path": "private"},
        result="not-json-and-potentially-large",
    )


@pytest.mark.parametrize(
    "result",
    [
        '{"success": false, "message": "bounded failure"}',
        '{"error": "bounded failure"}',
    ],
)
def test_capability_only_listener_detects_small_error_envelopes(monkeypatch, result):
    payloads: list[dict] = []
    monkeypatch.setattr(
        plugin_runtime, "has_hook", lambda name: name == "capability_event"
    )
    monkeypatch.setattr(
        plugin_runtime,
        "invoke_hook",
        lambda _name, **payload: payloads.append(payload) or [],
    )

    model_tools._emit_post_tool_call_hook(
        function_name="browser_navigate",
        function_args={},
        result=result,
        tool_call_id="tool-failed",
    )

    assert payloads[0]["outcome"] == "failed"


def test_capability_only_listener_never_json_parses_large_result(monkeypatch):
    payloads: list[dict] = []
    monkeypatch.setattr(
        plugin_runtime, "has_hook", lambda name: name == "capability_event"
    )
    monkeypatch.setattr(
        plugin_runtime,
        "invoke_hook",
        lambda _name, **payload: payloads.append(payload) or [],
    )
    monkeypatch.setattr(
        model_tools.json,
        "loads",
        lambda _value: pytest.fail("large capability result must not be JSON parsed"),
    )
    result = '{"ok": true, "content": "' + ("x" * 100_000) + '"}'

    model_tools._emit_post_tool_call_hook(
        function_name="read_file",
        function_args={},
        result=result,
        tool_call_id="tool-large",
    )

    assert payloads[0]["outcome"] == "success"


def test_rich_tool_listener_retains_precise_result_parser(monkeypatch):
    observed: list[str] = []
    rich_payloads: list[dict] = []
    result = '{"content": "' + ("x" * 100_000) + '"}'

    monkeypatch.setattr(
        plugin_runtime,
        "has_hook",
        lambda name: name in {"capability_event", "post_tool_call"},
    )
    monkeypatch.setattr(
        model_tools,
        "_tool_result_observer_fields",
        lambda value: observed.append(value) or ("ok", None, None),
    )
    monkeypatch.setattr(
        plugin_runtime,
        "invoke_hook",
        lambda name, **payload: rich_payloads.append({"name": name, **payload}) or [],
    )

    model_tools._emit_post_tool_call_hook(
        function_name="read_file",
        function_args={"path": "private"},
        result=result,
        tool_call_id="tool-rich",
    )

    assert observed == [result]
    assert any(payload["name"] == "post_tool_call" for payload in rich_payloads)
