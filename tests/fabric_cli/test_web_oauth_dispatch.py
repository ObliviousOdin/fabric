"""Regression tests for the OAuth dispatcher in fabric_cli.web_server.

Bug history (2026-05-09): the `_OAUTH_PROVIDER_CATALOG` had two entries
flagged ``flow: "pkce"`` — anthropic and minimax-oauth — and the
dispatcher ``start_oauth_login`` hardcoded a PKCE-flow starter for any
pkce-flagged provider. So clicking "Login" next to MiniMax in the
dashboard's Keys tab silently launched the Anthropic/Claude OAuth flow.

The fix:
  1. Catalog entry for minimax-oauth changed from ``flow: "pkce"`` to
     ``flow: "device_code"`` (the actual UX is verification URI + user
     code + background poll, with PKCE as a security extension).
  2. New MiniMax branch added to ``_start_device_code_flow``.

Anthropic itself no longer has an OAuth/PKCE flow at all — Fabric
authenticates to native Anthropic with an API key only (see NOTICE) — so
``_OAUTH_PROVIDER_CATALOG`` has no ``flow: "pkce"`` entries left; these
tests now pin that no dispatcher branch resurrects one.
"""

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from fabric_cli.web_server import _SESSION_TOKEN, app

client = TestClient(app)
HEADERS = {"X-Fabric-Session-Token": _SESSION_TOKEN}


@pytest.fixture(autouse=True)
def _isolated_oauth_service_registry(tmp_path, monkeypatch):
    from fabric_cli import web_server as ws

    # Personal-provider starts now reserve durable profile-owned generations;
    # never let a focused web test touch the developer's real Fabric home.
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    ws._provider_oauth_service.reset_for_tests()
    yield
    ws._provider_oauth_service.reset_for_tests()


def _make_profile_home(tmp_path, monkeypatch, profile="coder"):
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    profile_home = tmp_path / "profiles" / profile
    profile_home.mkdir(parents=True)
    return profile_home


def _cancel_oauth_session(session_id):
    from fabric_cli import web_server as ws

    session = ws._oauth_sessions[session_id]
    provider_id = session["provider"]
    profile = session.get("profile")
    suffix = f"?profile={profile}" if profile else ""
    response = client.delete(
        f"/api/providers/oauth/{provider_id}/sessions/{session_id}{suffix}",
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "session_id": session_id}


def _fake_nous_device_data():
    return {
        "device_code": "device-code",
        "user_code": "NOUS-1234",
        "verification_uri": "https://portal.nousresearch.com/device",
        "verification_uri_complete": (
            "https://portal.nousresearch.com/device?user_code=NOUS-1234"
        ),
        "expires_in": 600,
        "interval": 5,
    }


def _oauth_start_request(body: bytes = b'{"expected_revision":0}') -> Request:
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/providers/oauth/xai-oauth/start",
            "raw_path": b"/api/providers/oauth/xai-oauth/start",
            "query_string": b"",
            "headers": [
                (b"x-fabric-session-token", _SESSION_TOKEN.encode("utf-8")),
                (b"content-type", b"application/json"),
            ],
            "app": app,
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        },
        receive,
    )


def _prepare_successful_personal_worker(provider_id, monkeypatch):
    """Return a fully local successful worker without starting a thread."""

    from fabric_cli import auth as auth_mod
    from fabric_cli import web_server as ws

    if provider_id == "xai-oauth":
        monkeypatch.setattr(
            auth_mod,
            "_xai_oauth_discovery",
            lambda *_args, **_kwargs: {
                "token_endpoint": "https://auth.x.ai/token",
            },
        )
        monkeypatch.setattr(
            auth_mod,
            "_xai_oauth_poll_device_token",
            lambda *_args, **_kwargs: {
                "access_token": "xai-worker-access",
                "refresh_token": "xai-worker-refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
        session_id, session = ws._new_oauth_session(
            provider_id,
            "device_code",
        )
        session.update({
            "device_code": "device-code",
            "interval": 1,
            "expires_at": time.time() + 600,
            "_provider_deadline_monotonic": time.monotonic() + 600,
        })
        return session_id, session, ws._xai_device_poller

    class _Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, **_kwargs):
            if url.endswith("/deviceauth/usercode"):
                return _Response(
                    200,
                    {
                        "device_auth_id": "device-auth-id",
                        "interval": 3,
                        "user_code": "CODEX-1234",
                    },
                )
            if url.endswith("/deviceauth/token"):
                return _Response(
                    200,
                    {
                        "authorization_code": "authorization-code",
                        "code_verifier": "code-verifier",
                    },
                )
            return _Response(
                200,
                {
                    "access_token": "codex-worker-access",
                    "refresh_token": "codex-worker-refresh",
                },
            )

    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setattr(ws.time, "sleep", lambda _seconds: None)
    session_id, session = ws._new_oauth_session(provider_id, "device_code")
    return session_id, session, ws._codex_full_login_worker


def _invoke_scope_refusal():
    request = httpx.Request("POST", "https://portal.nousresearch.com/oauth/device/code")
    response = httpx.Response(
        400,
        json={
            "error": "invalid_scope",
            "error_description": "unsupported scope inference:invoke",
        },
        request=request,
    )
    return httpx.HTTPStatusError("invalid scope", request=request, response=response)


def test_oauth_start_empty_body_and_object_replay_same_process_session():
    """Legacy empty starts and modern JSON starts share one provider ceremony."""

    from fabric_cli import web_server as ws

    with patch(
        "fabric_cli.auth.get_provider_auth_state",
        return_value={"client_id": "registered-nous-client"},
    ), patch(
        "fabric_cli.auth._request_device_code",
        return_value=_fake_nous_device_data(),
    ) as request_device_code, patch.object(ws, "_nous_poller", return_value=None):
        first = client.post(
            "/api/providers/oauth/nous/start",
            headers=HEADERS,
        )
        second = client.post(
            "/api/providers/oauth/nous/start",
            headers=HEADERS,
            json={},
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    assert request_device_code.call_count == 1
    assert first.json()["flow"] == "device_code"
    assert first.json()["user_code"] == "NOUS-1234"


@pytest.mark.parametrize(
    "body",
    (
        '{"unexpected":true}',
        '{"expected_revision":true}',
        '{"expected_revision":NaN}',
        '{"takeover":false,"takeover":true}',
    ),
)
def test_oauth_start_rejects_non_strict_bodies_without_value_echo(body):
    response = client.post(
        "/api/providers/oauth/nous/start",
        headers={**HEADERS, "Content-Type": "application/json"},
        content=body,
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {"code": "invalid_input", "retryable": False}
    }
    assert body not in response.text


def test_unknown_oauth_provider_is_not_reflected_into_logs(caplog):
    from fabric_cli import web_server as ws

    sentinel = "raw-provider-log-sentinel"
    caplog.set_level(logging.WARNING, logger=ws.__name__)

    response = client.post(
        f"/api/providers/oauth/{sentinel}/start",
        headers=HEADERS,
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {"code": "invalid_provider", "retryable": False}
    }
    assert sentinel not in caplog.text
    assert "provider=unrecognized code=invalid_provider" in caplog.text


def test_personal_start_rejects_revision_changed_by_concurrent_managed_intent(
    tmp_path,
    monkeypatch,
):
    from fabric_cli import provider_accounts as accounts
    from fabric_cli import web_server as ws

    requested = accounts.create_managed_request(
        home=tmp_path,
        provider_id="openai-codex",
        device_label="front desk",
        expected_revision=0,
    )
    worker_calls: list[str] = []
    monkeypatch.setattr(
        ws,
        "_codex_full_login_worker",
        lambda session_id: worker_calls.append(session_id),
    )

    response = client.post(
        "/api/providers/oauth/openai-codex/start",
        headers=HEADERS,
        json={"expected_revision": 0},
    )
    snapshot = accounts.get_account_snapshot(
        home=tmp_path,
        provider_id="openai-codex",
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "stale_revision", "retryable": True}
    }
    assert worker_calls == []
    assert snapshot.revision == requested.snapshot.revision
    assert snapshot.desired_ownership == "fabric_managed"
    assert snapshot.active_request_id == requested.request.request_id


def test_personal_start_account_lock_contention_does_not_stop_event_loop(
    tmp_path,
    monkeypatch,
):
    """Every durable start step runs outside FastAPI's event-loop thread."""

    from fabric_cli import provider_accounts as accounts
    from fabric_cli import web_server as ws

    held = threading.Event()
    release = threading.Event()

    def hold_account_lock():
        with accounts.provider_account_lock(tmp_path, timeout_seconds=1):
            held.set()
            assert release.wait(2)

    holder = threading.Thread(target=hold_account_lock, daemon=True)
    holder.start()
    assert held.wait(1)

    real_capture = accounts.capture_personal_oauth_start

    def bounded_capture(**kwargs):
        return real_capture(**kwargs, lock_timeout_seconds=0.75)

    def publish_codex_code(session_id):
        with ws._oauth_sessions_lock:
            session = ws._oauth_sessions[session_id]
            session["user_code"] = "CODEX-1234"
            session["verification_url"] = "https://auth.openai.com/codex/device"
            session["expires_in"] = 900
            session["interval"] = 5

    monkeypatch.setattr(accounts, "capture_personal_oauth_start", bounded_capture)
    monkeypatch.setattr(ws, "_codex_full_login_worker", publish_codex_code)

    async def scenario():
        ticks = 0
        stop = False

        async def heartbeat():
            nonlocal ticks
            while not stop:
                ticks += 1
                await asyncio.sleep(0)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as async_client:
            beat = asyncio.create_task(heartbeat())
            try:
                request = asyncio.create_task(
                    async_client.post(
                        "/api/providers/oauth/openai-codex/start",
                        headers=HEADERS,
                        json={"expected_revision": 0},
                    )
                )
                await asyncio.sleep(0.05)
                assert not request.done()
                assert ticks > 10
                release.set()
                response = await asyncio.wait_for(request, timeout=2)
            finally:
                stop = True
                await beat
            assert response.status_code == 200, response.text
            session_id = response.json()["session_id"]
            cancelled = await async_client.delete(
                f"/api/providers/oauth/openai-codex/sessions/{session_id}",
                headers=HEADERS,
            )
            assert cancelled.status_code == 200

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        holder.join(timeout=2)


def test_codex_readiness_never_blocks_event_loop_on_commit_lock_contention(
    tmp_path,
    monkeypatch,
):
    """Codex readiness reads stay off-loop while commit holds the service RLock."""

    from fabric_cli import provider_accounts as accounts
    from fabric_cli import web_server as ws

    commit_waiting = threading.Event()
    contention_enabled = threading.Event()
    release_account_lock = threading.Event()
    worker_done = threading.Event()
    real_snapshot = accounts.get_account_snapshot

    def mark_contended_snapshot(**kwargs):
        # _durable_is_current calls this only after commit_if_active owns the
        # service RLock. The account lock below then keeps it contended.
        if contention_enabled.is_set():
            commit_waiting.set()
        return real_snapshot(**kwargs)

    monkeypatch.setattr(
        accounts,
        "get_account_snapshot",
        mark_contended_snapshot,
    )

    def contended_codex_worker(session_id):
        session = ws._oauth_sessions[session_id]
        account_lock_held = threading.Event()

        def hold_account_lock():
            with accounts.provider_account_lock(tmp_path, timeout_seconds=2):
                account_lock_held.set()
                assert release_account_lock.wait(3)

        holder = threading.Thread(target=hold_account_lock, daemon=True)
        holder.start()
        assert account_lock_held.wait(1)
        contention_enabled.set()
        try:
            # commit_if_active holds the service RLock while it waits for the
            # provider-account lock, reproducing the audited contention shape.
            ws._provider_oauth_service.commit_if_active(
                session_id,
                session,
                lambda: None,
            )
        finally:
            holder.join(2)
            worker_done.set()

    monkeypatch.setattr(ws, "_codex_full_login_worker", contended_codex_worker)

    async def scenario():
        ticks = 0
        stop = False

        async def heartbeat():
            nonlocal ticks
            while not stop:
                ticks += 1
                await asyncio.sleep(0)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as async_client:
            beat = asyncio.create_task(heartbeat())
            request = asyncio.create_task(
                async_client.post(
                    "/api/providers/oauth/openai-codex/start",
                    headers=HEADERS,
                    json={"expected_revision": 0},
                )
            )
            try:
                assert await asyncio.to_thread(commit_waiting.wait, 1)
                before = ticks
                await asyncio.sleep(0.05)
                assert ticks > before + 10
                assert not request.done()
                release_account_lock.set()
                response = await asyncio.wait_for(request, 3)
                assert response.status_code == 503
            finally:
                release_account_lock.set()
                stop = True
                await beat

    asyncio.run(scenario())
    assert worker_done.wait(2)


def test_oauth_poll_and_cancel_hide_provider_profile_and_absence_mismatches(
    tmp_path,
    monkeypatch,
):
    from fabric_cli import web_server as ws

    _make_profile_home(tmp_path, monkeypatch)
    sid, _ = ws._new_oauth_session("nous", "device_code", profile="coder")
    expected = {"error": {"code": "not_found", "retryable": False}}

    responses = (
        client.get(
            f"/api/providers/oauth/xai-oauth/poll/{sid}?profile=coder",
            headers=HEADERS,
        ),
        client.get(
            f"/api/providers/oauth/nous/poll/{sid}",
            headers=HEADERS,
        ),
        client.get(
            "/api/providers/oauth/nous/poll/missing?profile=coder",
            headers=HEADERS,
        ),
        client.delete(
            f"/api/providers/oauth/xai-oauth/sessions/{sid}?profile=coder",
            headers=HEADERS,
        ),
        client.delete(
            f"/api/providers/oauth/nous/sessions/{sid}",
            headers=HEADERS,
        ),
        client.delete(
            "/api/providers/oauth/nous/sessions/missing?profile=coder",
            headers=HEADERS,
        ),
    )

    assert {(response.status_code, str(response.json())) for response in responses} == {
        (404, str(expected))
    }


def test_legacy_oauth_cancel_has_fixed_deprecation_headers_on_success_and_error():
    from fabric_cli import web_server as ws

    sid, _ = ws._new_oauth_session("nous", "device_code")
    success = client.delete(
        f"/api/providers/oauth/sessions/{sid}",
        headers=HEADERS,
    )
    missing = client.delete(
        "/api/providers/oauth/sessions/missing",
        headers=HEADERS,
    )

    for response in (success, missing):
        assert response.headers["Deprecation"] == "true"
        assert response.headers["Sunset"] == "Sat, 31 Oct 2026 23:59:59 GMT"
    assert success.status_code == 200
    assert success.json() == {"ok": True, "session_id": sid}
    assert missing.status_code == 404
    assert missing.json() == {
        "error": {"code": "not_found", "retryable": False}
    }


def test_qualified_cancel_returns_stable_failure_until_lease_release_is_confirmed(
    monkeypatch,
):
    from fabric_cli import provider_accounts as accounts
    from fabric_cli import web_server as ws

    sid, session = ws._new_oauth_session("openai-codex", "device_code")
    real_release = accounts.release_oauth_lease
    monkeypatch.setattr(
        accounts,
        "release_oauth_lease",
        lambda **_kwargs: (_ for _ in ()).throw(
            accounts.ProviderAccountError(
                accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
            )
        ),
    )

    failed = client.delete(
        f"/api/providers/oauth/openai-codex/sessions/{sid}",
        headers=HEADERS,
    )

    assert failed.status_code == 503
    assert failed.json() == {
        "error": {"code": "io_unavailable", "retryable": True}
    }
    assert session["status"] == "cancelled"
    assert session["_release_pending"] is True

    monkeypatch.setattr(accounts, "release_oauth_lease", real_release)
    retried = client.delete(
        f"/api/providers/oauth/openai-codex/sessions/{sid}",
        headers=HEADERS,
    )
    assert retried.status_code == 200
    assert retried.json() == {"ok": True, "session_id": sid}


def test_web_lifespan_shutdown_cancels_worker_and_releases_personal_lease(
    tmp_path,
):
    from fabric_cli import provider_accounts as accounts
    from fabric_cli import web_server as ws

    with TestClient(app):
        sid, session = ws._new_oauth_session("openai-codex", "device_code")
        assert (
            accounts.get_account_snapshot(
                home=tmp_path,
                provider_id="openai-codex",
            ).oauth_lease
            is not None
        )

    assert session["_cancel_event"].is_set()
    assert sid not in ws._oauth_sessions
    assert (
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id="openai-codex",
        ).oauth_lease
        is None
    )


