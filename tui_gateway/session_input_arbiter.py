"""Deterministic, idempotent input ordering for one live Fabric session."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, replace
from typing import Literal

InputState = Literal["accepted", "queued", "completed", "rejected", "duplicate"]


@dataclass(frozen=True)
class InputReceipt:
    """Stable decision for one controller-scoped request id."""

    controller_id: str
    request_id: str
    ordinal: int | None
    state: InputState
    original_state: InputState | None = None
    reason: str | None = None


@dataclass
class _InputRecord:
    digest: str
    receipt: InputReceipt


class SessionInputArbiter:
    """Serialize local and remote transcript mutations exactly once.

    The arbiter owns ordering and idempotency, not model execution. The caller
    executes the request returned as ``accepted`` and calls :meth:`complete`
    when that turn releases the mutation slot. The returned next receipt, if
    any, is the queued request that became accepted.
    """

    def __init__(self, *, max_queue: int = 32, receipt_retention: int = 1024) -> None:
        if max_queue < 0:
            raise ValueError("max_queue cannot be negative")
        if receipt_retention < 1:
            raise ValueError("receipt_retention must be at least 1")
        self._max_queue = max_queue
        self._receipt_retention = receipt_retention
        self._lock = threading.RLock()
        self._next_ordinal = 1
        self._active: tuple[str, str] | None = None
        self._queue: deque[tuple[str, str]] = deque()
        self._records: OrderedDict[tuple[str, str], _InputRecord] = OrderedDict()

    @property
    def active(self) -> InputReceipt | None:
        with self._lock:
            if self._active is None:
                return None
            return self._records[self._active].receipt

    @property
    def queued(self) -> tuple[InputReceipt, ...]:
        with self._lock:
            return tuple(self._records[key].receipt for key in self._queue)

    def submit(
        self,
        *,
        controller_id: str,
        request_id: str,
        payload: str | bytes,
    ) -> InputReceipt:
        """Claim one mutation intent or return its stable prior decision."""
        controller_id = controller_id.strip()
        request_id = request_id.strip()
        if not controller_id:
            raise ValueError("controller_id is required")
        if not request_id:
            raise ValueError("request_id is required")
        raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        digest = hashlib.sha256(raw).hexdigest()
        key = (controller_id, request_id)

        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                self._records.move_to_end(key)
                if existing.digest != digest:
                    return InputReceipt(
                        controller_id=controller_id,
                        request_id=request_id,
                        ordinal=existing.receipt.ordinal,
                        state="rejected",
                        original_state=existing.receipt.state,
                        reason="request_id_conflict",
                    )
                return InputReceipt(
                    controller_id=controller_id,
                    request_id=request_id,
                    ordinal=existing.receipt.ordinal,
                    state="duplicate",
                    original_state=existing.receipt.state,
                )

            ordinal = self._next_ordinal
            self._next_ordinal += 1
            if self._active is None:
                state: InputState = "accepted"
            elif len(self._queue) < self._max_queue:
                state = "queued"
            else:
                state = "rejected"
            receipt = InputReceipt(
                controller_id=controller_id,
                request_id=request_id,
                ordinal=ordinal,
                state=state,
                reason="queue_full" if state == "rejected" else None,
            )
            self._records[key] = _InputRecord(digest=digest, receipt=receipt)
            if state == "accepted":
                self._active = key
            elif state == "queued":
                self._queue.append(key)
            self._trim_records()
            return receipt

    def complete(
        self,
        *,
        controller_id: str,
        request_id: str,
    ) -> InputReceipt | None:
        """Complete the active request and promote the next queued request."""
        key = (controller_id.strip(), request_id.strip())
        with self._lock:
            if self._active != key:
                raise ValueError("request is not the active mutation")
            record = self._records[key]
            record.receipt = replace(record.receipt, state="completed")
            self._active = None

            promoted: InputReceipt | None = None
            if self._queue:
                next_key = self._queue.popleft()
                next_record = self._records[next_key]
                next_record.receipt = replace(next_record.receipt, state="accepted")
                self._active = next_key
                promoted = next_record.receipt
            self._trim_records()
            return promoted

    def receipt(
        self,
        *,
        controller_id: str,
        request_id: str,
    ) -> InputReceipt | None:
        """Return the current authoritative receipt without mutating it."""
        key = (controller_id.strip(), request_id.strip())
        with self._lock:
            record = self._records.get(key)
            return record.receipt if record is not None else None

    def _trim_records(self) -> None:
        if len(self._records) <= self._receipt_retention:
            return
        protected = set(self._queue)
        if self._active is not None:
            protected.add(self._active)
        for key in list(self._records):
            if len(self._records) <= self._receipt_retention:
                break
            record = self._records[key]
            if key not in protected and record.receipt.state in {"completed", "rejected"}:
                self._records.pop(key, None)
