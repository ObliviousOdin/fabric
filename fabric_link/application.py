"""Encrypted Fabric Link application records and an in-memory relay conformance harness.

This module owns no socket, listener, identity provider, or model tool. It
proves the security ordering required before a blind relay is introduced:
opaque MLS record -> decrypt/authenticate -> grant/replay authorization ->
existing dispatcher -> encrypted response.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from typing import Any

from .authorization import LinkAuthorizationError, check_link_request
from .capabilities import grant_for_method
from .core import LinkCryptoCore
from .protocol import (
    MAX_PARAMS_BYTES,
    LinkApplicationEnvelope,
    LinkProtocolError,
    LinkRequest,
    LinkResponse,
    canonical_dumps,
    canonical_loads,
)
from .store import LinkDevice, LinkDeviceStore, LinkStorageError


class LinkApplicationError(RuntimeError):
    """A non-sensitive failure while carrying one encrypted Link application record."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class LinkApplicationDispatchRejected(RuntimeError):
    """A reviewed dispatcher returned a stable client-safe rejection."""

    def __init__(self, code: str = "rpc_rejected") -> None:
        self.code = code
        super().__init__(code)


ApplicationDispatcher = Callable[[LinkDevice, LinkRequest, dict[str, Any]], Any]


@dataclass(frozen=True)
class PreparedLinkApplicationResponse:
    device: LinkDevice
    request: LinkRequest
    expected_host_state: bytes = field(repr=False)
    evolved_host_state: bytes = field(repr=False)
    response_record: bytes = field(repr=False)
    audit_decision: str
    audit_error_code: str | None


class LinkApplicationController:
    """One paired controller's in-memory MLS application state.

    Production surfaces must replace ``opaque_state`` in their platform secure
    store after each successful method. This small object deliberately has no
    persistence implementation so it cannot fall back to renderer, preference,
    or plain-file storage.
    """

    def __init__(
        self,
        *,
        core: LinkCryptoCore,
        route_id: bytes,
        credential_serial: bytes,
        opaque_state: bytes,
    ) -> None:
        self._core = core
        self._route_id = route_id
        self._credential_serial = credential_serial
        self._opaque_state = opaque_state
        # Validate all public routing fields before a caller can produce a
        # first record. A placeholder ciphertext is never transmitted.
        LinkApplicationEnvelope(
            route_id=route_id,
            credential_serial=credential_serial,
            ciphertext=b"validation",
        )

    @property
    def opaque_state(self) -> bytes:
        return self._opaque_state

    def encrypt_request(self, request: LinkRequest) -> bytes:
        try:
            update = self._core.controller_encrypt(
                opaque_state=self._opaque_state,
                plaintext=request.to_cbor(),
            )
        except Exception as exc:
            raise LinkApplicationError("controller_encrypt_failed") from exc
        self._opaque_state = update.opaque_state
        return LinkApplicationEnvelope(
            route_id=self._route_id,
            credential_serial=self._credential_serial,
            ciphertext=update.message,
        ).to_cbor()

    def decrypt_response(self, delivery_cbor: bytes) -> LinkResponse:
        envelope = _parse_envelope(delivery_cbor)
        if not (
            hmac.compare_digest(envelope.route_id, self._route_id)
            and hmac.compare_digest(
                envelope.credential_serial,
                self._credential_serial,
            )
        ):
            raise LinkApplicationError("response_recipient_mismatch")
        try:
            decrypted = self._core.decrypt_controller(
                opaque_state=self._opaque_state,
                message=envelope.ciphertext,
            )
        except Exception as exc:
            raise LinkApplicationError("response_decrypt_failed") from exc
        self._opaque_state = decrypted.opaque_state
        try:
            return LinkResponse.from_cbor(decrypted.plaintext)
        except LinkProtocolError as exc:
            raise LinkApplicationError("invalid_encrypted_response") from exc