def test_web_lifespan_retries_shutdown_off_loop_and_surfaces_stable_count(
    monkeypatch,
):
    from fabric_cli import web_server as ws

    results = iter(
        (
            {"cancelled": 1, "release_attempts": 1, "release_failures": 1},
            {"cancelled": 0, "release_attempts": 1, "release_failures": 1},
            {"cancelled": 0, "release_attempts": 1, "release_failures": 0},
        )
    )
    calls: list[int] = []

    def shutdown():
        calls.append(threading.get_ident())
        return next(results)

    monkeypatch.setattr(ws._provider_oauth_service, "shutdown", shutdown)
    event_loop_thread = threading.get_ident()
    with TestClient(app):
        pass

    assert len(calls) == 3
    assert all(thread_id != event_loop_thread for thread_id in calls)
    assert app.state.oauth_shutdown_summary == {
        "attempts": 3,
        "cancelled": 1,
        "release_attempts": 3,
        "release_failures": 0,
    }
    assert app.state.oauth_shutdown_release_failures == 0


def test_minimax_login_does_not_launch_anthropic_flow():
    """Click 'Login' on MiniMax → MUST NOT return claude.ai auth_url."""
    fake_user_code_resp = {
        "user_code": "ABCD-1234",
        "verification_uri": "https://api.minimax.io/oauth/verify",
        # `expired_in` < 1e12 so the heuristic treats it as seconds.
        "expired_in": 600,
        "interval": 2000,
        "state": "stub-state",
    }
    with patch(
        "fabric_cli.auth._minimax_request_user_code",
        return_value=fake_user_code_resp,
    ), patch(
        "fabric_cli.auth._minimax_pkce_pair",
        return_value=("verifier-stub", "challenge-stub", "stub-state"),
    ), patch(
        "fabric_cli.web_server._minimax_poller",
        return_value=None,
    ):
        resp = client.post(
            "/api/providers/oauth/minimax-oauth/start",
            headers=HEADERS,
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The bug used to return Anthropic's auth_url — make sure the response
    # references neither the auth_url field nor anything Claude-related.
    assert "auth_url" not in body
    assert "claude.ai" not in str(body).lower()

    # And the response IS the device-code shape pointing at MiniMax.
    assert body["flow"] == "device_code"
    assert "minimax" in body["verification_url"].lower()
    assert body["user_code"] == "ABCD-1234"
    assert body["expires_in"] == 600


def test_nous_dashboard_device_flow_uses_default_scope(monkeypatch):
    from fabric_cli import auth as auth_mod
    from fabric_cli import web_server as ws

    requests = []

    def fake_request_device_code(**kwargs):
        requests.append((kwargs["scope"], kwargs["client_id"]))
        return _fake_nous_device_data()

    monkeypatch.setattr(auth_mod, "_request_device_code", fake_request_device_code)
    monkeypatch.setattr(
        auth_mod,
        "get_provider_auth_state",
        lambda _provider: {"client_id": "registered-nous-client"},
    )
    monkeypatch.setattr(ws, "_nous_poller", lambda sid: None)

    result = asyncio.run(ws._start_device_code_flow("nous"))
    try:
        assert requests == [
            (auth_mod.DEFAULT_NOUS_SCOPE, "registered-nous-client")
        ]
        assert result["flow"] == "device_code"
        assert result["user_code"] == "NOUS-1234"
        assert (
            ws._oauth_sessions[result["session_id"]]["scope"]
            == auth_mod.DEFAULT_NOUS_SCOPE
        )
    finally:
        ws._oauth_sessions.pop(result["session_id"], None)


def test_oauth_provider_status_uses_profile_query(tmp_path, monkeypatch):
    from fabric_cli import web_server as ws
    from fabric_constants import get_fabric_home

    profile_home = _make_profile_home(tmp_path, monkeypatch)
    observed_homes = []

    def fake_status():
        observed_homes.append(get_fabric_home())
        return {"logged_in": False, "source": None}

    fake_catalog = ({
        "id": "fake-oauth",
        "name": "Fake OAuth",
        "flow": "pkce",
        "cli_command": "fabric auth add fake-oauth",
        "docs_url": "https://example.com",
        "status_fn": fake_status,
    },)
    monkeypatch.setattr(ws, "_OAUTH_PROVIDER_CATALOG", fake_catalog)

    resp = client.get("/api/providers/oauth?profile=coder", headers=HEADERS)

    assert resp.status_code == 200, resp.text
    assert observed_homes == [profile_home]


def test_oauth_start_stores_profile_for_background_completion(tmp_path, monkeypatch):
    from fabric_cli import web_server as ws

    _make_profile_home(tmp_path, monkeypatch)
    fake_user_code_resp = {
        "user_code": "ABCD-1234",
        "verification_uri": "https://api.minimax.io/oauth/verify",
        "expired_in": 600,
        "interval": 2000,
        "state": "stub-state",
    }
    with patch(
        "fabric_cli.auth._minimax_request_user_code",
        return_value=fake_user_code_resp,
    ), patch(
        "fabric_cli.auth._minimax_pkce_pair",
        return_value=("verifier-stub", "challenge-stub", "stub-state"),
    ), patch(
        "fabric_cli.web_server._minimax_poller",
        return_value=None,
    ):
        resp = client.post(
            "/api/providers/oauth/minimax-oauth/start?profile=coder",
            headers=HEADERS,
        )

    assert resp.status_code == 200, resp.text
    session_id = resp.json()["session_id"]
    try:
        assert ws._oauth_sessions[session_id]["profile"] == "coder"
    finally:
        ws._oauth_sessions.pop(session_id, None)


def test_nous_dashboard_device_flow_does_not_retry_scope_on_invoke_refusal(monkeypatch):
    from fabric_cli import auth as auth_mod
    from fabric_cli import web_server as ws

    requested_scopes = []

    def fake_request_device_code(**kwargs):
        requested_scopes.append(kwargs["scope"])
        raise _invoke_scope_refusal()

    monkeypatch.setattr(auth_mod, "_request_device_code", fake_request_device_code)
    monkeypatch.setattr(
        auth_mod,
        "get_provider_auth_state",
        lambda _provider: {"client_id": "registered-nous-client"},
    )
    monkeypatch.setattr(ws, "_nous_poller", lambda sid: None)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(ws._start_device_code_flow("nous"))
    assert requested_scopes == [auth_mod.DEFAULT_NOUS_SCOPE]


def test_nous_dashboard_start_requires_stored_client_id(monkeypatch):
    from fabric_cli import auth as auth_mod

    request_attempted = False

    def _unexpected_request(**_kwargs):
        nonlocal request_attempted
        request_attempted = True
        raise AssertionError("provider request must not run without a client ID")

    monkeypatch.setattr(auth_mod, "_request_device_code", _unexpected_request)

    response = client.post(
        "/api/providers/oauth/nous/start",
        headers=HEADERS,
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "nous_client_id_required", "retryable": False}
    }
    assert request_attempted is False


