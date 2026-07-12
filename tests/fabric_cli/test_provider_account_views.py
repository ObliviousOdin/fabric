"""Public provider-account DTO and backend-owned handoff tests."""

from __future__ import annotations

import inspect
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fabric_cli import provider_account_views as views
from fabric_cli import provider_accounts as accounts


NOW = datetime(2026, 7, 11, 18, 0, tzinfo=timezone.utc)


def _create_request(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider_id: str = "openai-codex",
    device_label: str = "front-desk-fabric",
    token_hex: str = "ab" * 12,
) -> accounts.ManagedRequestResult:
    monkeypatch.setattr(accounts, "_utc_now", lambda: NOW)
    monkeypatch.setattr(
        accounts.secrets,
        "token_hex",
        lambda size: token_hex if size == 12 else "ef" * size,
    )
    return accounts.create_managed_request(
        home=home,
        provider_id=provider_id,
        device_label=device_label,
        expected_revision=0,
    )


def test_public_self_hosted_request_has_no_handoff_and_never_persists_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create_request(tmp_path, monkeypatch)
    first = views.serialize_account_result(created)
    state_path = tmp_path / accounts.STATE_FILENAME
    durable_before = state_path.read_bytes()

    reloaded = accounts.get_account_snapshot(
        home=tmp_path,
        provider_id="openai-codex",
    )
    second = views.serialize_account_result(reloaded)

    assert first["snapshot"]["handoff"] is None
    assert second["snapshot"]["handoff"] is None
    assert state_path.read_bytes() == durable_before
    durable_text = durable_before.decode("utf-8")
    assert "mailto:" not in durable_text
    assert "11676741+ObliviousOdin@users.noreply.github.com" not in durable_text
    assert "github.com/ObliviousOdin/fabric/tree/main/website/docs" not in durable_text


@pytest.mark.parametrize(
    ("provider_id", "token_hex"),
    [
        ("openai-codex", "ab" * 12),
        ("xai-oauth", "cd" * 12),
    ],
)
def test_public_self_hosted_request_has_no_remote_handoff_for_each_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
    token_hex: str,
) -> None:
    created = _create_request(
        tmp_path,
        monkeypatch,
        provider_id=provider_id,
        token_hex=token_hex,
    )
    payload = views.serialize_account_result(created)
    snapshot = payload["snapshot"]

    assert snapshot["active_request"]["status"] == "requested"
    assert snapshot["active_request"]["handoff_state"] == "offered"
    assert snapshot["handoff"] is None
    assert "mailto:" not in json.dumps(payload, sort_keys=True)


def test_internal_oauth_owner_path_and_raw_exception_attributes_never_serialize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create_request(tmp_path, monkeypatch)
    sentinel = "FORBIDDEN-CEREMONY-SENTINEL-91f0"
    snapshot = replace(
        created.snapshot,
        oauth_generation=987,
        oauth_lease=accounts.OAuthLease(
            generation=987,
            operation_id=f"pao_{sentinel}",
            store_instance_id=f"pas_{sentinel}",
            ownership_epoch=created.snapshot.ownership_epoch,
            active_request_id_at_start=created.snapshot.active_request_id,
            started_at=f"session_id={sentinel}",
            expires_at=f"access_token={sentinel}",
        ),
        oauth_completion=accounts.OAuthCompletion(
            generation=987,
            operation_id=f"pao_completion_{sentinel}",
            store_instance_id=f"pas_completion_{sentinel}",
            ownership_epoch=created.snapshot.ownership_epoch,
            active_request_id_at_start=created.snapshot.active_request_id,
            completed_at=f"session_id={sentinel}",
            intent_matched=False,
            superseded_request_id=None,
        ),
    )
    object.__setattr__(
        snapshot,
        "flow_owner",
        accounts.ProviderAccountFlowOwner(
            Path(f"/private/{sentinel}"),
            (987, 654),
        ),
    )
    object.__setattr__(
        snapshot,
        "raw_exception",
        RuntimeError(f"refresh_token={sentinel}"),
    )
    for request in snapshot.requests:
        object.__setattr__(request, "user_code", sentinel)
        object.__setattr__(request, "device_code", sentinel)

    encoded = json.dumps(views.serialize_account_result(snapshot), sort_keys=True)

    assert sentinel not in encoded
    for forbidden_key in (
        "oauth_generation",
        "oauth_lease",
        "oauth_completion",
        "operation_id",
        "store_instance_id",
        "flow_owner",
        "canonical_home",
        "raw_exception",
        "user_code",
        "device_code",
        "session_id",
        "access_token",
        "refresh_token",
        "notification_policy_key",
    ):
        assert f'"{forbidden_key}"' not in encoded


