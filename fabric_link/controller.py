"""Crash-safe enrollment and application client for Link controller surfaces."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .application import LinkApplicationController, LinkApplicationError
from .controller_profile import (
    ControllerPendingApplication,
    ControllerProfile,
    ControllerProfileError,
    ControllerProfileStore,
    ControllerSecretBundle,
)
from .core import LinkCryptoCore
from .enrollment import (
    EnrollmentRequest,
    build_enrollment_request,
    decrypt_enrollment_response,
)
from .protocol import (
    LinkRequest,
    LinkResponse,
    PairingPayload,
)
from .relay_auth import create_controller_authentication
from .relay_client import LinkRelayClient, LinkRelayClientError
from .relay_contract import (
    RelayAcknowledgement,
    RelayChallenge,
    RelayEnrollmentAcknowledgement,
    RelayEnrollmentDelivery,
    RelayEnrollmentMailbox,
    RelayEnrollmentPoll,
    RelayEnrollmentPublish,
    RelayMailbox,
    RelayDelivery,
    RelayPoll,
    RelayPublish,
)


class LinkControllerError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ControllerEnrollmentStart:
    profile: ControllerProfile
    encrypted_request: bytes
    short_auth_string: str


@dataclass(frozen=True)
class PendingControllerRequest:
    request_id: bytes
    message_id: bytes
    expires_at: int
    envelope: bytes


def _advance_relay_cursor(
    *,
    after_sequence: int,
    deliveries: Sequence[RelayDelivery | RelayEnrollmentDelivery],
    high_watermark: int,
) -> int:
    """Advance through one bounded page without skipping undispatched rows."""
    if deliveries:
        return max(after_sequence, deliveries[-1].sequence)
    return max(after_sequence, high_watermark)


def start_controller_enrollment(
    *,
    profiles: ControllerProfileStore,
    core: LinkCryptoCore,
    payload: PairingPayload,
    label: str,
    platform: str,
    requested_grants: tuple[str, ...],
    now: int,
) -> ControllerEnrollmentStart:
    """Create and persist controller authority before sending a pairing request."""

    relay_private_key = Ed25519PrivateKey.generate()
    relay_private_bytes = relay_private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    relay_public_key = relay_private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    bootstrap = core.create_controller(
        identity=b"fabric-link-controller:" + secrets.token_bytes(32)
    )
    request, encrypted_request = build_enrollment_request(
        payload=payload,
        controller_name=label,
        platform=platform,
        requested_grants=requested_grants,
        relay_public_key=relay_public_key,
        key_package=bootstrap.key_package,
        now=now,
    )
    profile = profiles.create_pending(
        label=label,
        platform=platform,
        payload=payload,
        secret_bundle=ControllerSecretBundle(
            opaque_state=bootstrap.opaque_state,
            relay_private_key=relay_private_bytes,
            pairing_payload=payload.to_cbor(),
            enrollment_request=request.to_cbor(),
        ),
        now=now,
    )
    return ControllerEnrollmentStart(
        profile=profile,
        encrypted_request=encrypted_request,
        short_auth_string=_short_auth_string(payload, request),
    )


def finish_controller_enrollment(
    *,
    profiles: ControllerProfileStore,
    core: LinkCryptoCore,
    controller_id: str,
    encrypted_response: bytes,
    now: int,
) -> ControllerProfile:
    """Verify the pinned machine response and atomically activate the profile."""

    profile = profiles.get(controller_id)
    if profile is None or profile.status != "pending":
        raise LinkControllerError("controller_enrollment_not_pending")
    bundle = profiles.load_secret(controller_id)
    if bundle.pairing_payload is None or bundle.enrollment_request is None:
        raise LinkControllerError("controller_enrollment_state_missing")
    try:
        payload = PairingPayload.from_cbor(
            bundle.pairing_payload,
            now=now,
            allow_loopback_http=True,
        )
        request = EnrollmentRequest.from_cbor(bundle.enrollment_request)
        result = decrypt_enrollment_response(
            payload=payload,
            request=request,
            encrypted_response=encrypted_response,
            now=now,
        )
        joined_state = core.join_controller(
            opaque_state=bundle.opaque_state,
            welcome=result.welcome,
        )
        active_bundle = ControllerSecretBundle(
            opaque_state=joined_state,
            relay_private_key=bundle.relay_private_key,
            credential_serial=result.credential_serial,
            admission_certificate=result.admission_certificate,
            grants=result.approved_grants,
        )
        return profiles.activate(
            controller_id,
            credential_serial=result.credential_serial,
            admission_certificate=result.admission_certificate,
            grants=result.approved_grants,
            active_bundle=active_bundle,
            now=now,
        )
    except (ControllerProfileError, LinkControllerError):
        raise
    except Exception as exc:
        raise LinkControllerError("controller_enrollment_failed") from exc


class PersistentLinkController:
    """Single-owner controller MLS state with a vault-atomic encrypted outbox."""

    def __init__(
        self,
        *,
        profiles: ControllerProfileStore,
        core: LinkCryptoCore,
        controller_id: str,
    ) -> None:
        self._profiles = profiles
        self._core = core
        self.controller_id = controller_id
        self._lock = threading.RLock()
        self._active_profile()

    @property
    def profile(self) -> ControllerProfile:
        return self._active_profile()

    def create_authentication(
        self,
        challenge: RelayChallenge,
        *,
        now: int,
    ):
        with self._lock:
            profile = self._active_profile()
            bundle = self._profiles.load_secret(self.controller_id)
            if (
                profile.credential_serial is None
                or profile.admission_certificate is None
            ):
                raise LinkControllerError("controller_admission_missing")
            return create_controller_authentication(
                route_id=profile.route_id,
                credential_serial=profile.credential_serial,
                admission_certificate=profile.admission_certificate,
                controller_private_key=bundle.relay_private_key_object,
                challenge=challenge,
                relay_origin=profile.relay_origin,
                now=now,
            )

    def encrypt_request(
        self,
        request: LinkRequest,
        *,
        now: int | None = None,
    ) -> PendingControllerRequest:
        with self._lock:
            profile = self._active_profile()
            current_time = int(time.time()) if now is None else now
            bundle = self._profiles.load_secret(self.controller_id)
            pending = bundle.pending_application
            if pending is not None and pending.expires_at <= current_time:
                bundle = replace(bundle, pending_application=None)
                self._profiles.store_secret(self.controller_id, bundle)
                pending = None
            if pending is not None:
                if pending.request_id != request.request_id:
                    raise LinkControllerError("controller_request_in_flight")
                return PendingControllerRequest(
                    request_id=pending.request_id,
                    message_id=pending.message_id,
                    expires_at=pending.expires_at,
                    envelope=pending.envelope,
                )
            if profile.credential_serial is None:
                raise LinkControllerError("controller_admission_missing")
            controller = LinkApplicationController(
                core=self._core,
                route_id=profile.route_id,
                credential_serial=profile.credential_serial,
                opaque_state=bundle.opaque_state,
            )
            try:
                envelope = controller.encrypt_request(request)
            except LinkApplicationError as exc:
                raise LinkControllerError(exc.code) from exc
            pending = ControllerPendingApplication(
                request_id=request.request_id,
                message_id=secrets.token_bytes(16),
                expires_at=request.expires_at,
                envelope=envelope,
            )
            self._profiles.store_secret(
                self.controller_id,
                replace(
                    bundle,
                    opaque_state=controller.opaque_state,
                    pending_application=pending,
                ),
            )
            return PendingControllerRequest(
                request_id=pending.request_id,
                message_id=pending.message_id,
                expires_at=pending.expires_at,
                envelope=pending.envelope,
            )

    def decrypt_response(self, delivery_cbor: bytes) -> LinkResponse:
        with self._lock:
            profile = self._active_profile()
            bundle = self._profiles.load_secret(self.controller_id)
            pending = bundle.pending_application
            if pending is None or profile.credential_serial is None:
                raise LinkControllerError("controller_request_not_in_flight")
            controller = LinkApplicationController(
                core=self._core,
                route_id=profile.route_id,
                credential_serial=profile.credential_serial,
                opaque_state=bundle.opaque_state,
            )
            try:
                response = controller.decrypt_response(delivery_cbor)
            except LinkApplicationError as exc:
                raise LinkControllerError(exc.code) from exc
            if response.request_id != pending.request_id:
                self._profiles.store_secret(
                    self.controller_id,
                    replace(
                        bundle,
                        opaque_state=controller.opaque_state,
                    ),
                )
                raise LinkControllerError("controller_response_request_mismatch")
            self._profiles.store_secret(
                self.controller_id,
                replace(
                    bundle,
                    opaque_state=controller.opaque_state,
                    pending_application=None,
                ),
            )
            return response

    def abandon_expired_request(self, *, now: int) -> bool:
        with self._lock:
            return self._profiles.clear_expired_pending_application(
                self.controller_id,
                now=now,
            )

    def _active_profile(self) -> ControllerProfile:
        profile = self._profiles.get(self.controller_id)
        if profile is None:
            raise LinkControllerError("controller_profile_not_found")
        if profile.status != "active":
            raise LinkControllerError("controller_profile_not_active")
        return profile


class ControllerRelaySession:
    """Synchronous invoke path used by CLI and the local Desktop backend."""

    def __init__(
        self,
        *,
        controller: PersistentLinkController,
        timeout_seconds: float = 60.0,
        poll_interval_seconds: float = 0.25,
        client_factory=LinkRelayClient,
    ) -> None:
        if timeout_seconds <= 0 or poll_interval_seconds <= 0:
            raise LinkControllerError("invalid_controller_timeout")
        self._controller = controller
        self._timeout = timeout_seconds
        self._poll_interval = min(poll_interval_seconds, 5.0)
        self._client_factory = client_factory

    def invoke(self, request: LinkRequest) -> LinkResponse:
        pending = self._controller.encrypt_request(request)
        profile = self._controller.profile
        if profile.credential_serial is None:
            raise LinkControllerError("controller_admission_missing")
        now_for_auth = lambda: int(time.time())
        client = self._client_factory(
            relay_origin=profile.relay_origin,
            authentication_factory=lambda challenge: (
                self._controller.create_authentication(
                    challenge,
                    now=now_for_auth(),
                )
            ),
        )
        deadline = time.monotonic() + self._timeout
        try:
            client.connect()
            request_mailbox = RelayMailbox(
                route_id=profile.route_id,
                credential_serial=profile.credential_serial,
                recipient="host",
            )
            client.publish(
                RelayPublish(
                    mailbox=request_mailbox,
                    message_id=pending.message_id,
                    expires_at=pending.expires_at,
                    opaque_record=pending.envelope,
                )
            )
            response_mailbox = RelayMailbox(
                route_id=profile.route_id,
                credential_serial=profile.credential_serial,
                recipient="controller",
            )
            after_sequence = 0
            while time.monotonic() < deadline:
                deliveries, sync = client.poll(
                    RelayPoll(
                        mailbox=response_mailbox,
                        request_id=secrets.token_bytes(16),
                        after_sequence=after_sequence,
                        limit=10,
                    )
                )
                after_sequence = _advance_relay_cursor(
                    after_sequence=after_sequence,
                    deliveries=deliveries,
                    high_watermark=sync.high_watermark,
                )
                for delivery in deliveries:
                    try:
                        response = self._controller.decrypt_response(
                            delivery.opaque_record
                        )
                    except LinkControllerError as exc:
                        if exc.code == "controller_response_request_mismatch":
                            client.acknowledge(
                                RelayAcknowledgement(
                                    mailbox=response_mailbox,
                                    sequence=delivery.sequence,
                                    message_id=delivery.message_id,
                                )
                            )
                            continue
                        raise
                    client.acknowledge(
                        RelayAcknowledgement(
                            mailbox=response_mailbox,
                            sequence=delivery.sequence,
                            message_id=delivery.message_id,
                        )
                    )
                    return response
                time.sleep(self._poll_interval)
        except (LinkRelayClientError, ControllerProfileError) as exc:
            raise LinkControllerError(
                getattr(exc, "code", "controller_relay_failed")
            ) from exc
        finally:
            client.close()
        raise LinkControllerError("controller_response_timeout")


def publish_enrollment_request(
    *,
    start: ControllerEnrollmentStart,
    payload: PairingPayload,
    client_factory=LinkRelayClient,
) -> None:
    with client_factory(
        relay_origin=payload.relay,
        authentication_factory=None,
    ) as client:
        client.publish_enrollment(
            RelayEnrollmentPublish(
                mailbox=RelayEnrollmentMailbox(
                    route_id=payload.route,
                    pairing_handle=payload.handle,
                    recipient="host",
                ),
                message_id=secrets.token_bytes(16),
                expires_at=payload.expires_at,
                opaque_record=start.encrypted_request,
            )
        )


def await_enrollment_response(
    *,
    payload: PairingPayload,
    timeout_seconds: float = 300,
    poll_interval_seconds: float = 0.5,
    client_factory=LinkRelayClient,
) -> bytes:
    deadline = time.monotonic() + timeout_seconds
    with client_factory(
        relay_origin=payload.relay,
        authentication_factory=None,
    ) as client:
        mailbox = RelayEnrollmentMailbox(
            route_id=payload.route,
            pairing_handle=payload.handle,
            recipient="controller",
        )
        after_sequence = 0
        while time.monotonic() < deadline:
            deliveries, sync = client.poll_enrollment(
                RelayEnrollmentPoll(
                    mailbox=mailbox,
                    request_id=secrets.token_bytes(16),
                    after_sequence=after_sequence,
                )
            )
            after_sequence = _advance_relay_cursor(
                after_sequence=after_sequence,
                deliveries=deliveries,
                high_watermark=sync.high_watermark,
            )
            if deliveries:
                delivery = deliveries[0]
                client.acknowledge_enrollment(
                    RelayEnrollmentAcknowledgement(
                        mailbox=mailbox,
                        sequence=delivery.sequence,
                        message_id=delivery.message_id,
                    )
                )
                return delivery.opaque_record
            time.sleep(min(max(poll_interval_seconds, 0.05), 5.0))
    raise LinkControllerError("controller_enrollment_timeout")


def _short_auth_string(
    payload: PairingPayload,
    request: EnrollmentRequest,
) -> str:
    import hashlib

    transcript = hashlib.sha256(payload.to_cbor() + request.to_cbor()).digest()
    return f"{int.from_bytes(transcript[:4], 'big') % 1_000_000:06d}"
