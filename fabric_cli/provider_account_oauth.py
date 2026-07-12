"""Profile-owned personal OAuth coordination for provider-account CLI flows.

This module keeps provider network ceremonies outside the provider-account
lock, then uses the domain's durable lease to fence credential persistence.
Only safe labels/counts and the final account snapshot leave this adapter;
OAuth codes, tokens, lease generations, operation identifiers, and profile
paths never do.
"""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, NoReturn

from agent.credential_pool import (
    AUTH_TYPE_OAUTH,
    SOURCE_MANUAL_DEVICE_CODE,
    CredentialPool,
    PooledCredential,
    label_from_token,
)
from fabric_cli import auth as auth_mod
from fabric_cli import provider_accounts as accounts
from fabric_cli.auth_reengagement import clear_provider_suppressions
from fabric_cli.provider_oauth_service import release_exact_oauth_lease
from fabric_constants import reset_fabric_home_override, set_fabric_home_override


_SINGLETON_DEVICE_CODE_SOURCE = "device_code"
_MAX_RELEASE_RECOVERIES = 128


@dataclass(frozen=True)
class _PersonalOAuthReleaseRecovery:
    """One non-secret exact lease handle retained after direct-flow cleanup."""

    key: tuple[str, int, int, str, str, int, str] = field(repr=False)
    home: Path = field(repr=False)
    provider_id: str
    started: accounts.PersonalOAuthStartResult = field(repr=False)
    lease_result: accounts.OAuthLeaseResult = field(repr=False)


class _PersonalOAuthReleaseRecoveryRegistry:
    """Bounded process-owned recovery for direct OAuth release failures.

    Entries retain the captured profile-directory identity and exact store/lease
    fence, never pathname authority by itself. Capacity is reserved before a
    provider ceremony starts, so cleanup can always retain its handle without
    evicting another live recovery.
    """

    def __init__(self, *, maximum: int = _MAX_RELEASE_RECOVERIES) -> None:
        self._maximum = maximum
        self._entries: dict[
            tuple[str, int, int, str, str, int, str],
            _PersonalOAuthReleaseRecovery,
        ] = {}
        self._reservations: set[str] = set()
        self._lock = threading.RLock()

    @staticmethod
    def _key(
        provider_id: str,
        started: accounts.PersonalOAuthStartResult,
        lease_result: accounts.OAuthLeaseResult,
    ) -> tuple[str, int, int, str, str, int, str]:
        owner = started.intent.flow_owner
        lease = lease_result.lease
        return (
            os.path.normcase(str(owner.canonical_home)),
            owner.home_identity[0],
            owner.home_identity[1],
            provider_id,
            started.intent.store_instance_id,
            lease.generation,
            lease.operation_id,
        )

    def reserve(self) -> str:
        with self._lock:
            if len(self._entries) + len(self._reservations) >= self._maximum:
                _raise_account_error(accounts.ProviderAccountErrorCode.IO_UNAVAILABLE)
            slot = uuid.uuid4().hex
            while slot in self._reservations:
                slot = uuid.uuid4().hex
            self._reservations.add(slot)
            return slot

    def finish(self, slot: str) -> None:
        with self._lock:
            self._reservations.discard(slot)

    def retain(
        self,
        slot: str,
        *,
        home: Path,
        provider_id: str,
        started: accounts.PersonalOAuthStartResult,
        lease_result: accounts.OAuthLeaseResult,
    ) -> None:
        key = self._key(provider_id, started, lease_result)
        entry = _PersonalOAuthReleaseRecovery(
            key=key,
            home=home,
            provider_id=provider_id,
            started=started,
            lease_result=lease_result,
        )
        with self._lock:
            if slot not in self._reservations:
                # Internal invariant failure: never evict an existing handle or
                # pretend this new exact lease can be recovered.
                _raise_account_error(accounts.ProviderAccountErrorCode.INVALID_STATE)
            self._reservations.remove(slot)
            self._entries[key] = entry

    def retry_for(self, *, home: Path, provider_id: str) -> int:
        """Retry only handles whose captured canonical pathname matches ``home``."""

        try:
            canonical = accounts.canonical_provider_account_home(home)
        except accounts.ProviderAccountError:
            return 0
        canonical_key = os.path.normcase(str(canonical))
        with self._lock:
            candidates = [
                entry
                for entry in self._entries.values()
                if entry.key[0] == canonical_key and entry.provider_id == provider_id
            ]

        released = 0
        for entry in candidates:
            error = _release_lease_exact(
                home=entry.home,
                provider_id=entry.provider_id,
                started=entry.started,
                lease_result=entry.lease_result,
            )
            if error is not None:
                continue
            with self._lock:
                if self._entries.get(entry.key) is entry:
                    self._entries.pop(entry.key, None)
                    released += 1
        return released

    def reset_for_tests(self) -> None:
        with self._lock:
            self._entries.clear()
            self._reservations.clear()


