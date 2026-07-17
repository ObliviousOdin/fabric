"""Gateway contract for the Desktop browser live-view status RPC."""

import logging
import sys
import types
from unittest.mock import patch

import pytest

from fabric_constants import (
    get_fabric_home,
    reset_fabric_home_override,
    set_fabric_home_override,
)
from tui_gateway import server


@pytest.fixture(autouse=True)
def _isolate_sessions(monkeypatch):
    original = server._sessions.copy()
    server._sessions.clear()
    yield
    server._sessions.clear()
    server._sessions.update(original)


def test_visual_status_is_pool_routed():
    assert "visual.status" in server._LONG_HANDLERS


def test_visual_frame_is_pool_routed():
    assert "visual.frame" in server._LONG_HANDLERS


def test_visual_status_maps_runtime_sid_to_durable_browser_task(monkeypatch):
    server._sessions["runtime-sid"] = {
        "session_key": "durable-session-key",
        "profile_home": "/tmp/profile-a",
    }
    monkeypatch.setattr(
        server, "_durable_session_key_profile_ambiguous", lambda _key: False
    )
    calls = []

    def status(task_id, *, timeout):
        calls.append((task_id, timeout))
        return {
            "available": True,
            "transport": "gateway_pull",
            "min_interval_ms": 500,
        }

    fake_browser_tool = types.SimpleNamespace(get_browser_stream_status=status)
    with patch.dict(sys.modules, {"tools.browser_tool": fake_browser_tool}):
        response = server.handle_request(
            {
                "id": "rpc-1",
                "method": "visual.status",
                "params": {"session_id": "runtime-sid"},
            }
        )

    assert calls == [("durable-session-key", 2)]
    assert response["result"] == {
        "available": True,
        "transport": "gateway_pull",
        "min_interval_ms": 500,
    }
    assert "durable-session-key" not in response["result"]


def test_visual_status_fails_closed_for_ambiguous_profile(monkeypatch):
    server._sessions["runtime-sid"] = {"session_key": "cloned-key"}
    monkeypatch.setattr(
        server, "_durable_session_key_profile_ambiguous", lambda _key: True
    )
    fake_browser_tool = types.SimpleNamespace(
        get_browser_stream_status=lambda *args, **kwargs: pytest.fail(
            "ambiguous session must not inspect process-global browser state"
        )
    )

    with patch.dict(sys.modules, {"tools.browser_tool": fake_browser_tool}):
        response = server.handle_request(
            {
                "id": "rpc-2",
                "method": "visual.status",
                "params": {"session_id": "runtime-sid"},
            }
        )

    assert response["result"] == {
        "available": False,
        "reason": "ambiguous_session_profile",
    }


def test_visual_status_requires_live_runtime_session():
    response = server.handle_request(
        {
            "id": "rpc-3",
            "method": "visual.status",
            "params": {"session_id": "missing-sid"},
        }
    )

    assert response["error"]["code"] == 4007
    assert "session not found" in response["error"]["message"]


def test_visual_status_redacts_helper_failures(monkeypatch, caplog):
    server._sessions["runtime-sid"] = {"session_key": "durable-key"}
    monkeypatch.setattr(
        server, "_durable_session_key_profile_ambiguous", lambda _key: False
    )
    caplog.set_level(logging.WARNING, logger=server.__name__)
    caplog.clear()

    def fail(*_args, **_kwargs):
        raise RuntimeError("wss://provider.example/devtools/browser/secret-token")

    fake_browser_tool = types.SimpleNamespace(get_browser_stream_status=fail)
    with patch.dict(sys.modules, {"tools.browser_tool": fake_browser_tool}):
        response = server.handle_request(
            {
                "id": "rpc-4",
                "method": "visual.status",
                "params": {"session_id": "runtime-sid"},
            }
        )

    assert response["result"] == {
        "available": False,
        "reason": "stream_status_failed",
    }
    assert "secret-token" not in str(response)
    server_records = [
        record for record in caplog.records if record.name == server.__name__
    ]
    assert [record.getMessage() for record in server_records] == [
        "visual.status browser stream inspection failed"
    ]
    assert all(record.exc_info is None for record in server_records)
    assert "secret-token" not in caplog.text


