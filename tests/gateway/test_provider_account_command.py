"""Fail-closed gateway `/account` status and managed-request lifecycle."""

from __future__ import annotations

import builtins

import pytest

from fabric_constants import reset_fabric_home_override, set_fabric_home_override
from fabric_cli import provider_accounts
from fabric_cli.commands import (
    ACTIVE_SESSION_BYPASS_COMMANDS,
    GATEWAY_KNOWN_COMMANDS,
    gateway_help_lines,
    resolve_command,
)
from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent, MessageType
from gateway.run import GatewayRunner
from gateway.session import SessionSource


def _config(*, admins=(), group_admins=(), user_commands=()) -> GatewayConfig:
    return GatewayConfig(
        platforms={
            Platform.TELEGRAM: PlatformConfig(
                enabled=True,
                extra={
                    "allow_admin_from": list(admins),
                    "group_allow_admin_from": list(group_admins),
                    "user_allowed_commands": list(user_commands),
                },
            )
        }
    )


def _runner(config: GatewayConfig) -> GatewayRunner:
    runner = object.__new__(GatewayRunner)
    runner.config = config
    return runner


def _event(
    text: str,
    *,
    user_id: str = "user",
    chat_type: str = "dm",
) -> MessageEvent:
    return MessageEvent(
        text=text,
        message_type=MessageType.TEXT,
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id="account-chat",
            chat_type=chat_type,
            user_id=user_id,
        ),
    )


@pytest.fixture()
def account_home(tmp_path):
    home = tmp_path / "profile"
    home.mkdir()
    token = set_fabric_home_override(home)
    try:
        yield home
    finally:
        reset_fabric_home_override(token)


def _guard_provider_imports(monkeypatch):
    real_import = builtins.__import__
    calls = []

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        requested = {str(item) for item in (fromlist or ())}
        if name == "fabric_cli" and requested & {
            "provider_account_views",
            "provider_accounts",
        }:
            calls.append((name, tuple(fromlist or ())))
            raise AssertionError("provider account domain imported before authorization")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded)
    return calls


def test_account_command_is_registry_derived_for_gateway_only():
    command = resolve_command("account")

    assert command is not None and command.gateway_only is True
    assert command.subcommands == (
        "status",
        "request",
        "handoff",
        "cancel",
        "acknowledge",
        "reject",
    )
    assert "account" in GATEWAY_KNOWN_COMMANDS
    assert "account" in ACTIVE_SESSION_BYPASS_COMMANDS
    assert any(line.startswith("`/account ") for line in gateway_help_lines())


@pytest.mark.asyncio
async def test_status_is_minimal_and_does_not_expose_handoff_or_ceremony_data(
    account_home,
):
    result = await _runner(_config())._handle_account_command(_event("/account"))

    assert "ChatGPT subscription" in result
    assert "xAI Grok subscription" in result
    assert result.count("Ownership: not selected") == 2
    assert "mailto:" not in result
    assert "personal@example.invalid" not in result
    for forbidden in (
        "access_token",
        "device_code",
        "refresh_token",
        "session_id",
        "user_code",
    ):
        assert forbidden not in result


@pytest.mark.asyncio
async def test_mutation_defaults_to_deny_before_provider_domain_import(
    account_home,
    monkeypatch,
):
    calls = _guard_provider_imports(monkeypatch)

    result = await _runner(_config())._handle_account_command(
        _event("/account request openai-codex Lobby Account")
    )

    assert "require an explicit admin policy" in result
    assert "`allow_admin_from` for DMs" in result
    assert calls == []


@pytest.mark.asyncio
async def test_non_admin_remains_denied_even_when_account_status_is_allowlisted(
    account_home,
):
    runner = _runner(_config(admins=("admin",), user_commands=("account",)))

    result = await runner._handle_account_command(
        _event("/account request openai-codex Lobby Account", user_id="member")
    )

    assert "require an explicit admin policy" in result
    assert provider_accounts.get_account_snapshot(
        home=account_home,
        provider_id="openai-codex",
    ).desired_ownership == "unselected"


@pytest.mark.asyncio
async def test_dm_admin_is_not_implicitly_a_group_account_admin(account_home):
    runner = _runner(_config(admins=("admin",)))

    result = await runner._handle_account_command(
        _event(
            "/account request openai-codex Group Account",
            user_id="admin",
            chat_type="group",
        )
    )

    assert "require an explicit admin policy" in result
    assert "`group_allow_admin_from` for groups" in result
    assert provider_accounts.get_account_snapshot(
        home=account_home,
        provider_id="openai-codex",
    ).desired_ownership == "unselected"