def test_empty_and_terminal_snapshots_have_no_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = accounts.get_account_snapshot(
        home=tmp_path,
        provider_id="openai-codex",
    )
    assert views.serialize_account_result(empty)["snapshot"]["handoff"] is None

    created = _create_request(tmp_path, monkeypatch)
    terminal = accounts.transition_request(
        home=tmp_path,
        provider_id="openai-codex",
        request_id=created.request.request_id,
        target="rejected",
        expected_revision=created.snapshot.revision,
        source="local_operator",
    )
    public = views.serialize_account_result(terminal)

    assert public["snapshot"]["handoff"] is None
    assert public["snapshot"]["active_request"] is None
    assert public["request"]["status"] == "rejected"
    assert public["request"]["handoff_state"] == "offered"


def test_all_domain_result_types_share_one_snapshot_serializer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create_request(tmp_path, monkeypatch)
    mutation = accounts.AccountMutationResult(
        snapshot=created.snapshot,
        request=created.request,
    )

    snapshot_view = views.serialize_account_result(created.snapshot)
    mutation_view = views.serialize_account_result(mutation)
    managed_view = views.serialize_account_result(created)

    assert snapshot_view["snapshot"] == mutation_view["snapshot"]
    assert mutation_view["snapshot"] == managed_view["snapshot"]
    assert snapshot_view["request"] is None
    assert snapshot_view["created"] is None
    assert mutation_view["request"] == managed_view["request"]
    assert mutation_view["created"] is None
    assert managed_view["created"] is True
    assert json.loads(json.dumps(managed_view)) == managed_view


def test_repair_result_serializer_is_path_and_state_free() -> None:
    result = accounts.RepairResult(schema_version=1, backup_created=True)

    assert views.serialize_account_repair_result(result) == {
        "repair": {
            "backup_created": True,
            "providers_reset": True,
            "schema_version": 1,
        }
    }

    with pytest.raises(accounts.ProviderAccountError) as exc:
        views.serialize_account_repair_result(
            accounts.RepairResult(schema_version=2, backup_created=True)
        )
    assert exc.value.code is accounts.ProviderAccountErrorCode.INVALID_STATE


def test_mail_content_has_no_client_controlled_parameters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create_request(tmp_path, monkeypatch)
    assert tuple(inspect.signature(views.serialize_account_result).parameters) == (
        "value",
    )

    with pytest.raises(TypeError):
        views.serialize_account_result(
            created,
            recipient="attacker@example.test",
            subject="device_code=secret",
        )


def test_invalid_notification_policy_fails_closed_without_fallback_mail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create_request(tmp_path, monkeypatch)
    bad_request = replace(
        created.request,
        notification_policy_key="client_chosen_recipient",
    )
    bad_snapshot = replace(
        created.snapshot,
        active_request=bad_request,
        requests=(bad_request,),
    )

    with pytest.raises(accounts.ProviderAccountError) as exc:
        views.serialize_account_result(bad_snapshot)

    assert exc.value.code is accounts.ProviderAccountErrorCode.INVALID_STATE
    assert "client_chosen_recipient" not in str(exc.value)


