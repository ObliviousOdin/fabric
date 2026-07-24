"""Ordered event fanout for one live Fabric session.

The hub does not own an agent or transcript.  It keeps the current local
transport authoritative and, while Remote Control publication is enabled,
fans immutable sequence-bearing event frames out to independent subscribers.

Snapshot correctness depends on one shared re-entrant ``fence_lock``:

* state changes that produce an event use :meth:`mutate_and_emit`;
* snapshot attachment uses :meth:`attach`;
* both operations hold the same fence while state and sequence advance.

That gives clients a precise boundary: the snapshot contains state through
``snapshot_seq`` and the subscriber receives only events after that sequence.
Slow or broken subscribers are detached independently and never block the
owner transport or another subscriber.
"""

from __future__ import annotations

import copy
import queue
import threading
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tui_gateway.transport import Transport


class SessionPublicationError(RuntimeError):
    """Base error for invalid publication or attachment operations."""


class SessionNotPublishedError(SessionPublicationError):
    """Raised when a subscriber tries to attach to an unpublished session."""


class SubscriberAlreadyAttachedError(SessionPublicationError):
    """Raised when a live subscriber id is reused without first detaching it."""


class TransportAlreadyAttachedError(SessionPublicationError):
    """Raised when one transport tries to claim a second subscriber identity."""


class SnapshotRequiredError(SessionPublicationError):
    """Raised when a requested replay cursor is older than retained events."""


@dataclass(frozen=True)
class AttachResult:
    """Fenced state returned when a subscriber attaches."""

    generation: str
    snapshot_seq: int
    snapshot: dict[str, Any] | None
    resumed: bool


class _SubscriberPump:
    """Private bounded writer queue for one subscriber transport."""

    def __init__(
        self,
        subscriber_id: str,
        transport: Transport,
        *,
        queue_size: int,
        on_dead: Callable[[str, "_SubscriberPump"], None],
    ) -> None:
        self.subscriber_id = subscriber_id
        self.transport = transport
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(
            maxsize=queue_size
        )
        self._on_dead = on_dead
        self._closed = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"fabric-session-subscriber-{subscriber_id}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def enqueue(self, frame: dict[str, Any]) -> bool:
        if self._closed.is_set():
            return False
        try:
            self._queue.put_nowait(frame)
            return True
        except queue.Full:
            return False

    def close(self, *, close_transport: bool = True) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            # The daemon writer may be blocked in a peer transport. Closing the
            # transport is the only bounded way to wake a real socket writer.
            pass
        if close_transport:
            try:
                self.transport.close()
            except Exception:
                pass

    def _run(self) -> None:
        try:
            while not self._closed.is_set():
                frame = self._queue.get()
                if frame is None:
                    return
                try:
                    if not self.transport.write(frame):
                        return
                except Exception:
                    return
        finally:
            self._closed.set()
            self._on_dead(self.subscriber_id, self)


