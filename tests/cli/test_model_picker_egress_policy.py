"""Classic CLI model picker and switch must enter policy first."""

from __future__ import annotations

from types import SimpleNamespace

from cli import FabricCLI


def _strict_local():
    return {
        "security": {
            "egress_mode": "local_ai",
            "local_ai_allowed_cidrs": [],
        },
        "model": {
            "provider": "custom",
            "default": "local-model",
            "base_url": "http://localhost:11434/v1",
        },
        "providers": {
            "localbox": {
                "name": "Local Box",
                "api": "http://127.0.0.1:8000/v1",
                "models": ["local-a"],
            }
        },
        "custom_providers": [],
    }


def _bomb(label):
    def fail(*_args, **_kwargs):
        raise AssertionError(f"{label} must not run before restricted policy")

    return fail


def _cli(**overrides):
    values = {
        "provider": "custom",
        "model": "local-model",
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key": "",
        "agent": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_typed_restricted_switch_rejects_before_expansion_or_discovery(
    monkeypatch,
):
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config", lambda: _strict_local()
    )
    monkeypatch.setattr("fabric_cli.config.load_config", _bomb("expanded config"))
    monkeypatch.setattr(
        "fabric_cli.model_switch.resolve_provider_full",
        _bomb("provider metadata"),
    )
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        _bomb("credential resolution"),
    )
    output = []
    monkeypatch.setattr("cli._cprint", lambda value="": output.append(str(value)))

    FabricCLI._handle_model_switch(
        _cli(),
        "/model remote-model --provider openrouter --session",
    )

    assert any("egress_policy:remote_ai_forbidden" in line for line in output)


def test_restricted_cli_picker_renders_only_configured_local_rows(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config", lambda: _strict_local()
    )
    monkeypatch.setattr("fabric_cli.config.load_config", _bomb("expanded config"))
    monkeypatch.setattr(
        "fabric_cli.model_switch.list_authenticated_providers",
        _bomb("provider discovery"),
    )
    monkeypatch.setattr(
        "fabric_cli.providers.get_label",
        _bomb("provider label metadata"),
    )
    captured = []
    cli = _cli(
        _open_model_picker=lambda providers, *_args, **_kwargs: captured.extend(
            providers
        )
    )

    FabricCLI._handle_model_switch(cli, "/model")

    assert [row["slug"] for row in captured] == [
        "custom",
        "custom:localbox",
    ]
