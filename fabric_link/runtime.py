"""Process-local ownership of the foreground Fabric Link broker."""

from __future__ import annotations

import atexit
import threading
from dataclasses import dataclass
from typing import Any, Callable

from fabric_cli.config import load_config

from .broker import BrokerOwnershipLease, FabricLinkBroker, LinkBrokerError
from .core import load_openmls_core
from .protocol import normalize_relay_origin
from .service import LinkServiceManager
from .store import LinkDeviceStore


@dataclass(frozen=True)
class ForegroundLinkStatus:
    active: bool
    relay: str | None
    owner: str
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "active": self.active,
            "owner": self.owner,
            "reason": self.reason,
            "relay": self.relay,
        }


class ForegroundLinkRuntime:
    """Share one broker across published sessions in this Python process."""

    def __init__(
        self,
        *,
        broker_factory: Callable[..., FabricLinkBroker] = FabricLinkBroker,
    ) -> None:
        self._broker_factory = broker_factory
        self._lock = threading.RLock()
        self._published_sessions: set[str] = set()
        self._lease: BrokerOwnershipLease | None = None
        self._store: LinkDeviceStore | None = None
        self._broker: FabricLinkBroker | None = None
        self._thread: threading.Thread | None = None
        self._relay: str | None = None
        self._resume_service = False
        self._bridge_mode = "gateway"

    def publish(
        self,
        session_id: str,
        *,
        bridge_factory: Callable[[Any], Any] | None = None,
    ) -> ForegroundLinkStatus:
        if not session_id:
            raise LinkBrokerError("link_session_id_required")
        enabled, relay = _runtime_config()
        if not enabled:
            return ForegroundLinkStatus(
                active=False,
                relay=relay,
                owner="local",
                reason="link_disabled",
            )
        if relay is None:
            return ForegroundLinkStatus(
                active=False,
                relay=None,
                owner="local",
                reason="relay_not_configured",
            )
        with self._lock:
            if self._broker is not None:
                if self._relay != relay:
                    raise LinkBrokerError("link_relay_change_requires_unpublish")
                requested_mode = "custom" if bridge_factory is not None else "gateway"
                if requested_mode != self._bridge_mode:
                    raise LinkBrokerError("link_broker_bridge_conflict")
                self._published_sessions.add(session_id)
                return ForegroundLinkStatus(True, relay, "foreground")
            self._start(relay, bridge_factory=bridge_factory)
            self._published_sessions.add(session_id)
            return ForegroundLinkStatus(True, relay, "foreground")

    def unpublish(self, session_id: str) -> None:
        with self._lock:
            self._published_sessions.discard(session_id)
            if not self._published_sessions:
                self._stop_locked()

    def shutdown(self) -> None:
        with self._lock:
            self._published_sessions.clear()
            self._stop_locked()

    def status(self) -> ForegroundLinkStatus:
        with self._lock:
            if self._broker is None:
                return ForegroundLinkStatus(
                    active=False,
                    relay=self._relay,
                    owner="local",
                    reason="foreground_broker_stopped",
                )
            return ForegroundLinkStatus(True, self._relay, "foreground")

    def _start(
        self,
        relay: str,
        *,
        bridge_factory: Callable[[Any], Any] | None,
    ) -> None:
        resume_service = False
        try:
            service = LinkServiceManager()
            service_status = service.status()
            if service_status.installed and service_status.running:
                service.stop()
                resume_service = True
        except Exception:
            # Service inspection is advisory. The ownership lease remains the
            # authoritative split-brain guard.
            resume_service = False

        lease = BrokerOwnershipLease()
        store: LinkDeviceStore | None = None
        broker: FabricLinkBroker | None = None
        bridge = None
        try:
            lease.acquire()
            store = LinkDeviceStore()
            bridge = (
                bridge_factory(store.machine_identity())
                if bridge_factory is not None
                else None
            )
            broker = self._broker_factory(
                relay_origin=relay,
                store=store,
                core=load_openmls_core(),
                bridge=bridge,
            )
            thread = threading.Thread(
                target=broker.run_forever,
                name="fabric-link-foreground",
                daemon=True,
            )
            thread.start()
        except Exception:
            if broker is not None:
                broker.close()
            elif bridge is not None:
                bridge.close()
            if store is not None:
                store.close()
            lease.release()
            if resume_service:
                _best_effort_service_start()
            raise
        self._lease = lease
        self._store = store
        self._broker = broker
        self._thread = thread
        self._relay = relay
        self._resume_service = resume_service
        self._bridge_mode = "custom" if bridge_factory is not None else "gateway"

    def _stop_locked(self) -> None:
        broker, self._broker = self._broker, None
        thread, self._thread = self._thread, None
        store, self._store = self._store, None
        lease, self._lease = self._lease, None
        resume_service, self._resume_service = self._resume_service, False
        self._relay = None
        self._bridge_mode = "gateway"
        if broker is not None:
            broker.stop()
        if thread is not None:
            thread.join(timeout=5)
        if broker is not None:
            broker.close()
        if store is not None:
            store.close()
        if lease is not None:
            lease.release()
        if resume_service:
            _best_effort_service_start()


def _runtime_config() -> tuple[bool, str | None]:
    config = load_config()
    section = config.get("link")
    if not isinstance(section, dict):
        return False, None
    raw_relay = str(section.get("relay_url", "") or "").strip()
    relay = None
    if raw_relay:
        try:
            relay = normalize_relay_origin(
                raw_relay.replace("wss://", "https://", 1).removesuffix("/link"),
                allow_loopback_http=True,
            )
        except Exception as exc:
            raise LinkBrokerError("invalid_relay_url") from exc
    return bool(section.get("enabled", False)), relay


def _best_effort_service_start() -> None:
    try:
        manager = LinkServiceManager()
        if manager.status().installed:
            manager.start()
    except Exception:
        pass


_runtime = ForegroundLinkRuntime()
atexit.register(_runtime.shutdown)


def publish_link_session(session_id: str) -> dict[str, object]:
    return _runtime.publish(session_id).to_dict()


def publish_classic_link_session(host: Any) -> dict[str, object]:
    from .classic_bridge import ClassicLinkGatewayBridge

    return _runtime.publish(
        str(host.session_id),
        bridge_factory=lambda identity: ClassicLinkGatewayBridge(
            host=host,
            machine_identity=identity,
        ),
    ).to_dict()


def unpublish_link_session(session_id: str) -> None:
    _runtime.unpublish(session_id)


def shutdown_link_runtime() -> None:
    _runtime.shutdown()