def test_visual_frame_maps_runtime_sid_to_durable_browser_task(monkeypatch):
    server._sessions["runtime-sid"] = {
        "session_key": "durable-session-key",
        "profile_home": "/tmp/profile-a",
    }
    monkeypatch.setattr(
        server, "_durable_session_key_profile_ambiguous", lambda _key: False
    )
    calls = []

    def frame(task_id, *, timeout):
        calls.append((task_id, timeout))
        return {"available": True, "data": "jpeg", "mime_type": "image/jpeg"}

    fake_browser_tool = types.SimpleNamespace(get_browser_stream_frame=frame)
    with patch.dict(sys.modules, {"tools.browser_tool": fake_browser_tool}):
        response = server.handle_request(
            {
                "id": "rpc-frame-1",
                "method": "visual.frame",
                "params": {"session_id": "runtime-sid"},
            }
        )

    assert calls == [("durable-session-key", 2)]
    assert response["result"] == {
        "available": True,
        "data": "jpeg",
        "mime_type": "image/jpeg",
    }
    assert "durable-session-key" not in response["result"]


def test_visual_frame_fails_closed_for_ambiguous_profile(monkeypatch):
    server._sessions["runtime-sid"] = {"session_key": "cloned-key"}
    monkeypatch.setattr(
        server, "_durable_session_key_profile_ambiguous", lambda _key: True
    )
    fake_browser_tool = types.SimpleNamespace(
        get_browser_stream_frame=lambda *args, **kwargs: pytest.fail(
            "ambiguous session must not inspect process-global browser state"
        )
    )

    with patch.dict(sys.modules, {"tools.browser_tool": fake_browser_tool}):
        response = server.handle_request(
            {
                "id": "rpc-frame-2",
                "method": "visual.frame",
                "params": {"session_id": "runtime-sid"},
            }
        )

    assert response["result"] == {
        "available": False,
        "reason": "ambiguous_session_profile",
    }


def test_visual_frame_redacts_helper_failures(monkeypatch, caplog):
    server._sessions["runtime-sid"] = {"session_key": "durable-key"}
    monkeypatch.setattr(
        server, "_durable_session_key_profile_ambiguous", lambda _key: False
    )
    caplog.set_level(logging.WARNING, logger=server.__name__)
    caplog.clear()

    def fail(*_args, **_kwargs):
        raise RuntimeError("wss://provider.example/devtools/browser/secret-token")

    fake_browser_tool = types.SimpleNamespace(get_browser_stream_frame=fail)
    with patch.dict(sys.modules, {"tools.browser_tool": fake_browser_tool}):
        response = server.handle_request(
            {
                "id": "rpc-frame-3",
                "method": "visual.frame",
                "params": {"session_id": "runtime-sid"},
            }
        )

    assert response["result"] == {
        "available": False,
        "reason": "frame_capture_failed",
    }
    assert "secret-token" not in str(response)
    frame_records = [
        record
        for record in caplog.records
        if record.name == server.__name__
        and record.getMessage() == "visual.frame browser capture failed"
    ]
    assert len(frame_records) == 1
    assert frame_records[0].exc_info is None
    assert "secret-token" not in caplog.text


