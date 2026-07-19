"""Mobile pairing helpers: build and display the ``fabric://pair`` QR.

``fabric serve --qr`` / ``fabric dashboard --qr`` print a QR code a Fabric
mobile client scans to connect, instead of typing a URL and credential by
hand. The payload is a ``fabric://pair`` URI:

    fabric://pair?v=1&url=<http(s) base>&auth=<token|gated>[&token=<session token>]

Two auth shapes, matching the server's WS-upgrade contract
(``_ws_auth_reason`` in ``web_server.py``):

* ``auth=token`` — loopback/tunnel deployments where the ephemeral
  ``_SESSION_TOKEN`` is the credential. The token rides in the QR, so the
  phone connects with zero typing. Only emitted when the auth gate is OFF:
  in gated mode the legacy token path is rejected outright, and a QR that
  leaked the session token would be a credential exfil channel.
* ``auth=gated`` — non-loopback binds, where the June 2026 hardening
  requires an auth provider. The QR carries the URL only; the phone probes
  ``/api/auth/providers`` and shows a username/password form (or, later,
  the OAuth browser flow). Credentials never appear in the QR.

The QR itself renders with the optional ``qrcode`` package (already pinned
by the messaging extras). Without it the pairing URI still prints, so the
feature degrades to copy/paste instead of failing.

Distinct from ``fabric_cli/pairing.py``, which is the messaging-gateway DM
pairing (approving chat users), not device pairing.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import quote, urlsplit

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

# Tailscale hands out CGNAT-range addresses (100.64.0.0/10). When the server
# binds 0.0.0.0 we prefer advertising that address in the pairing URI: it is
# the one a phone on the same tailnet can actually reach, and unlike LAN IPs
# it is stable across networks.
_TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


def machine_addresses() -> list[str]:
    """Best-effort list of this machine's IPv4 addresses, no external deps.

    Uses the connected-UDP trick (no packets are sent) plus getaddrinfo on
    the hostname. Order is deduplicated and loopback-free; callers pick with
    :func:`preferred_advertise_host`.
    """
    found: list[str] = []

    # Route-based discovery: which source address would we use to reach the
    # Tailscale range / a LAN / the internet? Captures the tailnet and
    # primary-LAN addresses even when the hostname doesn't resolve to them.
    for probe in ("100.100.100.100", "10.255.255.255", "8.8.8.8"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect((probe, 1))
                addr = s.getsockname()[0]
            finally:
                s.close()
            if addr and not addr.startswith("127.") and addr not in found:
                found.append(addr)
        except Exception:
            continue

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            if addr and not addr.startswith("127.") and addr not in found:
                found.append(addr)
    except Exception:
        pass

    return found


def is_tailscale_address(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr) in _TAILSCALE_NET
    except ValueError:
        return False


def preferred_advertise_host(bound_host: str) -> str | None:
    """Pick the host to advertise in the pairing URI.

    * explicit non-wildcard bind → advertise exactly that;
    * wildcard bind (``0.0.0.0`` / ``::``) → prefer a Tailscale (CGNAT)
      address, else the first discovered private address;
    * loopback bind → None (a phone cannot reach it directly; the caller
      must pass an explicit ``--qr-url`` for its tunnel).
    """
    if bound_host in ("0.0.0.0", "::"):
        addrs = machine_addresses()
        for addr in addrs:
            if is_tailscale_address(addr):
                return addr
        return addrs[0] if addrs else None
    if bound_host in _LOOPBACK_HOSTS:
        return None
    return bound_host


def build_pairing_uri(base_url: str, *, token: str | None = None) -> str:
    """Assemble the ``fabric://pair`` URI. ``token`` only for ungated mode."""
    uri = f"fabric://pair?v=1&url={quote(base_url, safe='')}"
    if token:
        uri += f"&auth=token&token={quote(token, safe='')}"
    else:
        uri += "&auth=gated"
    return uri


