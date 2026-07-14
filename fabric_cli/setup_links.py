"""Trusted link presentation for setup and device-authorization flows."""

from __future__ import annotations

import io
import sys
import webbrowser
from dataclasses import dataclass
from typing import Any, TextIO
from urllib.parse import urlsplit


@dataclass(frozen=True)
class LinkPresentation:
    """Record which optional link-presentation affordances succeeded."""

    qr_rendered: bool
    browser_opened: bool


def _load_qrcode() -> Any:
    import qrcode

    return qrcode


def _validate_setup_url(url: str) -> None:
    if not isinstance(url, str) or not url or url != url.strip():
        raise ValueError("setup links must use an absolute HTTPS URL")
    if any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise ValueError("setup links must use an absolute HTTPS URL")

    try:
        parsed = urlsplit(url)
        _port = parsed.port  # Validate a present port without rewriting the URL.
    except (TypeError, ValueError) as exc:
        raise ValueError("setup links must use an absolute HTTPS URL") from exc

    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("setup links must use an absolute HTTPS URL")


def render_terminal_qr(url: str, *, output: TextIO | None = None) -> bool:
    """Render a compact terminal QR, returning false on optional failures."""

    stream = output or sys.stdout
    try:
        qrcode = _load_qrcode()
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=1,
        )
        qr.add_data(url)
        qr.make(fit=True)
        rendered = io.StringIO()
        qr.print_ascii(out=rendered, tty=False, invert=True)
        print(rendered.getvalue().rstrip("\n"), file=stream)
        return True
    except Exception:
        return False


def present_setup_link(
    url: str,
    *,
    label: str,
    open_browser: bool,
    output: TextIO | None = None,
) -> LinkPresentation:
    """Present an exact trusted URL with optional terminal QR and browser open.

    QR generation and browser launch are deliberately best-effort. The exact
    URL is always printed first so setup remains usable without either.
    """

    _validate_setup_url(url)
    stream = output or sys.stdout
    print(f"  {label}: {url}", file=stream)
    qr_rendered = render_terminal_qr(url, output=stream)

    browser_opened = False
    if open_browser:
        try:
            browser_opened = bool(webbrowser.open(url))
        except Exception:
            browser_opened = False

    return LinkPresentation(
        qr_rendered=qr_rendered,
        browser_opened=browser_opened,
    )