def test_codex_dashboard_worker_persists_runtime_provider(tmp_path, monkeypatch):
    from fabric_cli import web_server as ws
    from fabric_cli.auth import get_active_provider
    from fabric_cli.runtime_provider import resolve_runtime_provider

    access_token = "h.eyJleHAiOjk5OTk5OTk5OTl9.s"

    class _Resp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            if url.endswith("/deviceauth/usercode"):
                return _Resp(200, {
                    "device_auth_id": "device-auth-id",
                    "interval": 3,
                    "user_code": "CODEX-1234",
                })
            if url.endswith("/deviceauth/token"):
                return _Resp(200, {
                    "authorization_code": "authorization-code",
                    "code_verifier": "code-verifier",
                })
            return _Resp(200, {
                "access_token": access_token,
                "refresh_token": "codex-refresh",
            })

    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setattr(ws.time, "sleep", lambda _: None)

    sid, _ = ws._new_oauth_session("openai-codex", "device_code")
    try:
        ws._codex_full_login_worker(sid)

        assert ws._oauth_sessions[sid]["status"] == "approved"
        assert get_active_provider() == "openai-codex"

        runtime = resolve_runtime_provider(requested=None)
        assert runtime["provider"] == "openai-codex"
        assert runtime["api_key"] == access_token
        assert runtime["api_mode"] == "codex_responses"
    finally:
        ws._oauth_sessions.pop(sid, None)


@pytest.mark.parametrize("provider_id", ["openai-codex", "xai-oauth"])
@pytest.mark.parametrize(
    ("signal_type", "exit_code"),
    [(KeyboardInterrupt, None), (SystemExit, 130)],
)
def test_personal_worker_signal_stabilizes_session_and_releases_exact_lease(
    tmp_path,
    monkeypatch,
    provider_id,
    signal_type,
    exit_code,
):
    from fabric_cli import provider_account_oauth
    from fabric_cli import provider_accounts as accounts

    session_id, session, worker = _prepare_successful_personal_worker(
        provider_id,
        monkeypatch,
    )

    def interrupt_reengagement(_provider_id):
        if signal_type is KeyboardInterrupt:
            raise KeyboardInterrupt
        raise SystemExit(exit_code)

    monkeypatch.setattr(
        provider_account_oauth,
        "clear_provider_suppressions",
        interrupt_reengagement,
    )

    with pytest.raises(signal_type) as interrupted:
        worker(session_id)

    if signal_type is SystemExit:
        assert interrupted.value.code == exit_code
    assert session["status"] == "error"
    assert session["error_code"] == "io_unavailable"
    assert session["_cancel_event"].is_set()
    assert session["_release_pending"] is False
    snapshot = accounts.get_account_snapshot(home=tmp_path, provider_id=provider_id)
    assert snapshot.oauth_lease is None
    assert snapshot.oauth_completion is None


@pytest.mark.parametrize("provider_id", ["openai-codex", "xai-oauth"])
@pytest.mark.parametrize(
    "signal",
    [KeyboardInterrupt("pre-commit interrupt"), SystemExit(73)],
)
def test_personal_worker_process_control_before_session_capture_is_stabilized(
    tmp_path,
    monkeypatch,
    provider_id,
    signal,
):
    from fabric_cli import provider_accounts as accounts
    from fabric_cli import web_server as ws

    session_id, session, worker = _prepare_successful_personal_worker(
        provider_id,
        monkeypatch,
    )
    real_worker_session = ws._oauth_worker_session

    def interrupt_before_return(candidate_session_id):
        assert real_worker_session(candidate_session_id) is not None
        raise signal

    monkeypatch.setattr(ws, "_oauth_worker_session", interrupt_before_return)

    with pytest.raises(type(signal)) as interrupted:
        worker(session_id)

    assert interrupted.value is signal
    assert session["status"] == "error"
    assert session["error_code"] == "io_unavailable"
    assert session["_cancel_event"].is_set()
    assert session["_release_pending"] is False
    snapshot = accounts.get_account_snapshot(home=tmp_path, provider_id=provider_id)
    assert snapshot.oauth_lease is None
    assert snapshot.oauth_completion is None


def test_personal_worker_preserves_original_signal_when_release_is_interrupted(
    tmp_path,
    monkeypatch,
):
    from fabric_cli import provider_accounts as accounts
    from fabric_cli import web_server as ws

    session_id, session, worker = _prepare_successful_personal_worker(
        "xai-oauth",
        monkeypatch,
    )
    original_signal = KeyboardInterrupt("original worker interrupt")
    real_worker_session = ws._oauth_worker_session

    def interrupt_worker(candidate_session_id):
        assert real_worker_session(candidate_session_id) is not None
        raise original_signal

    monkeypatch.setattr(ws, "_oauth_worker_session", interrupt_worker)
    monkeypatch.setattr(
        ws._provider_oauth_service,
        "_release_and_record",
        lambda _session: (_ for _ in ()).throw(SystemExit(92)),
    )

    with pytest.raises(KeyboardInterrupt) as interrupted:
        worker(session_id)

    assert interrupted.value is original_signal
    assert session["status"] == "error"
    assert session["error_code"] == "io_unavailable"
    assert session["_release_pending"] is True
    assert session["_release_error_code"] == "io_unavailable"
    assert (
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id="xai-oauth",
        ).oauth_lease
        is not None
    )


@pytest.mark.parametrize("provider_id", ["openai-codex", "xai-oauth"])
def test_cancelled_start_request_releases_created_personal_reservation(
    tmp_path,
    monkeypatch,
    provider_id,
):
    from fabric_cli import provider_accounts as accounts
    from fabric_cli import web_server as ws

    entered = None
    blocker = None

    async def scenario():
        nonlocal entered, blocker
        entered = asyncio.Event()
        blocker = asyncio.Event()

        async def block_after_reservation(
            _provider_id,
            profile=None,
            reservation=None,
        ):
            assert reservation is not None and reservation.created
            entered.set()
            await blocker.wait()
            raise AssertionError("cancelled start must not resume provider work")

        monkeypatch.setattr(ws, "_start_device_code_flow", block_after_reservation)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as async_client:
            request = asyncio.create_task(
                async_client.post(
                    f"/api/providers/oauth/{provider_id}/start",
                    headers=HEADERS,
                    json={"expected_revision": 0},
                )
            )
            await asyncio.wait_for(entered.wait(), timeout=2)
            session = next(iter(ws._oauth_sessions.values()))
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            return session

    session = asyncio.run(scenario())
    assert session["status"] == "error"
    assert session["error_code"] == "io_unavailable"
    assert session["_release_pending"] is False
    assert (
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id=provider_id,
        ).oauth_lease
        is None
    )