def build_pairing_page_url(base_url: str, pairing_uri: str) -> str:
    """Return the browser-safe landing URL encoded by the terminal QR.

    The pairing payload belongs in the URL fragment so credentials in a
    token-mode URI are never sent in the HTTP request, reverse-proxy logs,
    cookies, or referrer headers. The mobile web client removes the fragment
    from browser history as soon as it has read it.
    """
    return f"{base_url.rstrip('/')}/mobile/pair#pair={quote(pairing_uri, safe='')}"


def validate_pairing_base_url(value: str) -> str:
    """Return a safe pairing base URL or raise ``ValueError``.

    Native release clients and installable PWAs require HTTPS. Plain HTTP is
    accepted only for loopback development, where the credential cannot cross
    the network. Query strings, fragments, and URL userinfo are never valid
    gateway coordinates.
    """
    raw = value.strip().rstrip("/")
    if not raw or any(ord(character) <= 32 for character in raw):
        raise ValueError("--qr-url must be an absolute http:// or https:// URL")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("--qr-url must be an absolute http:// or https:// URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("--qr-url must not contain embedded credentials")
    if "?" in raw or "#" in raw:
        raise ValueError("--qr-url must not contain a query string or fragment")
    if parsed.path:
        raise ValueError("--qr-url must be an origin without a path")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("--qr-url contains an invalid port") from exc
    if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK_HOSTS:
        raise ValueError(
            "--qr-url must use HTTPS unless it targets loopback-only development"
        )
    return raw


def _render_qr(data: str) -> str | None:
    """ASCII QR via the optional ``qrcode`` package; None when unavailable."""
    try:
        import io

        import qrcode
    except Exception:
        return None
    try:
        qr = qrcode.QRCode(border=1)
        qr.add_data(data)
        qr.make(fit=True)
        buf = io.StringIO()
        qr.print_ascii(out=buf, invert=True)
        return buf.getvalue()
    except Exception:
        return None


def print_pairing_info(
    *,
    bound_host: str,
    port: int,
    auth_required: bool,
    session_token: str,
    override_url: str = "",
) -> None:
    """Print the pairing URI (and QR when renderable) for a live server.

    Called from ``start_server`` right after the ready banner, when the
    operator passed ``--qr``. Never raises: pairing display is advisory and
    must not take down the server it describes.
    """
    try:
        if override_url:
            base_url = override_url.rstrip("/")
        else:
            advertise = preferred_advertise_host(bound_host)
            if advertise is None:
                print(
                    "  Pairing QR skipped: the server is bound to loopback, which "
                    "a phone cannot reach directly.\n"
                    "  Either bind a reachable address (requires an auth provider, "
                    "e.g. `--host <tailscale-ip>`), or front this port with a "
                    "tunnel and pass its URL: `--qr-url https://<machine>.<tailnet>.ts.net`.",
                    flush=True,
                )
                return
            base_url = f"http://{advertise}:{port}"

        # In gated mode the session token is NOT a usable (or safe) credential
        # for remote clients — the QR carries only the URL and the phone asks
        # for the provider login.
        uri = build_pairing_uri(
            base_url, token=None if auth_required else session_token
        )
        page_url = build_pairing_page_url(base_url, uri)

        print(f"\n  Mobile pairing → {base_url}", flush=True)
        if auth_required:
            print(
                "  Auth: provider login (the app asks for username/password after scanning).",
                flush=True,
            )
        else:
            print(
                "  Auth: session token embedded in the QR — anyone who can see this QR "
                "can control this Fabric. Treat it like a password.",
                flush=True,
            )

        rendered = _render_qr(page_url)
        if rendered:
            print(rendered, flush=True)
        else:
            print(
                "  (Install the `qrcode` package to render this as a scannable QR.)",
                flush=True,
            )
        print("  Scan with the phone camera to open Fabric Mobile, or with the")
        print("  Fabric app's scanner to pair directly:", flush=True)
        print(f"  {page_url}\n", flush=True)
    except Exception:
        # Advisory output only — never let pairing display break serving.
        pass
