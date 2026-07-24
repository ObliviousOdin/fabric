from __future__ import annotations

import copy
import threading
import time

import pytest

from tui_gateway.session_event_hub import (
    SessionEventHub,
    SnapshotRequiredError,
)


class RecordingTransport:
    def __init__(self) -> None:
        self.frames: list[dict] = []
        self.closed = False
        self._lock = threading.Lock()

    def write(self, obj: dict) -> bool:
        with self._lock:
            self.frames.append(copy.deepcopy(obj))
        return True

    def close(self) -> None:
        self.closed = True


class BlockingTransport(RecordingTransport):
    def __init__(self) -> None:
        super().__init__()
        self.write_started = threading.Event()
        self.release_write = threading.Event()

    def write(self, obj: dict) -> bool:
        self.write_started.set()
        self.release_write.wait(timeout=5)
        return super().write(obj)


def _event(text: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "event",
        "params": {
            "type": "message.delta",
            "session_id": "live-1",
            "payload": {"text": text},
        },
    }


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


def _event_sequences(transport: RecordingTransport) -> list[int]:
    return [
        frame["params"]["publication"]["event_seq"]
        for frame in transport.frames
    ]


def test_fans_out_one_ordered_stream_without_changing_owner() -> None:
    fence = threading.RLock()
    owner = RecordingTransport()
    first = RecordingTransport()
    second = RecordingTransport()
    state = {"assistant": ""}
    hub = SessionEventHub(
        "live-1",
        owner,
        fence_lock=fence,
        generation_factory=lambda: "generation-1",
    )

    assert hub.enable_remote() == "generation-1"
    first_attach = hub.attach("phone", first, lambda: dict(state))
    second_attach = hub.attach("desktop", second, lambda: dict(state))
    assert first_attach.snapshot == {"assistant": ""}
    assert second_attach.snapshot_seq == 0

    def emit_delta(delta: str) -> None:
        def mutation() -> dict:
            state["assistant"] += delta
            return _event(delta)

        assert hub.mutate_and_emit(mutation)

    emit_delta("hello")
    emit_delta(" world")
    _wait_for(lambda: len(first.frames) == 2 and len(second.frames) == 2)

    assert state == {"assistant": "hello world"}
    assert _event_sequences(owner) == [1, 2]
    assert _event_sequences(first) == [1, 2]
    assert _event_sequences(second) == [1, 2]
    assert owner.frames == first.frames == second.frames
    assert hub.owner_transport is owner

    assert hub.detach("phone")
    emit_delta("!")
    _wait_for(lambda: len(second.frames) == 3)
    assert len(first.frames) == 2
    assert _event_sequences(owner) == [1, 2, 3]
    assert _event_sequences(second) == [1, 2, 3]
    assert hub.subscriber_ids == ("desktop",)

    hub.disable_remote()


def test_attach_fence_has_no_snapshot_stream_gap_or_duplicate() -> None:
    fence = threading.RLock()
    owner = RecordingTransport()
    subscriber = RecordingTransport()
    state = {"assistant": ""}
    snapshot_started = threading.Event()
    release_snapshot = threading.Event()
    attach_result = []
    hub = SessionEventHub(
        "live-1",
        owner,
        fence_lock=fence,
        generation_factory=lambda: "generation-1",
    )
    hub.enable_remote()

    def snapshot() -> dict:
        snapshot_started.set()
        release_snapshot.wait(timeout=5)
        return dict(state)

    attach_thread = threading.Thread(
        target=lambda: attach_result.append(
            hub.attach("phone", subscriber, snapshot)
        )
    )
    attach_thread.start()
    assert snapshot_started.wait(timeout=2)

    def mutation() -> dict:
        state["assistant"] = "after"
        return _event("after")

    emit_thread = threading.Thread(target=lambda: hub.mutate_and_emit(mutation))
    emit_thread.start()
    time.sleep(0.02)
    assert owner.frames == []
    assert subscriber.frames == []

    release_snapshot.set()
    attach_thread.join(timeout=2)
    emit_thread.join(timeout=2)
    _wait_for(lambda: len(subscriber.frames) == 1)

    assert attach_result[0].snapshot == {"assistant": ""}
    assert attach_result[0].snapshot_seq == 0
    assert subscriber.frames[0]["params"]["payload"] == {"text": "after"}
    assert _event_sequences(subscriber) == [1]
    assert state == {"assistant": "after"}

    hub.disable_remote()


def test_slow_subscriber_overflow_is_isolated() -> None:
    owner = RecordingTransport()
    slow = BlockingTransport()
    fast = RecordingTransport()
    hub = SessionEventHub(
        "live-1",
        owner,
        subscriber_queue_size=1,
        generation_factory=lambda: "generation-1",
    )
    hub.enable_remote()
    hub.attach("slow", slow, lambda: {})
    hub.attach("fast", fast, lambda: {})

    hub.emit(_event("one"))
    assert slow.write_started.wait(timeout=2)
    _wait_for(lambda: len(fast.frames) == 1)
    hub.emit(_event("two"))
    _wait_for(lambda: len(fast.frames) == 2)
    hub.emit(_event("three"))

    _wait_for(lambda: hub.subscriber_ids == ("fast",))
    _wait_for(lambda: len(fast.frames) == 3)
    assert _event_sequences(owner) == [1, 2, 3]
    assert _event_sequences(fast) == [1, 2, 3]
    assert slow.closed

    slow.release_write.set()
    hub.disable_remote()


def test_cursor_resume_replays_only_missing_retained_events() -> None:
    owner = RecordingTransport()
    original = RecordingTransport()
    resumed = RecordingTransport()
    hub = SessionEventHub(
        "live-1",
        owner,
        retention=4,
        generation_factory=lambda: "generation-1",
    )
    generation = hub.enable_remote()
    hub.attach("phone", original, lambda: {"history": []})
    hub.emit(_event("one"))
    hub.emit(_event("two"))
    _wait_for(lambda: len(original.frames) == 2)
    hub.detach("phone")

    result = hub.attach(
        "phone",
        resumed,
        lambda: pytest.fail("resume must not rebuild a snapshot"),
        generation=generation,
        after_event_seq=1,
    )
    _wait_for(lambda: len(resumed.frames) == 1)

    assert result.resumed
    assert result.snapshot is None
    assert result.snapshot_seq == 1
    assert _event_sequences(resumed) == [2]

    hub.disable_remote()


def test_cursor_older_than_retention_requires_fresh_snapshot() -> None:
    hub = SessionEventHub(
        "live-1",
        RecordingTransport(),
        retention=2,
        generation_factory=lambda: "generation-1",
    )
    generation = hub.enable_remote()
    for text in ("one", "two", "three"):
        hub.emit(_event(text))

    with pytest.raises(SnapshotRequiredError, match="older than retention"):
        hub.attach(
            "phone",
            RecordingTransport(),
            lambda: {},
            generation=generation,
            after_event_seq=0,
        )

    hub.disable_remote()


def test_unpublished_events_keep_legacy_owner_shape() -> None:
    owner = RecordingTransport()
    hub = SessionEventHub("live-1", owner)

    frame = _event("local")
    assert hub.emit(frame)

    assert owner.frames == [frame]
    assert "publication" not in owner.frames[0]["params"]