_personal_oauth_release_recoveries = _PersonalOAuthReleaseRecoveryRegistry()


def retry_pending_personal_oauth_releases(
    *,
    home: Path,
    provider_id: str,
) -> int:
    """Retry captured direct-flow cleanup at a profile-safe lifecycle point."""

    return _personal_oauth_release_recoveries.retry_for(
        home=home,
        provider_id=provider_id,
    )


def _raise_account_error(
    code: accounts.ProviderAccountErrorCode,
    *,
    retryable: bool | None = None,
) -> NoReturn:
    """Raise a fresh stable error with no recoverable raw exception context."""

    error = accounts.ProviderAccountError(code, retryable=retryable)
    try:
        raise error from None
    finally:
        error.__context__ = None


def _raise_clean_exit(code: int) -> NoReturn:
    """Preserve a conventional CLI exit without retaining exception context."""

    error = SystemExit(code)
    try:
        raise error from None
    finally:
        error.__context__ = None


def _raise_clean_keyboard_interrupt() -> NoReturn:
    error = KeyboardInterrupt()
    try:
        raise error from None
    finally:
        error.__context__ = None


@dataclass(frozen=True)
class PersonalProviderLoginResult:
    """Non-secret result consumed by human CLI and safe-view adapters."""

    snapshot: accounts.AccountSnapshot
    credential_label: str
    credential_count: int


def _release_lease_exact(
    *,
    home: Path,
    provider_id: str,
    started: accounts.PersonalOAuthStartResult,
    lease_result: accounts.OAuthLeaseResult,
) -> accounts.ProviderAccountError | None:
    """Release this coordinator's exact lease or return a stable failure."""

    try:
        error = release_exact_oauth_lease(
            home=home,
            provider_id=provider_id,
            captured_intent=started.intent,
            lease_result=lease_result,
        )
    except Exception:
        return accounts.ProviderAccountError(
            accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
        )
    if error is None:
        return None
    try:
        code = accounts.ProviderAccountErrorCode(error.code.value)
    except ValueError:
        code = accounts.ProviderAccountErrorCode.INVALID_STATE
    return accounts.ProviderAccountError(code, retryable=error.retryable)


def _release_lease_after_failure(
    *,
    home: Path,
    provider_id: str,
    started: accounts.PersonalOAuthStartResult,
    lease_result: accounts.OAuthLeaseResult,
    original: BaseException,
) -> accounts.ProviderAccountError | None:
    """Preserve process-control signals if lease cleanup is interrupted too."""

    try:
        return _release_lease_exact(
            home=home,
            provider_id=provider_id,
            started=started,
            lease_result=lease_result,
        )
    except BaseException:
        # The exact lease remains durably identifiable in the recovery registry.
        # Never let cleanup replace the ceremony's original failure or signal.
        return accounts.ProviderAccountError(
            accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
        )


def _verified_credential_writer(
    *,
    provider_id: str,
    credential_writer: Callable[[str], None],
) -> Callable[[str], None]:
    """Add strict, exactly-once source re-engagement to a retryable writer."""

    reengagement_state = "pending"

    def verified(operation_id: str) -> None:
        nonlocal reengagement_state
        with auth_mod._auth_store_lock():
            credential_writer(operation_id)
            if reengagement_state == "failed":
                _raise_account_error(accounts.ProviderAccountErrorCode.IO_UNAVAILABLE)
            if reengagement_state == "pending":
                # Latch both outcomes.  A successful outer account-state retry
                # must not repeat the publication, while a failed publication
                # must remain failed rather than being skipped into approval.
                reengagement_state = "failed"
                clear_provider_suppressions(provider_id)
                reengagement_state = "complete"

    return verified


