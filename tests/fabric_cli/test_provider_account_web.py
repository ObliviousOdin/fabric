"""Profile-scoped REST contract for provider-account ownership state."""

from __future__ import annotations

import asyncio
from pathlib import Path
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from fabric_cli import provider_accounts as accounts
from fabric_cli import web_server as web_server_mod
from fabric_cli.web_server import _SESSION_TOKEN, app
from fabric_constants import get_fabric_home


HEADERS = {"X-Fabric-Session-Token": _SESSION_TOKEN}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, headers=HEADERS)


def test_provider_account_rest_creates_local_request_then_cancels(
    client: TestClient,
) -> None:
    initial = client.get("/api/providers/accounts")
    assert initial.status_code == 200
    assert {
        item["provider_id"]: item["desired_ownership"]
        for item in initial.json()["accounts"]
    } == {"openai-codex": "unselected", "xai-oauth": "unselected"}

    created = client.post(
        "/api/providers/accounts/openai-codex/managed-request",
        json={"device_label": "front desk fabric", "expected_revision": 0},
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["created"] is True
    assert payload["snapshot"]["desired_ownership"] == "fabric_managed"
    assert payload["snapshot"]["handoff"] is None
    request_id = payload["request"]["request_id"]

    attempted = client.post(
        "/api/providers/accounts/openai-codex/handoff-attempted",
        json={"request_id": request_id, "expected_revision": 1},
    )
    assert attempted.status_code == 200
    assert attempted.json()["request"]["handoff_state"] == (
        "launch_attempted_unverified"
    )
    assert attempted.json()["request"]["status"] == "requested"

    cancelled = client.post(
        "/api/providers/accounts/openai-codex/cancel",
        json={"request_id": request_id, "expected_revision": 2},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["request"]["status"] == "cancelled"
    assert cancelled.json()["snapshot"]["active_request"] is None


def test_provider_account_rest_rejects_extra_secret_without_echo_or_write(
    client: TestClient,
) -> None:
    sentinel = "RAW-DEVICE-CODE-SENTINEL"
    response = client.post(
        "/api/providers/accounts/xai-oauth/managed-request",
        json={
            "device_label": "lobby",
            "expected_revision": 0,
            "device_code": sentinel,
        },
    )

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "invalid_input", "retryable": False}}
    assert sentinel not in response.text
    snapshot = accounts.get_account_snapshot(
        home=Path(get_fabric_home()),
        provider_id="xai-oauth",
    )
    assert snapshot.desired_ownership == "unselected"
    assert snapshot.requests == ()


@pytest.mark.parametrize(
    "raw_body",
    [
        b'{"device_label":"MALFORMED-SENTINEL"',
        b'{"device_label":"first","device_label":"DUPLICATE-SENTINEL",'
        b'"expected_revision":0}',
        b'{"device_label":"NONFINITE-SENTINEL","expected_revision":NaN}',
        b'["ARRAY-SENTINEL"]',
    ],
)
def test_provider_account_rest_rejects_non_strict_json_with_stable_redaction(
    client: TestClient,
    raw_body: bytes,
) -> None:
    response = client.post(
        "/api/providers/accounts/xai-oauth/managed-request",
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "invalid_input", "retryable": False}}
    assert "SENTINEL" not in response.text
    snapshot = accounts.get_account_snapshot(
        home=Path(get_fabric_home()),
        provider_id="xai-oauth",
    )
    assert snapshot.desired_ownership == "unselected"
    assert snapshot.requests == ()


def test_provider_account_rest_isolates_named_profile(
    client: TestClient,
) -> None:
    root = Path(get_fabric_home())
    named = root / "profiles" / "worker"
    named.mkdir(parents=True)

    created = client.post(
        "/api/providers/accounts/xai-oauth/managed-request?profile=worker",
        json={"device_label": "worker fabric", "expected_revision": 0},
    )
    assert created.status_code == 200

    named_status = client.get("/api/providers/accounts/xai-oauth?profile=worker")
    default_status = client.get("/api/providers/accounts/xai-oauth")
    assert named_status.status_code == 200
    assert named_status.json()["snapshot"]["desired_ownership"] == "fabric_managed"
    assert default_status.status_code == 200
    assert default_status.json()["snapshot"]["desired_ownership"] == "unselected"
    assert (named / accounts.STATE_FILENAME).is_file()
    assert not (root / accounts.STATE_FILENAME).exists()


def test_provider_account_rest_uses_stable_profile_and_provider_errors(
    client: TestClient,
) -> None:
    unknown_profile = client.get("/api/providers/accounts/openai-codex?profile=missing")
    invalid_provider = client.get("/api/providers/accounts/not-a-provider")

    assert unknown_profile.status_code == 404
    assert unknown_profile.json() == {
        "error": {"code": "not_found", "retryable": False}
    }
    assert invalid_provider.status_code == 400
    assert invalid_provider.json() == {
        "error": {"code": "invalid_provider", "retryable": False}
    }


def test_provider_account_rest_mutations_require_dashboard_token() -> None:
    unauthenticated = TestClient(app)

    response = unauthenticated.post(
        "/api/providers/accounts/openai-codex/managed-request",
        json={"device_label": "front desk", "expected_revision": 0},
    )

    assert response.status_code in {401, 403}


def test_provider_account_rest_offloads_locking_domain_work(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body_threads: list[int] = []
    domain_threads: list[int] = []
    real_read = web_server_mod._read_provider_account_body
    real_create = web_server_mod._create_provider_account_managed_request_sync

    async def tracked_read(request):
        body_threads.append(threading.get_ident())
        return await real_read(request)

    def tracked_create(**kwargs):
        domain_threads.append(threading.get_ident())
        return real_create(**kwargs)

    monkeypatch.setattr(web_server_mod, "_read_provider_account_body", tracked_read)
    monkeypatch.setattr(
        web_server_mod,
        "_create_provider_account_managed_request_sync",
        tracked_create,
    )

    response = client.post(
        "/api/providers/accounts/openai-codex/managed-request",
        json={"device_label": "front desk", "expected_revision": 0},
    )

    assert response.status_code == 200
    assert len(body_threads) == len(domain_threads) == 1
    assert body_threads[0] != domain_threads[0]


def test_provider_account_body_stream_stops_at_limit_without_content_length() -> None:
    delivered = 0
    chunks = [
        b"{" + (b"a" * (web_server_mod._PROVIDER_ACCOUNT_BODY_LIMIT - 1)),
        b"x",
        b"UNREAD-SECRET-SENTINEL",
    ]

    async def receive():
        nonlocal delivered
        chunk = chunks[delivered]
        delivered += 1
        return {
            "type": "http.request",
            "body": chunk,
            "more_body": delivered < len(chunks),
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/providers/accounts/openai-codex/managed-request",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )

    with pytest.raises(accounts.ProviderAccountError) as caught:
        asyncio.run(web_server_mod._read_provider_account_body(request))

    assert caught.value.code is accounts.ProviderAccountErrorCode.INVALID_INPUT
    assert delivered == 2