def test_cancelled_start_during_error_cleanup_cannot_strand_personal_lease(
    tmp_path,
    monkeypatch,
):
    from fabric_cli import provider_accounts as accounts
    from fabric_cli import web_server as ws

    cleanup_entered = threading.Event()
    allow_cleanup = threading.Event()
    real_fail = ws._provider_oauth_service.fail

    async def provider_failure(*_args, **_kwargs):
        raise ws.OAuthFlowError(ws.OAuthFlowErrorCode.IO_UNAVAILABLE)

    def delayed_fail(*args, **kwargs):
        cleanup_entered.set()
        assert allow_cleanup.wait(2)
        return real_fail(*args, **kwargs)

    monkeypatch.setattr(ws, "_start_device_code_flow", provider_failure)
    monkeypatch.setattr(ws._provider_oauth_service, "fail", delayed_fail)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as async_client:
            request = asyncio.create_task(
                async_client.post(
                    "/api/providers/oauth/xai-oauth/start",
                    headers=HEADERS,
                    json={"expected_revision": 0},
                )
            )
            assert await asyncio.to_thread(cleanup_entered.wait, 2)
            session = next(iter(ws._oauth_sessions.values()))
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            return session

    try:
        session = asyncio.run(scenario())
    finally:
        allow_cleanup.set()
    assert session["status"] == "error"
    assert session["_release_pending"] is False
    assert (
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id="xai-oauth",
        ).oauth_lease
        is None
    )


def test_xai_post_reservation_device_request_process_control_is_released(
    tmp_path,
    monkeypatch,
):
    from fabric_cli import provider_accounts as accounts
    from fabric_cli import web_server as ws

    original = SystemExit(64)

    async def interrupt_device_request(provider_id, *, profile, reservation):
        assert provider_id == "xai-oauth"
        assert profile is None
        assert reservation is not None and reservation.created
        raise original

    monkeypatch.setattr(ws, "_start_device_code_flow", interrupt_device_request)

    async def scenario():
        try:
            await ws.start_oauth_login(
                "xai-oauth",
                _oauth_start_request(),
            )
        except SystemExit as interrupted:
            return interrupted
        raise AssertionError("process-control signal was swallowed")

    interrupted = asyncio.run(scenario())
    assert interrupted is original
    session = next(iter(ws._oauth_sessions.values()))
    assert session["status"] == "error"
    assert session["_release_pending"] is False
    assert (
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id="xai-oauth",
        ).oauth_lease
        is None
    )


def test_post_reservation_custom_base_exception_is_stabilized_and_reraised(
    tmp_path,
    monkeypatch,
):
    from fabric_cli import provider_accounts as accounts
    from fabric_cli import web_server as ws

    original = BaseException("non-local start exit")

    async def interrupt_start(_provider_id, *, profile, reservation):
        assert profile is None
        assert reservation is not None and reservation.created
        raise original

    monkeypatch.setattr(ws, "_start_device_code_flow", interrupt_start)

    async def scenario():
        try:
            await ws.start_oauth_login(
                "xai-oauth",
                _oauth_start_request(),
            )
        except BaseException as interrupted:
            return interrupted
        raise AssertionError("custom BaseException was swallowed")

    interrupted = asyncio.run(scenario())
    assert interrupted is original
    session = next(iter(ws._oauth_sessions.values()))
    assert session["status"] == "error"
    assert session["_release_pending"] is False
    assert (
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id="xai-oauth",
        ).oauth_lease
        is None
    )


@pytest.mark.parametrize("provider_id", ["openai-codex", "xai-oauth"])
def test_personal_start_thread_failure_terminalizes_exact_reservation(
    tmp_path,
    monkeypatch,
    provider_id,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_accounts as accounts
    from fabric_cli import web_server as ws

    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_request_device_code",
        lambda _client: {
            "device_code": "device-code",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://accounts.x.ai/oauth2/device",
            "verification_uri_complete": (
                "https://accounts.x.ai/oauth2/device?user_code=ABCD-EFGH"
            ),
            "expires_in": 600,
            "interval": 5,
        },
    )
    monkeypatch.setattr(
        ws,
        "_start_oauth_worker_thread",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("thread sentinel")),
    )

    response = client.post(
        f"/api/providers/oauth/{provider_id}/start",
        headers=HEADERS,
        json={"expected_revision": 0},
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "io_unavailable", "retryable": True}
    }
    session = next(iter(ws._oauth_sessions.values()))
    assert session["status"] == "error"
    assert session["_release_pending"] is False
    assert (
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id=provider_id,
        ).oauth_lease
        is None
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX profile rename ABA fixture")
def test_start_process_control_retains_release_until_profile_is_restored(
    tmp_path,
    monkeypatch,
):
    from fabric_cli import provider_accounts as accounts
    from fabric_cli import web_server as ws

    home = _make_profile_home(tmp_path, monkeypatch)
    displaced = tmp_path / "profile-original"
    successor = tmp_path / "profile-successor"
    original = KeyboardInterrupt("post-reservation interrupt")
    captured = {}

    async def replace_then_interrupt(_provider_id, *, profile, reservation):
        assert profile == "coder"
        assert reservation is not None and reservation.created
        home.rename(displaced)
        home.mkdir()
        successor_state = home / accounts.STATE_FILENAME
        successor_state.write_bytes(
            (displaced / accounts.STATE_FILENAME).read_bytes()
        )
        successor_state.chmod(0o600)
        captured["before"] = successor_state.read_bytes()
        raise original

    monkeypatch.setattr(ws, "_start_device_code_flow", replace_then_interrupt)

    async def scenario():
        try:
            await ws.start_oauth_login(
                "xai-oauth",
                _oauth_start_request(),
                profile="coder",
            )
        except KeyboardInterrupt as interrupted:
            return interrupted
        raise AssertionError("process-control signal was swallowed")

    interrupted = asyncio.run(scenario())
    assert interrupted is original
    session = next(iter(ws._oauth_sessions.values()))
    assert session["status"] == "error"
    assert session["_release_pending"] is True
    assert (home / accounts.STATE_FILENAME).read_bytes() == captured["before"]
    assert not (home / accounts.LOCK_FILENAME).exists()

    home.rename(successor)
    displaced.rename(home)
    summary = ws._provider_oauth_service.shutdown()
    assert summary["release_failures"] == 0
    assert (
        accounts.get_account_snapshot(
            home=home,
            provider_id="xai-oauth",
        ).oauth_lease
        is None
    )
    assert (successor / accounts.STATE_FILENAME).read_bytes() == captured["before"]


