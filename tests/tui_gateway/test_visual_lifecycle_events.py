from __future__ import annotations

import json

from tui_gateway import server, visual_events


def _capture_events(monkeypatch):
    events: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        server,
        "_emit",
        lambda event_type, sid, payload: events.append((event_type, sid, payload)),
    )
    return events


def _session(monkeypatch, sid: str, mode: str) -> None:
    monkeypatch.setitem(
        server._sessions,
        sid,
        {
            "edit_snapshots": {},
            "tool_progress_mode": mode,
            "tool_started_at": {},
        },
    )


def test_visual_events_survive_disabled_tool_progress(monkeypatch):
    sid = "visual-progress-off"
    events = _capture_events(monkeypatch)
    _session(monkeypatch, sid, "off")

    server._on_tool_start(
        sid,
        "browser-1",
        "browser_navigate",
        {"url": "https://example.com"},
    )
    server._on_tool_complete(
        sid,
        "browser-1",
        "browser_navigate",
        {"url": "https://example.com"},
        '{"title":"Example","url":"https://example.com"}',
    )

    assert [event[0] for event in events] == ["visual.start", "visual.complete"]
    assert events[0][1] == sid
    assert events[0][2]["tool_id"] == "browser-1"
    assert events[0][2]["name"] == "browser_navigate"
    assert events[0][2]["args"] == {"url": "https://example.com"}
    assert events[0][2]["status"] == "running"
    assert events[1][2]["result"]["title"] == "Example"
    assert events[1][2]["status"] == "complete"
    assert "args" not in events[1][2]


def test_visual_events_do_not_duplicate_enabled_tool_events(monkeypatch):
    sid = "visual-progress-on"
    events = _capture_events(monkeypatch)
    _session(monkeypatch, sid, "all")

    server._on_tool_start(sid, "desktop-1", "computer_use", {"action": "screenshot"})
    server._on_tool_complete(
        sid,
        "desktop-1",
        "computer_use",
        {"action": "screenshot"},
        '{"success":true}',
    )

    assert [event[0] for event in events] == ["tool.start", "tool.complete"]


def test_nonvisual_tools_stay_silent_when_tool_progress_is_disabled(monkeypatch):
    sid = "terminal-progress-off"
    events = _capture_events(monkeypatch)
    _session(monkeypatch, sid, "off")

    server._on_tool_start(sid, "terminal-1", "terminal", {"command": "pwd"})
    server._on_tool_complete(
        sid,
        "terminal-1",
        "terminal",
        {"command": "pwd"},
        '{"success":true}',
    )

    assert events == []


def test_visual_fallback_never_emits_typed_args_or_raw_browser_results(monkeypatch):
    sid = "visual-secret-boundary"
    events = _capture_events(monkeypatch)
    _session(monkeypatch, sid, "off")
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"

    server._on_tool_start(
        sid,
        "browser-secret",
        "browser_type",
        {"ref": "e12", "text": secret},
    )

    huge_result = json.dumps(
        {
            "success": True,
            "title": "Example",
            "url": "https://example.com",
            "snapshot": "x"
            * (visual_events._LIVE_VIEW_RESULT_PARSE_MAX_CHARS + 1),
            "raw_secret": secret,
        }
    )
    real_loads = json.loads
    parsed_sizes: list[int] = []

    def bounded_loads(value, *args, **kwargs):
        if isinstance(value, str):
            parsed_sizes.append(len(value))
            assert len(value) <= visual_events._LIVE_VIEW_RESULT_PARSE_MAX_CHARS
        return real_loads(value, *args, **kwargs)

    monkeypatch.setattr(visual_events.json, "loads", bounded_loads)
    server._on_tool_complete(
        sid,
        "browser-secret",
        "browser_type",
        {"ref": "e12", "text": secret},
        huge_result,
    )

    start_payload = events[0][2]
    complete_payload = events[1][2]
    assert start_payload == {
        "tool_id": "browser-secret",
        "name": "browser_type",
        "status": "running",
    }
    assert complete_payload["status"] == "complete"
    assert complete_payload["title"] == "Example"
    assert complete_payload["url"] == "https://example.com"
    assert complete_payload["result"] == {
        "status": "complete",
        "success": True,
        "title": "Example",
        "url": "https://example.com",
    }
    assert "args" not in complete_payload
    assert "snapshot" not in repr(complete_payload)
    assert secret not in repr(events)
    assert len(json.dumps(complete_payload)) < 1_000
    assert parsed_sizes


