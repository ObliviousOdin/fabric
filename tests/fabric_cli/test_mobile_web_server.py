from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient

from fabric_cli import web_server
from fabric_cli.dashboard_auth.middleware import _path_is_public


def _mobile_app(monkeypatch, tmp_path, *, enabled: bool, gated: bool):
    dist = tmp_path / "mobile_web_dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<html><head></head><body>Fabric Mobile</body></html>",
        encoding="utf-8",
    )
    (assets / "app.js").write_text("console.log('mobile')", encoding="utf-8")
    monkeypatch.setattr(web_server, "MOBILE_WEB_DIST", dist)

    application = FastAPI()
    application.state.mobile_client_enabled = enabled
    application.state.auth_required = gated
    web_server.mount_mobile_spa(application)
    return TestClient(application)


def test_mobile_spa_is_opt_in(monkeypatch, tmp_path):
    client = _mobile_app(monkeypatch, tmp_path, enabled=False, gated=False)

    response = client.get("/mobile")

    assert response.status_code == 404


def test_mobile_spa_serves_pairing_fallback_and_assets(monkeypatch, tmp_path):
    client = _mobile_app(monkeypatch, tmp_path, enabled=True, gated=False)

    root = client.get("/mobile/pair")
    asset = client.get("/mobile/assets/app.js")

    assert root.status_code == 200
    assert "Fabric Mobile" in root.text
    assert "window.__FABRIC_AUTH_REQUIRED__=false" in root.text
    assert "window.__FABRIC_SESSION_TOKEN__" not in root.text
    assert root.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert asset.status_code == 200
    assert asset.text == "console.log('mobile')"


def test_gated_mobile_index_does_not_embed_ephemeral_token(monkeypatch, tmp_path):
    client = _mobile_app(monkeypatch, tmp_path, enabled=True, gated=True)

    response = client.get("/mobile/")

    assert response.status_code == 200
    assert "window.__FABRIC_AUTH_REQUIRED__=true" in response.text
    assert "window.__FABRIC_SESSION_TOKEN__" not in response.text


def test_mobile_service_worker_never_persists_documents_or_credentials():
    root = Path(__file__).resolve().parents[2]
    source = (root / "apps/mobile-web/public/sw.js").read_text(encoding="utf-8")

    assert "cache.add" not in source
    assert "caches.match" not in source
    assert ".filter((key) => key.startsWith(CACHE_PREFIX))" in source


def test_mobile_auth_bypass_is_prefix_safe():
    assert _path_is_public("/mobile")
    assert _path_is_public("/mobile/pair")
    assert not _path_is_public("/mobileevil")
    assert not _path_is_public("/api/sessions")
