"""Classic/one-shot CLI adapter for provider-account ownership state."""

from __future__ import annotations

import contextlib
import json
import sys
from typing import NoReturn

from fabric_cli import provider_accounts as accounts
from fabric_cli import provider_account_views as views
from fabric_cli.provider_account_oauth import login_personal_provider
from fabric_constants import get_fabric_home


def _exit_provider_account_error(
    error: object,
    *,
    json_output: bool,
) -> NoReturn:
    """Render only the shared stable provider-account error contract."""

    payload = views.serialize_account_error(error)
    metadata = views.error_transport(error)
    if json_output:
        print(json.dumps(payload, sort_keys=True))
    else:
        code = payload["error"]["code"]
        print(
            f"Provider account error ({code}): {metadata.client_meaning}",
            file=sys.stderr,
        )
    exit_error = SystemExit(metadata.cli_exit_code)
    try:
        raise exit_error from None
    finally:
        exit_error.__context__ = None


def exit_provider_account_error(
    error: object,
    *,
    json_output: bool = False,
) -> NoReturn:
    """Stable error exit used by legacy ``auth add`` compatibility paths."""

    _exit_provider_account_error(error, json_output=json_output)


def _provider_account_payload(value) -> dict[str, object]:
    return views.serialize_account_result(value)


def _print_provider_account_human(payload: dict[str, object]) -> None:
    """Render a safe-view payload without consulting internal domain fields."""

    snapshot = payload["snapshot"]
    if not isinstance(snapshot, dict):  # serializer contract seat belt
        _exit_provider_account_error("invalid_state", json_output=False)
    provider_id = snapshot["provider_id"]
    desired = str(snapshot["desired_ownership"]).replace("_", " ")
    print(f"{provider_id}: {desired}")
    print(f"  revision: {snapshot['revision']}")

    active = snapshot.get("active_request")
    requests = snapshot.get("requests")
    shown_request = active
    if shown_request is None and isinstance(requests, list) and requests:
        shown_request = requests[-1]
    if isinstance(shown_request, dict):
        print(
            "  request: "
            f"{shown_request['request_id']} ({shown_request['status']}, "
            f"{shown_request['handoff_state'].replace('_', ' ')})"
        )
        print(f"  device: {shown_request['device_label']}")
        print(f"  expires: {shown_request['expires_at']}")
        decision_source = shown_request.get("decision_source")
        if decision_source == "local_operator":
            print(
                "  decision source: trusted local operator; this is not proof "
                "that Fabric received or decided the request"
            )

    if isinstance(active, dict):
        print(
            "  remote handoff: not configured in this self-hosted build; "
            "the request is local state only"
        )
        print(
            "  safety: no OAuth code, session ID, token, or credential was sent"
        )


def _emit_provider_account_result(value, *, json_output: bool) -> None:
    payload = _provider_account_payload(value)
    if json_output:
        print(json.dumps(payload, sort_keys=True))
    else:
        _print_provider_account_human(payload)


def _selected_logical_profile_name() -> str:
    """Return a safe logical label for the profile selected by CLI startup."""

    try:
        from fabric_cli.profiles import (
            get_active_profile_name,
            normalize_profile_name,
            validate_profile_name,
        )

        name = get_active_profile_name()
        if name != "custom":
            return name
        # CLI profile pre-parsing accepts deployment-specific ``profiles/<id>``
        # roots. Infer only the validated logical id; never render its parent or
        # canonical path in the destructive confirmation prompt.
        home = get_fabric_home()
        if home.parent.name == "profiles":
            candidate = normalize_profile_name(home.name)
            validate_profile_name(candidate)
            return candidate
    except (OSError, RuntimeError, ValueError):
        pass
    return "custom"


def _require_json_revision(args) -> int | None:
    expected = getattr(args, "expected_revision", None)
    if bool(getattr(args, "json", False)) and expected is None:
        raise accounts.ProviderAccountError(
            accounts.ProviderAccountErrorCode.INVALID_INPUT
        )
    return expected


def _active_request_matches(snapshot, request_id: str, action: str) -> bool:
    request = snapshot.active_request
    if request is None or request.request_id != request_id:
        return False
    if action == "acknowledge":
        return request.status == "requested"
    return request.status in {"requested", "awaiting"}


def _run_human_revision_mutation(
    *,
    home,
    provider_id: str,
    action: str,
    operation,
    initial_snapshot,
):
    """Retry one stale human mutation only when its target is unchanged."""

    try:
        return operation(initial_snapshot.revision)
    except accounts.ProviderAccountError as exc:
        if exc.code is not accounts.ProviderAccountErrorCode.STALE_REVISION:
            raise

    refreshed = accounts.get_account_snapshot(home=home, provider_id=provider_id)
    if action == "request":
        applicable = (
            refreshed.active_request_id == initial_snapshot.active_request_id
            and refreshed.desired_ownership == initial_snapshot.desired_ownership
        )
    else:
        request_id = initial_snapshot.active_request_id
        applicable = request_id is not None and _active_request_matches(
            refreshed, request_id, action
        )
    if not applicable:
        raise accounts.ProviderAccountError(
            accounts.ProviderAccountErrorCode.STALE_REVISION
        )
    return operation(refreshed.revision)