def _capture_personal_start(
    *,
    home: Path,
    provider_id: str,
    expected_revision: int | None,
) -> accounts.PersonalOAuthStartResult:
    """Capture intent, with the one narrowly permitted human retry."""

    if expected_revision is not None:
        return accounts.capture_personal_oauth_start(
            home=home,
            provider_id=provider_id,
            expected_revision=expected_revision,
        )

    initial = accounts.get_account_snapshot(home=home, provider_id=provider_id)
    try:
        return accounts.capture_personal_oauth_start(
            home=home,
            provider_id=provider_id,
            expected_revision=initial.revision,
        )
    except accounts.ProviderAccountError as exc:
        if exc.code is not accounts.ProviderAccountErrorCode.STALE_REVISION:
            raise

    refreshed = accounts.get_account_snapshot(home=home, provider_id=provider_id)
    if (
        refreshed.active_request_id != initial.active_request_id
        or refreshed.desired_ownership != initial.desired_ownership
    ):
        raise accounts.ProviderAccountError(
            accounts.ProviderAccountErrorCode.STALE_REVISION
        )
    return accounts.capture_personal_oauth_start(
        home=home,
        provider_id=provider_id,
        expected_revision=refreshed.revision,
    )


def _acquire_oauth_lease(
    *,
    home: Path,
    provider_id: str,
    started: accounts.PersonalOAuthStartResult,
) -> accounts.OAuthLeaseResult:
    """Acquire once, replaying only this caller's exact idempotency key."""

    operation_id = accounts.new_oauth_operation_id()

    try:
        return accounts.acquire_oauth_lease(
            home=home,
            provider_id=provider_id,
            captured_intent=started.intent,
            operation_id=operation_id,
        )
    except accounts.ProviderAccountError as exc:
        if exc.code is not accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN:
            raise

    # The first atomic replace may or may not be durable. Retrying the exact
    # caller-known key either creates the missing lease, replays this lease, or
    # rejects a rival worker's distinct lease without starting a ceremony.
    try:
        return accounts.acquire_oauth_lease(
            home=home,
            provider_id=provider_id,
            captured_intent=started.intent,
            operation_id=operation_id,
        )
    except accounts.ProviderAccountError as exc:
        if exc.code is accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN:
            _raise_account_error(accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN)
        raise


def _load_local_pool_entries(provider_id: str) -> list[PooledCredential]:
    """Load only this profile's persisted pool, never the global fallback."""

    try:
        with auth_mod._auth_store_lock():
            store = auth_mod._load_auth_store()
        pool = store.get("credential_pool") if isinstance(store, dict) else None
        raw_entries = pool.get(provider_id) if isinstance(pool, dict) else None
        if raw_entries is None:
            return []
        if not isinstance(raw_entries, list) or not all(
            isinstance(raw, dict) for raw in raw_entries
        ):
            _raise_account_error(accounts.ProviderAccountErrorCode.IO_UNAVAILABLE)
        return [PooledCredential.from_dict(provider_id, raw) for raw in raw_entries]
    except accounts.ProviderAccountError:
        raise
    except Exception:
        _raise_account_error(accounts.ProviderAccountErrorCode.IO_UNAVAILABLE)


def _local_pool_match(
    provider_id: str,
    *,
    access_token: str,
    refresh_token: str | None,
) -> PooledCredential | None:
    """Find an already-written local entry after an uncertain writer return.

    Reading the active auth store directly is intentional: ``load_pool`` may
    include a global fallback for a named profile, and a borrowed credential
    must not be mistaken for proof that this fresh profile-owned write landed.
    """

    for entry in _load_local_pool_entries(provider_id):
        if (
            entry.source == SOURCE_MANUAL_DEVICE_CODE
            and entry.access_token == access_token
            and entry.refresh_token == refresh_token
        ):
            return entry
    return None


def _load_local_credential_pool(provider_id: str) -> CredentialPool:
    return CredentialPool(provider_id, _load_local_pool_entries(provider_id))


def _write_xai_local_pool_entry(
    *,
    credentials: dict[str, Any],
    access_token: str,
    refresh_token: str,
) -> tuple[PooledCredential, int]:
    """Upsert the singleton mirror without materializing root pool rows."""

    entries = _load_local_pool_entries("xai-oauth")
    matches = [
        (index, entry)
        for index, entry in enumerate(entries)
        if entry.source == _SINGLETON_DEVICE_CODE_SOURCE
    ]
    if len(matches) > 1:
        _raise_account_error(accounts.ProviderAccountErrorCode.IO_UNAVAILABLE)

    last_refresh = credentials.get("last_refresh")
    base_url = credentials.get("base_url") or auth_mod.DEFAULT_XAI_OAUTH_BASE_URL
    if matches:
        index, existing = matches[0]
        entry = replace(
            existing,
            access_token=access_token,
            refresh_token=refresh_token,
            base_url=base_url,
            last_refresh=last_refresh,
            last_status=None,
            last_status_at=None,
            last_error_code=None,
            last_error_reason=None,
            last_error_message=None,
            last_error_reset_at=None,
        )
        entries[index] = entry
    else:
        entry = PooledCredential(
            provider="xai-oauth",
            id=uuid.uuid4().hex[:6],
            label=label_from_token(access_token, _SINGLETON_DEVICE_CODE_SOURCE),
            auth_type=AUTH_TYPE_OAUTH,
            priority=len(entries),
            source=_SINGLETON_DEVICE_CODE_SOURCE,
            access_token=access_token,
            refresh_token=refresh_token,
            base_url=base_url,
            last_refresh=last_refresh,
        )
        entries.append(entry)

    auth_mod.write_credential_pool(
        "xai-oauth", [candidate.to_dict() for candidate in entries]
    )
    return entry, len(entries)


