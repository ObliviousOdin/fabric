"""Framework-neutral, profile-owned OAuth ceremony lifecycle service.

The service owns the process-local session registry and its concurrency rules.
Provider adapters remain responsible for the provider-specific network exchange,
but every start, poll, worker commit, expiry, and cancellation is fenced here.

For the two provider-account ownership providers (OpenAI Codex and xAI), the
process-local session is additionally bound to the durable personal-intent and
OAuth-generation primitives in :mod:`fabric_cli.provider_accounts`.  No public
view from this module contains a canonical path, operation id, lease generation,
credential, provider response, or the independent internal flow trace id.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, NoReturn

from fabric_cli import provider_accounts as accounts


PERSONAL_ACCOUNT_PROVIDERS = frozenset({"openai-codex", "xai-oauth"})
FLOW_TYPES = frozenset({"device_code", "pkce"})
TERMINAL_STATUSES = frozenset({"approved", "cancelled", "denied", "error", "expired"})


class OAuthFlowErrorCode(str, Enum):
    """Allowlisted OAuth-service failures shared by every transport adapter."""

    INVALID_PROVIDER = "invalid_provider"
    INVALID_INPUT = "invalid_input"
    NOT_FOUND = "not_found"
    NOT_AUTHORIZED = "not_authorized"
    STALE_REVISION = "stale_revision"
    ILLEGAL_TRANSITION = "illegal_transition"
    OAUTH_IN_PROGRESS = "oauth_in_progress"
    INVALID_STATE = "invalid_state"
    NEWER_SCHEMA = "newer_schema"
    PATH_REDIRECT = "path_redirect"
    LOCK_TIMEOUT = "lock_timeout"
    IO_UNAVAILABLE = "io_unavailable"
    COMMIT_UNCERTAIN = "commit_uncertain"
    RUNTIME_MODE_UNAVAILABLE = "runtime_mode_unavailable"
    NOUS_CLIENT_ID_REQUIRED = "nous_client_id_required"


_RETRYABLE_CODES = frozenset({
    OAuthFlowErrorCode.STALE_REVISION,
    OAuthFlowErrorCode.ILLEGAL_TRANSITION,
    OAuthFlowErrorCode.OAUTH_IN_PROGRESS,
    OAuthFlowErrorCode.LOCK_TIMEOUT,
    OAuthFlowErrorCode.IO_UNAVAILABLE,
})

_HTTP_STATUS = {
    OAuthFlowErrorCode.INVALID_PROVIDER: 400,
    OAuthFlowErrorCode.INVALID_INPUT: 400,
    OAuthFlowErrorCode.NOT_FOUND: 404,
    OAuthFlowErrorCode.NOT_AUTHORIZED: 403,
    OAuthFlowErrorCode.STALE_REVISION: 409,
    OAuthFlowErrorCode.ILLEGAL_TRANSITION: 409,
    OAuthFlowErrorCode.OAUTH_IN_PROGRESS: 409,
    OAuthFlowErrorCode.INVALID_STATE: 409,
    OAuthFlowErrorCode.NEWER_SCHEMA: 409,
    OAuthFlowErrorCode.PATH_REDIRECT: 409,
    OAuthFlowErrorCode.LOCK_TIMEOUT: 503,
    OAuthFlowErrorCode.IO_UNAVAILABLE: 503,
    OAuthFlowErrorCode.COMMIT_UNCERTAIN: 503,
    OAuthFlowErrorCode.RUNTIME_MODE_UNAVAILABLE: 503,
    OAuthFlowErrorCode.NOUS_CLIENT_ID_REQUIRED: 409,
}

_STABLE_MESSAGES = {
    OAuthFlowErrorCode.INVALID_PROVIDER: "Unsupported OAuth provider.",
    OAuthFlowErrorCode.INVALID_INPUT: "Invalid OAuth request.",
    OAuthFlowErrorCode.NOT_FOUND: "OAuth session not found.",
    OAuthFlowErrorCode.NOT_AUTHORIZED: "OAuth action is not authorized.",
    OAuthFlowErrorCode.STALE_REVISION: "Account state changed; refresh and retry.",
    OAuthFlowErrorCode.ILLEGAL_TRANSITION: "OAuth state changed; refresh and retry.",
    OAuthFlowErrorCode.OAUTH_IN_PROGRESS: "An OAuth sign-in is already in progress.",
    OAuthFlowErrorCode.INVALID_STATE: "OAuth state requires local repair or upgrade.",
    OAuthFlowErrorCode.NEWER_SCHEMA: "OAuth state requires a newer Fabric version.",
    OAuthFlowErrorCode.PATH_REDIRECT: "OAuth state path is unavailable.",
    OAuthFlowErrorCode.LOCK_TIMEOUT: "OAuth state is busy; retry shortly.",
    OAuthFlowErrorCode.IO_UNAVAILABLE: "OAuth provider or local credential storage is unavailable.",
    OAuthFlowErrorCode.COMMIT_UNCERTAIN: "OAuth completion is uncertain; inspect current state.",
    OAuthFlowErrorCode.RUNTIME_MODE_UNAVAILABLE: "OAuth is unavailable in this runtime mode.",
    OAuthFlowErrorCode.NOUS_CLIENT_ID_REQUIRED: (
        "Nous Portal OAuth requires a registered client ID. Run "
        "`fabric auth add nous --client-id <registered-client-id>`."
    ),
}


class OAuthFlowError(RuntimeError):
    """Stable OAuth failure with no raw provider, path, or credential context."""

    def __init__(
        self,
        code: OAuthFlowErrorCode | str,
        *,
        retryable: bool | None = None,
    ) -> None:
        try:
            parsed = OAuthFlowErrorCode(code)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown OAuth flow error code") from exc
        self.code = parsed
        self.retryable = (
            parsed in _RETRYABLE_CODES if retryable is None else bool(retryable)
        )
        super().__init__(parsed.value)


def _raise_flow(
    code: OAuthFlowErrorCode,
    *,
    retryable: bool | None = None,
) -> NoReturn:
    error = OAuthFlowError(code, retryable=retryable)
    try:
        raise error from None
    finally:
        error.__context__ = None


def _from_account_error(error: accounts.ProviderAccountError) -> OAuthFlowError:
    try:
        code = OAuthFlowErrorCode(error.code.value)
    except (AttributeError, ValueError):
        code = OAuthFlowErrorCode.INVALID_STATE
    return OAuthFlowError(code, retryable=error.retryable)


def oauth_error_http_status(error: OAuthFlowError | OAuthFlowErrorCode | object) -> int:
    if isinstance(error, OAuthFlowError):
        code = error.code
    else:
        try:
            code = OAuthFlowErrorCode(error)
        except (TypeError, ValueError):
            code = OAuthFlowErrorCode.INVALID_STATE
    return _HTTP_STATUS[code]


def serialize_oauth_error(
    error: OAuthFlowError | OAuthFlowErrorCode | object,
) -> dict[str, dict[str, object]]:
    if isinstance(error, OAuthFlowError):
        code = error.code
        retryable = error.retryable
    else:
        try:
            code = OAuthFlowErrorCode(error)
        except (TypeError, ValueError):
            code = OAuthFlowErrorCode.INVALID_STATE
        retryable = code in _RETRYABLE_CODES
    return {"error": {"code": code.value, "retryable": retryable}}


def stable_oauth_message(code: OAuthFlowErrorCode | str | object) -> str:
    try:
        parsed = OAuthFlowErrorCode(code)
    except (TypeError, ValueError):
        parsed = OAuthFlowErrorCode.INVALID_STATE
    return _STABLE_MESSAGES[parsed]


def release_exact_oauth_lease(
    *,
    home: Path,
    provider_id: str,
    captured_intent: accounts.PersonalOAuthIntent,
    lease_result: accounts.OAuthLeaseResult,
) -> OAuthFlowError | None:
    """Release one exact lease and prove the durable post-condition.

    The release mutation can fail before or after its atomic publication.  An
    exact-key retry is safe, and a final account-state read distinguishes an
    unreleased lease from a post-effect error.  Returning a stable error keeps
    policy at the caller: services can retain a retry handle, while direct CLI
    flows can surface cleanup failure instead of reporting the earlier generic
    provider error.
    """

    if (
        not isinstance(home, Path)
        or not isinstance(captured_intent, accounts.PersonalOAuthIntent)
        or not isinstance(lease_result, accounts.OAuthLeaseResult)
    ):
        return OAuthFlowError(OAuthFlowErrorCode.INVALID_INPUT)
    lease = lease_result.lease
    last_error = OAuthFlowError(OAuthFlowErrorCode.IO_UNAVAILABLE)
    for attempt in range(2):
        try:
            accounts.release_oauth_lease(
                home=home,
                provider_id=provider_id,
                generation=lease.generation,
                operation_id=lease.operation_id,
                store_instance_id=lease.store_instance_id,
                captured_intent=captured_intent,
            )
            return None
        except accounts.ProviderAccountError as exc:
            last_error = _from_account_error(exc)
            if attempt == 0 and exc.code in {
                accounts.ProviderAccountErrorCode.LOCK_TIMEOUT,
                accounts.ProviderAccountErrorCode.IO_UNAVAILABLE,
                accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN,
            }:
                continue
            break
    # The domain release is idempotent only *after* it validates the captured
    # profile owner and store instance.  A NOT_FOUND here is therefore an
    # identity failure, not proof that our lease disappeared.  Retain the exact
    # retry handle rather than reading whichever store now occupies the path.
    return last_error


@dataclass(frozen=True)
class OAuthFlowOwner:
    """Canonical profile identity used only inside the ceremony service."""

    canonical_home: Path = field(repr=False)
    identity: tuple[int, int] = field(repr=False)

    @property
    def key(self) -> tuple[str, int, int]:
        return (
            os.path.normcase(str(self.canonical_home)),
            self.identity[0],
            self.identity[1],
        )


@dataclass(frozen=True)
class OAuthStartReservation:
    """Internal start reservation; only ``public_response`` may cross an adapter."""

    session_id: str
    session: dict[str, Any] = field(repr=False)
    created: bool
    account_snapshot: accounts.AccountSnapshot | None = field(default=None, repr=False)


class OAuthFlowService:
    """One process-local OAuth registry backed by optional durable generation fences."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 15 * 60,
        terminal_retention_seconds: float = 60,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if ttl_seconds <= 0 or terminal_retention_seconds < 0:
            raise ValueError("OAuth service timeouts must be positive")
        self.ttl_seconds = float(ttl_seconds)
        self.terminal_retention_seconds = float(terminal_retention_seconds)
        self._clock = clock
        self._sessions: dict[str, dict[str, Any]] = {}
        self._pending: dict[tuple[tuple[str, int, int], str], str] = {}
        self._lock = threading.RLock()

    @property
    def sessions(self) -> dict[str, dict[str, Any]]:
        """Compatibility view for existing workers/tests; the service remains owner."""

        return self._sessions

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def reset_for_tests(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                self._cancel_event_locked(session).set()
            self._sessions.clear()
            self._pending.clear()

    def _owner(self, home: Path) -> OAuthFlowOwner:
        try:
            canonical = accounts.canonical_provider_account_home(Path(home))
            stat_result = canonical.stat(follow_symlinks=False)
        except accounts.ProviderAccountError as exc:
            raise _from_account_error(exc) from None
        except (OSError, RuntimeError, TypeError, ValueError):
            _raise_flow(OAuthFlowErrorCode.IO_UNAVAILABLE)
        return OAuthFlowOwner(canonical, (stat_result.st_dev, stat_result.st_ino))

    @staticmethod
    def _cancel_event_locked(session: dict[str, Any]) -> threading.Event:
        event = session.get("_cancel_event")
        if not isinstance(event, threading.Event):
            event = threading.Event()
            session["_cancel_event"] = event
        return event

    def cancel_event(self, session: dict[str, Any]) -> threading.Event:
        with self._lock:
            return self._cancel_event_locked(session)

    @staticmethod
    def _session_deadline(session: dict[str, Any]) -> float:
        values = [session.get("_registry_expires_at"), session.get("expires_at")]
        numeric = [float(value) for value in values if isinstance(value, (int, float))]
        return min(numeric) if numeric else 0.0

    @staticmethod
    def _pending_key(owner: OAuthFlowOwner, provider_id: str):
        return (owner.key, provider_id)

    def _remove_pending_locked(self, session: dict[str, Any]) -> None:
        key = session.get("_pending_key")
        if isinstance(key, tuple) and self._pending.get(key) == session.get(
            "session_id"
        ):
            self._pending.pop(key, None)

    def _find_pending_locked(
        self,
        owner: OAuthFlowOwner,
        provider_id: str,
    ) -> dict[str, Any] | None:
        key = self._pending_key(owner, provider_id)
        session_id = self._pending.get(key)
        session = self._sessions.get(session_id) if session_id else None
        if (
            session is not None
            and session.get("status") == "pending"
            and not self._cancel_event_locked(session).is_set()
        ):
            if self._durable_is_current(session):
                return session
            self._cancel_stale_locked(session)
        self._pending.pop(key, None)
        # Compatibility for tests which manipulate the registry mapping directly.
        for candidate in self._sessions.values():
            if (
                candidate.get("status") == "pending"
                and candidate.get("provider") == provider_id
                and candidate.get("_owner_key") == owner.key
                and not self._cancel_event_locked(candidate).is_set()
            ):
                if not self._durable_is_current(candidate):
                    self._cancel_stale_locked(candidate)
                    continue
                self._pending[key] = str(candidate.get("session_id"))
                candidate["_pending_key"] = key
                return candidate
        return None

    @staticmethod
    def _capture_personal_start(
        *,
        home: Path,
        provider_id: str,
        expected_revision: int | None,
    ) -> accounts.PersonalOAuthStartResult:
        try:
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
            refreshed = accounts.get_account_snapshot(
                home=home, provider_id=provider_id
            )
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
        except accounts.ProviderAccountError as exc:
            raise _from_account_error(exc) from None

    @staticmethod
    def _acquire_personal_lease(
        *,
        home: Path,
        provider_id: str,
        started: accounts.PersonalOAuthStartResult,
        takeover: bool,
    ) -> accounts.OAuthLeaseResult:
        operation_id = accounts.new_oauth_operation_id()
        for attempt in range(2):
            try:
                return accounts.acquire_oauth_lease(
                    home=home,
                    provider_id=provider_id,
                    captured_intent=started.intent,
                    operation_id=operation_id,
                    # A first replace that reported COMMIT_UNCERTAIN may
                    # nevertheless have published this exact operation.  An
                    # exact replay must use takeover=False; takeover=True is
                    # reserved for a genuinely distinct worker generation.
                    takeover=(
                        takeover
                        if attempt == 0
                        else not OAuthFlowService._operation_is_active(
                            home=home,
                            provider_id=provider_id,
                            operation_id=operation_id,
                            started=started,
                        )
                        and takeover
                    ),
                )
            except accounts.ProviderAccountError as exc:
                if (
                    attempt == 0
                    and exc.code is accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN
                ):
                    continue
                raise _from_account_error(exc) from None
        _raise_flow(OAuthFlowErrorCode.COMMIT_UNCERTAIN, retryable=False)

    @staticmethod
    def _operation_is_active(
        *,
        home: Path,
        provider_id: str,
        operation_id: str,
        started: accounts.PersonalOAuthStartResult,
    ) -> bool:
        """Whether an uncertain lease write published our idempotency key."""

        try:
            snapshot = accounts.get_account_snapshot(
                home=home,
                provider_id=provider_id,
            )
        except accounts.ProviderAccountError as exc:
            raise _from_account_error(exc) from None
        lease = snapshot.oauth_lease
        return bool(
            lease is not None
            and lease.operation_id == operation_id
            and lease.store_instance_id == started.intent.store_instance_id
            and lease.ownership_epoch == started.intent.ownership_epoch
            and lease.active_request_id_at_start
            == started.intent.active_request_id_at_start
        )

    def reserve_start(
        self,
        *,
        home: Path,
        provider_id: str,
        flow: str,
        profile_name: str | None,
        expected_revision: int | None = None,
        takeover: bool = False,
    ) -> OAuthStartReservation:
        """Reserve or replay one profile/provider ceremony before network I/O."""

        if not isinstance(provider_id, str) or not provider_id.strip():
            _raise_flow(OAuthFlowErrorCode.INVALID_PROVIDER)
        provider_id = provider_id.strip()
        if flow not in FLOW_TYPES or not isinstance(takeover, bool):
            _raise_flow(OAuthFlowErrorCode.INVALID_INPUT)
        if expected_revision is not None and (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            _raise_flow(OAuthFlowErrorCode.INVALID_INPUT)

        owner = self._owner(home)
        self._retry_pending_releases(owner=owner, provider_id=provider_id)
        with self._lock:
            existing = self._find_pending_locked(owner, provider_id)
            if existing is not None and not takeover:
                return OAuthStartReservation(
                    session_id=str(existing["session_id"]),
                    session=existing,
                    created=False,
                    account_snapshot=existing.get("_account_snapshot"),
                )

            started: accounts.PersonalOAuthStartResult | None = None
            lease_result: accounts.OAuthLeaseResult | None = None
            if provider_id in PERSONAL_ACCOUNT_PROVIDERS:
                started = self._capture_personal_start(
                    home=owner.canonical_home,
                    provider_id=provider_id,
                    expected_revision=expected_revision,
                )
                lease_result = self._acquire_personal_lease(
                    home=owner.canonical_home,
                    provider_id=provider_id,
                    started=started,
                    takeover=takeover,
                )

            if existing is not None:
                self.signal_cancelled_locked(existing)

            session_id = secrets.token_urlsafe(24)
            while session_id in self._sessions:
                session_id = secrets.token_urlsafe(24)
            now = self._clock()
            pending_key = self._pending_key(owner, provider_id)
            session: dict[str, Any] = {
                "session_id": session_id,
                "provider": provider_id,
                "flow": flow,
                "profile": profile_name,
                "created_at": now,
                "status": "pending",
                "error_code": None,
                "error_message": None,
                "_registry_expires_at": now + self.ttl_seconds,
                "_terminal_at": None,
                "_cancel_event": threading.Event(),
                "_start_event": threading.Event(),
                "_start_response": None,
                "_stale_generation": False,
                "_release_pending": False,
                "_release_error_code": None,
                "_owner_key": owner.key,
                "_owner_home": owner.canonical_home,
                "_pending_key": pending_key,
                "_flow_trace_id": secrets.token_urlsafe(18),
                "_personal_started": started,
                "_lease_result": lease_result,
                "_account_snapshot": (
                    lease_result.snapshot
                    if lease_result is not None
                    else (started.snapshot if started is not None else None)
                ),
            }
            self._sessions[session_id] = session
            self._pending[pending_key] = session_id
            return OAuthStartReservation(
                session_id=session_id,
                session=session,
                created=True,
                account_snapshot=session.get("_account_snapshot"),
            )

    def publish_start(
        self,
        session_id: str,
        session: dict[str, Any],
        response: dict[str, Any],
    ) -> dict[str, Any]:
        allowed = {
            "flow",
            "auth_url",
            "user_code",
            "verification_url",
            "expires_in",
            "poll_interval",
        }
        public = {key: response[key] for key in allowed if key in response}
        public["session_id"] = session_id
        with self._lock:
            if self._sessions.get(session_id) is not session:
                _raise_flow(OAuthFlowErrorCode.NOT_FOUND)
            status = session.get("status")
            if status == "error" and session.get("error_code") is not None:
                _raise_flow(OAuthFlowErrorCode(session["error_code"]))
            if status not in {"pending", "approved"}:
                _raise_flow(OAuthFlowErrorCode.NOT_FOUND)
            if status == "pending" and self._cancel_event_locked(session).is_set():
                _raise_flow(OAuthFlowErrorCode.NOT_FOUND)
            if status == "pending" and not self._durable_is_current(session):
                self._cancel_stale_locked(session)
                _raise_flow(OAuthFlowErrorCode.NOT_FOUND)
            session["_start_response"] = dict(public)
            start_event = session.get("_start_event")
            if isinstance(start_event, threading.Event):
                start_event.set()
        return public

    def wait_for_start(
        self,
        reservation: OAuthStartReservation,
        *,
        timeout_seconds: float = 10,
    ) -> dict[str, Any]:
        session = reservation.session
        event = session.get("_start_event")
        if isinstance(event, threading.Event) and not event.wait(timeout_seconds):
            _raise_flow(OAuthFlowErrorCode.IO_UNAVAILABLE)
        with self._lock:
            if self._sessions.get(reservation.session_id) is not session:
                _raise_flow(OAuthFlowErrorCode.NOT_FOUND)
            if session.get("_stale_generation") is True:
                _raise_flow(OAuthFlowErrorCode.NOT_FOUND)
            if session.get("status") in {"cancelled", "expired"}:
                _raise_flow(OAuthFlowErrorCode.NOT_FOUND)
            if session.get("status") == "pending" and not self._durable_is_current(
                session
            ):
                self._cancel_stale_locked(session)
                _raise_flow(OAuthFlowErrorCode.NOT_FOUND)
            response = session.get("_start_response")
            if not isinstance(response, dict):
                code = session.get("error_code")
                if code is not None:
                    _raise_flow(OAuthFlowErrorCode(code))
                _raise_flow(OAuthFlowErrorCode.IO_UNAVAILABLE)
            return dict(response)

    def start_progress(
        self,
        session_id: str,
        session: dict[str, Any],
        *,
        fail_if_unready: bool = False,
    ) -> dict[str, Any]:
        """Return a bounded public start snapshot under the registry lock.

        Dashboard adapters call this method in a worker thread.  Keeping both
        the readiness read and timeout transition service-owned prevents an
        async request from entering the threading RLock and closes the race
        where a worker publishes a code between a timeout check and ``fail``.
        """

        release = False
        with self._lock:
            if self._sessions.get(session_id) is not session:
                _raise_flow(OAuthFlowErrorCode.NOT_FOUND)
            status = str(session.get("status") or "error")
            user_code = session.get("user_code")
            if fail_if_unready and status == "pending" and not user_code:
                session["status"] = "error"
                session["error_code"] = OAuthFlowErrorCode.IO_UNAVAILABLE.value
                session["error_message"] = stable_oauth_message(
                    OAuthFlowErrorCode.IO_UNAVAILABLE
                )
                session["_terminal_at"] = self._clock()
                self._cancel_event_locked(session).set()
                self._remove_pending_locked(session)
                session["_release_pending"] = isinstance(
                    session.get("_lease_result"),
                    accounts.OAuthLeaseResult,
                )
                session["_release_error_code"] = None
                event = session.get("_start_event")
                if isinstance(event, threading.Event):
                    event.set()
                status = "error"
                release = True
            result = {
                "status": status,
                "user_code": user_code,
                "verification_url": session.get("verification_url"),
                "expires_in": session.get("expires_in"),
                "interval": session.get("interval"),
            }
        if release:
            self._release_and_record(session)
        return result

    def _lookup_locked(
        self,
        *,
        owner: OAuthFlowOwner,
        provider_id: str,
        session_id: str,
        revalidate_generation: bool = True,
    ) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        # Absence, provider mismatch, and profile mismatch deliberately share
        # the same branch and public error.
        if (
            session is None
            or session.get("provider") != provider_id
            or session.get("_owner_key") != owner.key
        ):
            _raise_flow(OAuthFlowErrorCode.NOT_FOUND)
        if session.get("_stale_generation") is True:
            _raise_flow(OAuthFlowErrorCode.NOT_FOUND)
        if (
            revalidate_generation
            and session.get("status") == "pending"
            and not self._durable_is_current(session)
        ):
            self._cancel_stale_locked(session)
            _raise_flow(OAuthFlowErrorCode.NOT_FOUND)
        return session

    def owned_session(
        self,
        *,
        home: Path,
        provider_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        owner = self._owner(home)
        with self._lock:
            return self._lookup_locked(
                owner=owner,
                provider_id=provider_id,
                session_id=session_id,
            )

    def legacy_provider_for_owner(self, *, home: Path, session_id: str) -> str:
        owner = self._owner(home)
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.get("_owner_key") != owner.key:
                _raise_flow(OAuthFlowErrorCode.NOT_FOUND)
            provider_id = session.get("provider")
            if not isinstance(provider_id, str) or not provider_id:
                _raise_flow(OAuthFlowErrorCode.NOT_FOUND)
            return provider_id

    def _durable_is_current(self, session: dict[str, Any]) -> bool:
        if not self._owner_path_is_current(session):
            return False
        started = session.get("_personal_started")
        lease_result = session.get("_lease_result")
        home = session.get("_owner_home")
        provider_id = session.get("provider")
        if started is None and lease_result is None:
            return True
        if (
            not isinstance(started, accounts.PersonalOAuthStartResult)
            or not isinstance(lease_result, accounts.OAuthLeaseResult)
            or not isinstance(home, Path)
            or not isinstance(provider_id, str)
        ):
            return False
        try:
            snapshot = accounts.get_account_snapshot(home=home, provider_id=provider_id)
        except accounts.ProviderAccountError as exc:
            if exc.code is accounts.ProviderAccountErrorCode.NOT_FOUND:
                return False
            raise _from_account_error(exc) from None
        active = snapshot.oauth_lease
        lease = lease_result.lease
        return bool(
            active is not None
            and snapshot.oauth_generation == lease.generation
            and active.generation == lease.generation
            and active.operation_id == lease.operation_id
            and active.store_instance_id == lease.store_instance_id
            and active.ownership_epoch == started.intent.ownership_epoch
            and active.active_request_id_at_start
            == started.intent.active_request_id_at_start
        )

    @staticmethod
    def _owner_path_is_current(session: dict[str, Any]) -> bool:
        home = session.get("_owner_home")
        owner_key = session.get("_owner_key")
        if not isinstance(home, Path) or not isinstance(owner_key, tuple):
            return False
        try:
            stat_result = home.stat(follow_symlinks=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            return False
        return owner_key == (
            os.path.normcase(str(home)),
            stat_result.st_dev,
            stat_result.st_ino,
        )

    def _cancel_stale_locked(self, session: dict[str, Any]) -> None:
        """Stop a process-local worker whose durable generation moved on."""

        session["_stale_generation"] = True
        if session.get("status") == "pending":
            self.signal_cancelled_locked(session)

    def session_is_cancelled(self, session: dict[str, Any]) -> bool:
        with self._lock:
            status = session.get("status")
            if self._cancel_event_locked(session).is_set() or status != "pending":
                return True
            current = self._durable_is_current(session)
            if not current:
                self._cancel_stale_locked(session)
            return not current

    def worker_session(
        self,
        session_id: str,
    ) -> tuple[dict[str, Any], str | None] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.get("status") != "pending":
                return None
            try:
                cancelled = self.session_is_cancelled(session)
            except OAuthFlowError as exc:
                self.fail(session_id, session, exc.code)
                return None
            if cancelled:
                return None
            profile = session.get("profile")
            return session, profile if isinstance(profile, str) else None

    def poll(
        self,
        *,
        home: Path,
        provider_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        owner = self._owner(home)
        release: dict[str, Any] | None = None
        with self._lock:
            session = self._lookup_locked(
                owner=owner,
                provider_id=provider_id,
                session_id=session_id,
                revalidate_generation=False,
            )
            if (
                session.get("status") == "pending"
                and self._session_deadline(session) <= self._clock()
            ):
                session["status"] = "expired"
                session["error_code"] = None
                session["error_message"] = None
                session["_terminal_at"] = self._clock()
                self._cancel_event_locked(session).set()
                self._remove_pending_locked(session)
                release = session
            elif session.get("status") == "pending" and not self._durable_is_current(
                session
            ):
                self._cancel_stale_locked(session)
                _raise_flow(OAuthFlowErrorCode.NOT_FOUND)
            status = str(session.get("status") or "error")
            response = {
                "session_id": session_id,
                "status": status,
                "error_message": session.get("error_message"),
                "expires_at": session.get("expires_at"),
            }
            if session.get("error_code") is not None:
                response["error_code"] = session["error_code"]
        if release is not None:
            self._release_and_record(release)
        return response

    def signal_cancelled_locked(
        self,
        session: dict[str, Any],
        *,
        status: str = "cancelled",
    ) -> None:
        if status not in {"cancelled", "expired"}:
            status = "cancelled"
        session["status"] = status
        session["error_code"] = None
        session["error_message"] = None
        session["_terminal_at"] = self._clock()
        self._cancel_event_locked(session).set()
        self._remove_pending_locked(session)
        session["_release_pending"] = isinstance(
            session.get("_lease_result"),
            accounts.OAuthLeaseResult,
        )
        session["_release_error_code"] = None
        start_event = session.get("_start_event")
        if isinstance(start_event, threading.Event):
            start_event.set()

    def cancel(
        self,
        *,
        home: Path,
        provider_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        owner = self._owner(home)
        release: dict[str, Any] | None = None
        with self._lock:
            session = self._lookup_locked(
                owner=owner,
                provider_id=provider_id,
                session_id=session_id,
            )
            status = str(session.get("status") or "error")
            if status == "pending":
                self.signal_cancelled_locked(session)
                release = session
            elif status == "cancelled" and session.get("_release_pending") is True:
                # A prior cancel stopped the worker but could not confirm its
                # durable lease release. Repeating the exact cancel is safe.
                release = session
            else:
                return {"ok": False, "session_id": session_id, "status": status}
        release_error = self._release_and_record(release)
        if release_error is not None:
            raise release_error
        return {"ok": True, "session_id": session_id}

    def expire_if_active(
        self,
        session_id: str,
        session: dict[str, Any],
    ) -> bool:
        """Expire one worker-owned pending session and release its exact lease."""

        release = False
        with self._lock:
            if (
                self._sessions.get(session_id) is not session
                or session.get("status") != "pending"
            ):
                return False
            self.signal_cancelled_locked(session, status="expired")
            release = True
        if release:
            self._release_and_record(session)
        return True

    def fail(
        self,
        session_id: str,
        session: dict[str, Any],
        code: OAuthFlowErrorCode = OAuthFlowErrorCode.IO_UNAVAILABLE,
        *,
        remove: bool = False,
    ) -> None:
        with self._lock:
            release = self._mark_failed_locked(session_id, session, code)
        if release:
            release_error = self._release_and_record(session)
            if remove and release_error is None:
                with self._lock:
                    if self._sessions.get(session_id) is session:
                        self._sessions.pop(session_id, None)

    def stabilize_worker_process_control(self, session_id: str) -> None:
        """Terminalize a signal-interrupted worker and settle its exact lease.

        Web worker entry points call this from a ``BaseException`` boundary
        before re-raising the original ``KeyboardInterrupt`` or ``SystemExit``.
        Cleanup failures never replace that process-control signal: the retained
        session remains the exact retry handle for shutdown, GC, or a later
        explicit cancellation.
        """

        try:
            session: dict[str, Any] | None
            release = False
            with self._lock:
                candidate = self._sessions.get(session_id)
                session = candidate if isinstance(candidate, dict) else None
                if session is None:
                    return
                if session.get("status") == "pending":
                    release = self._mark_failed_locked(
                        session_id,
                        session,
                        OAuthFlowErrorCode.IO_UNAVAILABLE,
                    )
                elif session.get("_release_pending") is True:
                    release = True
            if release:
                self._release_and_record(session)
        except BaseException:
            # Even if stabilization itself receives another process-control
            # signal, preserve the entry point's original signal and leave an
            # observable exact-release handle.  Keep this fallback independent
            # of the ordinary marking helper so an interruption inside that
            # helper cannot leave the session pending.
            with self._lock:
                candidate = self._sessions.get(session_id)
                if not isinstance(candidate, dict):
                    return
                if candidate.get("status") == "pending":
                    candidate["status"] = "error"
                    candidate["error_code"] = OAuthFlowErrorCode.IO_UNAVAILABLE.value
                    candidate["error_message"] = stable_oauth_message(
                        OAuthFlowErrorCode.IO_UNAVAILABLE
                    )
                    try:
                        candidate["_terminal_at"] = self._clock()
                    except BaseException:
                        candidate["_terminal_at"] = time.time()
                    self._cancel_event_locked(candidate).set()
                    self._remove_pending_locked(candidate)
                    event = candidate.get("_start_event")
                    if isinstance(event, threading.Event):
                        event.set()
                candidate["_release_pending"] = isinstance(
                    candidate.get("_lease_result"),
                    accounts.OAuthLeaseResult,
                )
                candidate["_release_error_code"] = (
                    OAuthFlowErrorCode.IO_UNAVAILABLE.value
                    if candidate["_release_pending"]
                    else None
                )

    def _mark_failed_locked(
        self,
        session_id: str,
        session: dict[str, Any],
        code: OAuthFlowErrorCode,
    ) -> bool:
        """Stabilize one current pending session before external cleanup."""

        if (
            self._sessions.get(session_id) is not session
            or session.get("status") != "pending"
        ):
            return False
        session["status"] = "error"
        session["error_code"] = code.value
        session["error_message"] = stable_oauth_message(code)
        session["_terminal_at"] = self._clock()
        self._cancel_event_locked(session).set()
        self._remove_pending_locked(session)
        session["_release_pending"] = isinstance(
            session.get("_lease_result"),
            accounts.OAuthLeaseResult,
        )
        session["_release_error_code"] = None
        event = session.get("_start_event")
        if isinstance(event, threading.Event):
            event.set()
        return True

    def _matching_completion(
        self,
        session: dict[str, Any],
    ) -> accounts.OAuthCompletionResult | None:
        started = session.get("_personal_started")
        lease_result = session.get("_lease_result")
        home = session.get("_owner_home")
        provider_id = session.get("provider")
        if (
            not isinstance(started, accounts.PersonalOAuthStartResult)
            or not isinstance(lease_result, accounts.OAuthLeaseResult)
            or not isinstance(home, Path)
            or not isinstance(provider_id, str)
        ):
            return None
        try:
            snapshot = accounts.get_account_snapshot(home=home, provider_id=provider_id)
        except accounts.ProviderAccountError:
            return None
        completion = snapshot.oauth_completion
        lease = lease_result.lease
        if (
            completion is None
            or completion.generation != lease.generation
            or completion.operation_id != lease.operation_id
            or completion.store_instance_id != lease.store_instance_id
            or completion.ownership_epoch != started.intent.ownership_epoch
            or completion.active_request_id_at_start
            != started.intent.active_request_id_at_start
        ):
            return None
        return accounts.OAuthCompletionResult(
            snapshot=snapshot,
            operation_id=completion.operation_id,
            superseded_request_id=completion.superseded_request_id,
            intent_matched=completion.intent_matched,
            replayed=True,
        )

    def commit_if_active(
        self,
        session_id: str,
        session: dict[str, Any],
        credential_writer: Callable[[], None],
    ) -> bool:
        """Linearize cancellation and stabilize signal-interrupted commits."""

        try:
            return self._commit_if_active(
                session_id,
                session,
                credential_writer,
            )
        except (KeyboardInterrupt, SystemExit):
            # The implementation's registry lock has unwound.  Record a stable
            # terminal state before touching the durable lease, then preserve
            # the original process-control signal even if cleanup is itself
            # interrupted.
            with self._lock:
                release = self._mark_failed_locked(
                    session_id,
                    session,
                    OAuthFlowErrorCode.IO_UNAVAILABLE,
                )
            if release:
                try:
                    self._release_and_record(session)
                except BaseException:
                    with self._lock:
                        session["_release_pending"] = True
                        session["_release_error_code"] = (
                            OAuthFlowErrorCode.IO_UNAVAILABLE.value
                        )
            raise

    def _commit_if_active(
        self,
        session_id: str,
        session: dict[str, Any],
        credential_writer: Callable[[], None],
    ) -> bool:
        """Implement one commit while holding the registry linearization lock."""

        if not callable(credential_writer):
            _raise_flow(OAuthFlowErrorCode.INVALID_INPUT)
        with self._lock:
            if (
                self._sessions.get(session_id) is not session
                or session.get("status") != "pending"
                or self._cancel_event_locked(session).is_set()
            ):
                return False
            if not self._durable_is_current(session):
                self._cancel_stale_locked(session)
                return False
            started = session.get("_personal_started")
            lease_result = session.get("_lease_result")
            if started is None and lease_result is None:
                try:
                    credential_writer()
                except Exception:
                    self.fail(session_id, session, OAuthFlowErrorCode.IO_UNAVAILABLE)
                    return False
                completed_snapshot = None
            else:
                if not isinstance(
                    started, accounts.PersonalOAuthStartResult
                ) or not isinstance(lease_result, accounts.OAuthLeaseResult):
                    self.fail(session_id, session, OAuthFlowErrorCode.INVALID_STATE)
                    return False
                lease = lease_result.lease
                completed = None
                for attempt in range(2):
                    try:
                        completed = accounts.persist_personal_oauth_completion(
                            home=session["_owner_home"],
                            provider_id=str(session["provider"]),
                            generation=lease.generation,
                            operation_id=lease.operation_id,
                            credential_writer=lambda _operation_id: credential_writer(),
                            captured_intent=started.intent,
                        )
                        break
                    except accounts.ProviderAccountError as exc:
                        if exc.code is accounts.ProviderAccountErrorCode.NOT_FOUND:
                            self.signal_cancelled_locked(session)
                            return False
                        if (
                            exc.code
                            in {
                                accounts.ProviderAccountErrorCode.IO_UNAVAILABLE,
                                accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN,
                            }
                            and attempt == 0
                        ):
                            durable = self._matching_completion(session)
                            if durable is not None:
                                completed = durable
                                break
                            continue
                        code = _from_account_error(exc).code
                        self.fail(session_id, session, code)
                        return False
                if completed is None:
                    self.fail(
                        session_id,
                        session,
                        OAuthFlowErrorCode.COMMIT_UNCERTAIN,
                    )
                    return False
                completed_snapshot = completed.snapshot
            session["status"] = "approved"
            session["error_code"] = None
            session["error_message"] = None
            session["_terminal_at"] = self._clock()
            session["_account_snapshot"] = completed_snapshot
            session["_release_pending"] = False
            session["_release_error_code"] = None
            self._remove_pending_locked(session)
            return True

    def _release_durable(
        self,
        session: dict[str, Any],
    ) -> OAuthFlowError | None:
        """Confirm that this exact durable lease is no longer active."""

        lease_result = session.get("_lease_result")
        started = session.get("_personal_started")
        home = session.get("_owner_home")
        provider_id = session.get("provider")
        if (
            not isinstance(lease_result, accounts.OAuthLeaseResult)
            or not isinstance(started, accounts.PersonalOAuthStartResult)
            or not isinstance(home, Path)
            or not isinstance(provider_id, str)
        ):
            return None
        return release_exact_oauth_lease(
            home=home,
            provider_id=provider_id,
            captured_intent=started.intent,
            lease_result=lease_result,
        )

    def _release_and_record(
        self,
        session: dict[str, Any],
    ) -> OAuthFlowError | None:
        try:
            error = self._release_durable(session)
        except OAuthFlowError as exc:
            error = exc
        except Exception:
            error = OAuthFlowError(OAuthFlowErrorCode.IO_UNAVAILABLE)
        with self._lock:
            session["_release_pending"] = error is not None
            session["_release_error_code"] = (
                error.code.value if error is not None else None
            )
        return error

    def _retry_pending_releases(
        self,
        *,
        owner: OAuthFlowOwner,
        provider_id: str,
    ) -> None:
        with self._lock:
            pending = [
                session
                for session in self._sessions.values()
                if session.get("_owner_key") == owner.key
                and session.get("provider") == provider_id
                and session.get("_release_pending") is True
            ]
        for session in pending:
            error = self._release_and_record(session)
            if error is not None:
                raise error

    def gc(self) -> None:
        now = self._clock()
        releases: list[dict[str, Any]] = []
        with self._lock:
            for session_id, session in list(self._sessions.items()):
                status = str(session.get("status") or "error")
                if status == "pending" and self._session_deadline(session) <= now:
                    self.signal_cancelled_locked(session, status="expired")
                    releases.append(session)
                    continue
                if (
                    status in TERMINAL_STATUSES
                    and session.get("_release_pending") is True
                ):
                    releases.append(session)
        for session in releases:
            self._release_and_record(session)
        with self._lock:
            for session_id, session in list(self._sessions.items()):
                status = str(session.get("status") or "error")
                terminal_at = session.get("_terminal_at")
                if (
                    status in TERMINAL_STATUSES
                    and session.get("_release_pending") is not True
                    and isinstance(terminal_at, (int, float))
                    and terminal_at + self.terminal_retention_seconds <= now
                ):
                    self._sessions.pop(session_id, None)

    def shutdown(self) -> dict[str, int]:
        """Cancel workers and synchronously release every retained lease.

        The web adapter calls this in a worker thread during graceful shutdown.
        Sessions whose exact durable release cannot be confirmed remain in the
        registry with ``_release_pending`` set so a repeated shutdown attempt is
        safe and observable in tests; confirmed/generic sessions are discarded.
        No provider response, path, operation id, or credential is returned.
        """

        releases: list[dict[str, Any]] = []
        cancelled = 0
        with self._lock:
            for session in list(self._sessions.values()):
                if session.get("status") == "pending":
                    self.signal_cancelled_locked(session)
                    cancelled += 1
                if session.get("_release_pending") is True:
                    releases.append(session)

        failures = 0
        for session in releases:
            if self._release_and_record(session) is not None:
                failures += 1

        with self._lock:
            for session_id, session in list(self._sessions.items()):
                if session.get("_release_pending") is not True:
                    self._remove_pending_locked(session)
                    self._sessions.pop(session_id, None)
            # ``signal_cancelled_locked`` removes all live entries. Rebuild
            # defensively from retained failures rather than carrying stale ids.
            self._pending = {
                key: session_id
                for key, session_id in self._pending.items()
                if session_id in self._sessions
            }
        return {
            "cancelled": cancelled,
            "release_attempts": len(releases),
            "release_failures": failures,
        }

    def trace_id(self, session: dict[str, Any]) -> str:
        trace = session.get("_flow_trace_id")
        return trace if isinstance(trace, str) else "unavailable"


oauth_flow_service = OAuthFlowService()


__all__ = [
    "OAuthFlowError",
    "OAuthFlowErrorCode",
    "OAuthFlowOwner",
    "OAuthFlowService",
    "OAuthStartReservation",
    "PERSONAL_ACCOUNT_PROVIDERS",
    "oauth_error_http_status",
    "oauth_flow_service",
    "release_exact_oauth_lease",
    "serialize_oauth_error",
    "stable_oauth_message",
]