@pytest.mark.parametrize("provider_id", ["openai-codex", "xai-oauth"])
def test_personal_worker_suppression_failure_cannot_publish_approval(
    tmp_path,
    monkeypatch,
    provider_id,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_account_oauth
    from fabric_cli import provider_accounts as accounts

    auth_mod.suppress_credential_source(provider_id, "device_code")
    auth_mod.suppress_credential_source(provider_id, "environment")
    session_id, session, worker = _prepare_successful_personal_worker(
        provider_id,
        monkeypatch,
    )
    clear_calls: list[str] = []

    def fail_clear(current_provider_id):
        clear_calls.append(current_provider_id)
        raise RuntimeError("suppression publication failed")

    monkeypatch.setattr(
        provider_account_oauth,
        "clear_provider_suppressions",
        fail_clear,
    )

    worker(session_id)

    assert session["status"] == "error"
    assert session["error_code"] == "io_unavailable"
    assert session["_release_pending"] is False
    snapshot = accounts.get_account_snapshot(home=tmp_path, provider_id=provider_id)
    assert snapshot.oauth_lease is None
    assert snapshot.oauth_completion is None
    assert clear_calls == [provider_id]
    auth_store = auth_mod._load_auth_store()
    assert set(auth_store["suppressed_sources"][provider_id]) == {
        "device_code",
        "environment",
    }


@pytest.mark.parametrize("provider_id", ["openai-codex", "xai-oauth"])
def test_personal_worker_reengages_suppressions_once_across_commit_retry(
    tmp_path,
    monkeypatch,
    provider_id,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_account_oauth
    from fabric_cli import provider_accounts as accounts

    auth_mod.suppress_credential_source(provider_id, "device_code")
    auth_mod.suppress_credential_source(provider_id, "environment")
    session_id, session, worker = _prepare_successful_personal_worker(
        provider_id,
        monkeypatch,
    )
    real_clear = provider_account_oauth.clear_provider_suppressions
    clear_calls: list[str] = []

    def clear_spy(current_provider_id):
        clear_calls.append(current_provider_id)
        return real_clear(current_provider_id)

    monkeypatch.setattr(
        provider_account_oauth,
        "clear_provider_suppressions",
        clear_spy,
    )
    real_write_state = accounts._write_state
    state_writes = 0

    def fail_first_completion_publication(canonical_home, state):
        nonlocal state_writes
        state_writes += 1
        if state_writes == 1:
            raise accounts.ProviderAccountError(
                accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
            )
        return real_write_state(canonical_home, state)

    monkeypatch.setattr(accounts, "_write_state", fail_first_completion_publication)

    worker(session_id)

    assert session["status"] == "approved"
    assert clear_calls == [provider_id]
    assert state_writes == 2
    snapshot = accounts.get_account_snapshot(home=tmp_path, provider_id=provider_id)
    assert snapshot.oauth_lease is None
    assert snapshot.oauth_completion is not None
    assert provider_id not in auth_mod._load_auth_store().get(
        "suppressed_sources",
        {},
    )


def test_codex_dashboard_worker_persists_inside_session_profile(tmp_path, monkeypatch):
    from fabric_cli import web_server as ws

    profile_home = _make_profile_home(tmp_path, monkeypatch)

    class _Resp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            if url.endswith("/deviceauth/usercode"):
                return _Resp(200, {
                    "device_auth_id": "device-auth-id",
                    "interval": 3,
                    "user_code": "CODEX-1234",
                })
            if url.endswith("/deviceauth/token"):
                return _Resp(200, {
                    "authorization_code": "authorization-code",
                    "code_verifier": "code-verifier",
                })
            return _Resp(200, {
                "access_token": "codex-access",
                "refresh_token": "codex-refresh",
            })

    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setattr(ws.time, "sleep", lambda _: None)

    sid, _ = ws._new_oauth_session(
        "openai-codex",
        "device_code",
        profile="coder",
    )
    try:
        ws._codex_full_login_worker(sid)

        assert ws._oauth_sessions[sid]["status"] == "approved"
        auth_store = json.loads(
            (profile_home / "auth.json").read_text(encoding="utf-8")
        )
        assert "openai-codex" not in auth_store.get("providers", {})
        entries = auth_store["credential_pool"]["openai-codex"]
        assert len(entries) == 1
        assert entries[0]["access_token"] == "codex-access"
        assert entries[0]["refresh_token"] == "codex-refresh"
        assert not (tmp_path / "auth.json").exists()
    finally:
        ws._oauth_sessions.pop(sid, None)


def test_oauth_cancel_signals_retained_session_and_keeps_response_contract():
    from fabric_cli import web_server as ws

    sid, sess = ws._new_oauth_session("openai-codex", "device_code")
    cancel_event = sess["_cancel_event"]

    _cancel_oauth_session(sid)

    assert sid in ws._oauth_sessions
    assert sess["status"] == "cancelled"
    assert cancel_event.is_set()


def test_oauth_gc_signals_retained_session_before_removal():
    from fabric_cli import web_server as ws

    sid, sess = ws._new_oauth_session("nous", "device_code")
    cancel_event = sess["_cancel_event"]
    sess["_registry_expires_at"] = time.time() - 1

    ws._gc_oauth_sessions()

    assert sid in ws._oauth_sessions
    assert sess["status"] == "expired"
    assert cancel_event.is_set()

    sess["_terminal_at"] = (
        time.time()
        - ws._provider_oauth_service.terminal_retention_seconds
        - 1
    )
    ws._gc_oauth_sessions()
    assert sid not in ws._oauth_sessions


def test_oauth_cancel_wins_race_before_credential_commit():
    from fabric_cli import web_server as ws

    sid, sess = ws._new_oauth_session("nous", "device_code")
    worker_ready = threading.Barrier(2)
    allow_commit = threading.Event()
    writes = []
    commit_results = []

    def worker():
        worker_ready.wait()
        allow_commit.wait(timeout=5)
        commit_results.append(
            ws._oauth_commit_if_active(
                sid,
                sess,
                lambda: writes.append("persisted"),
            )
        )

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        worker_ready.wait(timeout=5)
        response = client.delete(
            f"/api/providers/oauth/nous/sessions/{sid}",
            headers=HEADERS,
        )
        allow_commit.set()
        thread.join(timeout=5)
    finally:
        allow_commit.set()
        thread.join(timeout=5)
        ws._oauth_sessions.pop(sid, None)

    assert not thread.is_alive()
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "session_id": sid}
    assert commit_results == [False]
    assert writes == []
    assert sess["status"] == "cancelled"


def test_oauth_credential_commit_wins_race_before_cancel():
    from fabric_cli import web_server as ws

    sid, sess = ws._new_oauth_session("nous", "device_code")
    commit_started = threading.Event()
    allow_commit = threading.Event()
    cancel_ready = threading.Barrier(2)
    writes = []
    commit_results = []
    cancel_responses = []

    def persist():
        commit_started.set()
        allow_commit.wait(timeout=5)
        writes.append("persisted")

    def worker():
        commit_results.append(ws._oauth_commit_if_active(sid, sess, persist))

    def cancel():
        cancel_ready.wait()
        cancel_responses.append(
            client.delete(
                f"/api/providers/oauth/nous/sessions/{sid}",
                headers=HEADERS,
            )
        )

    worker_thread = threading.Thread(target=worker)
    cancel_thread = threading.Thread(target=cancel)
    worker_thread.start()
    try:
        assert commit_started.wait(timeout=5)
        cancel_thread.start()
        cancel_ready.wait(timeout=5)
        allow_commit.set()
        worker_thread.join(timeout=5)
        cancel_thread.join(timeout=5)
    finally:
        allow_commit.set()
        worker_thread.join(timeout=5)
        if cancel_thread.ident is not None:
            cancel_thread.join(timeout=5)

    try:
        assert not worker_thread.is_alive()
        assert not cancel_thread.is_alive()
        assert commit_results == [True]
        assert writes == ["persisted"]
        assert sess["status"] == "approved"
        assert sid in ws._oauth_sessions
        assert len(cancel_responses) == 1
        response = cancel_responses[0]
        assert response.status_code == 200, response.text
        assert response.json() == {
            "ok": False,
            "session_id": sid,
            "status": "approved",
        }
    finally:
        ws._oauth_sessions.pop(sid, None)


def test_codex_worker_cancellation_prevents_profile_or_root_persistence(
    tmp_path,
    monkeypatch,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import web_server as ws

    _make_profile_home(tmp_path, monkeypatch)

    class _Resp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            if url.endswith("/deviceauth/usercode"):
                return _Resp(200, {
                    "device_auth_id": "device-auth-id",
                    "interval": 3,
                    "user_code": "CODEX-1234",
                })
            if url.endswith("/deviceauth/token"):
                _cancel_oauth_session(sid)
                return _Resp(200, {
                    "authorization_code": "authorization-code",
                    "code_verifier": "code-verifier",
                })
            return _Resp(200, {
                "access_token": "codex-access",
                "refresh_token": "codex-refresh",
            })

    persisted = []
    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setattr(ws.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        auth_mod,
        "_save_codex_tokens",
        lambda tokens: persisted.append(tokens),
    )

    sid, sess = ws._new_oauth_session(
        "openai-codex",
        "device_code",
        profile="coder",
    )
    ws._codex_full_login_worker(sid)

    assert persisted == []
    assert sess["status"] == "cancelled"
    assert sess["_cancel_event"].is_set()


def test_codex_dashboard_start_redacts_device_authorization_error(monkeypatch):
    from fabric_cli import web_server as ws

    before_sessions = set(ws._oauth_sessions)

    class _Resp:
        status_code = 400
        text = "Enable device code authorization"

        def json(self):
            return {
                "error": {
                    "message": "Enable device code authorization",
                    "code": "device_authorization_not_enabled",
                }
            }

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            assert url.endswith("/deviceauth/usercode")
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)

    try:
        resp = client.post(
            "/api/providers/oauth/openai-codex/start",
            headers=HEADERS,
        )

        assert resp.status_code == 503
        assert resp.json() == {
            "error": {"code": "io_unavailable", "retryable": True}
        }
        assert "Enable device code authorization" not in resp.text
    finally:
        for sid in set(ws._oauth_sessions) - before_sessions:
            ws._oauth_sessions.pop(sid, None)


def test_codex_worker_logs_only_random_trace_and_stable_error(
    caplog,
    monkeypatch,
):
    from fabric_cli import web_server as ws

    sentinel = "raw-provider-body TOKEN-URL-sentinel"

    class _Resp:
        status_code = 400
        text = sentinel

        def json(self):
            return {"error": {"message": sentinel}}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    sid, sess = ws._new_oauth_session("openai-codex", "device_code")
    trace_id = sess["_flow_trace_id"]
    caplog.set_level(logging.WARNING, logger=ws.__name__)

    ws._codex_full_login_worker(sid)

    logs = caplog.text
    assert trace_id in logs
    assert "code=io_unavailable" in logs
    assert sentinel not in logs
    assert sid not in logs
    assert hashlib.sha256(sid.encode()).hexdigest() not in logs
    assert sess["error_code"] == "io_unavailable"
    assert sess["error_message"] == ws.stable_oauth_message(
        ws.OAuthFlowErrorCode.IO_UNAVAILABLE
    )


def test_codex_dashboard_start_timeout_cancels_hidden_worker_session(monkeypatch):
    from fabric_cli import web_server as ws

    before_sessions = set(ws._oauth_sessions)
    real_time = time.time
    real_new_session = ws._new_oauth_session
    monotonic_values = iter((0.0, 11.0))
    captured_session = {}

    class _ImmediateTimeoutClock:
        @staticmethod
        def time():
            return real_time()

        @staticmethod
        def monotonic():
            return next(monotonic_values)

    monkeypatch.setattr(ws, "time", _ImmediateTimeoutClock)
    monkeypatch.setattr(ws, "_codex_full_login_worker", lambda _sid: None)

    def _capture_new_session(*args, **kwargs):
        sid, sess = real_new_session(*args, **kwargs)
        captured_session["value"] = sess
        return sid, sess

    monkeypatch.setattr(ws, "_new_oauth_session", _capture_new_session)

    with pytest.raises(ws.OAuthFlowError) as caught:
        asyncio.run(ws._start_device_code_flow("openai-codex"))

    assert caught.value.code is ws.OAuthFlowErrorCode.IO_UNAVAILABLE
    assert set(ws._oauth_sessions) - before_sessions
    assert captured_session["value"]["status"] == "error"
    assert captured_session["value"]["_cancel_event"].is_set()


def test_nous_dashboard_poller_preserves_effective_scope_when_token_omits_scope(monkeypatch):
    from fabric_cli import auth as auth_mod
    from fabric_cli import web_server as ws

    session_id, session = ws._new_oauth_session("nous", "device_code")
    session.update({
        "portal_base_url": "https://portal.nousresearch.com",
        "client_id": "registered-nous-client",
        "device_code": "device-code",
        "interval": 5,
        "expires_at": time.time() + 600,
        "scope": auth_mod.DEFAULT_NOUS_SCOPE,
    })
    captured_state = {}

    def fake_refresh_nous_oauth_from_state(state, **kwargs):
        captured_state.update(state)
        return {**state, "agent_key": "jwt-agent-key"}

    monkeypatch.setattr(
        auth_mod,
        "_poll_for_token",
        lambda **kwargs: {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        },
    )
    monkeypatch.setattr(
        auth_mod,
        "refresh_nous_oauth_from_state",
        fake_refresh_nous_oauth_from_state,
    )
    monkeypatch.setattr(auth_mod, "persist_nous_credentials", lambda state: None)

    try:
        ws._nous_poller(session_id)
        assert captured_state["scope"] == auth_mod.DEFAULT_NOUS_SCOPE
        assert ws._oauth_sessions[session_id]["status"] == "approved"
    finally:
        ws._oauth_sessions.pop(session_id, None)


def test_nous_worker_cancellation_prevents_profile_or_root_persistence(
    tmp_path,
    monkeypatch,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import web_server as ws

    _make_profile_home(tmp_path, monkeypatch)
    sid, sess = ws._new_oauth_session("nous", "device_code", profile="coder")
    sess.update({
        "portal_base_url": "https://portal.nousresearch.com",
        "client_id": "registered-nous-client",
        "device_code": "device-code",
        "interval": 5,
        "expires_at": time.time() + 600,
        "scope": auth_mod.DEFAULT_NOUS_SCOPE,
    })
    persisted = []

    def cancel_then_return_token(**kwargs):
        _cancel_oauth_session(sid)
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    monkeypatch.setattr(auth_mod, "_poll_for_token", cancel_then_return_token)
    monkeypatch.setattr(
        auth_mod,
        "refresh_nous_oauth_from_state",
        lambda state, **kwargs: state,
    )
    monkeypatch.setattr(
        auth_mod,
        "persist_nous_credentials",
        lambda state: persisted.append(state),
    )

    ws._nous_poller(sid)

    assert persisted == []
    assert sess["status"] == "cancelled"
    assert sess["_cancel_event"].is_set()


def test_minimax_dashboard_poller_accepts_absolute_ms_expired_in():
    """Dashboard MiniMax completion must accept unix-ms token expiry values."""
    from fabric_cli import web_server as ws

    now = datetime.now(timezone.utc)
    abs_ms = int((now.timestamp() + 1800) * 1000)
    session_id, session = ws._new_oauth_session(
        "minimax-oauth",
        "device_code",
    )
    session.update({
        "portal_base_url": "https://api.minimax.io",
        "client_id": "client-id",
        "user_code": "ABCD-1234",
        "code_verifier": "verifier",
        "interval_ms": 2000,
        "expired_in_raw": abs_ms,
        "region": "global",
    })
    captured_state = {}

    try:
        with patch(
            "fabric_cli.auth._minimax_poll_token",
            return_value={
                "status": "success",
                "access_token": "access",
                "refresh_token": "refresh",
                "expired_in": abs_ms,
                "token_type": "Bearer",
            },
        ), patch(
            "fabric_cli.auth._minimax_save_auth_state",
            side_effect=lambda state: captured_state.update(state),
        ):
            ws._minimax_poller(session_id)
    finally:
        ws._oauth_sessions.pop(session_id, None)

    assert captured_state["access_token"] == "access"
    assert 1790 <= captured_state["expires_in"] <= 1810
    assert datetime.fromisoformat(captured_state["expires_at"]).year < 9999


def test_minimax_worker_cancellation_prevents_profile_or_root_persistence(
    tmp_path,
    monkeypatch,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import web_server as ws

    _make_profile_home(tmp_path, monkeypatch)
    sid, sess = ws._new_oauth_session(
        "minimax-oauth",
        "device_code",
        profile="coder",
    )
    sess.update({
        "portal_base_url": "https://api.minimax.io",
        "client_id": "client-id",
        "user_code": "ABCD-1234",
        "code_verifier": "verifier",
        "interval_ms": 2000,
        "expired_in_raw": 600,
        "region": "global",
    })
    persisted = []

    def cancel_then_return_token(**kwargs):
        _cancel_oauth_session(sid)
        return {
            "status": "success",
            "access_token": "access",
            "refresh_token": "refresh",
            "expired_in": 600,
            "token_type": "Bearer",
        }

    monkeypatch.setattr(auth_mod, "_minimax_poll_token", cancel_then_return_token)
    monkeypatch.setattr(
        auth_mod,
        "_minimax_save_auth_state",
        lambda state: persisted.append(state),
    )

    ws._minimax_poller(sid)

    assert persisted == []
    assert sess["status"] == "cancelled"
    assert sess["_cancel_event"].is_set()


def test_xai_oauth_listed_as_device_code_flow():
    """xAI Grok OAuth must surface in the catalog as a device-code flow."""
    resp = client.get("/api/providers/oauth", headers=HEADERS)
    assert resp.status_code == 200, resp.text
    providers = {p["id"]: p for p in resp.json()["providers"]}
    assert "xai-oauth" in providers
    assert providers["xai-oauth"]["flow"] == "device_code"
    assert "grok" in providers["xai-oauth"]["name"].lower()


def test_accounts_offers_every_oauth_provider_from_catalog():
    """PARITY CONTRACT: every accounts-tab provider in the unified catalog (the
    `fabric model` universe) must be offered by /api/providers/oauth. This keeps
    the desktop Accounts tab in lockstep with the CLI picker — no provider the
    CLI can sign into may be missing from the GUI.
    """
    from fabric_cli.provider_catalog import provider_catalog

    resp = client.get("/api/providers/oauth", headers=HEADERS)
    assert resp.status_code == 200, resp.text
    offered = {p["id"] for p in resp.json()["providers"]}
    for d in provider_catalog():
        if d.tab == "accounts":
            assert d.slug in offered, (
                f"{d.slug} is an accounts-tab provider in `fabric model` but is "
                f"missing from the desktop Accounts tab (/api/providers/oauth)"
            )


def test_copilot_acp_now_in_accounts():
    """Regression: copilot-acp was a canonical provider the CLI could configure,
    but had no Accounts card (the reported GUI/CLI drift).
    """
    resp = client.get("/api/providers/oauth", headers=HEADERS)
    assert resp.status_code == 200, resp.text
    providers = {p["id"]: p for p in resp.json()["providers"]}
    assert "copilot-acp" in providers
    # copilot-acp is managed by an external CLI: read-only card, not auto-removable.
    assert providers["copilot-acp"]["flow"] == "external"
    assert providers["copilot-acp"]["disconnectable"] is False


def test_oauth_catalog_marks_external_providers_not_disconnectable():
    """External CLI credentials are visible in Accounts but cannot be removed by Fabric."""
    resp = client.get("/api/providers/oauth", headers=HEADERS)
    assert resp.status_code == 200, resp.text
    providers = {p["id"]: p for p in resp.json()["providers"]}

    # Qwen: external and not auto-removable, and we don't know a clear command,
    # so it stays a manual hint with no runnable disconnect command.
    assert providers["qwen-oauth"]["flow"] == "external"
    assert providers["qwen-oauth"]["disconnectable"] is False
    assert "provider's CLI" in providers["qwen-oauth"]["disconnect_hint"]
    assert providers["qwen-oauth"]["disconnect_command"] is None

    # Fabric does not read or reuse Claude Code's own credentials at all (see
    # NOTICE) — there is no separate "claude-code" catalog entry any more.
    assert "claude-code" not in providers


def test_external_oauth_disconnect_rejected_before_auth_mutation(monkeypatch):
    """DELETE must not pretend to remove credentials owned by another CLI."""
    from fabric_cli import auth as auth_mod

    def fail_clear_provider_auth(provider_id=None):
        raise AssertionError("external providers must not reach clear_provider_auth")

    monkeypatch.setattr(auth_mod, "clear_provider_auth", fail_clear_provider_auth)

    resp = client.delete("/api/providers/oauth/qwen-oauth", headers=HEADERS)
    assert resp.status_code == 400, resp.text
    assert "cannot be disconnected automatically" in resp.text
    assert "provider's CLI" in resp.text


def test_oauth_disconnect_failure_is_stable_and_redacted(caplog, monkeypatch):
    from fabric_cli import auth as auth_mod
    from fabric_cli import web_server as ws

    sentinel = "raw disconnect path and credential sentinel"
    monkeypatch.setattr(
        auth_mod,
        "clear_provider_auth",
        lambda _provider: (_ for _ in ()).throw(RuntimeError(sentinel)),
    )
    caplog.set_level(logging.WARNING, logger=ws.__name__)

    response = client.delete("/api/providers/oauth/openai-codex", headers=HEADERS)

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "io_unavailable", "retryable": True}
    }
    assert sentinel not in response.text
    assert sentinel not in caplog.text
    assert "provider=openai-codex code=io_unavailable" in caplog.text


def test_env_sourced_oauth_status_is_not_disconnectable(tmp_path):
    """An env/.env-backed Anthropic API key is removed from Keys, not OAuth Accounts."""
    (tmp_path / ".env").write_text(
        "ANTHROPIC_API_KEY=test-anthropic-key\n",
        encoding="utf-8",
    )

    resp = client.get("/api/providers/oauth", headers=HEADERS)
    assert resp.status_code == 200, resp.text
    providers = {p["id"]: p for p in resp.json()["providers"]}

    assert providers["anthropic"]["status"]["source"] == "env_var"
    assert providers["anthropic"]["disconnectable"] is False
    assert providers["anthropic"]["disconnect_hint"] == "Remove the API key from Settings → Keys instead."

    delete_resp = client.delete("/api/providers/oauth/anthropic", headers=HEADERS)
    assert delete_resp.status_code == 400, delete_resp.text
    assert "Settings" in delete_resp.text


def test_anthropic_status_ignores_oauth_shaped_api_key(tmp_path):
    """An OAuth/setup-token-shaped value in ANTHROPIC_API_KEY is never accepted
    — Fabric has no other Anthropic credential source to fall back to (no
    ANTHROPIC_TOKEN, no Claude Code credential reuse — see NOTICE), so status
    is simply "not logged in"."""
    (tmp_path / ".env").write_text(
        "ANTHROPIC_API_KEY=sk-ant-oat01-wrong-slot\n",
        encoding="utf-8",
    )

    resp = client.get("/api/providers/oauth", headers=HEADERS)
    assert resp.status_code == 200, resp.text
    providers = {p["id"]: p for p in resp.json()["providers"]}

    status = providers["anthropic"]["status"]
    assert status["logged_in"] is False


def test_xai_oauth_device_code_start_returns_user_code(monkeypatch):
    """Start MUST hand back xAI's verification URL and user code."""
    from fabric_cli import auth as auth_mod
    from fabric_cli import web_server as ws

    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_request_device_code",
        lambda *a, **k: {
            "device_code": "device-code",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://accounts.x.ai/oauth2/device",
            "verification_uri_complete": "https://accounts.x.ai/oauth2/device?user_code=ABCD-EFGH",
            "expires_in": 1800,
            "interval": 5,
        },
    )
    # Don't let the background poller hit the real token endpoint.
    monkeypatch.setattr(ws, "_xai_device_poller", lambda sid: None)

    resp = client.post("/api/providers/oauth/xai-oauth/start", headers=HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    try:
        assert body["flow"] == "device_code"
        assert body["user_code"] == "ABCD-EFGH"
        assert body["verification_url"].startswith("https://accounts.x.ai/oauth2/device")
        sess = ws._oauth_sessions[body["session_id"]]
        assert sess["provider"] == "xai-oauth"
        assert sess["flow"] == "device_code"
        assert sess["device_code"] == "device-code"
        assert sess["_provider_deadline_monotonic"] > time.monotonic()
    finally:
        ws._oauth_sessions.pop(body["session_id"], None)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("verification_uri", "http://accounts.x.ai/oauth2/device"),
        ("verification_uri_complete", "https://x.ai.evil.test/device"),
        ("verification_uri_complete", "https://x.ai@evil.test/device"),
        ("user_code", "A" * 129),
        ("user_code", "ABCD EFGH"),
        ("device_code", "D" * 4097),
        ("expires_in", 0),
        ("expires_in", 3601),
        ("interval", 0),
        ("interval", 61),
        ("interval", True),
    ),
)
def test_xai_start_response_rejects_untrusted_or_unbounded_fields(field, value):
    from fabric_cli import auth as auth_mod

    payload = {
        "device_code": "device-code",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://accounts.x.ai/oauth2/device",
        "verification_uri_complete": (
            "https://accounts.x.ai/oauth2/device?user_code=ABCD-EFGH"
        ),
        "expires_in": 1800,
        "interval": 5,
    }
    payload[field] = value

    with pytest.raises(auth_mod.AuthError) as invalid:
        auth_mod._xai_validate_device_authorization_response(payload)
    assert invalid.value.code == "device_code_invalid"


