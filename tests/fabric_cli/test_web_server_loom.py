"""Tests for the Loom deploy-plane HTTP endpoints in fabric_cli.web_server.

These exercise the ``/api/loom/*`` routes end-to-end through the FastAPI app
using Starlette's TestClient. ``open_service`` is monkeypatched so each request
gets a fresh ``LoomService`` backed by a throwaway temp SQLite DB and a fake
driver — no real Docker/SSH is touched, but every request still shares state
through the same ``loom.db`` file.
"""

from __future__ import annotations

import pytest

from fabric_cli.loom.service import LoomService
from fabric_cli.loom.store import LoomStore
from tests.loom._fakes import make_factory


@pytest.fixture
def loom_client(monkeypatch, tmp_path):
    """A TestClient wired to a temp-backed LoomService + fake driver.

    ``web_server`` imports ``open_service`` into its own namespace
    (``from fabric_cli.loom import open_service``), so the stable patch target
    is ``fabric_cli.web_server.open_service``. We return a *new* service per
    call (matching production, where each request opens and closes its own
    store) but point every one at the same ``loom.db`` so state persists.
    """
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    import fabric_cli.web_server as web_server
    from fabric_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    db_path = tmp_path / "loom.db"

    def _fake_open_service() -> LoomService:
        return LoomService(LoomStore(db_path=db_path), driver_factory=make_factory())

    monkeypatch.setattr(web_server, "open_service", _fake_open_service)

    client = TestClient(app)
    client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return client


def test_status_empty(loom_client):
    resp = loom_client.get("/api/loom/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["hosts"] == 0
    assert data["projects"] == 0
    assert data["deployments"] == 0
    assert data["active"] == []


def test_add_host_local(loom_client):
    resp = loom_client.post(
        "/api/loom/hosts", json={"name": "here", "kind": "local"}
    )
    assert resp.status_code == 200
    host = resp.json()
    assert host["name"] == "here"
    assert host["kind"] == "local"
    assert host["state"] == "ready"
    assert host["id"]

    # It shows up in the list and bumps the status count.
    listed = loom_client.get("/api/loom/hosts").json()
    assert [h["name"] for h in listed] == ["here"]
    assert loom_client.get("/api/loom/status").json()["hosts"] == 1


def test_add_project(loom_client):
    resp = loom_client.post(
        "/api/loom/projects",
        json={"name": "app", "kind": "compose", "source": "/srv/app"},
    )
    assert resp.status_code == 200
    project = resp.json()
    assert project["name"] == "app"
    assert project["kind"] == "compose"
    assert project["source"] == "/srv/app"

    listed = loom_client.get("/api/loom/projects").json()
    assert [p["name"] for p in listed] == ["app"]


def test_deploy_reaches_active(loom_client):
    loom_client.post("/api/loom/hosts", json={"name": "here", "kind": "local"})
    loom_client.post(
        "/api/loom/projects",
        json={"name": "app", "kind": "compose", "source": "/srv/app"},
    )

    resp = loom_client.post(
        "/api/loom/deploy", json={"project": "app", "host": "here"}
    )
    assert resp.status_code == 200
    dep = resp.json()
    assert dep["state"] == "active"
    assert dep["active"] is True
    # The snapshotted plan survives JSON serialisation as a nested dict.
    assert dep["plan"]["steps"]

    # Logs for the real deployment are retrievable.
    logs = loom_client.get(f"/api/loom/deployments/{dep['id']}/logs")
    assert logs.status_code == 200
    assert "logs" in logs.json()

    # And it appears in the deployment list.
    deployments = loom_client.get("/api/loom/deployments").json()
    assert any(d["id"] == dep["id"] for d in deployments)


def test_logs_bad_deployment_404(loom_client):
    resp = loom_client.get("/api/loom/deployments/does-not-exist/logs")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "not-found"


def test_add_host_bad_kind_400(loom_client):
    resp = loom_client.post(
        "/api/loom/hosts", json={"name": "x", "kind": "kubernetes"}
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "validation"


def test_unauthorized_post_rejected(monkeypatch, tmp_path):
    """A client without the session header cannot mutate the deploy plane."""
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    import fabric_cli.web_server as web_server
    from fabric_cli.web_server import app

    db_path = tmp_path / "loom.db"

    def _fake_open_service() -> LoomService:
        return LoomService(LoomStore(db_path=db_path), driver_factory=make_factory())

    monkeypatch.setattr(web_server, "open_service", _fake_open_service)

    anon = TestClient(app)  # no _SESSION_HEADER_NAME header
    resp = anon.post("/api/loom/hosts", json={"name": "here", "kind": "local"})
    assert resp.status_code in (401, 403)
