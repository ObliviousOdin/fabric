"""Guided Tailscale enrollment using the official Tailscale CLI.

Fabric does not own Tailscale credentials or network policy.  This module only
discovers an already-installed client, reads its status, and asks that client
to run its native QR login ceremony.  It deliberately never installs
Tailscale, supplies auth keys, or changes routes, SSH, Funnel, exit-node, tag,
or ACL settings.
"""

from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fabric_cli.cli_output import print_info, print_success, print_warning
from fabric_constants import is_container, is_wsl


_STATUS_TIMEOUT_SECONDS = 10
_LOGIN_TIMEOUT_SECONDS = 620
_VERIFY_ATTEMPTS = 5
_VERIFY_DELAY_SECONDS = 0.5
_LOGIN_ARGS = ("login", "--qr", "--qr-format=small", "--timeout=10m")

_MACOS_CANDIDATES = (
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    "/usr/local/bin/tailscale",
    "/opt/homebrew/bin/tailscale",
)
_LINUX_CANDIDATES = (
    "/usr/bin/tailscale",
    "/usr/local/bin/tailscale",
    "/snap/bin/tailscale",
)
_WSL_WINDOWS_CANDIDATES = (
    "/mnt/c/Program Files/Tailscale/tailscale.exe",
    "/mnt/c/Program Files (x86)/Tailscale/tailscale.exe",
)

_SUBPROCESS_ENV_KEYS = frozenset({
    "PATH",
    "HOME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TMP",
    "TEMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "TERM",
    "XDG_RUNTIME_DIR",
    "WSL_INTEROP",
    "WSL_DISTRO_NAME",
    "WSLENV",
})


@dataclass(frozen=True)
class TailscaleStatus:
    """Small, stable projection of ``tailscale status --json`` output."""

    backend_state: str
    dns_name: str | None = None
    ip: str | None = None
    hostname: str | None = None

    @property
    def is_running(self) -> bool:
        return self.backend_state.casefold() == "running"


Runner = Callable[..., subprocess.CompletedProcess[Any]]


def _platform_family(platform: str | None) -> str:
    value = (platform or sys.platform).strip().lower()
    if value.startswith(("win", "cygwin", "msys")):
        return "windows"
    if value in {"darwin", "mac", "macos"}:
        return "macos"
    if value.startswith("linux"):
        return "linux"
    return value or "unknown"


def _is_wsl_runtime(environ: Mapping[str, str], platform: str | None) -> bool:
    if _platform_family(platform) != "linux":
        return False
    if environ.get("WSL_DISTRO_NAME") or environ.get("WSL_INTEROP"):
        return True
    try:
        return is_wsl()
    except Exception:
        return False


def _is_executable_file(path: str, *, platform: str | None) -> bool:
    try:
        candidate = Path(path)
        if not candidate.is_file():
            return False
        # Windows executables do not carry POSIX execute bits.  ``is_file``
        # plus an executable extension is the appropriate check there.
        if _platform_family(platform) == "windows":
            return candidate.suffix.casefold() in {".exe", ".cmd", ".bat", ".com"}
        return os.access(candidate, os.X_OK)
    except OSError:
        return False