def test_invalid_xai_navigation_response_fails_start_and_releases_lease(
    tmp_path,
    monkeypatch,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_accounts as accounts
    from fabric_cli import web_server as ws

    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_request_device_code",
        lambda *_args, **_kwargs: {
            "device_code": "device-code",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://accounts.x.ai/oauth2/device",
            "verification_uri_complete": "https://attacker.test/device",
            "expires_in": 1800,
            "interval": 5,
        },
    )
    pollers: list[str] = []
    monkeypatch.setattr(ws, "_xai_device_poller", pollers.append)

    response = client.post(
        "/api/providers/oauth/xai-oauth/start",
        headers=HEADERS,
        json={"expected_revision": 0},
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "io_unavailable", "retryable": True}
    }
    assert pollers == []
    assert (
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id="xai-oauth",
        ).oauth_lease
        is None
    )


def test_xai_dashboard_poller_seeds_single_entry_and_clears_suppression(tmp_path, monkeypatch):
    """The dashboard device-code poller must leave exactly ONE pool entry — the
    singleton-seeded ``device_code`` source — and must NOT create a parallel
    ``manual:dashboard_*`` entry.

    Dedupe: a parallel dashboard entry would share the singleton's single-use
    refresh token, and two entries racing the same rotation ->
    ``refresh_token_reused`` (on main, the dashboard login inserted exactly
    such a duplicate alongside the singleton seed). The poller writes the
    singleton only; the seed is the single source of truth.

    Suppression: an interactive dashboard login must also clear any
    ``device_code`` suppression left by a prior ``fabric auth remove
    xai-oauth``.
    """
    from fabric_cli import auth as auth_mod
    from fabric_cli import web_server as ws
    from agent.credential_pool import load_pool

    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    monkeypatch.delenv("XAI_BASE_URL", raising=False)

    # Prior `fabric auth remove xai-oauth` left the source suppressed.
    auth_mod.suppress_credential_source("xai-oauth", "device_code")
    assert auth_mod.is_source_suppressed("xai-oauth", "device_code") is True

    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_discovery",
        lambda *a, **k: {"token_endpoint": "https://auth.x.ai/token"},
    )
    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_poll_device_token",
        lambda client, **kwargs: {
            "access_token": "xai-dashboard-access",
            "refresh_token": "rt-dashboard",
            "id_token": "",
            "expires_in": 3600,
            "token_type": "Bearer",
        },
    )

    session_id, session = ws._new_oauth_session(
        "xai-oauth",
        "device_code",
    )
    session.update({
        "device_code": "device-code",
        "interval": 5,
        "expires_at": time.time() + 600,
        "_provider_deadline_monotonic": time.monotonic() + 600,
    })
    try:
        ws._xai_device_poller(session_id)
        assert ws._oauth_sessions[session_id]["status"] == "approved"
    finally:
        ws._oauth_sessions.pop(session_id, None)

    # The interactive dashboard login cleared the suppression marker.
    assert auth_mod.is_source_suppressed("xai-oauth", "device_code") is False

    # The credential pool has exactly one entry, seeded from the
    # singleton as ``device_code`` — no parallel ``manual:dashboard_*``
    # duplicate sharing the single-use refresh token.
    entries = load_pool("xai-oauth").entries()
    assert len(entries) == 1
    assert entries[0].source == "device_code"
    assert entries[0].refresh_token == "rt-dashboard"
    assert not any(
        getattr(e, "source", "").startswith("manual:dashboard") for e in entries
    )