@pytest.mark.parametrize(
    ("method_name", "helper_name", "helper_result"),
    [
        (
            "visual.status",
            "get_browser_stream_status",
            {"available": True, "transport": "gateway_pull"},
        ),
        (
            "visual.frame",
            "get_browser_stream_frame",
            {"available": True, "data": "jpeg", "mime_type": "image/jpeg"},
        ),
    ],
)
def test_visual_polling_binds_secondary_home_without_resolving_credentials(
    monkeypatch,
    tmp_path,
    method_name,
    helper_name,
    helper_result,
):
    """High-frequency visual polling needs config scope, never vault scope."""
    profile_home = tmp_path / "secondary"
    profile_home.mkdir()
    outer_home = tmp_path / "unrelated"
    outer_home.mkdir()
    server._sessions["runtime-sid"] = {
        "session_key": "durable-secondary-key",
        "profile_home": str(profile_home),
    }
    monkeypatch.setattr(
        server, "_durable_session_key_profile_ambiguous", lambda _key: False
    )

    def forbidden_runtime_scope(*_args, **_kwargs):
        pytest.fail("visual polling must not reconstruct the profile secret scope")

    monkeypatch.setattr(server, "_set_profile_runtime_scope", forbidden_runtime_scope)
    from agent import secret_scope

    monkeypatch.setattr(
        secret_scope, "build_profile_secret_scope", forbidden_runtime_scope
    )

    def helper(task_id, *, timeout):
        assert task_id == "durable-secondary-key"
        assert timeout == 2
        assert get_fabric_home() == profile_home
        return helper_result

    fake_browser_tool = types.SimpleNamespace(**{helper_name: helper})
    outer_token = set_fabric_home_override(outer_home)
    try:
        with patch.dict(sys.modules, {"tools.browser_tool": fake_browser_tool}):
            response = server.handle_request(
                {
                    "id": "rpc-secondary-profile",
                    "method": method_name,
                    "params": {"session_id": "runtime-sid"},
                }
            )
        assert get_fabric_home() == outer_home
    finally:
        reset_fabric_home_override(outer_token)

    assert response["result"] == helper_result


def test_visual_polling_rebinds_launch_home_from_foreign_context(monkeypatch, tmp_path):
    server._sessions["runtime-sid"] = {"session_key": "launch-key"}
    monkeypatch.setattr(
        server, "_durable_session_key_profile_ambiguous", lambda _key: False
    )
    foreign_home = tmp_path / "foreign"
    foreign_home.mkdir()

    def status(_task_id, *, timeout):
        assert timeout == 2
        assert get_fabric_home() == server._fabric_home
        return {"available": False, "reason": "test"}

    fake_browser_tool = types.SimpleNamespace(get_browser_stream_status=status)
    outer_token = set_fabric_home_override(foreign_home)
    try:
        with patch.dict(sys.modules, {"tools.browser_tool": fake_browser_tool}):
            response = server.handle_request(
                {
                    "id": "rpc-launch-profile",
                    "method": "visual.status",
                    "params": {"session_id": "runtime-sid"},
                }
            )
        assert get_fabric_home() == foreign_home
    finally:
        reset_fabric_home_override(outer_token)

    assert response["result"] == {"available": False, "reason": "test"}


@pytest.mark.parametrize(
    ("method_name", "helper_name"),
    [
        ("visual.status", "get_browser_stream_status"),
        ("visual.frame", "get_browser_stream_frame"),
    ],
)
def test_visual_requests_do_not_take_ownership_of_chat_transport(
    monkeypatch, method_name, helper_name
):
    """The dedicated frame socket must never steal model-event delivery."""
    chat_transport = object()
    visual_transport = object()
    server._sessions["runtime-sid"] = {
        "session_key": "durable-key",
        "transport": chat_transport,
    }
    monkeypatch.setattr(
        server, "_durable_session_key_profile_ambiguous", lambda _key: False
    )
    helper = lambda *_args, **_kwargs: {"available": False, "reason": "test"}
    fake_browser_tool = types.SimpleNamespace(**{helper_name: helper})

    token = server.bind_transport(visual_transport)
    try:
        with patch.dict(sys.modules, {"tools.browser_tool": fake_browser_tool}):
            response = server.handle_request(
                {
                    "id": "rpc-transport",
                    "method": method_name,
                    "params": {"session_id": "runtime-sid"},
                }
            )
    finally:
        server.reset_transport(token)

    assert response["result"] == {"available": False, "reason": "test"}
    assert server._sessions["runtime-sid"]["transport"] is chat_transport
