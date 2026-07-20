from __future__ import annotations

import re

import pytest

from tui_gateway.auth_context import make_authenticated_ws_context


def test_context_projects_verified_identity_without_retaining_raw_subject() -> None:
    raw_subject = "provider:account-owner@example.test"

    context = make_authenticated_ws_context(
        auth_kind="provider_cookie",
        gateway_identity="dashboard:gateway-a",
        principal_identity=raw_subject,
    )

    assert context.auth_kind == "provider_cookie"
    assert context.device_id is None
    assert re.fullmatch(r"pri_[0-9a-f]{32}", context.principal_id or "")
    assert re.fullmatch(r"gwy_[0-9a-f]{32}", context.gateway_scope)
    assert re.fullmatch(r"cor_[0-9a-f]{32}", context.correlation_id)
    assert raw_subject not in repr(context)
    assert raw_subject not in str(context.public_projection())


def test_same_verified_subject_is_stable_for_process_but_scopes_do_not_collide() -> None:
    first = make_authenticated_ws_context(
        auth_kind="provider_cookie",
        gateway_identity="dashboard:one",
        principal_identity="stub:u1",
    )
    second = make_authenticated_ws_context(
        auth_kind="provider_cookie",
        gateway_identity="dashboard:one",
        principal_identity="stub:u1",
    )
    other_scope = make_authenticated_ws_context(
        auth_kind="provider_cookie",
        gateway_identity="dashboard:two",
        principal_identity="stub:u1",
    )

    assert first.principal_id == second.principal_id
    assert first.gateway_scope == second.gateway_scope
    assert first.gateway_scope != other_scope.gateway_scope
    assert first.correlation_id != second.correlation_id


def test_each_dispatch_receives_fresh_correlation_with_unchanged_identity() -> None:
    context = make_authenticated_ws_context(
        auth_kind="legacy_token",
        gateway_identity="dashboard:loopback",
    )

    request_context = context.for_request()

    assert request_context.auth_kind == context.auth_kind
    assert request_context.principal_id == context.principal_id
    assert request_context.gateway_scope == context.gateway_scope
    assert request_context.correlation_id != context.correlation_id


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "auth_kind": "spoofed",
                "gateway_identity": "dashboard:one",
            },
            "unsupported",
        ),
        (
            {
                "auth_kind": "legacy_token",
                "gateway_identity": "",
            },
            "gateway identity",
        ),
    ],
)
def test_context_constructor_rejects_invalid_server_inputs(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        make_authenticated_ws_context(**kwargs)
