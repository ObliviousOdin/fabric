"""Tests for the plan-then-apply dashboard path (/api/loom/deployments/{id}/apply).

The dashboard previews a plan (persisting a PLANNED deployment) and then applies
*that* deployment id on confirm, rather than replanning a fresh one — preserving
the plan-before-mutation guarantee in the UI.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from fabric_cli import web_server
from fabric_cli.loom.service import LoomService
from fabric_cli.loom.store import LoomStore
from tests.loom._fakes import make_factory


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "loom.db"

    def _fake_open_service() -> LoomService:
        # Fresh service per call (store created on the calling thread), same DB
        # path so state persists — matches production open-and-close-per-request
        # and works with _loom_run's worker-thread execution.
        return LoomService(LoomStore(db_path=db_path), driver_factory=make_factory())

    monkeypatch.setattr(web_server, "open_service", _fake_open_service)
    c = TestClient(web_server.app)
    c.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    return c


def test_plan_then_apply_reaches_active(client):
    assert client.post("/api/loom/hosts", json={"name": "here", "kind": "local"}).status_code == 200
    assert client.post("/api/loom/projects", json={"name": "app", "kind": "compose"}).status_code == 200

    planned = client.post("/api/loom/plan", json={"project": "app", "host": "here"}).json()
    assert planned["state"] == "planned"
    dep_id = planned["id"]

    applied = client.post(f"/api/loom/deployments/{dep_id}/apply", json={})
    assert applied.status_code == 200
    body = applied.json()
    assert body["id"] == dep_id  # the reviewed deployment, not a fresh one
    assert body["state"] == "active"
    assert body["active"] is True


def test_apply_unknown_deployment_404(client):
    resp = client.post("/api/loom/deployments/dep_missing/apply", json={})
    assert resp.status_code == 404


def test_apply_twice_conflicts(client):
    client.post("/api/loom/hosts", json={"name": "here", "kind": "local"})
    client.post("/api/loom/projects", json={"name": "app", "kind": "compose"})
    dep_id = client.post("/api/loom/plan", json={"project": "app", "host": "here"}).json()["id"]
    assert client.post(f"/api/loom/deployments/{dep_id}/apply", json={}).status_code == 200
    # Re-applying a no-longer-planned deployment is a conflict.
    assert client.post(f"/api/loom/deployments/{dep_id}/apply", json={}).status_code == 409


def test_apply_requires_auth(client, tmp_path, monkeypatch):
    unauth = TestClient(web_server.app)  # no session header
    resp = unauth.post("/api/loom/deployments/dep_x/apply", json={})
    assert resp.status_code in (401, 403)