def test_error_transport_table_exact_and_mismatch_is_only_not_found() -> None:
    expected = {
        "invalid_provider": (
            400,
            -32602,
            2,
            False,
            "Correct the allowlisted input.",
        ),
        "invalid_input": (
            400,
            -32602,
            2,
            False,
            "Correct the allowlisted input.",
        ),
        "not_found": (
            404,
            -32044,
            4,
            False,
            "Resource unavailable to this owner.",
        ),
        "not_authorized": (
            403,
            -32003,
            77,
            False,
            "Explicit admin policy does not permit mutation.",
        ),
        "stale_revision": (
            409,
            -32009,
            3,
            True,
            "Refresh the snapshot; do not infer success.",
        ),
        "illegal_transition": (
            409,
            -32009,
            3,
            True,
            "Refresh the snapshot; do not infer success.",
        ),
        "oauth_in_progress": (
            409,
            -32009,
            3,
            True,
            "Refresh the snapshot; do not infer success.",
        ),
        "invalid_state": (
            409,
            -32010,
            5,
            False,
            "Local operator repair or upgrade is required.",
        ),
        "newer_schema": (
            409,
            -32010,
            5,
            False,
            "Local operator repair or upgrade is required.",
        ),
        "path_redirect": (
            409,
            -32010,
            5,
            False,
            "Local operator repair or upgrade is required.",
        ),
        "lock_timeout": (
            503,
            -32053,
            75,
            True,
            "Preserve state and retry later.",
        ),
        "io_unavailable": (
            503,
            -32053,
            75,
            True,
            "Preserve state and retry later.",
        ),
        "commit_uncertain": (
            503,
            -32053,
            75,
            False,
            "Inspect current state before deciding whether to retry.",
        ),
        "runtime_mode_unavailable": (
            503,
            -32054,
            69,
            False,
            "This surface is unavailable in the current mode.",
        ),
    }
    actual = {
        code.value: (
            row.http_status,
            row.jsonrpc_code,
            row.cli_exit_code,
            row.retryable,
            row.client_meaning,
        )
        for code, row in views.PROVIDER_ACCOUNT_ERROR_TRANSPORTS.items()
    }

    assert actual == expected
    assert "ownership_mismatch" not in actual
    assert views.public_error_code("ownership_mismatch") is (
        accounts.ProviderAccountErrorCode.NOT_FOUND
    )
    assert views.serialize_account_error("ownership_mismatch") == {
        "error": {"code": "not_found", "retryable": False}
    }
    assert views.serialize_account_rpc_error_data("ownership_mismatch") == {
        "code": "not_found",
        "retryable": False,
    }


def test_raw_error_text_is_never_used_as_transport_payload() -> None:
    sentinel = "access_token=FORBIDDEN-RAW-EXCEPTION"
    payload = views.serialize_account_error(RuntimeError(sentinel))

    assert payload == {"error": {"code": "invalid_state", "retryable": False}}
    assert sentinel not in json.dumps(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_id", []),
        ("request_id", []),
        ("status", []),
        ("handoff_state", []),
        ("device_label", []),
        ("notification_policy_key", []),
        ("requested_at", []),
        ("updated_at", []),
        ("expires_at", []),
        ("decision_source", []),
        ("decision_reason", []),
    ],
)
def test_forged_request_field_types_are_stable_invalid_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    created = _create_request(tmp_path, monkeypatch)
    forged_request = replace(created.request, **{field: value})
    forged_snapshot = replace(
        created.snapshot,
        active_request=forged_request,
        requests=(forged_request,),
    )

    with pytest.raises(accounts.ProviderAccountError) as exc:
        views.serialize_account_result(forged_snapshot)

    assert exc.value.code is accounts.ProviderAccountErrorCode.INVALID_STATE
    assert str(exc.value) == "invalid_state"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_id", []),
        ("desired_ownership", []),
        ("revision", "1"),
        ("ownership_epoch", -1),
        ("pruned_terminal_count", True),
        ("requests", []),
        ("active_request_id", []),
        ("active_request", object()),
    ],
)
def test_forged_snapshot_field_types_are_stable_invalid_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    created = _create_request(tmp_path, monkeypatch)
    forged = replace(created.snapshot, **{field: value})

    with pytest.raises(accounts.ProviderAccountError) as exc:
        views.serialize_account_result(forged)

    assert exc.value.code is accounts.ProviderAccountErrorCode.INVALID_STATE
    assert str(exc.value) == "invalid_state"


