from __future__ import annotations

import threading

from tui_gateway import server
from tui_gateway.auth_context import make_authenticated_ws_context
from tui_gateway.transport import current_auth_context


class _RecordingTransport:
    def __init__(self) -> None:
        self.frames: list[dict] = []
        self.wrote = threading.Event()

    def write(self, obj: dict) -> bool:
        self.frames.append(obj)
        self.wrote.set()
        return True

    def close(self) -> None:
        return None


def _context():
    return make_authenticated_ws_context(
        auth_kind="provider_cookie",
        gateway_identity="dashboard:test",
        principal_identity="stub:user-42",
    )


def test_connection_context_is_server_derived_and_ignores_spoofed_params() -> None:
    context = _context()

    response = server.dispatch(
        {
            "jsonrpc": "2.0",
            "id": "context",
            "method": "connection.context",
            "params": {
                "auth_kind": "device",
                "principal_id": "attacker-controlled",
                "device_id": "attacker-controlled",
                "gateway_scope": "attacker-controlled",
                "correlation_id": "attacker-controlled",
            },
        },
        auth_context=context,
    )

    assert response is not None
    payload = response["result"]
    assert payload == context.public_projection()
    assert "attacker-controlled" not in str(payload)
    assert current_auth_context() is None


def test_connection_context_is_truthful_without_verified_websocket_auth() -> None:
    response = server.dispatch(
        {"jsonrpc": "2.0", "id": "context", "method": "connection.context"}
    )

    assert response is not None
    assert response["result"] == {
        "authenticated": False,
        "auth_kind": "unavailable",
        "principal_id": None,
        "device_id": None,
        "gateway_scope": None,
        "correlation_id": None,
        "credential_state": "unavailable",
        "recovery": "Connect through an authenticated gateway.",
    }


def test_long_handler_receives_context_copied_from_dispatch(monkeypatch) -> None:
    observed = []
    method_name = "test.auth-context-long"
    transport = _RecordingTransport()
    context = _context()

    def handler(rid, params):
        del params
        observed.append(current_auth_context())
        return {"jsonrpc": "2.0", "id": rid, "result": {"ok": True}}

    monkeypatch.setitem(server._methods, method_name, handler)
    monkeypatch.setattr(server, "_LONG_HANDLERS", frozenset({method_name}))

    assert (
        server.dispatch(
            {"jsonrpc": "2.0", "id": "long", "method": method_name},
            transport=transport,
            auth_context=context,
        )
        is None
    )
    assert transport.wrote.wait(timeout=5)
    assert observed == [context]
    assert transport.frames == [{"jsonrpc": "2.0", "id": "long", "result": {"ok": True}}]
    assert current_auth_context() is None