def _codex_credential_writer(
    *,
    pool,
    credentials: dict[str, Any],
    requested_label: str,
):
    tokens = credentials.get("tokens")
    if not isinstance(tokens, dict):
        _raise_account_error(accounts.ProviderAccountErrorCode.IO_UNAVAILABLE)
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not isinstance(access_token, str) or not access_token.strip():
        _raise_account_error(accounts.ProviderAccountErrorCode.IO_UNAVAILABLE)
    if refresh_token is not None and not isinstance(refresh_token, str):
        _raise_account_error(accounts.ProviderAccountErrorCode.IO_UNAVAILABLE)

    default_label = f"openai-codex-oauth-{len(pool.entries()) + 1}"
    label = requested_label or label_from_token(access_token, default_label)
    written: list[PooledCredential] = []

    def writer(_operation_id: str) -> None:
        if written:
            return
        existing = _local_pool_match(
            "openai-codex",
            access_token=access_token,
            refresh_token=refresh_token,
        )
        if existing is not None:
            auth_mod.mark_provider_active_if_unset("openai-codex")
            written.append(existing)
            return

        entry = PooledCredential(
            provider="openai-codex",
            id=uuid.uuid4().hex[:6],
            label=label,
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=SOURCE_MANUAL_DEVICE_CODE,
            access_token=access_token,
            refresh_token=refresh_token,
            base_url=credentials.get("base_url"),
            last_refresh=credentials.get("last_refresh"),
        )
        first_credential = not pool.entries()
        persisted = pool.add_entry(entry)
        if first_credential:
            auth_mod.mark_provider_active_if_unset("openai-codex")
        written.append(persisted)

    return writer, written


def _xai_credential_writer(*, credentials: dict[str, Any]):
    tokens = credentials.get("tokens")
    if not isinstance(tokens, dict):
        _raise_account_error(accounts.ProviderAccountErrorCode.IO_UNAVAILABLE)
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if (
        not isinstance(access_token, str)
        or not access_token.strip()
        or not isinstance(refresh_token, str)
        or not refresh_token.strip()
    ):
        _raise_account_error(accounts.ProviderAccountErrorCode.IO_UNAVAILABLE)

    written: list[tuple[PooledCredential, int]] = []

    def writer(_operation_id: str) -> None:
        if written:
            return
        auth_mod._save_xai_oauth_tokens(
            tokens,
            discovery=credentials.get("discovery"),
            redirect_uri=credentials.get("redirect_uri", ""),
            last_refresh=credentials.get("last_refresh"),
            auth_mode="oauth_device_code",
            profile_owned_fresh_login=True,
        )
        written.append(
            _write_xai_local_pool_entry(
                credentials=credentials,
                access_token=access_token,
                refresh_token=refresh_token,
            )
        )

    return writer, written


def _read_matching_completion(
    *,
    home: Path,
    provider_id: str,
    started: accounts.PersonalOAuthStartResult,
    lease_result: accounts.OAuthLeaseResult,
) -> accounts.OAuthCompletionResult | None:
    """Return only this coordinator's durable completion tombstone."""

    try:
        snapshot = accounts.get_captured_oauth_snapshot(
            home=home,
            provider_id=provider_id,
            captured_intent=started.intent,
        )
    except accounts.ProviderAccountError:
        return None
    completion = snapshot.oauth_completion
    lease = lease_result.lease
    intent = started.intent
    if (
        completion is None
        or completion.generation != lease.generation
        or completion.operation_id != lease.operation_id
        or completion.store_instance_id != lease.store_instance_id
        or completion.ownership_epoch != intent.ownership_epoch
        or completion.active_request_id_at_start != intent.active_request_id_at_start
    ):
        return None
    return accounts.OAuthCompletionResult(
        snapshot=snapshot,
        operation_id=completion.operation_id,
        superseded_request_id=completion.superseded_request_id,
        intent_matched=completion.intent_matched,
        replayed=True,
    )


