"""Nous Portal dashboard OAuth provider.

The provider uses the authorization-code flow with PKCE and registers only when
a per-install client ID is configured under ``dashboard.oauth`` in
``config.yaml``. Tokens are verified
against the configured Portal JWKS, and rotating refresh tokens are persisted
by the dashboard authentication middleware.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import urllib.parse
from typing import Any, Dict, Optional

import httpx

from fabric_cli.dashboard_auth import (
    DashboardAuthProvider,
    InvalidCodeError,
    LoginStart,
    ProviderError,
    RefreshExpiredError,
    Session,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# Production Portal URL. ``dashboard.oauth.portal_url`` selects a custom deployment.
_DEFAULT_PORTAL_URL = "https://portal.nousresearch.com"


# ---------------------------------------------------------------------------
# Skip-reason channel for operator-friendly error messages
# ---------------------------------------------------------------------------
#
# When the plugin loads but refuses to register (missing / malformed
# config), the auth gate downstream just sees "zero providers" and
# emits a generic "install a provider" error. That's misleading for the
# common case where the provider IS installed but mis-configured. The
# plugin writes the *specific* reason to this module-level slot; the
# gate reads it back when building its fail-closed SystemExit message.
#
# Cleared on every register() call so repeated dashboard starts in the
# same process (tests, hot-reload) don't leak stale reasons.

LAST_SKIP_REASON: str = ""


# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------

# Contract C3: scope name for the dashboard flow.
_SCOPE = "agent_dashboard:access"

# Contract C11: emitted claim should equal 1; tolerant (warn) if missing.
_EXPECTED_CONTRACT_VERSION = 1

# Contract C7: JWKS Cache-Control max-age=300.
_JWKS_CACHE_SECONDS = 300

# httpx timeout for the token endpoint POST.
_TOKEN_ENDPOINT_TIMEOUT_SEC = 10.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64url_no_pad(raw: bytes) -> str:
    """Base64url-encode without ``=`` padding (RFC 7636 §4)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class NousDashboardAuthProvider(DashboardAuthProvider):
    """Nous Portal OAuth via authorization-code + PKCE (S256)."""

    name = "nous"
    display_name = "Nous Research"

    def __init__(self, *, client_id: str, portal_url: str) -> None:
        if not client_id.startswith("agent:"):
            # Defense-in-depth. The plugin entry point already filters, but
            # the provider should never be constructible with a malformed id.
            raise ValueError(
                "client_id must match contract shape 'agent:{instance_id}', "
                f"got {client_id!r}"
            )
        self._client_id = client_id
        self._agent_instance_id = client_id[len("agent:") :]
        self._portal_url = portal_url.rstrip("/")
        self._jwks_url = f"{self._portal_url}/.well-known/jwks.json"
        self._authorize_url = f"{self._portal_url}/oauth/authorize"
        self._token_url = f"{self._portal_url}/api/oauth/token"
        # PyJWKClient is lazily imported so plugin discovery doesn't pay the
        # crypto-import cost when the provider isn't activated.
        self._jwks_client: Any = None

    # ---- public API (DashboardAuthProvider) -------------------------------

    def start_login(self, *, redirect_uri: str) -> LoginStart:
        self._validate_redirect_uri(redirect_uri)

        code_verifier = _b64url_no_pad(secrets.token_bytes(64))  # ~86 chars
        code_challenge = _b64url_no_pad(
            hashlib.sha256(code_verifier.encode("ascii")).digest()
        )
        state = _b64url_no_pad(secrets.token_bytes(32))

        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": _SCOPE,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        redirect_url = f"{self._authorize_url}?{urllib.parse.urlencode(params)}"
        # The auth-route layer expects ``cookie_payload[\"fabric_session_pkce\"]``
        # as a single semicolon-delimited string of ``key=value`` segments,
        # matching the stub provider's shape. The route handler prepends
        # ``provider=`` so the callback knows which plugin to dispatch to.
        cookie_payload = {
            "fabric_session_pkce": f"state={state};verifier={code_verifier}",
        }
        return LoginStart(redirect_url=redirect_url, cookie_payload=cookie_payload)

    def complete_login(
        self,
        *,
        code: str,
        state: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> Session:
        # ``state`` is verified by the auth-route layer before this call
        # (it checks the cookie-stashed state matches the query-param state);
        # we just receive it for symmetry with the protocol. Nous Portal
        # doesn't re-check state at the token endpoint, so we ignore it here.
        _ = state

        try:
            response = httpx.post(
                self._token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self._client_id,
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
                timeout=_TOKEN_ENDPOINT_TIMEOUT_SEC,
            )
        except httpx.RequestError as exc:
            raise ProviderError(f"Portal token endpoint unreachable: {exc}") from exc

        # The dashboard auth-code grant now issues a rotating refresh token
        # (24h session, reuse-detected) — Portal NAS PR #293. A 400 here means
        # the code/PKCE/redirect_uri failed, surfaced as InvalidCodeError.
        return self._token_response_to_session(
            response, bad_request_exc=InvalidCodeError
        )

    def refresh_session(self, *, refresh_token: str) -> Session:
        """Rotate the access token using the refresh token.

        Posts ``grant_type=refresh_token`` to Portal's token endpoint. The
        refresh token is sent in the ``X-Refresh-Token`` header (not the body)
        so it never lands in Portal's request-body access logs — mirroring the
        device-flow CLI convention; Portal reconciles header vs. body and
        rejects conflicts.

        Portal rotates the refresh token on every successful refresh, so the
        returned ``Session.refresh_token`` is a NEW value the caller MUST
        persist (replacing the old cookie). Failing to persist it means the
        next refresh replays a rotated token and — outside Portal's 60s grace
        — trips reuse-detection and revokes the whole session.

        Raises ``RefreshExpiredError`` on a 400 (expired / revoked / reuse-
        detected), so the middleware clears cookies and forces re-login.
        Raises ``ProviderError`` if Portal is unreachable.
        """
        if not refresh_token:
            # No RT to present — treat as a dead session so middleware
            # forces a clean re-login rather than emitting a malformed POST.
            raise RefreshExpiredError("no refresh token present in session")

        try:
            response = httpx.post(
                self._token_url,
                # The refresh token goes in BOTH the body and the
                # ``x-nous-refresh-token`` header. Portal's token endpoint
                # requires ``refresh_token`` in the body (its request schema
                # rejects a header-only request as ``invalid_request``), and
                # additionally reconciles the header against the body — sending
                # both lets Portal keep the value out of body-access-logs while
                # still satisfying the schema. The header name must match
                # Portal's ``REFRESH_TOKEN_HEADER`` exactly (``x-nous-refresh-
                # token``); any other name is silently ignored. (Verified
                # against the NAS #293 preview deploy: header-only → 400
                # invalid_request; body → accepted.)
                data={
                    "grant_type": "refresh_token",
                    "client_id": self._client_id,
                    "refresh_token": refresh_token,
                },
                headers={
                    "Accept": "application/json",
                    "x-nous-refresh-token": refresh_token,
                },
                timeout=_TOKEN_ENDPOINT_TIMEOUT_SEC,
            )
        except httpx.RequestError as exc:
            raise ProviderError(
                f"Portal token endpoint unreachable: {exc}"
            ) from exc

        # A 400 on refresh means the RT is expired / revoked / reuse-detected;
        # surface as RefreshExpiredError so middleware forces re-login.
        return self._token_response_to_session(
            response, bad_request_exc=RefreshExpiredError
        )

    def _token_response_to_session(
        self,
        response: httpx.Response,
        *,
        bad_request_exc: type[Exception],
    ) -> Session:
        """Translate a Portal ``/api/oauth/token`` response into a Session.

        Shared by ``complete_login`` (auth-code grant) and ``refresh_session``
        (refresh grant). ``bad_request_exc`` is the exception type raised on a
        400 — ``InvalidCodeError`` for the auth-code path, ``RefreshExpiredError``
        for the refresh path — so the middleware's distinct handling
        (400-on-callback vs. force-relogin) is preserved.
        """
        if response.status_code == 400:
            # Contract: invalid_code / invalid_grant / redirect_uri_mismatch
            # (auth-code) and expired / revoked / reuse-detected (refresh) all
            # surface as 400 with an OAuth-shaped JSON error envelope.
            body = self._parse_json_body(response)
            error_code = body.get("error", "invalid_request")
            raise bad_request_exc(f"Portal rejected token request: {error_code}")
        if response.status_code != 200:
            raise ProviderError(
                f"Portal token endpoint returned {response.status_code}: "
                f"{response.text[:200]!r}"
            )

        payload = self._parse_json_body(response)
        access_token = payload.get("access_token")
        if not access_token or not isinstance(access_token, str):
            raise ProviderError("Portal token response missing access_token")

        token_type = str(payload.get("token_type", "")).lower()
        if token_type and token_type != "bearer":
            raise ProviderError(f"unexpected token_type={token_type!r}")

        claims = self._verify_jwt(access_token)
        # The dashboard grant issues a rotating refresh token; capture it so
        # the caller can persist it. Empty string if Portal omitted it (the
        # session then behaves as access-token-only until expiry).
        refresh_token = payload.get("refresh_token") or ""
        if not isinstance(refresh_token, str):
            refresh_token = ""
        return self._session_from_claims(access_token, refresh_token, claims)


    def verify_session(self, *, access_token: str) -> Optional[Session]:
        # Contract: returns None on expiry/invalidity (the middleware then
        # tries refresh_session with the RT cookie, falling back to
        # redirect-to-login if that also fails); raises ProviderError if the
        # IDP is unreachable.
        try:
            claims = self._verify_jwt(access_token)
        except InvalidCodeError:
            # Expired/invalid token — middleware contract is None, not raise.
            return None
        except ProviderError:
            # JWKS unreachable, etc. Bubble up so middleware emits 503.
            raise
        # verify_session validates the AT in isolation and has no access to the
        # refresh token (it lives in a separate cookie the middleware reads);
        # pass "" here — the RT-driven rotation path is middleware's job.
        return self._session_from_claims(access_token, "", claims)

    def revoke_session(self, *, refresh_token: str) -> None:
        # Portal exposes no public refresh-token revocation grant on its token
        # endpoint (revocation is driven from the authenticated /sessions UI,
        # keyed by sessionId + userId, not by the RT value). So logout is
        # client-side cookie clearing; the server-side refresh session simply
        # expires within its 24h TTL. Best-effort no-op, must not raise.
        #
        # If Portal later adds a token-endpoint revoke grant (e.g.
        # grant_type=... + X-Refresh-Token), implement it here so logout
        # invalidates the RT server-side immediately rather than waiting out
        # the TTL.
        _ = refresh_token
        return None

    # ---- internals --------------------------------------------------------

    def _validate_redirect_uri(self, redirect_uri: str) -> None:
        """Surface obviously-broken redirect_uris before bouncing to Portal.

        The Portal-side check (``agent-redirect-uri.ts``) is authoritative;
        this is a fast-fail for the common operator-error case. We allow any
        ``http://`` host (not just localhost) so self-hosted dashboards reached
        over plain HTTP — LAN IPs, internal hostnames, reverse proxies that
        terminate TLS upstream — are not rejected here; Portal makes the final
        call on which redirect_uris are permitted.
        """
        parsed = urllib.parse.urlparse(redirect_uri)
        if parsed.scheme not in ("https", "http"):
            raise ProviderError(
                f"redirect_uri must be http(s), got {redirect_uri!r}"
            )
        if not parsed.path or not parsed.path.endswith("/auth/callback"):
            raise ProviderError(
                "redirect_uri path must end with '/auth/callback', "
                f"got {redirect_uri!r}"
            )

    def _parse_json_body(self, response: httpx.Response) -> Dict[str, Any]:
        ctype = response.headers.get("content-type", "")
        if not ctype.startswith("application/json"):
            return {}
        try:
            body = response.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    def _get_jwks_client(self) -> Any:
        if self._jwks_client is None:
            from jwt import PyJWKClient  # lazy import

            self._jwks_client = PyJWKClient(
                self._jwks_url,
                cache_keys=True,
                lifespan=_JWKS_CACHE_SECONDS,
            )
        return self._jwks_client

    def _verify_jwt(self, access_token: str) -> Dict[str, Any]:
        # Lazy import — keeps startup fast for operators who never trigger
        # the gated path.
        import jwt

        try:
            signing_key = self._get_jwks_client().get_signing_key_from_jwt(
                access_token
            )
        except jwt.PyJWKClientError as exc:
            raise ProviderError(f"JWKS lookup failed: {exc}") from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise ProviderError(f"JWKS lookup failed: {exc!r}") from exc

        try:
            claims = jwt.decode(
                access_token,
                signing_key.key,
                algorithms=["RS256"],
                # Contract C2: aud is the bare client_id.
                audience=self._client_id,
                # Contract: issuer is the Portal base URL.
                issuer=self._portal_url,
                options={"require": ["exp", "iat", "aud", "iss", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            # verify_session() catches this and returns None per protocol.
            raise InvalidCodeError(f"access token expired: {exc}") from exc
        except jwt.InvalidTokenError as exc:
            # Surface the actual claim values that failed verification so
            # operators don't have to dig into the JWT to debug drift between
            # dashboard.oauth.nous.portal_url / client_id and what Portal is
            # actually emitting. Decoding without verification
            # is safe here: we've already failed to verify, and we never trust
            # these values — they're surfaced for diagnostics only.
            details = ""
            try:
                unverified = jwt.decode(
                    access_token,
                    options={"verify_signature": False, "verify_exp": False},
                )
                details = (
                    f" [token iss={unverified.get('iss')!r} "
                    f"aud={unverified.get('aud')!r}; "
                    f"expected iss={self._portal_url!r} "
                    f"aud={self._client_id!r}]"
                )
            except Exception:
                pass
            raise ProviderError(
                f"access token verification failed: {exc}{details}"
            ) from exc

        self._check_agent_instance_id(claims)
        self._check_contract_version(claims)
        return claims

    def _check_agent_instance_id(self, claims: Dict[str, Any]) -> None:
        """Contract C9: cross-check agent_instance_id against our config."""
        token_instance_id = claims.get("agent_instance_id")
        if token_instance_id is None:
            # Tolerated — the claim is documented as "should" not "must".
            # Our audience check on the bare client_id already binds the
            # token to this instance; agent_instance_id is defense-in-depth.
            return
        if token_instance_id != self._agent_instance_id:
            raise ProviderError(
                f"agent_instance_id mismatch: token={token_instance_id!r} "
                f"vs configured={self._agent_instance_id!r}"
            )

    def _check_contract_version(self, claims: Dict[str, Any]) -> None:
        """Contract C11 — tolerant treatment per OQ-C2."""
        contract_version = claims.get("oauth_contract_version")
        if contract_version is None:
            logger.warning(
                "Nous Portal token missing oauth_contract_version claim "
                "(contract says it should be %d); proceeding anyway.",
                _EXPECTED_CONTRACT_VERSION,
            )
            return
        if contract_version != _EXPECTED_CONTRACT_VERSION:
            raise ProviderError(
                f"unsupported oauth_contract_version={contract_version!r}, "
                f"expected {_EXPECTED_CONTRACT_VERSION}"
            )

    def _session_from_claims(
        self,
        access_token: str,
        refresh_token: str,
        claims: Dict[str, Any],
    ) -> Session:
        # Contract C4: no email / display_name in tokens. AuthWidget will
        # show user_id (truncated). Session fields kept for forward-compat.
        user_id = str(claims.get("sub", ""))
        if not user_id:
            raise ProviderError("token missing 'sub' (user_id) claim")
        return Session(
            user_id=user_id,
            email="",
            display_name="",
            org_id=str(claims.get("org_id") or ""),
            provider=self.name,
            expires_at=int(claims["exp"]),
            access_token=access_token,
            refresh_token=refresh_token,
        )


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def _load_config_oauth_section() -> dict:
    """Return the ``dashboard.oauth`` block from ``config.yaml`` if it
    exists and is a dict; otherwise an empty dict.

    Robust to (a) load_config() raising (malformed YAML, IO error,
    config.yaml absent — common in fresh installs), (b) the
    ``dashboard`` key being absent or non-dict, and (c) the ``oauth``
    sub-key being present but not a dict (user typo). Each shape falls
    through to ``{}`` so register() can rely on `.get(...)` access.
    """
    try:
        from fabric_cli.config import cfg_get, load_config

        cfg = load_config()
    except Exception as exc:  # noqa: BLE001 — broad catch is intentional
        logger.debug(
            "dashboard-auth-nous: load_config() raised %s; "
            "treating the provider as unconfigured",
            exc,
        )
        return {}
    section = cfg_get(cfg, "dashboard", "oauth", default=None)
    return section if isinstance(section, dict) else {}


def _resolve_client_id() -> str:
    """Resolve ``dashboard.oauth.client_id`` from ``config.yaml``."""
    cfg_value = _load_config_oauth_section().get("client_id", "")
    return str(cfg_value).strip()


def _resolve_portal_url() -> str:
    """Resolve the configured Portal URL or the production default."""
    cfg_value = str(
        _load_config_oauth_section().get("portal_url", "")
    ).strip()
    return cfg_value or _DEFAULT_PORTAL_URL


def register(ctx) -> None:
    """Plugin entry — called by the plugin loader at startup.

    Registers ``NousDashboardAuthProvider`` only when a client_id is
    configured via ``dashboard.oauth.client_id`` in ``config.yaml``.

    When skipping, writes a short human-readable reason to the module-
    level :data:`LAST_SKIP_REASON` so the dashboard's fail-closed branch
    can surface the exact missing config key instead of the
    bare "no providers registered" the gate would otherwise emit. The
    reason names the canonical configuration surface.

    Loopback dashboards can leave this setting unset, so this plugin is a
    no-op for them. The gate-engagement layer
    (``fabric_cli.web_server.should_require_auth`` plus the fail-closed check
    in ``start_server``) handles a public bind with zero providers.
    """
    global LAST_SKIP_REASON
    LAST_SKIP_REASON = ""

    client_id = _resolve_client_id()
    portal_url = _resolve_portal_url()

    if not client_id:
        LAST_SKIP_REASON = (
            "dashboard.oauth.client_id is not set in config.yaml. The "
            "Nous Portal provisions a value shaped 'agent:{instance_id}'; "
            "store it under dashboard.oauth.client_id, or bind the dashboard "
            "to loopback."
        )
        logger.debug("dashboard-auth-nous: %s", LAST_SKIP_REASON)
        return

    if not client_id.startswith("agent:"):
        LAST_SKIP_REASON = (
            f"dashboard.oauth.client_id={client_id!r} doesn't match "
            f"the contract shape 'agent:{{instance_id}}'. The Nous Portal "
            f"provisions this value at deploy time; compare it with the "
            f"value from the Portal admin UI."
        )
        logger.warning("dashboard-auth-nous: %s", LAST_SKIP_REASON)
        return

    try:
        provider = NousDashboardAuthProvider(
            client_id=client_id, portal_url=portal_url
        )
    except ValueError as exc:
        LAST_SKIP_REASON = f"NousDashboardAuthProvider construction failed: {exc}"
        logger.warning("dashboard-auth-nous: %s", LAST_SKIP_REASON)
        return

    ctx.register_dashboard_auth_provider(provider)
    logger.info(
        "dashboard-auth-nous: registered provider (client_id=%s, portal=%s)",
        client_id,
        portal_url,
    )
