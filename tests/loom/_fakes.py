"""Shared test doubles for Loom tests."""

from __future__ import annotations

from typing import List

from fabric_cli.loom.drivers import ReleaseSpec, RuntimeDriver, ScanResult
from fabric_cli.loom.errors import LoomDriverError
from fabric_cli.loom.models import Host


class FakeDriver(RuntimeDriver):
    """A recording driver that never touches real infrastructure.

    Configure per-host behaviour via the class-level ``scripted`` dict keyed by
    host id, or use the defaults (reachable + docker + healthy).
    """

    def __init__(
        self,
        host: Host,
        *,
        healthy: bool = True,
        reachable: bool = True,
        docker: bool = True,
        raise_on_run: bool = False,
    ) -> None:
        self.host = host
        self.healthy = healthy
        self.reachable = reachable
        self.docker = docker
        self.raise_on_run = raise_on_run
        self.calls: List[str] = []

    def scan(self) -> ScanResult:
        self.calls.append("scan")
        return ScanResult(
            reachable=self.reachable,
            os="Linux",
            arch="x86_64",
            docker_available=self.docker,
            notes=[] if self.docker else ["docker missing"],
        )

    def run_release(self, spec: ReleaseSpec) -> str:
        self.calls.append("run_release")
        if self.raise_on_run:
            raise LoomDriverError("compose up failed")
        return f"fake: brought up {spec.name}"

    def health_check(self, spec: ReleaseSpec) -> bool:
        self.calls.append("health_check")
        return self.healthy

    def fetch_logs(self, spec: ReleaseSpec) -> str:
        self.calls.append("fetch_logs")
        return "fake logs"

    def stop(self, spec: ReleaseSpec) -> str:
        self.calls.append("stop")
        return "fake: stopped"


def make_factory(**kwargs):
    """Return a driver_factory that builds :class:`FakeDriver` with ``kwargs``.

    The most recently created driver is stashed on the returned factory as
    ``.last`` so tests can assert on recorded calls.
    """

    def factory(host: Host) -> FakeDriver:
        driver = FakeDriver(host, **kwargs)
        factory.last = driver  # type: ignore[attr-defined]
        return driver

    factory.last = None  # type: ignore[attr-defined]
    return factory