def test_visual_complete_emits_only_one_accepted_capped_computer_use_image(
    monkeypatch,
):
    sid = "visual-computer-image"
    events = _capture_events(monkeypatch)
    _session(monkeypatch, sid, "off")
    monkeypatch.setattr(visual_events, "_LIVE_VIEW_IMAGE_MAX_CHARS", 64)

    accepted = "data:image/jpeg;base64,AAAA"
    second = "data:image/png;base64,BBBB"
    oversized = "data:image/png;base64," + ("C" * 80)
    result = {
        "_multimodal": True,
        "content": [
            {"type": "text", "text": "secret desktop transcript"},
            {"type": "image_url", "image_url": {"url": oversized}},
            {"type": "image_url", "image_url": {"url": accepted}},
            {"type": "image_url", "image_url": {"url": second}},
        ],
        "meta": {
            "app": "System Settings",
            "window_title": "Settings",
            "raw_snapshot": "do not emit",
        },
        "raw_secret": "secret-value",
    }

    server._on_tool_complete(
        sid,
        "computer-1",
        "computer_use",
        {"action": "type", "text": "secret-value"},
        result,
    )

    payload = events[0][2]
    assert payload["title"] == "Settings"
    assert payload["app"] == "System Settings"
    assert payload["window_title"] == "Settings"
    assert payload["result"] == {
        "status": "complete",
        "success": True,
        "title": "Settings",
        "app": "System Settings",
        "window_title": "Settings",
        "content": [
            {"type": "image_url", "image_url": {"url": accepted}},
        ],
    }
    assert "args" not in payload
    assert second not in repr(payload)
    assert oversized not in repr(payload)
    assert "raw_snapshot" not in repr(payload)
    assert "secret-value" not in repr(payload)


def test_visual_complete_extracts_image_from_large_serialized_computer_result(
    monkeypatch,
):
    sid = "visual-computer-serialized-image"
    events = _capture_events(monkeypatch)
    _session(monkeypatch, sid, "off")
    monkeypatch.setattr(visual_events, "_LIVE_VIEW_IMAGE_MAX_CHARS", 128)
    accepted = "data:image/png;base64,QUJDRA=="
    result = json.dumps(
        {
            "_multimodal": True,
            "content": [
                {"type": "text", "text": "x" * 70_000},
                {"type": "image_url", "image_url": {"url": accepted}},
            ],
            "raw_snapshot": "must not cross the DTO boundary",
        }
    )
    assert len(result) > visual_events._LIVE_VIEW_RESULT_PARSE_MAX_CHARS

    server._on_tool_complete(
        sid,
        "computer-serialized",
        "computer_use",
        {"action": "screenshot"},
        result,
    )

    payload = events[0][2]
    assert payload["result"] == {
        "status": "complete",
        "success": True,
        "content": [
            {"type": "image_url", "image_url": {"url": accepted}},
        ],
    }
    assert len(json.dumps(payload)) < 1_000
    assert "raw_snapshot" not in repr(payload)


def test_visual_complete_reduces_failures_to_status_without_error_text(monkeypatch):
    sid = "visual-error-boundary"
    events = _capture_events(monkeypatch)
    _session(monkeypatch, sid, "off")

    server._on_tool_complete(
        sid,
        "browser-error",
        "browser_click",
        {"ref": "secret-ref"},
        json.dumps(
            {
                "success": False,
                "error": "credential sk-proj-abcdefghijklmnopqrstuvwxyz123456 failed",
            }
        ),
    )

    payload = events[0][2]
    assert payload == {
        "tool_id": "browser-error",
        "name": "browser_click",
        "status": "error",
        "result": {"status": "error", "success": False},
    }