@pytest.mark.parametrize(
    "changes",
    [
        {"requested_at": "not-a-time"},
        {"updated_at": "2026-07-10T18:00:00Z"},
        {"expires_at": "2026-07-19T18:00:00Z"},
        {"updated_at": "2026-07-18T18:00:00Z"},
        {"notification_handoff_at": "2026-07-11T18:00:00Z"},
        {"handoff_state": "launch_attempted_unverified"},
        {"decision_source": "local_operator"},
        {"decision_reason": "superseded_by_verified_personal"},
    ],
)
def test_forged_request_lifecycle_invariants_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, object],
) -> None:
    created = _create_request(tmp_path, monkeypatch)
    forged_request = replace(created.request, **changes)
    forged_snapshot = replace(
        created.snapshot,
        active_request=forged_request,
        requests=(forged_request,),
    )

    with pytest.raises(accounts.ProviderAccountError) as exc:
        views.serialize_account_result(forged_snapshot)

    assert exc.value.code is accounts.ProviderAccountErrorCode.INVALID_STATE


def test_snapshot_pointer_active_count_and_ownership_invariants_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create_request(tmp_path, monkeypatch)
    second = replace(
        created.request,
        request_id="par_" + "cd" * 12,
        requested_at="2026-07-11T18:01:00Z",
        updated_at="2026-07-11T18:01:00Z",
        expires_at="2026-07-18T18:01:00Z",
    )
    forged_snapshots = (
        replace(created.snapshot, active_request_id=None, active_request=None),
        replace(created.snapshot, requests=(created.request, second)),
        replace(created.snapshot, desired_ownership="unselected"),
        replace(created.snapshot, ownership_epoch=0),
    )

    for forged in forged_snapshots:
        with pytest.raises(accounts.ProviderAccountError) as exc:
            views.serialize_account_result(forged)
        assert exc.value.code is accounts.ProviderAccountErrorCode.INVALID_STATE


def test_wrapper_request_must_equal_the_exact_snapshot_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create_request(tmp_path, monkeypatch)
    same_id_different_record = replace(
        created.request,
        device_label="different-valid-device",
    )
    forged = accounts.AccountMutationResult(
        snapshot=created.snapshot,
        request=same_id_different_record,
    )

    with pytest.raises(accounts.ProviderAccountError) as exc:
        views.serialize_account_result(forged)

    assert exc.value.code is accounts.ProviderAccountErrorCode.INVALID_STATE


def test_terminal_decision_provenance_invariants_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create_request(tmp_path, monkeypatch)
    terminal = accounts.transition_request(
        home=tmp_path,
        provider_id="openai-codex",
        request_id=created.request.request_id,
        target="rejected",
        expected_revision=created.snapshot.revision,
        source="local_operator",
    )
    assert terminal.request is not None
    forged_requests = (
        replace(terminal.request, decision_source="system_expiry"),
        replace(terminal.request, decision_at="2026-07-11T17:59:59Z"),
        replace(
            terminal.request,
            status="expired",
            decision_source="system_expiry",
        ),
        replace(
            terminal.request,
            decision_reason="superseded_by_verified_personal",
        ),
        replace(
            terminal.request,
            status="awaiting",
            decision_source="system_expiry",
        ),
        replace(
            terminal.request,
            status="cancelled",
            decision_source="verified_personal_oauth",
            decision_reason=None,
        ),
    )

    for forged_request in forged_requests:
        forged_snapshot = replace(
            terminal.snapshot,
            requests=(forged_request,),
        )
        with pytest.raises(accounts.ProviderAccountError) as exc:
            views.serialize_account_result(forged_snapshot)
        assert exc.value.code is accounts.ProviderAccountErrorCode.INVALID_STATE
