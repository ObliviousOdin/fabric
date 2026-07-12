"""Every MoA advisor/aggregator slot must resolve through local-AI policy."""

import socket

import pytest

from agent import moa_loop
from agent.egress_policy import EgressPolicyUnavailable, EgressPolicyViolation


def _config(mode, *, model=None, providers=None, cidrs=None):
    return {
        "security": {
            "egress_mode": mode,
            "local_ai_allowed_cidrs": list(cidrs or []),
        },
        "model": model or {},
        "providers": providers or {},
        "custom_providers": [],
    }


def _set_policy(monkeypatch, config):
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config", lambda: config
    )


def test_online_slot_keeps_existing_resolver_call(monkeypatch):
    _set_policy(monkeypatch, _config("online"))
    seen = {}

    def resolve(**kwargs):
        seen.update(kwargs)
        return {
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "key",
        }

    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider", resolve
    )
    runtime = moa_loop._slot_runtime(
        {"provider": "openrouter", "model": "model"}
    )
    assert seen == {"requested": "openrouter", "target_model": "model"}
    assert runtime["base_url"] == "https://openrouter.ai/api/v1"


def test_remote_slot_rejected_before_credentials_or_dns(monkeypatch):
    _set_policy(monkeypatch, _config("local_ai"))
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("runtime credential resolution must not run")
        ),
    )
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("DNS must not run")
        ),
    )
    with pytest.raises(EgressPolicyViolation) as caught:
        moa_loop._slot_runtime({"provider": "openrouter", "model": "model"})
    assert caught.value.reason == "hostname_not_allowed"


def test_codex_slot_never_refreshes_remote_oauth(monkeypatch):
    _set_policy(monkeypatch, _config("local_ai"))
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_codex_runtime_credentials",
        lambda: (_ for _ in ()).throw(
            AssertionError("remote OAuth refresh must not run")
        ),
    )

    with pytest.raises(EgressPolicyViolation):
        moa_loop._slot_runtime(
            {"provider": "openai-codex", "model": "gpt-5-codex"}
        )


def test_local_named_slot_is_canonical_and_pinned(monkeypatch):
    config = _config(
        "local_ai",
        model={"provider": "custom:lab", "default": "model"},
        providers={"lab": {"base_url": "http://localhost:11434/v1"}},
    )
    _set_policy(monkeypatch, config)
    seen = {}

    def resolve(**kwargs):
        seen.update(kwargs)
        return {
            "provider": "custom",
            "base_url": kwargs["explicit_base_url"],
            "api_key": "local-key",
            "api_mode": "chat_completions",
        }

    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider", resolve
    )
    runtime = moa_loop._slot_runtime(
        {"provider": "custom:lab", "model": "model"}
    )
    assert seen["explicit_base_url"] == "http://127.0.0.1:11434/v1"
    assert runtime["base_url"] == "http://127.0.0.1:11434/v1"


def test_private_hostname_and_virtual_moa_label_are_not_route_evidence(
    monkeypatch,
):
    _set_policy(
        monkeypatch,
        _config(
            "local_ai",
            model={"provider": "custom:lab"},
            providers={"lab": {"base_url": "http://model.internal:11434/v1"}},
            cidrs=["192.168.0.0/16"],
        ),
    )
    with pytest.raises(EgressPolicyViolation) as hostname_error:
        moa_loop._slot_runtime({"provider": "custom:lab", "model": "model"})
    assert hostname_error.value.reason == "hostname_not_allowed"

    _set_policy(monkeypatch, _config("local_ai"))
    with pytest.raises(EgressPolicyViolation):
        moa_loop._slot_runtime({"provider": "moa", "model": "virtual"})


def test_local_slot_rejects_runtime_route_substitution(monkeypatch):
    config = _config(
        "local_ai",
        model={"provider": "custom:lab"},
        providers={"lab": {"base_url": "http://127.0.0.1:11434/v1"}},
    )
    _set_policy(monkeypatch, config)
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: {
            "provider": "custom",
            "base_url": "https://example.com/v1",
            "api_key": "key",
        },
    )
    with pytest.raises(EgressPolicyViolation):
        moa_loop._slot_runtime({"provider": "custom:lab", "model": "model"})


def test_air_gapped_slot_is_unavailable(monkeypatch):
    _set_policy(monkeypatch, _config("air_gapped"))
    with pytest.raises(EgressPolicyUnavailable):
        moa_loop._slot_runtime({"provider": "custom", "model": "model"})


def test_sequential_slot_policies_have_no_global_cache(monkeypatch):
    active = {
        "config": _config(
            "local_ai",
            model={"provider": "custom:lab"},
            providers={"lab": {"base_url": "http://localhost:11434/v1"}},
        )
    }
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config",
        lambda: active["config"],
    )

    def resolve(**kwargs):
        return {
            "provider": "custom",
            "base_url": kwargs.get("explicit_base_url") or "https://example.com/v1",
            "api_key": "key",
        }

    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider", resolve
    )
    local = moa_loop._slot_runtime({"provider": "custom:lab", "model": "model"})
    active["config"] = _config("online")
    online = moa_loop._slot_runtime({"provider": "custom:lab", "model": "model"})
    active["config"] = _config(
        "local_ai",
        model={"provider": "custom:lab"},
        providers={"lab": {"base_url": "http://localhost:11434/v1"}},
    )
    local_again = moa_loop._slot_runtime(
        {"provider": "custom:lab", "model": "model"}
    )
    assert local["base_url"] == "http://127.0.0.1:11434/v1"
    assert online["base_url"] == "https://example.com/v1"
    assert local_again["base_url"] == local["base_url"]