def test_xai_poller_uses_the_original_monotonic_provider_deadline(tmp_path, monkeypatch):
    from fabric_cli import auth as auth_mod
    from fabric_cli import web_server as ws

    captured: dict[str, float] = {}
    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_discovery",
        lambda *_args, **_kwargs: {"token_endpoint": "https://auth.x.ai/token"},
    )

    def poll(_client, **kwargs):
        captured["provider_deadline"] = kwargs["provider_deadline"]
        return {
            "access_token": "short-access",
            "refresh_token": "short-refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    monkeypatch.setattr(auth_mod, "_xai_oauth_poll_device_token", poll)
    monkeypatch.setattr(ws, "_oauth_commit_if_active", lambda *_args: False)
    session_id, session = ws._new_oauth_session(
        "xai-oauth",
        "device_code",
    )
    provider_deadline = time.monotonic() + 5.9
    session.update({
        "device_code": "short-device-code",
        "interval": 1,
        "expires_at": time.time() + 5.9,
        "_provider_deadline_monotonic": provider_deadline,
    })

    ws._xai_device_poller(session_id)

    assert captured["provider_deadline"] == provider_deadline


def test_xai_poller_bounds_discovery_and_token_client_to_provider_deadline(
    tmp_path, monkeypatch
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import web_server as ws

    captured: dict[str, object] = {}

    def discovery(timeout_seconds):
        captured["discovery_timeout"] = timeout_seconds
        return {"token_endpoint": "https://auth.x.ai/token"}

    class _CapturingClient:
        def __init__(self, *args, **kwargs):
            captured["client_timeout"] = kwargs["timeout"]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def poll(_client, **_kwargs):
        return {
            "access_token": "short-access",
            "refresh_token": "short-refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    monkeypatch.setattr(auth_mod, "_xai_oauth_discovery", discovery)
    monkeypatch.setattr(auth_mod, "_xai_oauth_poll_device_token", poll)
    monkeypatch.setattr(httpx, "Client", _CapturingClient)
    monkeypatch.setattr(ws, "_oauth_commit_if_active", lambda *_args: False)
    session_id, session = ws._new_oauth_session("xai-oauth", "device_code")
    session.update({
        "device_code": "short-device-code",
        "interval": 1,
        "expires_at": time.time() + 1.0,
        "_provider_deadline_monotonic": time.monotonic() + 1.0,
    })

    ws._xai_device_poller(session_id)

    discovery_timeout = captured["discovery_timeout"]
    assert isinstance(discovery_timeout, float)
    assert 0 < discovery_timeout <= 1.0
    client_timeout = captured["client_timeout"]
    assert isinstance(client_timeout, httpx.Timeout)
    assert 0 < client_timeout.connect <= 1.0
    assert 0 < client_timeout.read <= 1.0


def test_xai_poller_does_not_start_token_io_after_slow_discovery_expires(
    tmp_path, monkeypatch
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import web_server as ws

    clock = [100.0]
    discovery_timeouts: list[float] = []
    polls: list[object] = []

    def slow_discovery(timeout_seconds):
        discovery_timeouts.append(timeout_seconds)
        clock[0] = 101.01
        return {"token_endpoint": "https://auth.x.ai/token"}

    session_id, session = ws._new_oauth_session("xai-oauth", "device_code")
    session.update({
        "device_code": "short-device-code",
        "interval": 1,
        "expires_at": time.time() + 1.0,
        "_provider_deadline_monotonic": 101.0,
    })
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(auth_mod, "_xai_oauth_discovery", slow_discovery)
    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_poll_device_token",
        lambda *_args, **_kwargs: polls.append(object()),
    )

    ws._xai_device_poller(session_id)

    assert discovery_timeouts == [pytest.approx(1.0)]
    assert polls == []
    assert session["status"] == "expired"


def test_xai_poller_expires_when_slow_token_request_consumes_deadline(
    tmp_path, monkeypatch
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import web_server as ws

    clock = [100.0]
    request_timeouts: list[float] = []

    class _PendingResponse:
        status_code = 400
        text = ""

        @staticmethod
        def json():
            return {"error": "authorization_pending"}

    class _SlowClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, *_args, **kwargs):
            request_timeouts.append(kwargs["timeout"])
            clock[0] = 101.0
            return _PendingResponse()

    session_id, session = ws._new_oauth_session("xai-oauth", "device_code")
    session.update({
        "device_code": "short-device-code",
        "interval": 1,
        "expires_at": time.time() + 1.0,
        "_provider_deadline_monotonic": 101.0,
    })
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_discovery",
        lambda _timeout: {"token_endpoint": "https://auth.x.ai/token"},
    )
    monkeypatch.setattr(httpx, "Client", _SlowClient)

    ws._xai_device_poller(session_id)

    assert request_timeouts == [pytest.approx(1.0)]
    assert session["status"] == "expired"


def test_xai_poller_expires_without_network_after_deadline(tmp_path, monkeypatch):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_accounts as accounts
    from fabric_cli import web_server as ws

    discoveries: list[object] = []
    polls: list[object] = []
    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_discovery",
        lambda *_args, **_kwargs: discoveries.append(object()),
    )
    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_poll_device_token",
        lambda *_args, **_kwargs: polls.append(object()),
    )
    session_id, session = ws._new_oauth_session(
        "xai-oauth",
        "device_code",
    )
    session.update({
        "device_code": "expired-device-code",
        "interval": 1,
        "expires_at": time.time() - 0.01,
        "_provider_deadline_monotonic": time.monotonic() - 0.01,
    })

    ws._xai_device_poller(session_id)

    assert discoveries == []
    assert polls == []
    assert session["status"] == "expired"
    assert (
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id="xai-oauth",
        ).oauth_lease
        is None
    )


