from __future__ import annotations

from dataclasses import dataclass

from fabric_link import controller_manager
from tui_gateway import server
from tui_gateway.auth_context import AuthKind, WSAuthContext, make_authenticated_ws_context


class LocalTransport:
    peer_host = "127.0.0.1"

    def write(self, _obj: dict) -> bool:
        return True

    def close(self) -> None:
        return None


class RemoteTransport(LocalTransport):
    peer_host = "203.0.113.8"


def _auth_context(auth_kind: AuthKind = "legacy_token") -> WSAuthContext:
    return make_authenticated_ws_context(
        auth_kind=auth_kind,
        gateway_identity="link-controller-test",
        principal_identity=(
            "dashboard-user" if auth_kind == "provider_cookie" else None
        ),
    )


def _call(
    method: str,
    params: dict,
    *,
    transport=None,
    auth_context: WSAuthContext | None = None,
) -> dict:
    token = server.bind_transport(transport or LocalTransport())
    auth_token = server.bind_auth_context(auth_context or _auth_context())
    try:
        response = server.handle_request({
            "jsonrpc": "2.0",
            "id": "link-test",
            "method": method,
            "params": params,
        })
    finally:
        server.reset_auth_context(auth_token)
        server.reset_transport(token)
    assert response is not None
    return response


def test_link_controller_rpc_is_local_operator_only(monkeypatch) -> None:
    called = False

    def fake_list():
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(controller_manager, "list_controller_profiles", fake_list)
    response = _call(
        "link.controller.list",
        {},
        transport=RemoteTransport(),
    )

    assert response["error"]["code"] == 4031
    assert called is False


def test_link_controller_rpc_rejects_provider_auth_behind_loopback_proxy(
    monkeypatch,
) -> None:
    called = False

    def fake_list():
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(controller_manager, "list_controller_profiles", fake_list)
    response = _call(
        "link.controller.list",
        {},
        transport=LocalTransport(),
        auth_context=_auth_context("provider_cookie"),
    )

    assert response["error"]["code"] == 4031
    assert called is False


@dataclass(frozen=True)
class FakeStart:
    controller_id: str = "controller_1234567890"

    def to_dict(self):
        return {
            "controller_id": self.controller_id,
            "machine_fingerprint": "ABCD-EFGH",
            "short_auth_string": "word-word-1234",
            "expires_at": 1_784_840_300,
        }


def test_link_controller_pairing_rpc_splits_compare_from_wait(monkeypatch) -> None:
    monkeypatch.setattr(
        controller_manager,
        "start_controller_pairing",
        lambda **_kwargs: FakeStart(),
    )
    monkeypatch.setattr(
        controller_manager,
        "finish_controller_pairing",
        lambda **_kwargs: {
            "id": "controller_1234567890",
            "status": "active",
            "grants": ["observe", "dispatch"],
        },
    )

    started = _call(
        "link.controller.enrollment.start",
        {
            "pairing_url": "https://relay.example/link/pair#pair=opaque",
            "label": "My Desktop",
            "grants": ["observe", "dispatch"],
        },
    )
    finished = _call(
        "link.controller.enrollment.finish",
        {
            "controller_id": "controller_1234567890",
            "timeout_seconds": 60,
        },
    )

    assert started["result"]["short_auth_string"] == "word-word-1234"
    assert finished["result"]["status"] == "active"


def test_link_controller_invoke_rejects_unreviewed_method_before_transport(
    monkeypatch,
) -> None:
    called = False

    def fake_invoke(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(controller_manager, "invoke_controller", fake_invoke)
    response = _call(
        "link.controller.invoke",
        {
            "controller_id": "controller_1234567890",
            "method": "config.credentials",
            "params": {},
        },
    )

    assert response["error"]["code"] == 4030
    assert called is False


def test_link_controller_dispatch_returns_one_durable_receipt(monkeypatch) -> None:
    monkeypatch.setattr(
        controller_manager,
        "dispatch_controller_work",
        lambda **kwargs: {
            "job": {
                "id": "job-1",
                "title": kwargs["title"],
                "status": "queued",
            }
        },
    )
    response = _call(
        "link.controller.dispatch",
        {
            "controller_id": "controller_1234567890",
            "prompt": "Run the release checks",
            "title": "Release checks",
            "idempotency_key": "desktop-123",
        },
    )

    assert response["result"]["response"]["job"] == {
        "id": "job-1",
        "title": "Release checks",
        "status": "queued",
    }