def provider_account_command(args) -> None:
    """Handle ``fabric auth account`` through the domain and safe views."""

    json_output = bool(getattr(args, "json", False))
    provider_id = str(getattr(args, "provider", "") or "").strip().lower()
    action = str(getattr(args, "account_action", "") or "")
    home = get_fabric_home()
    try:
        if action == "status":
            result = accounts.get_account_snapshot(home=home, provider_id=provider_id)
            _emit_provider_account_result(result, json_output=json_output)
            return

        expected_revision = _require_json_revision(args)
        if action == "personal":
            if json_output:
                # Device ceremonies remain local, while machine-readable
                # stdout contains exactly one safe account DTO.
                with contextlib.redirect_stdout(sys.stderr):
                    login = login_personal_provider(
                        home=home,
                        provider_id=provider_id,
                        expected_revision=expected_revision,
                        label=(getattr(args, "label", None) or "").strip(),
                        no_browser=bool(getattr(args, "no_browser", False)),
                        timeout_seconds=getattr(args, "timeout", None),
                    )
            else:
                login = login_personal_provider(
                    home=home,
                    provider_id=provider_id,
                    expected_revision=expected_revision,
                    label=(getattr(args, "label", None) or "").strip(),
                    no_browser=bool(getattr(args, "no_browser", False)),
                    timeout_seconds=getattr(args, "timeout", None),
                )
                print(
                    f"Connected personal {provider_id} credential: "
                    f'"{login.credential_label}"'
                )
            _emit_provider_account_result(login.snapshot, json_output=json_output)
            return

        initial = accounts.get_account_snapshot(home=home, provider_id=provider_id)
        if action == "request":
            device_label = getattr(args, "device_label", None)

            def operation(revision):
                return accounts.create_managed_request(
                    home=home,
                    provider_id=provider_id,
                    device_label=device_label,
                    expected_revision=revision,
                )

        elif action in {
            "handoff-attempted",
            "cancel",
            "acknowledge",
            "reject",
        }:
            request_id = getattr(args, "request_id", None)
            if json_output and not request_id:
                raise accounts.ProviderAccountError(
                    accounts.ProviderAccountErrorCode.INVALID_INPUT
                )
            if not request_id:
                request_id = initial.active_request_id
            if not request_id:
                raise accounts.ProviderAccountError(
                    accounts.ProviderAccountErrorCode.NOT_FOUND
                )
            if action == "handoff-attempted":

                def operation(revision):
                    return accounts.record_handoff_attempt(
                        home=home,
                        provider_id=provider_id,
                        request_id=request_id,
                        expected_revision=revision,
                    )

            elif action == "acknowledge":

                def operation(revision):
                    return accounts.record_admin_acknowledgement(
                        home=home,
                        provider_id=provider_id,
                        request_id=request_id,
                        expected_revision=revision,
                        source="local_operator",
                    )

            else:
                target = "cancelled" if action == "cancel" else "rejected"

                def operation(revision):
                    return accounts.transition_request(
                        home=home,
                        provider_id=provider_id,
                        request_id=request_id,
                        target=target,
                        expected_revision=revision,
                        source="local_operator",
                    )

        else:
            raise accounts.ProviderAccountError(
                accounts.ProviderAccountErrorCode.INVALID_INPUT
            )

        if expected_revision is None:
            result = _run_human_revision_mutation(
                home=home,
                provider_id=provider_id,
                action=action,
                operation=operation,
                initial_snapshot=initial,
            )
        else:
            result = operation(expected_revision)
        _emit_provider_account_result(result, json_output=json_output)
    except accounts.ProviderAccountError as exc:
        _exit_provider_account_error(exc, json_output=json_output)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        _exit_provider_account_error(
            accounts.ProviderAccountErrorCode.INVALID_STATE,
            json_output=json_output,
        )


def provider_accounts_store_command(args) -> None:
    """Handle the confirmed local-operator store repair action."""

    json_output = bool(getattr(args, "json", False))
    action = str(getattr(args, "store_action", "") or "")
    if action != "repair":
        _exit_provider_account_error(
            accounts.ProviderAccountErrorCode.INVALID_INPUT,
            json_output=json_output,
        )

    confirmed = bool(getattr(args, "yes", False))
    if not confirmed:
        if json_output or not sys.stdin.isatty():
            _exit_provider_account_error(
                accounts.ProviderAccountErrorCode.INVALID_INPUT,
                json_output=json_output,
            )
        try:
            profile_name = _selected_logical_profile_name()
            answer = (
                input(
                    "Reset every provider-account record in profile "
                    f"'{profile_name}' after preserving a private backup? [y/N]: "
                )
                .strip()
                .lower()
            )
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in {"y", "yes"}:
            print("Provider-account repair cancelled; no state changed.")
            return

    try:
        result = accounts.repair_account_store(home=get_fabric_home())
        payload = views.serialize_account_repair_result(result)
        if json_output:
            print(json.dumps(payload, sort_keys=True))
        else:
            backup = "yes" if result.backup_created else "no existing state file"
            print("Provider-account store repaired; every provider record was reset.")
            print(f"  private backup preserved: {backup}")
            print(f"  schema version: {result.schema_version}")
    except accounts.ProviderAccountError as exc:
        _exit_provider_account_error(exc, json_output=json_output)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        _exit_provider_account_error(
            accounts.ProviderAccountErrorCode.INVALID_STATE,
            json_output=json_output,
        )


__all__ = [
    "exit_provider_account_error",
    "provider_account_command",
    "provider_accounts_store_command",
]
