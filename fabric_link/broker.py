"""Single-owner Fabric Link host broker and durable encrypted response outbox."""

from __future__ import annotations

import os
import secrets
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .application import LinkApplicationError, LinkApplicationHost
from .capabilities import grant_for_method
from .core import LinkCryptoCore
from .gateway_bridge import LinkGatewayBridge
from .relay_auth import create_host_authentication, create_relay_revocation
from .relay_client import LinkRelayClient, LinkRelayClientError
from .relay_contract import (
    RelayAcknowledgement,
    RelayMailbox,
    RelayPoll,
    RelayPublish,
)
from .store import (
    LinkDevice,
    LinkDeviceStore,
    LinkStorageError,
    _ensure_private_directory,
    _harden_private_path,
    link_home,
)


class LinkBrokerError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class BrokerRunResult:
    requests_processed: int
    responses_flushed: int
    records_rejected: int


@dataclass(frozen=True)
class _OutboxRecord:
    credential_serial: bytes
    source_sequence: int
    source_message_id: bytes
    response_message_id: bytes
    expires_at: int
    response_record: bytes


class BrokerOwnershipLease:
    """Cross-process exclusive ownership of all host MLS state."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (link_home() / "broker.lock")
        self._fd: int | None = None

    def acquire(self) -> None:
        if self._fd is not None:
            raise LinkBrokerError("broker_lease_already_held")
        _ensure_private_directory(self.path.parent)
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = -1
        try:
            fd = os.open(self.path, flags, 0o600)
            _lock_fd(fd)
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode("ascii"))
            os.fsync(fd)
            self._fd = fd
            _harden_private_path(self.path, directory=False)
        except BlockingIOError as exc:
            try:
                if fd >= 0:
                    os.close(fd)
            except Exception:
                pass
            raise LinkBrokerError("broker_already_running") from exc
        except OSError as exc:
            try:
                if fd >= 0:
                    os.close(fd)
            except Exception:
                pass
            raise LinkBrokerError("broker_lease_unavailable") from exc

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            _unlock_fd(fd)
        finally:
            os.close(fd)

    def __enter__(self) -> "BrokerOwnershipLease":
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class BrokerOutbox:
    """Adapter over the host store's transactionally-coupled ciphertext queue."""

    def __init__(self, store: LinkDeviceStore) -> None:
        self._store = store

    def close(self) -> None:
        return None

    def get(
        self,
        *,
        credential_serial: bytes,
        source_sequence: int,
    ) -> _OutboxRecord | None:
        row = self._store.response_outbox_get(
            credential_serial=credential_serial,
            source_sequence=source_sequence,
        )
        return self._row(row) if row is not None else None

    def pending(self) -> tuple[_OutboxRecord, ...]:
        rows = self._store.response_outbox_pending()
        return tuple(self._row(row) for row in rows)

    def complete(
        self,
        *,
        credential_serial: bytes,
        source_sequence: int,
    ) -> None:
        self._store.response_outbox_complete(
            credential_serial=credential_serial,
            source_sequence=source_sequence,
        )

    @staticmethod
    def _row(row: dict[str, object]) -> _OutboxRecord:
        return _OutboxRecord(
            credential_serial=bytes(row["credential_serial"]),  # type: ignore[arg-type]
            source_sequence=int(row["source_sequence"]),  # type: ignore[arg-type]
            source_message_id=bytes(row["source_message_id"]),  # type: ignore[arg-type]
            response_message_id=bytes(row["response_message_id"]),  # type: ignore[arg-type]
            expires_at=int(row["expires_at"]),  # type: ignore[arg-type]
            response_record=bytes(row["response_record"]),  # type: ignore[arg-type]
        )


