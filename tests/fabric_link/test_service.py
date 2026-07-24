from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from fabric_link.service import LinkServiceError, LinkServiceManager


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.launchd_running = False
        self.systemd_running = False
        self.systemd_enabled = False
        self.windows_installed = False
        self.windows_running = False

    def __call__(self, argv, **_kwargs):
        values = [str(value) for value in argv]
        self.calls.append(values)
        if values[0].endswith("whoami") or values[0].endswith("whoami.exe"):
            return done(values, stdout='"user","S-1-5-21-1000"\n')
        if values[0] == "launchctl":
            action = values[1]
            if action == "print":
                return done(values, code=0 if self.launchd_running else 113)
            if action in {"bootstrap", "kickstart"}:
                self.launchd_running = True
            elif action == "bootout":
                self.launchd_running = False
            return done(values)
        if values[:2] == ["systemctl", "--user"]:
            action = values[2]
            if action == "is-active":
                return done(values, code=0 if self.systemd_running else 3)
            if action == "is-enabled":
                return done(values, code=0 if self.systemd_enabled else 1)
            if action == "enable":
                self.systemd_enabled = True
            elif action == "disable":
                self.systemd_enabled = False
                if "--now" in values:
                    self.systemd_running = False
            elif action in {"start", "restart"}:
                self.systemd_running = True
            elif action == "stop":
                self.systemd_running = False
            return done(values)
        if values[0] == "schtasks.exe":
            action = values[1].lower()
            if action == "/query":
                return done(
                    values,
                    code=0 if self.windows_installed else 1,
                    stdout="Status: Running\n"
                    if self.windows_running
                    else "Status: Ready\n",
                )
            if action == "/create":
                self.windows_installed = True
            elif action == "/run":
                self.windows_running = True
            elif action == "/end":
                self.windows_running = False
            elif action == "/delete":
                self.windows_installed = False
                self.windows_running = False
            return done(values)
        return done(values)


def done(argv, *, code: int = 0, stdout: str = ""):
    return subprocess.CompletedProcess(argv, code, stdout=stdout, stderr="")


def manager(
    tmp_path: Path,
    *,
    platform: str,
    runner: FakeRunner,
) -> LinkServiceManager:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return LinkServiceManager(
        platform=platform,
        fabric_home=tmp_path / "fabric-home",
        workspace=workspace,
        python_executable=Path(sys.executable),
        runner=runner,
        user_home=tmp_path / "user-home",
    )


def test_launchd_service_is_current_user_outbound_entry_and_preserves_state(tmp_path):
    runner = FakeRunner()
    subject = manager(tmp_path, platform="darwin", runner=runner)
    identity = subject.link_home / "route.key"
    identity.parent.mkdir(parents=True)
    identity.write_bytes(b"identity")

    status = subject.install()

    assert status.installed and status.running and status.starts_on_login
    payload = plistlib.loads(subject.definition_path.read_bytes())
    assert payload["Label"] == "com.fabric.link"
    assert payload["ProgramArguments"][2] == "fabric_link.service_entry"
    assert "--fabric-home" in payload["ProgramArguments"]
    assert "oauth" not in repr(payload).lower()
    assert "google" not in repr(payload).lower()

    removed = subject.uninstall()
    assert not removed.installed and not removed.running
    assert identity.read_bytes() == b"identity"


def test_systemd_service_is_hardened_and_never_opens_a_listener(tmp_path):
    runner = FakeRunner()
    subject = manager(tmp_path, platform="linux", runner=runner)

    status = subject.install()
    unit = subject.definition_path.read_text()

    assert status.installed and status.running and status.starts_on_login
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "fabric_link.service_entry" in unit
    assert "link host" not in unit
    assert "--bind" not in unit
    assert "ListenStream" not in unit


def test_windows_task_uses_interactive_user_and_least_privilege(tmp_path):
    runner = FakeRunner()
    subject = manager(tmp_path, platform="windows", runner=runner)

    status = subject.install()
    definition = subject.definition_path.read_text(encoding="utf-16")

    assert status.installed and status.running
    assert "<LogonType>InteractiveToken</LogonType>" in definition
    assert "<RunLevel>LeastPrivilege</RunLevel>" in definition
    assert "S-1-5-21-1000" in definition
    assert "Password" not in definition
    assert "fabric_link.service_entry" in definition


def test_service_refuses_unmanaged_definition_and_invalid_workspace(tmp_path):
    runner = FakeRunner()
    subject = manager(tmp_path, platform="linux", runner=runner)
    subject.definition_path.parent.mkdir(parents=True)
    subject.definition_path.write_text("[Service]\nExecStart=/bin/false\n")
    with pytest.raises(LinkServiceError, match="link_service_definition_conflict"):
        subject.install(force=True)

    with pytest.raises(LinkServiceError, match="link_service_workspace_invalid"):
        LinkServiceManager(
            platform="linux",
            fabric_home=tmp_path / "fabric",
            workspace=tmp_path / "missing",
            python_executable=Path(sys.executable),
            runner=runner,
            user_home=tmp_path / "home",
        )
