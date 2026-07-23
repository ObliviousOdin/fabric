"""Parser for the first-class ``fabric mobile`` delivery command."""

from __future__ import annotations

import json
import socket
import subprocess
from argparse import Namespace
from functools import partial
from typing import Callable
from urllib.parse import urlsplit


_TAILSCALE_COMMAND_TIMEOUT_SECONDS = 20
_TAILSCALE_STATUS_TIMEOUT_SECONDS = 10
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _loopback_port_available(port: int) -> bool:
    """Return whether Fabric can claim the exact local Serve target."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def _tailscale_serve_config(binary: str, *, runner: Callable) -> dict:
    """Read Serve state without exposing tailnet-specific command output."""
    from fabric_cli.tailscale_setup import _subprocess_env

    try:
        completed = runner(
            [binary, "serve", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=_TAILSCALE_STATUS_TIMEOUT_SECONDS,
            check=False,
            env=_subprocess_env(),
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ValueError("Tailscale Serve status could not be verified") from exc
    if completed.returncode != 0:
        raise ValueError("Tailscale Serve status could not be verified")
    try:
        config = json.loads(completed.stdout or "null")
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("Tailscale Serve returned an unreadable status") from exc
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise ValueError("Tailscale Serve returned an unreadable status")
    return config


def _root_proxy_targets(config: dict, *, dns_name: str) -> list[str | None]:
    """Project this node's root handlers without retaining tailnet metadata."""
    web = config.get("Web", {})
    if web is None:
        return []
    if not isinstance(web, dict):
        return [None]

    targets: list[str | None] = []
    expected_host = dns_name.casefold().rstrip(".")
    for site_name, site in web.items():
        if not isinstance(site_name, str):
            continue
        parsed_site = urlsplit(
            site_name if "://" in site_name else f"//{site_name}"
        )
        site_host = (parsed_site.hostname or "").casefold().rstrip(".")
        if site_host != expected_host:
            continue
        if not isinstance(site, dict):
            continue
        handlers = site.get("Handlers", {})
        if not isinstance(handlers, dict) or "/" not in handlers:
            continue
        handler = handlers["/"]
        targets.append(handler.get("Proxy") if isinstance(handler, dict) else None)
    return targets


def _proxy_endpoint(value: str | None) -> tuple[str, int] | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.hostname.casefold(), port