@pytest.mark.parametrize("method", ["list", "disconnect"])
def test_oauth_status_and_disconnect_profile_work_never_blocks_event_loop(
    monkeypatch,
    method,
):
    from fabric_cli import web_server as ws

    entered = threading.Event()
    release = threading.Event()
    original_catalog = ws._OAUTH_PROVIDER_CATALOG
    ws._OAUTH_PROVIDER_CATALOG = (
        {
            "id": "openai-codex",
            "name": "OpenAI Codex",
            "flow": "device_code",
            "cli_command": "fabric auth add openai-codex",
            "docs_url": "https://openai.com",
            "status_fn": None,
        },
    )

    def blocking_status(*_args, **_kwargs):
        entered.set()
        assert release.wait(2)
        return {"logged_in": False}

    monkeypatch.setattr(ws, "_resolve_provider_status", blocking_status)
    if method == "disconnect":
        monkeypatch.setattr(
            "fabric_cli.auth.clear_provider_auth",
            lambda _provider: True,
        )

    async def scenario():
        ticks = 0
        stop = False

        async def heartbeat():
            nonlocal ticks
            while not stop:
                ticks += 1
                await asyncio.sleep(0)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as async_client:
            beat = asyncio.create_task(heartbeat())
            request = asyncio.create_task(
                async_client.get("/api/providers/oauth", headers=HEADERS)
                if method == "list"
                else async_client.delete(
                    "/api/providers/oauth/openai-codex",
                    headers=HEADERS,
                )
            )
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                before = ticks
                await asyncio.sleep(0.05)
                assert ticks > before + 10
                assert not request.done()
                release.set()
                response = await asyncio.wait_for(request, 2)
                assert response.status_code == 200
            finally:
                release.set()
                stop = True
                await beat

    try:
        asyncio.run(scenario())
    finally:
        ws._OAUTH_PROVIDER_CATALOG = original_catalog


def test_xai_worker_cancellation_prevents_profile_or_root_persistence(
    tmp_path,
    monkeypatch,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import web_server as ws

    _make_profile_home(tmp_path, monkeypatch)
    sid, sess = ws._new_oauth_session(
        "xai-oauth",
        "device_code",
        profile="coder",
    )
    sess.update({
        "device_code": "device-code",
        "interval": 5,
        "expires_at": time.time() + 600,
        "_provider_deadline_monotonic": time.monotonic() + 600,
    })
    persisted = []

    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_discovery",
        lambda *args, **kwargs: {"token_endpoint": "https://auth.x.ai/token"},
    )

    def cancel_then_return_token(*args, **kwargs):
        _cancel_oauth_session(sid)
        return {
            "access_token": "xai-access",
            "refresh_token": "xai-refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_poll_device_token",
        cancel_then_return_token,
    )
    monkeypatch.setattr(
        auth_mod,
        "_save_xai_oauth_tokens",
        lambda *args, **kwargs: persisted.append((args, kwargs)),
    )
    monkeypatch.setattr(
        auth_mod,
        "unsuppress_credential_source",
        lambda *args, **kwargs: persisted.append((args, kwargs)),
    )

    ws._xai_device_poller(sid)

    assert persisted == []
    assert sess["status"] == "cancelled"
    assert sess["_cancel_event"].is_set()


def test_unknown_pkce_provider_rejected_cleanly():
    """A future PKCE provider without an explicit branch must NOT silently route to Anthropic.

    Simulates a hypothetical catalog entry with ``flow: "pkce"`` and an
    id other than "anthropic". The dispatcher should fall through past
    the pkce branch (now gated on provider_id) and the device_code
    branch, then hit "Unsupported flow" — proving the bug class is
    structurally prevented.
    """
    from fabric_cli import web_server as ws

    # Inject a hypothetical catalog entry that's pkce-flagged but isn't
    # anthropic. This shape mirrors what would happen if a developer
    # added a new provider entry without remembering to wire up its
    # start function.
    fake_entry = {
        "id": "hypothetical-pkce-provider",
        "name": "Hypothetical PKCE Provider",
        "flow": "pkce",
        "cli_command": "fabric auth add hypothetical-pkce-provider",
        "docs_url": "https://example.com",
        "status_fn": None,
    }
    original_catalog = ws._OAUTH_PROVIDER_CATALOG
    try:
        ws._OAUTH_PROVIDER_CATALOG = original_catalog + (fake_entry,)
        resp = client.post(
            "/api/providers/oauth/hypothetical-pkce-provider/start",
            headers=HEADERS,
        )
    finally:
        ws._OAUTH_PROVIDER_CATALOG = original_catalog

    # Either 400 "Unsupported flow" (the explicit fall-through) or any
    # 4xx — what we MUST NOT see is a 200 with claude.ai in the body.
    assert resp.status_code >= 400, resp.text
    assert "claude.ai" not in resp.text.lower()


def test_status_falls_through_to_generic_dispatcher_for_catalog_only_provider():
    """Accounts-tab providers with no hardcoded branch reflect REAL status.

    Providers appended to the Accounts tab from the unified provider_catalog()
    carry status_fn=None and may have no explicit branch in
    _resolve_provider_status. Before the fallthrough they rendered permanently
    logged-out; now they dispatch to fabric_cli.auth.get_auth_status (the
    canonical slug dispatcher) so membership AND status both auto-extend.
    """
    import fabric_cli.web_server as ws

    fake_status = {
        "logged_in": True,
        "provider": "some-future-oauth",
        "name": "Future OAuth Provider",
        "access_token": "sk-future-secret-token-xyz",
        "expires_at": "2026-12-01T00:00:00Z",
        "has_refresh_token": True,
    }
    with patch("fabric_cli.auth.get_auth_status", return_value=fake_status):
        out = ws._resolve_provider_status("some-future-oauth", None)

    assert out["logged_in"] is True
    assert out["source"] == "some-future-oauth"
    assert out["source_label"] == "Future OAuth Provider"
    # Token is previewed, never returned whole.
    assert out["token_preview"] and "sk-future-secret-token-xyz" not in out["token_preview"]
    assert out["expires_at"] == "2026-12-01T00:00:00Z"
    assert out["has_refresh_token"] is True


def test_status_hardcoded_branch_wins_over_generic_fallback():
    """An existing hardcoded branch (nous) is unaffected by the fallthrough."""
    import fabric_cli.web_server as ws

    with patch(
        "fabric_cli.auth.get_nous_auth_status",
        return_value={"logged_in": True, "portal_base_url": "https://portal.test"},
    ):
        out = ws._resolve_provider_status("nous", None)
    assert out["source"] == "nous_portal"
    assert out["source_label"] == "https://portal.test"


def test_status_unknown_provider_degrades_to_logged_out():
    """A provider the generic dispatcher can't resolve stays logged-out cleanly."""
    import fabric_cli.web_server as ws

    with patch("fabric_cli.auth.get_auth_status", return_value={"logged_in": False}):
        out = ws._resolve_provider_status("totally-unknown", None)
    assert out["logged_in"] is False


def test_status_provider_exception_is_stable_and_redacted():
    import fabric_cli.web_server as ws

    sentinel = "raw status path and credential sentinel"
    with patch(
        "fabric_cli.auth.get_auth_status",
        side_effect=RuntimeError(sentinel),
    ):
        out = ws._resolve_provider_status("totally-unknown", None)

    assert out == {"logged_in": False, "error": "io_unavailable"}
    assert sentinel not in str(out)
