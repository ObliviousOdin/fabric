"""Regression tests for SshDriver exit-code handling (fail-closed)."""

from __future__ import annotations

import pytest

from fabric_cli.loom.drivers import ReleaseSpec, SshDriver
from fabric_cli.loom.errors import LoomDriverError
from fabric_cli.loom.models import Host


class _FakeEnv:
    """Stand-in for SSHEnvironment: returns a fixed base-env result dict."""

    def __init__(self, result):
        self._result = result
        self.cleaned = False

    def execute(self, command):
        return self._result

    def cleanup(self):
        self.cleaned = True


def _ssh_host() -> Host:
    return Host(id="h1", name="box", kind="ssh", address="1.2.3.4", user="root")


def _driver_returning(monkeypatch, result) -> SshDriver:
    driver = SshDriver(_ssh_host())
    monkeypatch.setattr(driver, "_env", lambda: _FakeEnv(result))
    return driver


def test_remote_raises_on_nonzero_returncode(monkeypatch):
    driver = _driver_returning(monkeypatch, {"output": "boom", "returncode": 1})
    with pytest.raises(LoomDriverError):
        driver._remote("docker compose up -d")


def test_remote_returns_output_on_zero(monkeypatch):
    driver = _driver_returning(monkeypatch, {"output": "hello\n", "returncode": 0})
    assert driver._remote("echo hello").strip() == "hello"


def test_run_release_failure_propagates(monkeypatch):
    # A failed remote `docker compose up` must raise, not be swallowed — so the
    # service marks the deployment failed instead of active.
    driver = _driver_returning(
        monkeypatch, {"output": "compose error", "returncode": 17}
    )
    spec = ReleaseSpec(name="app", kind="compose", workdir="/srv/app")
    with pytest.raises(LoomDriverError):
        driver.run_release(spec)


def test_scan_unreachable_when_remote_errors(monkeypatch):
    # A nonzero probe (e.g. auth/connection failure surfaced as nonzero) marks
    # the host unreachable rather than silently "scanned".
    driver = _driver_returning(monkeypatch, {"output": "denied", "returncode": 255})
    result = driver.scan()
    assert result.reachable is False
    assert result.notes  # carries the failure detail


def test_health_check_reads_status_code(monkeypatch):
    driver = _driver_returning(monkeypatch, {"output": "200", "returncode": 0})
    spec = ReleaseSpec(name="app", kind="compose", health_url="http://x/health")
    assert driver.health_check(spec) is True