def configure_mobile_tailscale(
    args: Namespace,
    *,
    runner: Callable | None = None,
) -> str:
    """Configure and verify the private HTTPS tunnel for ``mobile --tailscale``."""
    host = str(getattr(args, "host", "0.0.0.0") or "0.0.0.0").strip()
    qr_url = str(getattr(args, "qr_url", "") or "").strip()
    port = getattr(args, "port", 9119)
    if host not in {"0.0.0.0", *_LOOPBACK_HOSTS}:
        raise ValueError("--tailscale cannot be combined with a non-loopback --host")
    if qr_url:
        raise ValueError("--tailscale owns the advertised URL; remove --qr-url")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("--tailscale requires a fixed --port between 1 and 65535")
    if not _loopback_port_available(port):
        raise ValueError(
            f"loopback port {port} is already in use; Fabric did not change Tailscale Serve"
        )

    from fabric_cli.mobile_pairing import validate_pairing_base_url
    from fabric_cli.tailscale_setup import (
        _subprocess_env,
        find_tailscale_binary,
        tailscale_status,
    )

    binary = find_tailscale_binary()
    if not binary:
        raise ValueError(
            "Tailscale CLI not found; install Tailscale or run `fabric setup tailscale`"
        )
    run = runner or subprocess.run
    status = tailscale_status(binary, runner=run)
    if status is None or not status.is_running:
        raise ValueError(
            "Tailscale is not connected; connect it or run `fabric setup tailscale`"
        )
    if not status.dns_name:
        raise ValueError(
            "Tailscale did not report a MagicDNS hostname required for HTTPS Serve"
        )

    before = _tailscale_serve_config(binary, runner=run)
    existing_targets = _root_proxy_targets(before, dns_name=status.dns_name)
    if existing_targets and any(
        (endpoint := _proxy_endpoint(target)) is None or endpoint[1] != port
        for target in existing_targets
    ):
        raise ValueError(
            "Tailscale Serve already uses its HTTPS root for another service; "
            "Fabric did not overwrite it"
        )

    target = f"http://127.0.0.1:{port}"
    try:
        completed = run(
            [binary, "serve", "--bg", "--yes", target],
            capture_output=True,
            text=True,
            timeout=_TAILSCALE_COMMAND_TIMEOUT_SECONDS,
            check=False,
            env=_subprocess_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Tailscale Serve timed out while configuring the tunnel") from exc
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ValueError("Tailscale Serve could not configure the tunnel") from exc
    if completed.returncode != 0:
        raise ValueError(
            "Tailscale Serve could not configure the tunnel; run "
            f"`tailscale serve --bg {port}` once to complete any Tailscale approval"
        )

    after = _tailscale_serve_config(binary, runner=run)
    verified_targets = _root_proxy_targets(after, dns_name=status.dns_name)
    if not verified_targets or any(
        _proxy_endpoint(target) not in {
            ("127.0.0.1", port),
            ("localhost", port),
            ("::1", port),
        }
        for target in verified_targets
    ):
        raise ValueError("Tailscale Serve did not verify the expected loopback tunnel")

    advertised_url = validate_pairing_base_url(f"https://{status.dns_name}")
    args.host = "127.0.0.1"
    args.qr_url = advertised_url
    print("  Fabric Mobile network mode: private Tailscale HTTPS tunnel")
    print(f"  {advertised_url} → {target}")
    return advertised_url


def run_mobile_command(args: Namespace, *, cmd_mobile: Callable) -> object:
    """Apply the optional network mode, then invoke the ordinary mobile command."""
    if getattr(args, "tailscale", False) and not getattr(args, "devices", False):
        try:
            configure_mobile_tailscale(args)
        except ValueError as exc:
            raise SystemExit(f"Fabric Mobile Tailscale error: {exc}") from None
    return cmd_mobile(args)


def validate_mobile_install_selection(args: Namespace) -> str:
    """Validate explicit native selectors and return the effective install mode."""
    install_mode = str(getattr(args, "install", "auto") or "auto")
    android_serial = str(getattr(args, "android_serial", "") or "").strip()
    ios_device = str(getattr(args, "ios_device", "") or "").strip()

    if android_serial and ios_device:
        raise ValueError(
            "--android-serial and --ios-device are mutually exclusive; select one phone"
        )
    if android_serial:
        if install_mode not in {"auto", "android"}:
            raise ValueError("--android-serial requires --install android (or auto)")
        return "android"
    if ios_device:
        if install_mode not in {"auto", "ios"}:
            raise ValueError("--ios-device requires --install ios (or auto)")
        return "ios"
    return install_mode


def build_mobile_parser(subparsers, *, cmd_mobile: Callable) -> None:
    parser = subparsers.add_parser(
        "mobile",
        help="Install Fabric on an attached phone and start the secure mobile gateway",
        description=(
            "Build and install the native debug app on one attached phone when possible, "
            "then serve the Fabric Mobile PWA and print a secure pairing QR. Non-loopback "
            "binds always require configured authentication. Use --tailscale for a private "
            "HTTPS tunnel with a zero-typing token QR."
        ),
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Gateway bind host (default: 0.0.0.0 so a phone on the LAN can reach it)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9119,
        help="Gateway port (default: 9119; use 0 for an OS-assigned port)",
    )
    parser.add_argument(
        "--qr-url",
        default="",
        help=(
            "HTTPS base URL advertised in the QR, such as a trusted Tailscale or tunnel URL. "
            "Required for normal PWA installation outside localhost."
        ),
    )
    parser.add_argument(
        "--tailscale",
        action="store_true",
        help=(
            "Bind Fabric to loopback, configure and verify Tailscale Serve, and advertise "
            "the machine's MagicDNS HTTPS URL. Refuses to replace an unrelated root route."
        ),
    )
    parser.add_argument(
        "--no-qr",
        action="store_true",
        help="Start the mobile gateway without printing a pairing QR",
    )
    parser.add_argument(
        "--install",
        choices=("auto", "none", "android", "ios"),
        default="auto",
        help=(
            "Native install mode (default: auto). Auto installs only when exactly one "
            "eligible attached device is found; otherwise the PWA still starts."
        ),
    )
    parser.add_argument(
        "--android-serial",
        default="",
        help="Select an attached Android device by adb serial",
    )
    parser.add_argument(
        "--ios-device",
        default="",
        help="Select an attached physical iPhone by UDID",
    )
    parser.add_argument(
        "--ios-team",
        default="",
        help="Apple Development team ID used for physical-device signing",
    )
    parser.add_argument(
        "--native-source",
        default="",
        help=(
            "Path to a Fabric checkout or apps/mobile directory. Native installation is "
            "checkout-only; packaged installs still provide QR and PWA access."
        ),
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Install the native app but do not launch it",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Use an existing packaged mobile web bundle instead of rebuilding it",
    )
    parser.add_argument(
        "--devices",
        action="store_true",
        help="List eligible attached phones and exit without installing or serving",
    )
    parser.set_defaults(func=partial(run_mobile_command, cmd_mobile=cmd_mobile))