@pytest.mark.asyncio
async def test_explicit_group_admin_can_create_only_the_group_scoped_request(
    account_home,
):
    runner = _runner(_config(group_admins=("group-admin",)))

    created = await runner._handle_account_command(
        _event(
            "/account request xai-oauth Group Account",
            user_id="group-admin",
            chat_type="group",
        )
    )
    dm_denied = await runner._handle_account_command(
        _event(
            "/account request openai-codex DM Account",
            user_id="group-admin",
        )
    )

    assert "managed request created (requested)" in created
    assert "require an explicit admin policy" in dm_denied
    assert provider_accounts.get_account_snapshot(
        home=account_home,
        provider_id="xai-oauth",
    ).desired_ownership == "fabric_managed"
    assert provider_accounts.get_account_snapshot(
        home=account_home,
        provider_id="openai-codex",
    ).desired_ownership == "unselected"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verb",
    ["oauth", "personal", "poll", "repair", "restart", "start", "submit", "takeover"],
)
async def test_ceremony_and_repair_verbs_fail_before_domain_import(
    account_home,
    monkeypatch,
    verb,
):
    calls = _guard_provider_imports(monkeypatch)

    result = await _runner(_config(admins=("admin",)))._handle_account_command(
        _event(f"/account {verb} openai-codex", user_id="admin")
    )

    assert "not available in messaging gateways" in result
    assert "never send an OAuth code in chat" in result
    assert calls == []


@pytest.mark.asyncio
async def test_gateway_rejects_target_profile_before_domain_import(
    account_home,
    monkeypatch,
):
    calls = _guard_provider_imports(monkeypatch)

    result = await _runner(_config(admins=("admin",)))._handle_account_command(
        _event(
            "/account request openai-codex Lobby --profile other",
            user_id="admin",
        )
    )

    assert result == "Gateway account actions are confined to the running profile."
    assert calls == []


@pytest.mark.asyncio
async def test_admin_request_and_handoff_are_local_only_without_remote_delivery(
    account_home,
):
    runner = _runner(_config(admins=("admin",)))

    created = await runner._handle_account_command(
        _event(
            "/account request openai-codex Front Desk Account",
            user_id="admin",
        )
    )
    assert "managed request created (requested)" in created
    assert "No remote handoff is configured" in created
    assert "nothing was sent" in created
    assert "mailto:" not in created
    assert "No OAuth code" in created

    snapshot = provider_accounts.get_account_snapshot(
        home=account_home,
        provider_id="openai-codex",
    )
    assert snapshot.active_request is not None
    assert snapshot.active_request.handoff_state == "offered"

    offered_again = await runner._handle_account_command(
        _event("/account handoff chatgpt", user_id="admin")
    )
    assert "managed request already active" in offered_again
    assert provider_accounts.get_account_snapshot(
        home=account_home,
        provider_id="openai-codex",
    ).active_request.handoff_state == "offered"

    status = await runner._handle_account_command(
        _event("/account status openai", user_id="member")
    )
    assert "Managed request: requested" in status
    assert "Remote handoff: not configured" in status
    assert "request is local state only" in status
    assert "Front Desk Account" not in status
    assert "par_" not in status
    assert "mailto:" not in status


@pytest.mark.asyncio
async def test_admin_cancel_acknowledge_and_reject_use_local_operator_provenance(
    account_home,
):
    runner = _runner(_config(admins=("admin",)))

    await runner._handle_account_command(
        _event("/account request openai-codex Cancel Me", user_id="admin")
    )
    cancelled = await runner._handle_account_command(
        _event("/account cancel openai-codex", user_id="admin")
    )
    assert cancelled.endswith("managed request cancelled locally.")

    await runner._handle_account_command(
        _event("/account request xai-oauth Review Me", user_id="admin")
    )
    acknowledged = await runner._handle_account_command(
        _event("/account acknowledge grok", user_id="admin")
    )
    assert "local-operator awaiting assertion" in acknowledged
    assert "not proof of a remote approval" in acknowledged
    awaiting = provider_accounts.get_account_snapshot(
        home=account_home,
        provider_id="xai-oauth",
    )
    assert awaiting.active_request is not None
    assert awaiting.active_request.status == "awaiting"
    assert awaiting.active_request.decision_source == "local_operator"

    rejected = await runner._handle_account_command(
        _event("/account reject xai", user_id="admin")
    )
    assert "local-operator rejection" in rejected
    final = provider_accounts.get_account_snapshot(
        home=account_home,
        provider_id="xai-oauth",
    )
    assert final.active_request is None
    assert final.requests[-1].status == "rejected"
    assert final.requests[-1].decision_source == "local_operator"


@pytest.mark.asyncio
async def test_corrupt_state_returns_fixed_error_without_echo(account_home):
    sentinel = "secret-device-code-sentinel"
    (account_home / provider_accounts.STATE_FILENAME).write_text(
        "{\"device_code\": \"" + sentinel + "\"}",
        encoding="utf-8",
    )

    result = await _runner(_config())._handle_account_command(
        _event("/account status openai-codex")
    )

    assert result == "Provider-account state needs local repair or upgrade."
    assert sentinel not in result
