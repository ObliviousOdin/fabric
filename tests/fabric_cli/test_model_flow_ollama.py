from __future__ import annotations

from copy import deepcopy

from fabric_cli.model_setup_flows import _model_flow_ollama
from fabric_cli.ollama_runtime import OllamaModelDiscovery


def test_first_class_ollama_flow_discovers_selects_and_defaults_loopback_local_ai(
    monkeypatch, capsys
) -> None:
    persisted = {
        "model": {
            "provider": "custom",
            "default": "old",
            "base_url": "https://old.example/v1",
            "api_key": "stale-secret",
            "api_mode": "anthropic_messages",
        },
        "security": {"egress_mode": "online"},
    }
    caller = deepcopy(persisted)
    saved: list[dict] = []
    deactivated: list[bool] = []

    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    monkeypatch.setattr(
        "fabric_cli.ollama_runtime.discover_ollama_models",
        lambda _base_url: OllamaModelDiscovery(
            "reachable", ("qwen3:latest", "gemma4:27b")
        ),
    )
    monkeypatch.setattr(
        "fabric_cli.auth._prompt_model_selection",
        lambda models, **kwargs: (
            "qwen3:latest"
            if models == ["qwen3:latest", "gemma4:27b"]
            and kwargs["confirm_provider"] == "ollama"
            and kwargs["confirm_base_url"] == "http://127.0.0.1:11434"
            else None
        ),
    )
    monkeypatch.setattr("fabric_cli.auth._save_model_choice", lambda _model: None)
    monkeypatch.setattr(
        "fabric_cli.auth.deactivate_provider", lambda: deactivated.append(True)
    )
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: persisted)
    monkeypatch.setattr(
        "fabric_cli.config.save_config", lambda config: saved.append(deepcopy(config))
    )

    _model_flow_ollama(caller, current_model="old")

    assert saved
    assert saved[-1]["model"] == {
        "provider": "ollama",
        "default": "qwen3:latest",
        "base_url": "http://127.0.0.1:11434",
    }
    assert saved[-1]["security"]["egress_mode"] == "local_ai"
    assert caller["model"] == saved[-1]["model"]
    assert caller["security"]["egress_mode"] == "local_ai"
    assert deactivated == [True]
    output = capsys.readouterr().out
    assert "native /api/chat" in output
    assert "Network-capable tools and downloads remain separate" in output


def test_first_class_ollama_flow_does_not_save_when_daemon_is_unreachable(
    monkeypatch, capsys
) -> None:
    saved: list[dict] = []
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    monkeypatch.setattr(
        "fabric_cli.ollama_runtime.discover_ollama_models",
        lambda _base_url: OllamaModelDiscovery(
            "unreachable", issue_code="ollama_unreachable"
        ),
    )
    monkeypatch.setattr(
        "fabric_cli.config.save_config", lambda config: saved.append(deepcopy(config))
    )

    caller = {"model": {}}
    _model_flow_ollama(caller)

    assert saved == []
    assert caller == {"model": {}}
    assert "Start it with `ollama serve`" in capsys.readouterr().out


def test_lan_ollama_flow_requires_explicit_cidr_before_local_ai(
    monkeypatch, capsys
) -> None:
    persisted = {
        "model": {},
        "security": {"egress_mode": "online", "local_ai_allowed_cidrs": []},
    }
    caller = deepcopy(persisted)
    saved: list[dict] = []
    monkeypatch.setattr(
        "builtins.input", lambda _prompt="": "http://192.168.50.20:11434"
    )
    monkeypatch.setattr(
        "fabric_cli.ollama_runtime.discover_ollama_models",
        lambda _base_url: OllamaModelDiscovery("reachable", ("qwen3:latest",)),
    )
    monkeypatch.setattr(
        "fabric_cli.auth._prompt_model_selection",
        lambda _models, **_kwargs: "qwen3:latest",
    )
    monkeypatch.setattr("fabric_cli.auth._save_model_choice", lambda _model: None)
    monkeypatch.setattr("fabric_cli.auth.deactivate_provider", lambda: None)
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: persisted)
    monkeypatch.setattr(
        "fabric_cli.config.save_config", lambda config: saved.append(deepcopy(config))
    )

    _model_flow_ollama(caller)

    assert saved[-1]["model"]["provider"] == "ollama"
    assert saved[-1]["model"]["base_url"] == "http://192.168.50.20:11434"
    assert saved[-1]["security"]["egress_mode"] == "online"
    assert "approve its narrow private CIDR" in capsys.readouterr().out


def test_provider_picker_dispatches_ollama_to_native_flow(monkeypatch) -> None:
    import fabric_cli.main as main_mod

    called: list[tuple[dict, str]] = []
    monkeypatch.setattr(
        "fabric_cli.auth.resolve_provider", lambda *_args, **_kwargs: None
    )

    def choose_ollama(choices, default=0, **_kwargs):
        del default
        return next(
            index
            for index, label in enumerate(choices)
            if label.startswith("Ollama (") and "native /api/chat" in label
        )

    monkeypatch.setattr(main_mod, "_prompt_provider_choice", choose_ollama)
    monkeypatch.setattr(
        main_mod,
        "_model_flow_ollama",
        lambda config, current_model="": called.append((config, current_model)),
    )

    main_mod.select_provider_and_model()

    assert len(called) == 1
