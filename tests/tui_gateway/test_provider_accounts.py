"""Typed, profile-scoped provider-account JSON-RPC contract tests."""

from __future__ import annotations

import json

import pytest

from fabric_constants import reset_fabric_home_override, set_fabric_home_override
from tui_gateway import server


@pytest.fixture()
def account_home(tmp_path):
    home = tmp_path / "profile"
    home.mkdir()
    token = set_fabric_home_override(home)
    try:
        yield home
    finally:
        reset_fabric_home_override(token)


def _call(method: str, params: dict | None = None) -> dict:
    return server.handle_request({
        "jsonrpc": "2.0",
        "id": method,
        "method": method,
        "params": params or {},
    })


def test_provider_account_rpc_methods_are_offloaded(account_home):
    expected = {
        "provider.accounts.acknowledge",
        "provider.accounts.cancel",
        "provider.accounts.get",
        "provider.accounts.list",
        "provider.accounts.record_handoff",
        "provider.accounts.reject",
        "provider.accounts.request_managed",
    }

    assert expected <= server._LONG_HANDLERS
    assert expected <= set(server._methods)


def test_provider_account_rpc_managed_request_lifecycle_is_shared_and_redacted(
    account_home,
):
    listed = _call("provider.accounts.list")
    assert [row["provider_id"] for row in listed["result"]["accounts"]] == [
        "openai-codex",
        "xai-oauth",
    ]
    assert all(
        row["desired_ownership"] == "unselected" for row in listed["result"]["accounts"]
    )

    initial = _call(
        "provider.accounts.get",
        {"provider_id": "openai-codex"},
    )["result"]
    created = _call(
        "provider.accounts.request_managed",
        {
            "provider_id": "openai-codex",
            "device_label": "Front Desk Fabric",
            "expected_revision": initial["snapshot"]["revision"],
        },
    )["result"]

    assert created["created"] is True
    assert created["snapshot"]["desired_ownership"] == "fabric_managed"
    assert created["snapshot"]["handoff"] is None
    encoded = json.dumps(created, sort_keys=True)
    assert "mailto:" not in encoded
    forbidden = (
        "access_token",
        "api_key",
        "device_code",
        "refresh_token",
        "session_id",
        "user_code",
    )
    assert not any(value in encoded for value in forbidden)

    request_id = created["request"]["request_id"]
    handed_off = _call(
        "provider.accounts.record_handoff",
        {
            "provider_id": "openai-codex",
            "request_id": request_id,
            "expected_revision": created["snapshot"]["revision"],
        },
    )["result"]
    assert handed_off["request"]["handoff_state"] == "launch_attempted_unverified"

    cancelled = _call(
        "provider.accounts.cancel",
        {
            "provider_id": "openai-codex",
            "request_id": request_id,
            "expected_revision": handed_off["snapshot"]["revision"],
        },
    )["result"]
    assert cancelled["request"]["status"] == "cancelled"
    assert cancelled["snapshot"]["handoff"] is None


def test_provider_account_rpc_rejects_extra_or_secret_shaped_params_without_echo(
    account_home,
):
    sentinel = "secret-device-code-sentinel"
    response = _call(
        "provider.accounts.get",
        {
            "provider_id": "openai-codex",
            "device_code": sentinel,
        },
    )

    assert response["error"] == {
        "code": -32602,
        "message": "invalid_input",
        "data": {"code": "invalid_input", "retryable": False},
    }
    assert sentinel not in repr(response)


@pytest.mark.parametrize(
    "scope",
    [
        {"profile": 7},
        {"session_id": ["not", "a", "string"]},
        {"profile": "first", "session_id": "session-1"},
    ],
)
def test_provider_account_rpc_rejects_ambiguous_or_malformed_scope_without_echo(
    account_home,
    scope,
):
    response = _call(
        "provider.accounts.get",
        {"provider_id": "openai-codex", **scope},
    )

    assert response["error"] == {
        "code": -32602,
        "message": "invalid_input",
        "data": {"code": "invalid_input", "retryable": False},
    }
    assert repr(scope) not in repr(response)


@pytest.mark.parametrize(
    "scope",
    [
        {"profile": "secret-profile-selector-sentinel"},
        {"session_id": "secret-session-selector-sentinel"},
    ],
)
def test_provider_account_rpc_redacts_unknown_scope_selectors(account_home, scope):
    response = _call(
        "provider.accounts.get",
        {"provider_id": "openai-codex", **scope},
    )

    assert response["error"] == {
        "code": -32602,
        "message": "invalid_input",
        "data": {"code": "invalid_input", "retryable": False},
    }
    assert not any(value in repr(response) for value in scope.values())


def test_provider_account_rpc_never_resolves_runtime_secrets(
    account_home,
    monkeypatch,
):
    def forbidden_secret_scope(*_args, **_kwargs):
        raise AssertionError("provider-account RPC resolved runtime secrets")

    monkeypatch.setattr(server, "_set_profile_runtime_scope", forbidden_secret_scope)

    response = _call(
        "provider.accounts.get",
        {"provider_id": "openai-codex"},
    )

    assert response["result"]["snapshot"]["provider_id"] == "openai-codex"


def test_provider_account_rpc_maps_stale_revision_to_refreshable_error(account_home):
    response = _call(
        "provider.accounts.request_managed",
        {
            "provider_id": "xai-oauth",
            "device_label": "Workshop Fabric",
            "expected_revision": 42,
        },
    )

    assert response["error"] == {
        "code": -32009,
        "message": "stale_revision",
        "data": {"code": "stale_revision", "retryable": True},
    }


def test_provider_account_rpc_session_scope_does_not_cross_profiles(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    server._sessions["account-first"] = {"profile_home": str(first)}
    server._sessions["account-second"] = {"profile_home": str(second)}
    try:
        initial = _call(
            "provider.accounts.get",
            {
                "provider_id": "openai-codex",
                "session_id": "account-first",
            },
        )["result"]
        _call(
            "provider.accounts.request_managed",
            {
                "provider_id": "openai-codex",
                "device_label": "First Fabric",
                "expected_revision": initial["snapshot"]["revision"],
                "session_id": "account-first",
            },
        )

        first_view = _call(
            "provider.accounts.get",
            {
                "provider_id": "openai-codex",
                "session_id": "account-first",
            },
        )["result"]["snapshot"]
        second_view = _call(
            "provider.accounts.get",
            {
                "provider_id": "openai-codex",
                "session_id": "account-second",
            },
        )["result"]["snapshot"]
    finally:
        server._sessions.pop("account-first", None)
        server._sessions.pop("account-second", None)

    assert first_view["desired_ownership"] == "fabric_managed"
    assert second_view["desired_ownership"] == "unselected"
    assert second_view["requests"] == []