def find_tailscale_binary(
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> str | None:
    """Return an executable official Tailscale CLI candidate, if installed.

    WSL intentionally searches for the Windows-host client only.  Running a
    second Tailscale node inside WSL can create duplicate nodes and nested
    tunnel/MTU problems, so Fabric does not select a Linux client there.
    """

    env = os.environ if environ is None else environ
    family = _platform_family(platform)
    wsl = _is_wsl_runtime(env, platform)
    search_path = env.get("PATH", "")

    if wsl:
        command_names = ("tailscale.exe",)
    elif family == "windows":
        command_names = ("tailscale.exe", "tailscale")
    else:
        command_names = ("tailscale",)

    candidates: list[str] = []
    for name in command_names:
        resolved = shutil.which(name, path=search_path)
        if resolved:
            candidates.append(resolved)

    if wsl:
        candidates.extend(_WSL_WINDOWS_CANDIDATES)
    elif family == "macos":
        candidates.extend(_MACOS_CANDIDATES)
    elif family == "windows":
        for base_key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = env.get(base_key, "").strip()
            if base:
                candidates.append(str(Path(base) / "Tailscale" / "tailscale.exe"))
    elif family == "linux":
        candidates.extend(_LINUX_CANDIDATES)

    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.normpath(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        candidate_platform = "windows" if wsl else platform
        if _is_executable_file(candidate, platform=candidate_platform):
            return candidate
    return None


def _clean_label(value: object, *, max_length: int = 253) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = "".join(ch for ch in value.strip() if ch.isprintable())
    if not cleaned:
        return None
    return cleaned[:max_length]


def _preferred_ip(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    parsed: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for item in value:
        if not isinstance(item, str):
            continue
        try:
            parsed.append(ipaddress.ip_address(item.strip()))
        except ValueError:
            continue
    for address in parsed:
        if isinstance(address, ipaddress.IPv4Address):
            return str(address)
    return str(parsed[0]) if parsed else None


def parse_tailscale_status(payload: str | bytes) -> TailscaleStatus | None:
    """Parse the documented status fields while tolerating schema additions."""

    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    backend_state = _clean_label(data.get("BackendState"), max_length=64)
    if not backend_state:
        return None

    self_node = data.get("Self")
    if not isinstance(self_node, dict):
        self_node = {}
    dns_name = _clean_label(self_node.get("DNSName"))
    if dns_name:
        dns_name = dns_name.rstrip(".") or None
    return TailscaleStatus(
        backend_state=backend_state,
        dns_name=dns_name,
        ip=_preferred_ip(self_node.get("TailscaleIPs")),
        hostname=_clean_label(self_node.get("HostName")),
    )


def _subprocess_env() -> dict[str, str]:
    # Tailscale needs no Fabric/provider credentials.  Use the shared
    # strip-by-default child environment and force macOS app invocations to
    # behave as a CLI rather than opening the GUI.
    from tools.environments.local import hermes_subprocess_env

    base_env = hermes_subprocess_env(inherit_credentials=False)
    env = {
        key: value
        for key, value in base_env.items()
        if key in _SUBPROCESS_ENV_KEYS and isinstance(value, str)
    }
    env["TAILSCALE_BE_CLI"] = "1"
    return env


def tailscale_status(
    binary: str | None,
    *,
    runner: Runner | None = None,
) -> TailscaleStatus | None:
    """Read a bounded, machine-readable status snapshot from Tailscale."""

    if not binary:
        return None
    run = runner or subprocess.run
    try:
        completed = run(
            [binary, "status", "--json"],
            capture_output=True,
            text=True,
            timeout=_STATUS_TIMEOUT_SECONDS,
            check=False,
            env=_subprocess_env(),
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if completed.returncode != 0:
        return None
    return parse_tailscale_status(completed.stdout or "")


def _install_url(platform: str | None, environ: Mapping[str, str]) -> str:
    if _is_wsl_runtime(environ, platform):
        return "https://tailscale.com/download/windows"
    family = _platform_family(platform)
    if family == "macos":
        return "https://tailscale.com/download/mac"
    if family == "windows":
        return "https://tailscale.com/download/windows"
    if family == "linux":
        return "https://tailscale.com/download/linux"
    return "https://tailscale.com/download"


def _can_open_install_page() -> bool:
    try:
        from fabric_cli.auth import _can_open_graphical_browser, _is_remote_session

        return not _is_remote_session() and _can_open_graphical_browser()
    except Exception:
        return False


def _present_install_link(url: str) -> None:
    try:
        from fabric_cli.setup_links import present_setup_link

        present_setup_link(
            url,
            label="Install Tailscale",
            open_browser=_can_open_install_page(),
        )
    except Exception:
        # Link/QR presentation is deliberately non-fatal.  The exact HTTPS
        # URL remains a terminal-clickable fallback even without qrcode or a
        # graphical browser.
        print_info(f"Install Tailscale: {url}")


def _terminal_is_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _identity(status: TailscaleStatus) -> str | None:
    return status.dns_name or status.hostname or status.ip


def _print_retry() -> None:
    print_info("When Tailscale is ready, run: fabric setup tailscale")


def _wait_for_connected(
    binary: str,
    *,
    runner: Runner | None,
) -> TailscaleStatus | None:
    """Poll briefly for daemon state propagation after a successful login."""
    latest: TailscaleStatus | None = None
    for attempt in range(_VERIFY_ATTEMPTS):
        latest = tailscale_status(binary, runner=runner)
        if latest and (
            latest.is_running
            or latest.backend_state.casefold() == "needsmachineauth"
        ):
            return latest
        if attempt + 1 < _VERIFY_ATTEMPTS:
            time.sleep(_VERIFY_DELAY_SECONDS)
    return latest


def setup_tailscale(
    config: dict[str, Any] | None = None,
    *,
    runner: Runner | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    binary: str | None = None,
) -> bool:
    """Connect this machine through Tailscale's official QR login.

    The optional config argument matches Fabric setup-section handlers but is
    intentionally ignored: all node credentials and control-plane state stay
    owned by Tailscale.
    """

    del config
    env = os.environ if environ is None else environ
    executable = binary or find_tailscale_binary(env, platform)
    if not executable:
        print_warning("Tailscale is not installed, or its CLI is not available.")
        if _is_wsl_runtime(env, platform):
            print_info(
                "WSL detected: install and connect Tailscale on Windows, then "
                "run this command again from WSL."
            )
        else:
            try:
                in_container = is_container()
            except Exception:
                in_container = False
            if in_container:
                print_info(
                    "Container detected: connect Tailscale on the host or expose "
                    "a host-managed Tailscale CLI/socket to this container."
                )
        _present_install_link(_install_url(platform, env))
        _print_retry()
        return False

    before = tailscale_status(executable, runner=runner)
    if before is None:
        print_warning(
            "Tailscale status could not be verified, so Fabric did not start "
            "a login. Make sure the Tailscale service is running."
        )
        _print_retry()
        return False
    if before and before.is_running:
        identity = _identity(before)
        if identity:
            print_success(f"Tailscale is already connected as {identity}.")
        else:
            print_success("Tailscale is already connected on this machine.")
        return True
    if before and before.backend_state.casefold() == "needsmachineauth":
        print_warning(
            "Tailscale is signed in, but a tailnet administrator must approve "
            "this machine. No new login was started."
        )
        _print_retry()
        return False

    if not _terminal_is_interactive():
        print_warning("Tailscale QR login requires an interactive terminal.")
        _print_retry()
        return False

    print_info("Scan the QR code below with your phone to connect this machine.")
    print_info(
        "Press Ctrl+C to cancel; Fabric will not save any Tailscale credentials."
    )
    run = runner or subprocess.run
    command = [executable, *_LOGIN_ARGS]
    try:
        completed = run(
            command,
            timeout=_LOGIN_TIMEOUT_SECONDS,
            check=False,
            env=_subprocess_env(),
        )
    except KeyboardInterrupt:
        print_warning("Tailscale login was cancelled.")
        _print_retry()
        return False
    except subprocess.TimeoutExpired:
        print_warning("Tailscale login timed out before this machine was connected.")
        _print_retry()
        return False
    except (OSError, subprocess.SubprocessError, ValueError):
        print_warning("Tailscale could not start its login flow.")
        _print_retry()
        return False

    if completed.returncode != 0:
        print_warning("Tailscale login did not complete successfully.")
        _print_retry()
        return False

    after = _wait_for_connected(executable, runner=runner)
    if after and after.is_running:
        identity = _identity(after)
        if identity:
            print_success(f"Tailscale connected as {identity}.")
        else:
            print_success("Tailscale connected on this machine.")
        return True

    if after and after.backend_state.casefold() == "needsmachineauth":
        print_warning(
            "Tailscale sign-in succeeded, but a tailnet administrator must "
            "approve this machine."
        )
    else:
        print_warning(
            "Tailscale login finished, but the connected state was not verified."
        )
    _print_retry()
    return False


__all__ = [
    "TailscaleStatus",
    "find_tailscale_binary",
    "parse_tailscale_status",
    "setup_tailscale",
    "tailscale_status",
]
