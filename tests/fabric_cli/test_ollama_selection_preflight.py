"""Explicit model selection preflights Ollama without probing picker opens."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.egress_policy import EgressMode
from fabric_cli import model_switch
from fabric_cli.ollama_runtime import is_ollama_runtime_target


def _snapshot(
    *,
    state: str = "ready",
    context_state: str = "ready",
    effective_context_length: int | None = 65_536,
    tools_state: str = "supported",
    applicable: bool = True,
):
    return SimpleNamespace(
        applicable=applicable,
        context_state=context_state,
        effective_context_length=effective_context_length,
        state=state,
        tools_state=tools_state,
    )


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [
        ("ollama", "http://127.0.0.1:11434/v1"),
        ("custom:local-ollama", "http://127.0.0.1:18080/v1"),
        ("custom", "http://192.168.1.20:11434/v1"),
    ],
)
def test_ollama_target_identity_is_explicit_or_uses_native_port(provider, base_url):
    assert is_ollama_runtime_target(provider, base_url) is True


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [
        ("custom", "http://127.0.0.1:1234/v1"),
        ("lmstudio", "http://127.0.0.1:1234/v1"),
        ("vllm", "http://127.0.0.1:8000/v1"),
        ("ollama-cloud", "https://ollama.com/v1"),
    ],
)
def test_non_ollama_local_and_cloud_targets_are_not_probed(provider, base_url):
    assert is_ollama_runtime_target(provider, base_url) is False


def _assess(monkeypatch, snapshot):
    monkeypatch.setattr(
        "fabric_cli.ollama_runtime.build_ollama_readiness_snapshot",
        lambda **_kwargs: snapshot,
    )
    return model_switch._preflight_ollama_selection(
        provider="custom:local-ollama",
        model="qwen3:8b",
        base_url="http://127.0.0.1:11434/v1",
        api_key="no-key-required",
        config={"model": {"ollama_num_ctx": 65_536}},
    )


def test_context_below_agent_floor_blocks_without_suggesting_a_false_override(
    monkeypatch,
):
    error, warning = _assess(
        monkeypatch,
        _snapshot(
            state="blocked",
            context_state="too_small",
            effective_context_length=40_960,
        ),
    )

    assert warning is None
    assert "40,960" in error
    assert "64,000-token agent minimum" in error
    assert "do not claim a larger context" in error


def test_missing_tools_or_model_blocks_selection(monkeypatch):
    tools_error, tools_warning = _assess(
        monkeypatch,
        _snapshot(state="blocked", tools_state="unsupported"),
    )
    assert tools_warning is None
    assert "no tool support" in tools_error

    missing_error, missing_warning = _assess(
        monkeypatch,
        _snapshot(
            state="model_missing",
            context_state="unknown",
            effective_context_length=None,
            tools_state="unknown",
        ),
    )
    assert missing_warning is None
    assert "fabric ollama pull <model>" in missing_error


@pytest.mark.parametrize("state", ["access_unavailable", "not_configured", "unreachable"])
def test_unavailable_daemon_warns_without_destroying_offline_configuration(
    monkeypatch,
    state,
):
    error, warning = _assess(
        monkeypatch,
        _snapshot(
            state=state,
            context_state="unknown",
            effective_context_length=None,
            tools_state="unknown",
        ),
    )

    assert error is None
    assert "selection was not rejected" in warning
    assert "fabric status --deep" in warning


def test_unexpected_probe_error_is_redacted_but_process_interrupts_propagate(
    monkeypatch,
):
    sentinel = "https://user:password@example.invalid/?token=secret"

    def fail(**_kwargs):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(
        "fabric_cli.ollama_runtime.build_ollama_readiness_snapshot",
        fail,
    )
    error, warning = model_switch._preflight_ollama_selection(
        provider="ollama",
        model="qwen3:8b",
        base_url="http://127.0.0.1:11434/v1",
        api_key="secret-key",
        config={},
    )
    assert error is None
    assert "could not be verified" in warning
    assert sentinel not in warning
    assert "secret-key" not in warning

    monkeypatch.setattr(
        "fabric_cli.ollama_runtime.build_ollama_readiness_snapshot",
        lambda **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    with pytest.raises(KeyboardInterrupt):
        model_switch._preflight_ollama_selection(
            provider="ollama",
            model="qwen3:8b",
            base_url="http://127.0.0.1:11434/v1",
            api_key="",
            config={},
        )


def test_switch_model_opt_in_turns_preflight_failure_into_noop(monkeypatch):
    policy = SimpleNamespace(mode=EgressMode.ONLINE)
    monkeypatch.setattr(
        model_switch,
        "_load_model_switch_policy",
        lambda: (policy, {"model": {}}),
    )
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: {
            "provider": "custom",
            "api_key": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "api_mode": "chat_completions",
        },
    )
    monkeypatch.setattr(
        "fabric_cli.models.validate_requested_model",
        lambda *_args, **_kwargs: {
            "accepted": True,
            "persist": True,
            "recognized": True,
            "message": None,
        },
    )
    monkeypatch.setattr(model_switch, "get_model_capabilities", lambda *_a, **_k: None)
    monkeypatch.setattr(model_switch, "get_model_info", lambda *_a, **_k: None)
    monkeypatch.setattr(model_switch, "_check_hermes_model_warning", lambda _m: None)
    calls = []
    monkeypatch.setattr(
        model_switch,
        "_preflight_ollama_selection",
        lambda **kwargs: (calls.append(kwargs) or ("local model blocked", None)),
    )

    result = model_switch.switch_model(
        raw_input="qwen3:8b",
        current_provider="custom",
        current_model="old-model",
        current_base_url="http://127.0.0.1:11434/v1",
        preflight_local_runtime=True,
    )

    assert result.success is False
    assert result.error_message == "local model blocked"
    assert result.api_key == ""
    assert calls and calls[0]["model"] == "qwen3:8b"


def test_switch_model_default_keeps_inventory_and_legacy_callers_probe_free(
    monkeypatch,
):
    policy = SimpleNamespace(mode=EgressMode.ONLINE)
    monkeypatch.setattr(
        model_switch,
        "_load_model_switch_policy",
        lambda: (policy, {"model": {}}),
    )
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: {
            "provider": "custom",
            "api_key": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "api_mode": "chat_completions",
        },
    )
    monkeypatch.setattr(
        "fabric_cli.models.validate_requested_model",
        lambda *_args, **_kwargs: {
            "accepted": True,
            "persist": True,
            "recognized": True,
            "message": None,
        },
    )
    monkeypatch.setattr(model_switch, "get_model_capabilities", lambda *_a, **_k: None)
    monkeypatch.setattr(model_switch, "get_model_info", lambda *_a, **_k: None)
    monkeypatch.setattr(model_switch, "_check_hermes_model_warning", lambda _m: None)
    monkeypatch.setattr(
        model_switch,
        "_preflight_ollama_selection",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("default switch must remain probe-free")
        ),
    )

    result = model_switch.switch_model(
        raw_input="qwen3:8b",
        current_provider="custom",
        current_model="old-model",
        current_base_url="http://127.0.0.1:11434/v1",
    )

    assert result.success is True