class LinkApplicationHost:
    """The host-side MLS, authorization, and dispatch boundary for one machine."""

    def __init__(
        self,
        *,
        core: LinkCryptoCore,
        store: LinkDeviceStore,
        registered_methods: Collection[str],
        dispatch: ApplicationDispatcher,
    ) -> None:
        self._core = core
        self._store = store
        self._registered_methods = frozenset(registered_methods)
        self._dispatch = dispatch

    def receive(self, delivery_cbor: bytes, *, now: int) -> bytes:
        prepared = self.prepare(delivery_cbor, now=now)
        try:
            self._store.commit_application_response(
                device=prepared.device,
                expected_host_state=prepared.expected_host_state,
                evolved_host_state=prepared.evolved_host_state,
                request_id=prepared.request.request_id,
                request_expires_at=prepared.request.expires_at,
                method_class=grant_for_method(prepared.request.method),
                decision=prepared.audit_decision,
                error_code=prepared.audit_error_code,
                response_record=prepared.response_record,
                now=now,
            )
        except LinkStorageError as exc:
            raise LinkApplicationError(exc.code) from exc
        return prepared.response_record

    def prepare(
        self,
        delivery_cbor: bytes,
        *,
        now: int,
    ) -> PreparedLinkApplicationResponse:
        """Build a response without advancing persistent host state.

        The broker commits the evolved MLS state, replay claim, audit record,
        and durable ciphertext outbox in one SQLite transaction.
        """
        envelope = _parse_envelope(delivery_cbor)
        identity = self._store.machine_identity()
        if not hmac.compare_digest(envelope.route_id, identity.route_id):
            raise LinkApplicationError("unknown_route")
        try:
            device = self._store.require_active_by_credential_serial(
                envelope.credential_serial
            )
        except LinkStorageError as exc:
            raise LinkApplicationError("device_not_active") from exc
        try:
            decrypted = self._core.host_decrypt(
                opaque_state=device.host_state,
                message=envelope.ciphertext,
            )
        except Exception as exc:
            raise LinkApplicationError("request_decrypt_failed") from exc
        try:
            request = LinkRequest.from_cbor(decrypted.plaintext)
        except LinkProtocolError as exc:
            raise LinkApplicationError("invalid_encrypted_request") from exc
        if self._store.request_id_claimed(
            device_id=device.device_id,
            request_id=request.request_id,
        ):
            raise LinkApplicationError("request_replayed")

        audit_decision = "allow"
        audit_error_code = None
        try:
            check_link_request(
                device=device,
                method=request.method,
                now=now,
                request=request,
                registered_methods=self._registered_methods,
            )
        except LinkAuthorizationError as exc:
            response = LinkResponse(
                request_id=request.request_id,
                completed_at=now,
                ok=False,
                result_cbor=None,
                error_code=exc.code,
            )
            audit_decision = "deny"
            audit_error_code = exc.code
        else:
            try:
                params = canonical_loads(
                    request.params_cbor,
                    maximum=MAX_PARAMS_BYTES,
                    expected_type=dict,
                )
                result = self._dispatch(device, request, params)
                response = LinkResponse(
                    request_id=request.request_id,
                    completed_at=now,
                    ok=True,
                    result_cbor=canonical_dumps(result),
                    error_code=None,
                )
            except LinkApplicationDispatchRejected as exc:
                response = LinkResponse(
                    request_id=request.request_id,
                    completed_at=now,
                    ok=False,
                    result_cbor=None,
                    error_code=exc.code,
                )
            except Exception:
                # Dispatcher failures remain private to the host; callers receive
                # a stable encrypted error and no internal exception detail.
                response = LinkResponse(
                    request_id=request.request_id,
                    completed_at=now,
                    ok=False,
                    result_cbor=None,
                    error_code="dispatch_failed",
                )
        evolved_state, response_record = self._prepare_encrypted_response(
            device=device,
            host_state=decrypted.opaque_state,
            response=response,
        )
        return PreparedLinkApplicationResponse(
            device=device,
            request=request,
            expected_host_state=device.host_state,
            evolved_host_state=evolved_state,
            response_record=response_record,
            audit_decision=audit_decision,
            audit_error_code=audit_error_code,
        )

    def _prepare_encrypted_response(
        self,
        *,
        device: LinkDevice,
        host_state: bytes,
        response: LinkResponse,
    ) -> tuple[bytes, bytes]:
        try:
            update = self._core.host_encrypt(
                opaque_state=host_state,
                plaintext=response.to_cbor(),
            )
        except Exception as exc:
            raise LinkApplicationError("response_encrypt_failed") from exc
        record = LinkApplicationEnvelope(
            route_id=self._store.machine_identity().route_id,
            credential_serial=device.credential_serial,
            ciphertext=update.message,
        ).to_cbor()
        return update.opaque_state, record

@dataclass(frozen=True)
class InMemoryDeliveryTrace:
    direction: str
    byte_length: int
    record_digest: str


@dataclass
class InMemoryLinkDeliveryService:
    """A deterministic delivery-service stand-in that retains no plaintext records."""

    traces: list[InMemoryDeliveryTrace] = field(default_factory=list)

    def invoke(
        self,
        *,
        controller: LinkApplicationController,
        host: LinkApplicationHost,
        request: LinkRequest,
        now: int,
    ) -> LinkResponse:
        request_delivery = controller.encrypt_request(request)
        self._record("controller_to_host", request_delivery)
        response_delivery = host.receive(request_delivery, now=now)
        self._record("host_to_controller", response_delivery)
        return controller.decrypt_response(response_delivery)

    def _record(self, direction: str, delivery_cbor: bytes) -> None:
        self.traces.append(
            InMemoryDeliveryTrace(
                direction=direction,
                byte_length=len(delivery_cbor),
                record_digest=hashlib.sha256(delivery_cbor).hexdigest(),
            )
        )


def _parse_envelope(delivery_cbor: bytes) -> LinkApplicationEnvelope:
    try:
        return LinkApplicationEnvelope.from_cbor(delivery_cbor)
    except LinkProtocolError as exc:
        raise LinkApplicationError("invalid_delivery_record") from exc
