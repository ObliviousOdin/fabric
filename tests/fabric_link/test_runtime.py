from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from fabric_link.broker import LinkBrokerError
from fabric_link.runtime import ForegroundLinkRuntime


class FakeLease:
    acquired = 0
    released = 0

    def acquire(self):
        type(self).acquired += 1

    def release(self):
        type(self).released += 1


class FakeStore:
    closed = 0

    def machine_identity(self):
        return "machine"

    def close(self):
        type(self).closed += 1


class FakeBroker:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.stopped = threading.Event()
        self.closed = False
        type(self).instances.append(self)

    def run_forever(self):
        self.stopped.wait(5)

    def stop(self):
        self.stopped.set()

    def close(self):
        self.closed = True


class FakeService:
    installed = True
    running = True
    starts = 0
    stops = 0

    def status(self):
        return SimpleNamespace(
            installed=type(self).installed,
            running=type(self).running,
        )

    def stop(self):
        type(self).running = False
        type(self).stops += 1

    def start(self):
        type(self).running = True
        type(self).starts += 1


@pytest.fixture(autouse=True)
def reset_fakes(monkeypatch):
    FakeLease.acquired = FakeLease.released = 0
    FakeStore.closed = 0
    FakeBroker.instances = []
    FakeService.installed = True
    FakeService.running = True
    FakeService.starts = FakeService.stops = 0
    monkeypatch.setattr("fabric_link.runtime.BrokerOwnershipLease", FakeLease)
    monkeypatch.setattr("fabric_link.runtime.LinkDeviceStore", FakeStore)
    monkeypatch.setattr("fabric_link.runtime.LinkServiceManager", FakeService)
    monkeypatch.setattr("fabric_link.runtime.load_openmls_core", lambda: "core")


def test_disabled_link_keeps_remote_control_local(monkeypatch):
    monkeypatch.setattr(
        "fabric_link.runtime._runtime_config",
        lambda: (False, None),
    )
    subject = ForegroundLinkRuntime(broker_factory=FakeBroker)

    status = subject.publish("session-a")

    assert not status.active
    assert status.reason == "link_disabled"
    assert FakeBroker.instances == []
    assert FakeService.stops == 0


def test_foreground_broker_handoffs_service_and_is_shared(monkeypatch):
    monkeypatch.setattr(
        "fabric_link.runtime._runtime_config",
        lambda: (True, "https://relay.example"),
    )
    subject = ForegroundLinkRuntime(broker_factory=FakeBroker)

    first = subject.publish("session-a")
    second = subject.publish("session-b")

    assert first.active and second.active
    assert len(FakeBroker.instances) == 1
    assert FakeService.stops == 1
    assert FakeLease.acquired == 1

    subject.unpublish("session-a")
    assert not FakeBroker.instances[0].closed
    subject.unpublish("session-b")

    assert FakeBroker.instances[0].closed
    assert FakeLease.released == 1
    assert FakeStore.closed == 1
    assert FakeService.starts == 1


def test_foreground_runtime_rejects_bridge_mode_split_brain(monkeypatch):
    monkeypatch.setattr(
        "fabric_link.runtime._runtime_config",
        lambda: (True, "https://relay.example"),
    )
    FakeService.running = False
    subject = ForegroundLinkRuntime(broker_factory=FakeBroker)
    subject.publish("session-a")

    with pytest.raises(LinkBrokerError, match="link_broker_bridge_conflict"):
        subject.publish(
            "classic-session",
            bridge_factory=lambda _identity: SimpleNamespace(close=lambda: None),
        )

    subject.shutdown()