def _login_personal_provider_scoped(
    *,
    home: Path,
    provider_id: str,
    started: accounts.PersonalOAuthStartResult,
    recovery_slot: str,
    label: str = "",
    no_browser: bool = False,
    timeout_seconds: float | None = None,
) -> PersonalProviderLoginResult:
    """Run the ceremony after intent capture inside the captured home scope."""

    lease_result = _acquire_oauth_lease(
        home=home,
        provider_id=provider_id,
        started=started,
    )

    try:
        if provider_id == "openai-codex":
            credentials = auth_mod._codex_device_code_login()
            pool = _load_local_credential_pool(provider_id)
            writer, written = _codex_credential_writer(
                pool=pool,
                credentials=credentials,
                requested_label=label.strip(),
            )
        elif provider_id == "xai-oauth":
            credentials = auth_mod._xai_oauth_device_code_login(
                timeout_seconds=timeout_seconds or 20.0,
                open_browser=not no_browser,
            )
            writer, written = _xai_credential_writer(credentials=credentials)
        else:  # The domain rejects this too; keep the network branch closed.
            _raise_account_error(accounts.ProviderAccountErrorCode.INVALID_PROVIDER)

        writer = _verified_credential_writer(
            provider_id=provider_id,
            credential_writer=writer,
        )
    except BaseException as exc:
        cleanup_error = _release_lease_after_failure(
            home=home,
            provider_id=provider_id,
            started=started,
            lease_result=lease_result,
            original=exc,
        )
        if cleanup_error is not None:
            _personal_oauth_release_recoveries.retain(
                recovery_slot,
                home=home,
                provider_id=provider_id,
                started=started,
                lease_result=lease_result,
            )
        if isinstance(exc, accounts.ProviderAccountError):
            if cleanup_error is not None:
                _raise_account_error(
                    cleanup_error.code,
                    retryable=cleanup_error.retryable,
                )
            _raise_account_error(exc.code, retryable=exc.retryable)
        if isinstance(exc, KeyboardInterrupt):
            _raise_clean_keyboard_interrupt()
        if isinstance(exc, SystemExit) and isinstance(exc.code, int):
            _raise_clean_exit(exc.code)
        if isinstance(exc, Exception) or isinstance(exc, SystemExit):
            if cleanup_error is not None:
                _raise_account_error(
                    cleanup_error.code,
                    retryable=cleanup_error.retryable,
                )
            _raise_account_error(accounts.ProviderAccountErrorCode.IO_UNAVAILABLE)
        raise

    lease = lease_result.lease
    completion_attempt = 0
    uncertain_replay = False
    while True:
        try:
            completed = accounts.persist_personal_oauth_completion(
                home=home,
                provider_id=provider_id,
                generation=lease.generation,
                operation_id=lease.operation_id,
                credential_writer=writer,
                captured_intent=started.intent,
            )
            break
        except accounts.ProviderAccountError as exc:
            # The credential callbacks are idempotent. One immediate retry can
            # close a pre-commit I/O interruption without starting another
            # provider ceremony. A durability-uncertain replace must instead
            # be inspected by reading current state.
            if uncertain_replay:
                try:
                    durable = _read_matching_completion(
                        home=home,
                        provider_id=provider_id,
                        started=started,
                        lease_result=lease_result,
                    )
                except BaseException:
                    _personal_oauth_release_recoveries.retain(
                        recovery_slot,
                        home=home,
                        provider_id=provider_id,
                        started=started,
                        lease_result=lease_result,
                    )
                    raise
                if durable is not None:
                    completed = durable
                    break
                _personal_oauth_release_recoveries.retain(
                    recovery_slot,
                    home=home,
                    provider_id=provider_id,
                    started=started,
                    lease_result=lease_result,
                )
                _raise_account_error(accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN)
            if (
                exc.code is accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
                and completion_attempt == 0
            ):
                completion_attempt += 1
                continue
            if exc.code is accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN:
                uncertain_replay = True
                continue
            cleanup_error = _release_lease_after_failure(
                home=home,
                provider_id=provider_id,
                started=started,
                lease_result=lease_result,
                original=exc,
            )
            if cleanup_error is not None:
                _personal_oauth_release_recoveries.retain(
                    recovery_slot,
                    home=home,
                    provider_id=provider_id,
                    started=started,
                    lease_result=lease_result,
                )
                _raise_account_error(
                    cleanup_error.code,
                    retryable=cleanup_error.retryable,
                )
            _raise_account_error(exc.code, retryable=exc.retryable)
        except BaseException as exc:
            try:
                durable = _read_matching_completion(
                    home=home,
                    provider_id=provider_id,
                    started=started,
                    lease_result=lease_result,
                )
            except BaseException:
                _personal_oauth_release_recoveries.retain(
                    recovery_slot,
                    home=home,
                    provider_id=provider_id,
                    started=started,
                    lease_result=lease_result,
                )
                raise exc
            if durable is not None:
                completed = durable
                break
            if uncertain_replay:
                _personal_oauth_release_recoveries.retain(
                    recovery_slot,
                    home=home,
                    provider_id=provider_id,
                    started=started,
                    lease_result=lease_result,
                )
                _raise_account_error(accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN)
            cleanup_error = _release_lease_after_failure(
                home=home,
                provider_id=provider_id,
                started=started,
                lease_result=lease_result,
                original=exc,
            )
            if cleanup_error is not None:
                _personal_oauth_release_recoveries.retain(
                    recovery_slot,
                    home=home,
                    provider_id=provider_id,
                    started=started,
                    lease_result=lease_result,
                )
            if isinstance(exc, KeyboardInterrupt):
                _raise_clean_keyboard_interrupt()
            if isinstance(exc, SystemExit) and isinstance(exc.code, int):
                _raise_clean_exit(exc.code)
            if isinstance(exc, Exception) or isinstance(exc, SystemExit):
                if cleanup_error is not None:
                    _raise_account_error(
                        cleanup_error.code,
                        retryable=cleanup_error.retryable,
                    )
                _raise_account_error(accounts.ProviderAccountErrorCode.IO_UNAVAILABLE)
            raise

    if provider_id == "openai-codex":
        entry = written[0] if written else None
        if entry is None:  # Defensive: a successful callback must identify its entry.
            _raise_account_error(accounts.ProviderAccountErrorCode.IO_UNAVAILABLE)
        return PersonalProviderLoginResult(
            snapshot=completed.snapshot,
            credential_label=entry.label,
            credential_count=len(pool.entries()),
        )

    xai_write = written[0] if written else None
    if xai_write is None:
        # A replayed durable completion may follow a process-local result loss.
        # Read the strictly local mirror instead of consulting root fallback.
        local_entries = _load_local_pool_entries(provider_id)
        local_device_entries = [
            entry
            for entry in local_entries
            if entry.source == _SINGLETON_DEVICE_CODE_SOURCE
        ]
        if len(local_device_entries) != 1:
            _raise_account_error(accounts.ProviderAccountErrorCode.IO_UNAVAILABLE)
        xai_write = (local_device_entries[0], len(local_entries))
    entry, entry_count = xai_write
    return PersonalProviderLoginResult(
        snapshot=completed.snapshot,
        credential_label=entry.label,
        credential_count=entry_count,
    )


