"""Shared allowlist of ``/api/*`` paths that bypass dashboard auth.

Two middlewares enforce dashboard auth and previously kept independent
copies of this list:

* ``fabric_cli.web_server.auth_middleware`` — loopback / ``--insecure``
  mode, gates on the ephemeral ``_SESSION_TOKEN``.
* ``fabric_cli.dashboard_auth.middleware.gated_auth_middleware`` —
  non-loopback mode, gates on the OAuth session cookie.

When the lists drifted, ``/api/status`` ended up public under the legacy gate
but returned 401 under the OAuth gate. That broke unauthenticated liveness
checks even though the dashboard itself was healthy.

Centralising the allowlist here so both middlewares import the same
frozenset prevents the next drift. Keep this list minimal — only truly
non-sensitive, read-only endpoints belong here. As a sanity check, every
entry should be safe to expose to:

  * external uptime probes,
  * the dashboard SPA before the user has logged in,
  * anyone who happens to ``curl`` the hostname.

If a new endpoint doesn't pass all three tests, it should be gated and
the SPA should bootstrap it after login instead.
"""
from __future__ import annotations

PUBLIC_API_PATHS: frozenset[str] = frozenset({
    # Liveness probe target. Returns version, gateway state, active
    # session count, and the dashboard auth-gate shape. No bodies, no
    # session content, and no secrets.
    "/api/status",
    # Read-only config-defaults / schema feeds for the SPA's Config page.
    "/api/config/defaults",
    "/api/config/schema",
    # Read-only model metadata (context windows, etc.) — same shape as
    # provider catalogs already exposed on the public internet.
    "/api/model/info",
    # Read-only theme + plugin manifests for the dashboard skin engine.
    "/api/dashboard/themes",
    "/api/dashboard/plugins",
})
