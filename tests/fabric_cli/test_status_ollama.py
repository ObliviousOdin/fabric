"""Status integration tests for opt-in Ollama readiness."""

from __future__ import annotations

from types import SimpleNamespace

import fabric_cli.ollama_runtime as ollama_runtime
import fabric_cli.status as status


def test_plain_status_gate_never_runs_deep_checks(monkeypatch):
    calls = []
    monkeypatch.setattr(status, "_show_deep_checks", lambda config: calls.append(config))

    status._maybe_show_deep_checks(SimpleNamespace(deep=False), {"sentinel": 1})

    assert calls == []


def test_deep_status_gate_runs_once(monkeypatch):
    calls = []
    config = {"sentinel": 1}
    monkeypatch.setattr(status, "_show_deep_checks", lambda value: calls.append(value))

    status._maybe_show_deep_checks(SimpleNamespace(deep=True), config)

    assert calls == [config]


def test_local_custom_endpoint_is_candidate_but_cloud_provider_is_not():
    local = {
        "model": {
            "provider": "custom",
            "default": "local-model",
            "base_url": "http://127.0.0.1:11434/v1",
        }
    }
    cloud = {
        "model": {
            "provider": "openrouter",
            "default": "vendor/model",
            "base_url": "https://openrouter.ai/api/v1",
        }
    }
    assert ollama_runtime.is_ollama_readiness_candidate(local) is True
    assert ollama_runtime.is_ollama_readiness_candidate(cloud) is False
    for cloud_alias in ("ollama-cloud", "ollama_cloud"):
        ollama_cloud = {
            "model": {
                "provider": cloud_alias,
                "default": "qwen-cloud:latest",
                "base_url": "https://ollama.com/v1",
            }
        }
        assert ollama_runtime.is_ollama_readiness_candidate(ollama_cloud) is False


def test_ready_snapshot_is_rendered_without_endpoint_or_credential(monkeypatch, capsys):
    payload = {
        "applicable": True,
        "state": "ready",
        "model": "qwen-test:latest",
        "effective_context_length": 65536,
        "context_state": "ready",
        "context_source": "ollama_show",
        "tools_state": "supported",
        "vision_state": "unsupported",
        "resource_state": "loaded",
        "loaded_vram_bytes": 1234,
        "issues": [],
    }
    snapshot = SimpleNamespace(to_dict=lambda: payload)
    monkeypatch.setattr(ollama_runtime, "is_ollama_readiness_candidate", lambda _config: True)
    monkeypatch.setattr(
        ollama_runtime,
        "build_ollama_readiness_snapshot",
        lambda **_kwargs: snapshot,
    )

    status._show_ollama_deep_status({"model": {"api_key": "never-print-me"}})
    output = capsys.readouterr().out

    assert "Ollama:" in output
    assert "ready" in output
    assert "65,536 tokens" in output
    assert "supported" in output
    assert "1,234 bytes in VRAM" in output
    assert "never-print-me" not in output
    assert "http://" not in output


def test_non_ollama_custom_endpoint_renders_no_false_failure(monkeypatch, capsys):
    snapshot = SimpleNamespace(
        to_dict=lambda: {
            "applicable": False,
            "state": "incompatible",
            "issues": [],
        }
    )
    monkeypatch.setattr(ollama_runtime, "is_ollama_readiness_candidate", lambda _config: True)
    monkeypatch.setattr(
        ollama_runtime,
        "build_ollama_readiness_snapshot",
        lambda **_kwargs: snapshot,
    )

    status._show_ollama_deep_status({})

    assert capsys.readouterr().out == ""


def test_readiness_exception_is_nonfatal_and_sanitized(monkeypatch, capsys):
    secret = "https://user:secret@private-host.invalid/v1"
    monkeypatch.setattr(ollama_runtime, "is_ollama_readiness_candidate", lambda _config: True)

    def fail(**_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(ollama_runtime, "build_ollama_readiness_snapshot", fail)

    status._show_ollama_deep_status({})
    output = capsys.readouterr().out

    assert "readiness check failed safely" in output
    assert secret not in output
    assert "private-host" not in output


def test_openrouter_deep_failure_does_not_echo_transport_exception(
    monkeypatch,
    capsys,
):
    import httpx
    import socket

    secret = "proxy-password"
    monkeypatch.setattr(status, "_show_ollama_deep_status", lambda _config: None)
    monkeypatch.setattr(
        status,
        "get_env_value",
        lambda key: "profile-key" if key == "OPENROUTER_API_KEY" else "",
    )
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(secret)),
    )

    fake_socket = SimpleNamespace(
        settimeout=lambda _value: None,
        connect_ex=lambda _address: 1,
        close=lambda: None,
    )
    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: fake_socket)

    status._show_deep_checks({})
    output = capsys.readouterr().out

    assert "OpenRouter" in output
    assert "unreachable" in output
    assert secret not in output
    assert "profile-key" not in output