def login_personal_provider(
    *,
    home: Path,
    provider_id: str,
    expected_revision: int | None,
    label: str = "",
    no_browser: bool = False,
    timeout_seconds: float | None = None,
) -> PersonalProviderLoginResult:
    """Run one fenced personal OAuth ceremony for ChatGPT or Grok."""

    # A restored profile must settle any exact release retained by an earlier
    # direct flow before capture sees that lease as ``oauth_in_progress``.
    retry_pending_personal_oauth_releases(
        home=home,
        provider_id=provider_id,
    )
    recovery_slot = _personal_oauth_release_recoveries.reserve()
    try:
        started = _capture_personal_start(
            home=home,
            provider_id=provider_id,
            expected_revision=expected_revision,
        )
        captured_home = started.intent.flow_owner.canonical_home
        home_token = set_fabric_home_override(captured_home)
        try:
            return _login_personal_provider_scoped(
                home=captured_home,
                provider_id=provider_id,
                started=started,
                recovery_slot=recovery_slot,
                label=label,
                no_browser=no_browser,
                timeout_seconds=timeout_seconds,
            )
        finally:
            reset_fabric_home_override(home_token)
    finally:
        _personal_oauth_release_recoveries.finish(recovery_slot)


__all__ = [
    "PersonalProviderLoginResult",
    "login_personal_provider",
    "retry_pending_personal_oauth_releases",
]
