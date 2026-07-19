"""Parser for the first-class ``fabric mobile`` delivery command."""

from __future__ import annotations

from argparse import Namespace
from typing import Callable


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
            "binds always require configured authentication."
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
    parser.set_defaults(func=cmd_mobile)
