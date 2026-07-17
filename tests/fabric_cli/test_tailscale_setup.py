"""Focused tests for the official-CLI Tailscale setup flow."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from fabric_cli import tailscale_setup as tailscale
from fabric_cli.subcommands.setup import build_setup_parser

_REAL_SUBPROCESS_ENV = tailscale._subprocess_env


def _completed(
    argv: list[str],
    returncode: int = 0,
    stdout: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")


def _status_payload(
    state: str,
    *,
    dns_name: str = "fabric-box.example.ts.net.",
    hostname: str = "fabric-box",
    ips: list[str] | None = None,
) -> str:
    return json.dumps({
        "BackendState": state,
        "Self": {
            "DNSName": dns_name,
            "HostName": hostname,
            "TailscaleIPs": ips or ["fd7a:115c:a1e0::1", "100.64.0.9"],
        },
        "FutureField": {"is": "ignored"},
    })


def _make_executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture(autouse=True)
def _safe_child_env(monkeypatch):
    monkeypatch.setattr(
        tailscale,
        "_subprocess_env",
        lambda: {"PATH": "/usr/bin", "TAILSCALE_BE_CLI": "1"},
    )


def test_parse_status_projects_running_identity_and_prefers_ipv4():
    status = tailscale.parse_tailscale_status(_status_payload("Running"))

    assert status == tailscale.TailscaleStatus(
        backend_state="Running",
        dns_name="fabric-box.example.ts.net",
        ip="100.64.0.9",
        hostname="fabric-box",
    )
    assert status.is_running is True


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "not-json",
        "[]",
        "{}",
        '{"BackendState": 3}',
        b"\xff",
    ],
)
def test_parse_status_rejects_unusable_payloads(payload):
    assert tailscale.parse_tailscale_status(payload) is None


def test_parse_status_ignores_invalid_ips_and_control_characters():
    status = tailscale.parse_tailscale_status(
        json.dumps({
            "BackendState": "NeedsLogin\n",
            "Self": {
                "DNSName": "node.example.ts.net.\u001b",
                "HostName": "node\nname",
                "TailscaleIPs": ["not-an-ip", "fd7a:115c:a1e0::9"],
            },
        })
    )

    assert status is not None
    assert status.backend_state == "NeedsLogin"
    assert status.dns_name == "node.example.ts.net"
    assert status.hostname == "nodename"
    assert status.ip == "fd7a:115c:a1e0::9"


def test_find_binary_prefers_path_executable(tmp_path, monkeypatch):
    executable = _make_executable(tmp_path / "tailscale")
    monkeypatch.setattr(tailscale, "is_wsl", lambda: False)
    monkeypatch.setattr(tailscale, "_LINUX_CANDIDATES", ())

    found = tailscale.find_tailscale_binary(
        {"PATH": str(tmp_path)},
        platform="linux",
    )

    assert found == str(executable)


def test_find_binary_uses_known_macos_app_path(tmp_path, monkeypatch):
    executable = _make_executable(tmp_path / "Tailscale")
    monkeypatch.setattr(tailscale, "_MACOS_CANDIDATES", (str(executable),))

    found = tailscale.find_tailscale_binary({"PATH": ""}, platform="darwin")

    assert found == str(executable)


def test_find_binary_uses_windows_program_files(tmp_path):
    executable = tmp_path / "Tailscale" / "tailscale.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"MZ")

    found = tailscale.find_tailscale_binary(
        {"PATH": "", "ProgramFiles": str(tmp_path)},
        platform="win32",
    )

    assert found == str(executable)


def test_wsl_prefers_host_windows_cli_and_ignores_linux_cli(tmp_path, monkeypatch):
    _make_executable(tmp_path / "tailscale")
    windows_cli = _make_executable(tmp_path / "tailscale.exe")
    monkeypatch.setattr(tailscale, "_WSL_WINDOWS_CANDIDATES", ())

    found = tailscale.find_tailscale_binary(
        {"PATH": str(tmp_path), "WSL_DISTRO_NAME": "Ubuntu"},
        platform="linux",
    )

    assert found == str(windows_cli)


def test_wsl_does_not_select_a_nested_linux_client(tmp_path, monkeypatch):
    _make_executable(tmp_path / "tailscale")
    monkeypatch.setattr(tailscale, "_WSL_WINDOWS_CANDIDATES", ())

    found = tailscale.find_tailscale_binary(
        {"PATH": str(tmp_path), "WSL_INTEROP": "/run/WSL/1_interop"},
        platform="linux",
    )

    assert found is None


def test_status_uses_machine_readable_bounded_command():
    calls: list[tuple[list[str], dict]] = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return _completed(argv, stdout=_status_payload("Running"))

    status = tailscale.tailscale_status("/opt/tailscale", runner=runner)

    assert status is not None and status.is_running
    assert calls == [
        (
            ["/opt/tailscale", "status", "--json"],
            {
                "capture_output": True,
                "text": True,
                "timeout": 10,
                "check": False,
                "env": {"PATH": "/usr/bin", "TAILSCALE_BE_CLI": "1"},
            },
        )
    ]


def test_setup_child_env_is_minimal_and_drops_arbitrary_secrets(monkeypatch):
    monkeypatch.setattr(tailscale, "_subprocess_env", _REAL_SUBPROCESS_ENV)
    monkeypatch.setattr(
        "tools.environments.local.fabric_subprocess_env",
        lambda **_kwargs: {
            "PATH": "/usr/bin",
            "HOME": "/tmp/home",
            "WSL_INTEROP": "/run/WSL/123_interop",
            "WSL_DISTRO_NAME": "Ubuntu",
            "WSLENV": "PATH/l",
            "AWS_SECRET_ACCESS_KEY": "secret",
            "DATABASE_URL": "secret",
            "NPM_TOKEN": "secret",
        },
    )

    env = tailscale._subprocess_env()

    assert env == {
        "PATH": "/usr/bin",
        "HOME": "/tmp/home",
        "WSL_INTEROP": "/run/WSL/123_interop",
        "WSL_DISTRO_NAME": "Ubuntu",
        "WSLENV": "PATH/l",
        "TAILSCALE_BE_CLI": "1",
    }


def test_wsl_status_child_keeps_interop_socket_but_not_secrets(monkeypatch):
    monkeypatch.setattr(tailscale, "_subprocess_env", _REAL_SUBPROCESS_ENV)
    monkeypatch.setattr(
        "tools.environments.local.fabric_subprocess_env",
        lambda **_kwargs: {
            "PATH": "/usr/bin",
            "WSL_INTEROP": "/run/WSL/987_interop",
            "WSL_DISTRO_NAME": "Ubuntu",
            "DATABASE_URL": "secret",
        },
    )
    seen_env = {}

    def runner(argv, **kwargs):
        seen_env.update(kwargs["env"])
        return _completed(argv, stdout=_status_payload("Running"))

    status = tailscale.tailscale_status(
        "/mnt/c/Program Files/Tailscale/tailscale.exe",
        runner=runner,
    )

    assert status is not None and status.is_running
    assert seen_env["WSL_INTEROP"] == "/run/WSL/987_interop"
    assert seen_env["WSL_DISTRO_NAME"] == "Ubuntu"
    assert "DATABASE_URL" not in seen_env


@pytest.mark.parametrize("failure", [1, "timeout", "bad-json"])
def test_status_failures_are_unverified_not_success(failure):
    def runner(argv, **_kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 10)
        if failure == "bad-json":
            return _completed(argv, stdout="not-json")
        return _completed(argv, returncode=1, stdout=_status_payload("Running"))

    assert tailscale.tailscale_status("/opt/tailscale", runner=runner) is None


def test_already_connected_is_idempotent_and_skips_login(capsys):
    calls: list[list[str]] = []
    config = {"model": {"provider": "openai"}}
    original = json.loads(json.dumps(config))

    def runner(argv, **_kwargs):
        calls.append(argv)
        return _completed(argv, stdout=_status_payload("Running"))

    assert tailscale.setup_tailscale(
        config,
        runner=runner,
        binary="/opt/tailscale",
    )
    assert config == original
    assert calls == [["/opt/tailscale", "status", "--json"]]
    assert "already connected as fabric-box.example.ts.net" in capsys.readouterr().out


def test_login_uses_exact_native_qr_argv_then_verifies(capsys, monkeypatch):
    calls: list[tuple[list[str], dict]] = []
    states = iter(("NeedsLogin", "Running"))
    config = {"gateway": {"enabled": True}}
    original = json.loads(json.dumps(config))
    monkeypatch.setattr(tailscale, "_terminal_is_interactive", lambda: True)

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1:] == ["status", "--json"]:
            return _completed(argv, stdout=_status_payload(next(states)))
        return _completed(argv)

    assert tailscale.setup_tailscale(
        config,
        runner=runner,
        binary="/opt/tailscale",
    )
    assert config == original
    assert [argv for argv, _kwargs in calls] == [
        ["/opt/tailscale", "status", "--json"],
        [
            "/opt/tailscale",
            "login",
            "--qr",
            "--qr-format=small",
            "--timeout=10m",
        ],
        ["/opt/tailscale", "status", "--json"],
    ]
    login_kwargs = calls[1][1]
    assert login_kwargs == {
        "timeout": 620,
        "check": False,
        "env": {"PATH": "/usr/bin", "TAILSCALE_BE_CLI": "1"},
    }
    out = capsys.readouterr().out
    assert "Scan the QR code" in out
    assert "Tailscale connected as fabric-box.example.ts.net" in out


def test_noninteractive_terminal_never_starts_login(monkeypatch, capsys):
    calls: list[list[str]] = []
    monkeypatch.setattr(tailscale, "_terminal_is_interactive", lambda: False)

    def runner(argv, **_kwargs):
        calls.append(argv)
        return _completed(argv, stdout=_status_payload("NeedsLogin"))

    assert not tailscale.setup_tailscale(runner=runner, binary="/opt/tailscale")
    assert calls == [["/opt/tailscale", "status", "--json"]]
    assert "requires an interactive terminal" in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["nonzero", "timeout", "bad-json"])
def test_unverified_preflight_status_never_starts_login(failure, capsys):
    calls: list[list[str]] = []

    def runner(argv, **_kwargs):
        calls.append(argv)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 10)
        if failure == "bad-json":
            return _completed(argv, stdout="not-json")
        return _completed(argv, returncode=1)

    assert not tailscale.setup_tailscale(runner=runner, binary="/opt/tailscale")
    assert calls == [["/opt/tailscale", "status", "--json"]]
    output = capsys.readouterr().out
    assert "status could not be verified" in output
    assert "did not start a login" in output


def test_pending_admin_approval_does_not_start_another_login(capsys):
    calls: list[list[str]] = []

    def runner(argv, **_kwargs):
        calls.append(argv)
        return _completed(argv, stdout=_status_payload("NeedsMachineAuth"))

    assert not tailscale.setup_tailscale(runner=runner, binary="/opt/tailscale")
    assert calls == [["/opt/tailscale", "status", "--json"]]
    output = capsys.readouterr().out
    assert "administrator must approve" in output
    assert "No new login was started" in output


def test_login_retries_briefly_until_running(monkeypatch):
    states = iter(("NeedsLogin", "Starting", "Running"))
    sleeps = []
    monkeypatch.setattr(tailscale, "_terminal_is_interactive", lambda: True)
    monkeypatch.setattr(tailscale.time, "sleep", sleeps.append)

    def runner(argv, **_kwargs):
        if argv[1:] == ["status", "--json"]:
            return _completed(argv, stdout=_status_payload(next(states)))
        return _completed(argv)

    assert tailscale.setup_tailscale(runner=runner, binary="/opt/tailscale")
    assert sleeps == [0.5]


@pytest.mark.parametrize("failure", ["nonzero", "timeout", "interrupt", "oserror"])
def test_login_failure_never_claims_success(failure, monkeypatch, capsys):
    monkeypatch.setattr(tailscale, "_terminal_is_interactive", lambda: True)

    def runner(argv, **_kwargs):
        if argv[1:] == ["status", "--json"]:
            return _completed(argv, stdout=_status_payload("NeedsLogin"))
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 620)
        if failure == "interrupt":
            raise KeyboardInterrupt
        if failure == "oserror":
            raise OSError("cannot execute")
        return _completed(argv, returncode=1)

    assert not tailscale.setup_tailscale(runner=runner, binary="/opt/tailscale")
    output = capsys.readouterr().out
    assert "fabric setup tailscale" in output
    assert "connected as" not in output


def test_device_approval_is_reported_as_pending_not_connected(monkeypatch, capsys):
    monkeypatch.setattr(tailscale, "_terminal_is_interactive", lambda: True)
    states = iter(("NeedsLogin", "NeedsMachineAuth"))

    def runner(argv, **_kwargs):
        if argv[1:] == ["status", "--json"]:
            return _completed(argv, stdout=_status_payload(next(states)))
        return _completed(argv)

    assert not tailscale.setup_tailscale(runner=runner, binary="/opt/tailscale")
    output = capsys.readouterr().out
    assert "administrator must approve this machine" in output
    assert "Tailscale connected as" not in output


def test_missing_binary_shows_platform_install_link_without_running(
    monkeypatch,
    capsys,
):
    links: list[str] = []
    monkeypatch.setattr(tailscale, "find_tailscale_binary", lambda *_a, **_k: None)
    monkeypatch.setattr(tailscale, "_present_install_link", links.append)
    monkeypatch.setattr(tailscale, "is_wsl", lambda: False)
    monkeypatch.setattr(tailscale, "is_container", lambda: False)

    assert not tailscale.setup_tailscale(environ={"PATH": ""}, platform="linux")
    assert links == ["https://tailscale.com/download/linux"]
    output = capsys.readouterr().out
    assert "not installed" in output
    assert "fabric setup tailscale" in output


def test_missing_binary_in_wsl_points_to_windows_host(monkeypatch, capsys):
    links: list[str] = []
    monkeypatch.setattr(tailscale, "find_tailscale_binary", lambda *_a, **_k: None)
    monkeypatch.setattr(tailscale, "_present_install_link", links.append)

    assert not tailscale.setup_tailscale(
        environ={"PATH": "", "WSL_DISTRO_NAME": "Ubuntu"},
        platform="linux",
    )
    assert links == ["https://tailscale.com/download/windows"]
    assert "install and connect Tailscale on Windows" in capsys.readouterr().out


def test_missing_binary_in_container_does_not_offer_privileged_install(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(tailscale, "find_tailscale_binary", lambda *_a, **_k: None)
    monkeypatch.setattr(tailscale, "_present_install_link", lambda _url: None)
    monkeypatch.setattr(tailscale, "is_wsl", lambda: False)
    monkeypatch.setattr(tailscale, "is_container", lambda: True)

    assert not tailscale.setup_tailscale(environ={"PATH": ""}, platform="linux")
    output = capsys.readouterr().out
    assert "connect Tailscale on the host" in output
    assert "curl" not in output
    assert "sudo" not in output


def test_setup_parser_accepts_and_advertises_tailscale_section():
    parser = argparse.ArgumentParser(prog="fabric")
    subparsers = parser.add_subparsers(dest="command")
    handler = lambda _args: None
    build_setup_parser(subparsers, cmd_setup=handler)

    args = parser.parse_args(["setup", "tailscale"])

    assert args.section == "tailscale"
    assert args.func is handler
    assert "tailscale" in subparsers.choices["setup"].format_help()