class SessionEventHub:
    """Own ordered event delivery for exactly one live session owner."""

    def __init__(
        self,
        session_id: str,
        owner_transport: Transport,
        *,
        fence_lock: threading.RLock | None = None,
        retention: int = 512,
        subscriber_queue_size: int = 128,
        generation_factory: Callable[[], str] | None = None,
    ) -> None:
        if not session_id:
            raise ValueError("session_id is required")
        if retention < 1:
            raise ValueError("retention must be at least 1")
        if subscriber_queue_size < 1:
            raise ValueError("subscriber_queue_size must be at least 1")
        self.session_id = session_id
        self._owner_transport = owner_transport
        self._fence_lock = fence_lock or threading.RLock()
        self._lock = threading.RLock()
        self._retained: deque[dict[str, Any]] = deque(maxlen=retention)
        self._subscriber_queue_size = subscriber_queue_size
        self._generation_factory = generation_factory or (
            lambda: uuid.uuid4().hex
        )
        self._generation = ""
        self._sequence = 0
        self._published = False
        self._subscribers: dict[str, _SubscriberPump] = {}

    @property
    def owner_transport(self) -> Transport:
        with self._lock:
            return self._owner_transport

    @property
    def published(self) -> bool:
        with self._lock:
            return self._published

    @property
    def generation(self) -> str | None:
        with self._lock:
            return self._generation or None

    @property
    def sequence(self) -> int:
        with self._lock:
            return self._sequence

    @property
    def subscriber_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._subscribers)

    def owns_transport(self, transport: Transport) -> bool:
        """Return whether *transport* is the authoritative local owner."""
        with self._lock:
            return self._owner_transport is transport

    def subscriber_for_transport(self, transport: Transport) -> str | None:
        """Return the subscriber identity bound to *transport*, if any."""
        with self._lock:
            for subscriber_id, pump in self._subscribers.items():
                if pump.transport is transport:
                    return subscriber_id
        return None

    def rebind_owner(self, transport: Transport) -> None:
        """Move owner delivery after a verified local owner reconnect.

        This method never changes publication generation, subscribers, or
        transcript state. The server is responsible for calling it only from
        its existing owner-resume path; subscriber attachment never calls it.
        """
        with self._fence_lock:
            with self._lock:
                if any(
                    pump.transport is transport
                    for pump in self._subscribers.values()
                ):
                    raise TransportAlreadyAttachedError(
                        "subscriber transport cannot become session owner"
                    )
                self._owner_transport = transport

    def enable_remote(self) -> str:
        """Publish the session and return its publication generation.

        Repeated calls are idempotent while already published. A later
        disable/enable cycle receives a new generation and a fresh sequence.
        """
        with self._fence_lock:
            with self._lock:
                if self._published:
                    return self._generation
                self._generation = self._generation_factory()
                if not self._generation:
                    raise ValueError("generation_factory returned an empty value")
                self._sequence = 0
                self._retained.clear()
                self._published = True
                return self._generation

    def disable_remote(
        self,
        *,
        close_transports: bool = True,
    ) -> tuple[str, ...]:
        """Withdraw publication and detach every remote subscriber."""
        with self._fence_lock:
            with self._lock:
                self._published = False
                pumps = list(self._subscribers.values())
                detached = tuple(self._subscribers)
                self._subscribers.clear()
                self._retained.clear()
        for pump in pumps:
            pump.close(close_transport=close_transports)
        return detached

    def attach(
        self,
        subscriber_id: str,
        transport: Transport,
        snapshot_builder: Callable[[], dict[str, Any]],
        *,
        generation: str | None = None,
        after_event_seq: int | None = None,
    ) -> AttachResult:
        """Attach a subscriber at one exact snapshot/event fence.

        Supplying ``generation`` plus ``after_event_seq`` requests cursor
        resume. If retained history covers that cursor, no snapshot is rebuilt
        and the missing events are queued before live delivery. Otherwise a
        :class:`SnapshotRequiredError` tells the caller to attach fresh.
        """
        if not subscriber_id:
            raise ValueError("subscriber_id is required")
        if after_event_seq is not None and after_event_seq < 0:
            raise ValueError("after_event_seq cannot be negative")

        pump = _SubscriberPump(
            subscriber_id,
            transport,
            queue_size=self._subscriber_queue_size,
            on_dead=self._remove_dead_subscriber,
        )
        with self._fence_lock:
            with self._lock:
                if not self._published:
                    raise SessionNotPublishedError(self.session_id)
                if self._owner_transport is transport:
                    raise TransportAlreadyAttachedError(
                        "owner transport cannot attach as a subscriber"
                    )
                if subscriber_id in self._subscribers:
                    raise SubscriberAlreadyAttachedError(subscriber_id)
                if any(
                    current.transport is transport
                    for current in self._subscribers.values()
                ):
                    raise TransportAlreadyAttachedError(
                        "transport already has a subscriber identity"
                    )

                resumed = generation == self._generation and after_event_seq is not None
                snapshot: dict[str, Any] | None
                snapshot_seq: int
                replay: list[dict[str, Any]]
                if resumed:
                    oldest = (
                        int(
                            self._retained[0]["params"]["publication"]["event_seq"]
                        )
                        if self._retained
                        else self._sequence + 1
                    )
                    if after_event_seq > self._sequence:
                        raise SnapshotRequiredError("cursor is ahead of publication")
                    if after_event_seq < oldest - 1:
                        raise SnapshotRequiredError("cursor is older than retention")
                    snapshot = None
                    snapshot_seq = after_event_seq
                    replay = [
                        copy.deepcopy(frame)
                        for frame in self._retained
                        if int(frame["params"]["publication"]["event_seq"])
                        > after_event_seq
                    ]
                else:
                    snapshot = copy.deepcopy(snapshot_builder())
                    snapshot_seq = self._sequence
                    replay = []

                for frame in replay:
                    if not pump.enqueue(frame):
                        raise SnapshotRequiredError(
                            "retained replay exceeds subscriber queue"
                        )
                self._subscribers[subscriber_id] = pump
                result = AttachResult(
                    generation=self._generation,
                    snapshot_seq=snapshot_seq,
                    snapshot=snapshot,
                    resumed=resumed,
                )
        pump.start()
        return result

    def detach(
        self,
        subscriber_id: str,
        *,
        close_transport: bool = False,
    ) -> bool:
        """Detach one subscriber without changing session ownership."""
        with self._lock:
            pump = self._subscribers.pop(subscriber_id, None)
        if pump is None:
            return False
        pump.close(close_transport=close_transport)
        return True

    def detach_transport(self, transport: Transport) -> str | None:
        """Detach the subscriber using *transport* and return its identity."""
        subscriber_id = self.subscriber_for_transport(transport)
        if subscriber_id is None:
            return None
        self.detach(subscriber_id, close_transport=False)
        return subscriber_id

    def emit(self, frame: dict[str, Any]) -> bool:
        """Emit a stateless event to the owner and current subscribers."""
        return self.mutate_and_emit(lambda: frame)

    def mutate_and_emit(
        self,
        mutation: Callable[[], dict[str, Any]],
    ) -> bool:
        """Atomically mutate snapshot state and allocate the matching event.

        ``mutation`` runs under the same fence used by :meth:`attach`. It must
        return a JSON-RPC event frame for this session.
        """
        with self._fence_lock:
            frame = mutation()
            if not isinstance(frame, dict):
                raise TypeError("mutation must return an event frame")
            prepared, overflowed = self._prepare_remote_frame(frame)

        for subscriber_id, pump in overflowed:
            self._remove_dead_subscriber(subscriber_id, pump)
            pump.close()
        return self.owner_transport.write(prepared)

    def _prepare_remote_frame(
        self,
        frame: dict[str, Any],
    ) -> tuple[dict[str, Any], list[tuple[str, _SubscriberPump]]]:
        original = copy.deepcopy(frame)
        with self._lock:
            if not self._published:
                return original, []
            params = original.get("params")
            if not isinstance(params, dict):
                raise ValueError("published event frame requires object params")
            if params.get("session_id") != self.session_id:
                raise ValueError("event session_id does not match hub")

            self._sequence += 1
            publication = {
                "event_seq": self._sequence,
                "generation": self._generation,
            }
            params["publication"] = publication
            self._retained.append(copy.deepcopy(original))

            overflowed: list[tuple[str, _SubscriberPump]] = []
            for subscriber_id, pump in self._subscribers.items():
                if not pump.enqueue(copy.deepcopy(original)):
                    overflowed.append((subscriber_id, pump))
            for subscriber_id, _pump in overflowed:
                self._subscribers.pop(subscriber_id, None)
            return original, overflowed

    def _remove_dead_subscriber(
        self,
        subscriber_id: str,
        pump: _SubscriberPump,
    ) -> None:
        with self._lock:
            if self._subscribers.get(subscriber_id) is pump:
                self._subscribers.pop(subscriber_id, None)