class FabricLinkBroker:
    """Owns host crypto, the reviewed gateway bridge, and the relay connection."""

    def __init__(
        self,
        *,
        relay_origin: str,
        store: LinkDeviceStore,
        core: LinkCryptoCore,
        outbox: BrokerOutbox | None = None,
        bridge: LinkGatewayBridge | None = None,
        client_factory=LinkRelayClient,
    ) -> None:
        self._relay_origin = relay_origin
        self._store = store
        self._core = core
        self._identity = store.machine_identity()
        self._outbox = outbox or BrokerOutbox(store)
        self._bridge = bridge or LinkGatewayBridge(
            machine_identity=self._identity,
        )
        self._client_factory = client_factory
        self._stop = threading.Event()
        self._known_active_device_ids: set[str] = set()
        missing = set(self._reviewed_methods()) - set(self._bridge.registered_methods)
        if missing:
            raise LinkBrokerError("link_gateway_registry_mismatch")

    def close(self) -> None:
        self._stop.set()
        self._bridge.close()
        self._outbox.close()

    def stop(self) -> None:
        self._stop.set()

    def run_once(self, *, now: int | None = None) -> BrokerRunResult:
        current_time = int(time.time()) if now is None else now
        client = self._client_factory(
            relay_origin=self._relay_origin,
            authentication_factory=lambda challenge: create_host_authentication(
                machine_identity=self._identity,
                challenge=challenge,
                relay_origin=self._relay_origin,
                now=int(time.time()) if now is None else current_time,
            ),
        )
        processed = 0
        flushed = 0
        rejected = 0
        try:
            active_devices = self._active_devices()
            self._reconcile_local_revocations(active_devices)
            client.connect()
            self._flush_relay_revocations(
                client,
                now=current_time,
            )
            for pending in self._outbox.pending():
                if self._flush(client, pending, now=current_time):
                    flushed += 1
            host = LinkApplicationHost(
                core=self._core,
                store=self._store,
                registered_methods=self._bridge.registered_methods,
                dispatch=self._bridge.dispatch,
            )
            for device in active_devices:
                mailbox = RelayMailbox(
                    route_id=self._identity.route_id,
                    credential_serial=device.credential_serial,
                    recipient="host",
                )
                deliveries, _sync = client.poll(
                    RelayPoll(
                        mailbox=mailbox,
                        request_id=secrets.token_bytes(16),
                        after_sequence=0,
                        limit=50,
                    )
                )
                for delivery in deliveries:
                    existing = self._outbox.get(
                        credential_serial=device.credential_serial,
                        source_sequence=delivery.sequence,
                    )
                    if existing is not None:
                        if self._flush(client, existing, now=current_time):
                            flushed += 1
                        continue
                    try:
                        prepared = host.prepare(
                            delivery.opaque_record,
                            now=current_time,
                        )
                        self._store.commit_application_response(
                            device=prepared.device,
                            expected_host_state=prepared.expected_host_state,
                            evolved_host_state=prepared.evolved_host_state,
                            request_id=prepared.request.request_id,
                            request_expires_at=prepared.request.expires_at,
                            method_class=grant_for_method(
                                prepared.request.method
                            ),
                            decision=prepared.audit_decision,
                            error_code=prepared.audit_error_code,
                            response_record=prepared.response_record,
                            now=current_time,
                            source_sequence=delivery.sequence,
                            source_message_id=delivery.message_id,
                            response_expires_at=min(
                                delivery.expires_at,
                                current_time + 300,
                            ),
                        )
                        staged = self._outbox.get(
                            credential_serial=device.credential_serial,
                            source_sequence=delivery.sequence,
                        )
                        if staged is None:
                            raise LinkBrokerError("broker_outbox_missing")
                        processed += 1
                        if self._flush(client, staged, now=current_time):
                            flushed += 1
                    except (LinkApplicationError, LinkStorageError):
                        # Authenticated but invalid/expired/revoked ciphertext is
                        # a poison record. It never reaches the dispatcher.
                        client.acknowledge(
                            RelayAcknowledgement(
                                mailbox=mailbox,
                                sequence=delivery.sequence,
                                message_id=delivery.message_id,
                            )
                        )
                        rejected += 1
            return BrokerRunResult(
                requests_processed=processed,
                responses_flushed=flushed,
                records_rejected=rejected,
            )
        except LinkRelayClientError as exc:
            raise LinkBrokerError(exc.code) from exc
        finally:
            client.close()

    def run_forever(
        self,
        *,
        poll_interval_seconds: float = 0.25,
        max_backoff_seconds: float = 30.0,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise LinkBrokerError("invalid_broker_poll_interval")
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self.run_once()
                backoff = 1.0
                self._stop.wait(poll_interval_seconds)
            except LinkBrokerError:
                self._stop.wait(min(backoff, max_backoff_seconds))
                backoff = min(backoff * 2, max_backoff_seconds)

    def _flush(
        self,
        client: LinkRelayClient,
        pending: _OutboxRecord,
        *,
        now: int,
    ) -> bool:
        if pending.expires_at <= now:
            # The relay request has expired, so no controller can accept this
            # response. ACK the source to prevent an infinite poison loop.
            self._ack_source(client, pending)
            self._outbox.complete(
                credential_serial=pending.credential_serial,
                source_sequence=pending.source_sequence,
            )
            return False
        response_mailbox = RelayMailbox(
            route_id=self._identity.route_id,
            credential_serial=pending.credential_serial,
            recipient="controller",
        )
        client.publish(
            RelayPublish(
                mailbox=response_mailbox,
                message_id=pending.response_message_id,
                expires_at=pending.expires_at,
                opaque_record=pending.response_record,
            )
        )
        self._ack_source(client, pending)
        self._outbox.complete(
            credential_serial=pending.credential_serial,
            source_sequence=pending.source_sequence,
        )
        return True

    def _ack_source(
        self,
        client: LinkRelayClient,
        pending: _OutboxRecord,
    ) -> None:
        client.acknowledge(
            RelayAcknowledgement(
                mailbox=RelayMailbox(
                    route_id=self._identity.route_id,
                    credential_serial=pending.credential_serial,
                    recipient="host",
                ),
                sequence=pending.source_sequence,
                message_id=pending.source_message_id,
            )
        )

    def _active_devices(self) -> tuple[LinkDevice, ...]:
        return tuple(
            device for device in self._store.list_devices() if device.status == "active"
        )

    def _reconcile_local_revocations(
        self,
        active_devices: tuple[LinkDevice, ...],
    ) -> None:
        active_ids = {device.device_id for device in active_devices}
        revoke_transport = getattr(self._bridge, "revoke_device", None)
        if callable(revoke_transport):
            for device_id in self._known_active_device_ids - active_ids:
                revoke_transport(device_id)
        self._known_active_device_ids = active_ids

    def _flush_relay_revocations(
        self,
        client: LinkRelayClient,
        *,
        now: int,
    ) -> None:
        for device in self._store.list_devices():
            if device.status != "revoked" or self._store.relay_revocation_delivered(
                credential_serial=device.credential_serial,
                relay_origin=self._relay_origin,
            ):
                continue
            client.revoke(
                create_relay_revocation(
                    machine_identity=self._identity,
                    credential_serial=device.credential_serial,
                    relay_origin=self._relay_origin,
                    now=now,
                )
            )
            self._store.mark_relay_revocation_delivered(
                credential_serial=device.credential_serial,
                relay_origin=self._relay_origin,
                now=now,
            )

    @staticmethod
    def _reviewed_methods():
        from .capabilities import LINK_REMOTE_METHODS

        return LINK_REMOTE_METHODS


def _lock_fd(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_fd(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_UN)
