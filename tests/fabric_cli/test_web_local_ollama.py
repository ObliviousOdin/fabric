"""Desktop/web contract for first-class keyless local Ollama setup."""

from fastapi.testclient import TestClient
import yaml

from fabric_cli.ollama_runtime import OllamaModelDiscovery
from fabric_cli.web_server import _SESSION_TOKEN, app


client = TestClient(app)
HEADERS = {"X-Fabric-Session-Token": _SESSION_TOKEN}


def test_local_provider_catalog_is_passive_and_exposes_ollama(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("opening the local-provider catalog must not probe")

    monkeypatch.setattr("fabric_cli.ollama_runtime.discover_ollama_models", forbidden)

    response = client.get("/api/providers/local", headers=HEADERS)

    assert response.status_code == 200
    row = next(item for item in response.json()["providers"] if item["id"] == "ollama")
    assert row["configured"] is False
    assert row["base_url"] == "http://127.0.0.1:11434"
    assert row["discovery"] == "explicit"


def test_explicit_discovery_normalizes_v1_and_returns_only_stable_result(monkeypatch) -> None:
    calls: list[str] = []

    def discover(base_url: str):
        calls.append(base_url)
        return OllamaModelDiscovery(
            state="reachable",
            models=("qwen3:latest", "llama3.2:latest"),
        )

    monkeypatch.setattr("fabric_cli.ollama_runtime.discover_ollama_models", discover)

    response = client.post(
        "/api/providers/local/ollama/discover",
        headers=HEADERS,
        json={"base_url": "http://127.0.0.1:11434/v1"},
    )

    assert response.status_code == 200
    assert calls == ["http://127.0.0.1:11434"]
    assert response.json() == {
        "provider": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "state": "reachable",
        "models": ["qwen3:latest", "llama3.2:latest"],
        "issue_code": None,
    }


def test_configure_verifies_installed_model_and_enables_loopback_local_ai(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "fabric_cli.ollama_runtime.discover_ollama_models",
        lambda _base: OllamaModelDiscovery(
            state="reachable", models=("qwen3:latest",)
        ),
    )

    response = client.post(
        "/api/providers/local/ollama/configure",
        headers=HEADERS,
        json={
            "base_url": "http://127.0.0.1:11434",
            "model": "qwen3:latest",
        },
    )

    assert response.status_code == 200
    assert response.json()["local_ai_enabled"] is True
    from fabric_constants import get_fabric_home

    saved = yaml.safe_load((get_fabric_home() / "config.yaml").read_text())
    assert saved["model"] == {
        "provider": "ollama",
        "default": "qwen3:latest",
        "base_url": "http://127.0.0.1:11434",
    }
    assert saved["security"]["egress_mode"] == "local_ai"


def test_configure_rejects_model_missing_from_fresh_catalog(monkeypatch) -> None:
    monkeypatch.setattr(
        "fabric_cli.ollama_runtime.discover_ollama_models",
        lambda _base: OllamaModelDiscovery(
            state="reachable", models=("installed:latest",)
        ),
    )

    response = client.post(
        "/api/providers/local/ollama/configure",
        headers=HEADERS,
        json={
            "base_url": "http://127.0.0.1:11434",
            "model": "missing:latest",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "ollama_model_not_installed"


def test_invalid_url_is_rejected_before_discovery(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("invalid URL must fail before network")

    monkeypatch.setattr("fabric_cli.ollama_runtime.discover_ollama_models", forbidden)

    response = client.post(
        "/api/providers/local/ollama/discover",
        headers=HEADERS,
        json={"base_url": "http://user:secret@127.0.0.1:11434"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_ollama_url"


def test_public_endpoint_is_rejected_before_discovery(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("public URL must fail before network")

    monkeypatch.setattr("fabric_cli.ollama_runtime.discover_ollama_models", forbidden)

    response = client.post(
        "/api/providers/local/ollama/discover",
        headers=HEADERS,
        json={"base_url": "https://8.8.8.8:11434"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "ollama_endpoint_not_local"
