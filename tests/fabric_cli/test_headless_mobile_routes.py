"""Headless frontend-gate contracts for the opt-in mobile surface."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

import fabric_cli.web_server as web_server


def _headless_client(monkeypatch, tmp_path, *, mobile: bool) -> TestClient:
    dist = tmp_path / "web_dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(web_server, "WEB_DIST", dist)

    app = FastAPI()
    app.state.headless_backend = True
    app.state.mobile_client_enabled = mobile

    @app.get("/api/ping")
    async def ping():
        return {"route": "api"}

    @app.get("/login")
    async def login():
        return {"route": "login"}

    @app.post("/auth/password-login")
    async def password_login():
        return {"route": "password-login"}

    @app.get("/mobile/pair")
    async def mobile_pair():
        return {"route": "mobile-pair"}

    web_server.mount_spa(app)
    return TestClient(app)


def test_ordinary_headless_serve_blocks_mobile_bootstrap(monkeypatch, tmp_path):
    client = _headless_client(monkeypatch, tmp_path, mobile=False)

    assert client.get("/api/ping").json() == {"route": "api"}
    for method, path in (
        (client.get, "/login"),
        (client.post, "/auth/password-login"),
        (client.get, "/mobile/pair"),
    ):
        response = method(path)
        assert response.status_code == 404
        assert "web UI disabled" in response.json()["error"]


def test_headless_mobile_allows_only_mobile_bootstrap(monkeypatch, tmp_path):
    client = _headless_client(monkeypatch, tmp_path, mobile=True)

    assert client.get("/login").json() == {"route": "login"}
    assert client.post("/auth/password-login").json() == {
        "route": "password-login"
    }
    assert client.get("/mobile/pair").json() == {"route": "mobile-pair"}

    blocked = client.get("/")
    assert blocked.status_code == 404
    assert "web UI disabled" in blocked.json()["error"]


def test_headless_mobile_blocks_unknown_auth_path(monkeypatch, tmp_path):
    client = _headless_client(monkeypatch, tmp_path, mobile=True)

    blocked = client.get("/auth/loginx")

    assert blocked.status_code == 404
    assert blocked.headers["content-type"].startswith("application/json")
    assert "web UI disabled" in blocked.json()["error"]
