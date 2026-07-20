"""Tests for Anthropic credential persistence helpers.

Fabric authenticates to native Anthropic with an API key only — there is no
OAuth/subscription token slot or Claude Code credential handoff (see NOTICE).
"""

import json

import pytest

from fabric_cli.config import load_env


def test_save_anthropic_api_key_clears_fabric_oauth_slot_only(tmp_path, monkeypatch):
    home = tmp_path / "fabric"
    home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(home))
    (home / ".env").write_text(
        "ANTHROPIC_TOKEN=stale-fabric-oauth\n"
        "CLAUDE_CODE_OAUTH_TOKEN=claude-code-owned\n",
        encoding="utf-8",
    )

    from fabric_cli.config import save_anthropic_api_key

    save_anthropic_api_key("sk-ant-api03-key")

    env_vars = load_env()
    assert env_vars["ANTHROPIC_API_KEY"] == "sk-ant-api03-key"
    assert env_vars["ANTHROPIC_TOKEN"] == ""
    assert env_vars["CLAUDE_CODE_OAUTH_TOKEN"] == "claude-code-owned"


def test_save_anthropic_api_key_custom_writer_receives_cleanup(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path / "fabric"))
    from fabric_cli.config import save_anthropic_api_key

    writes = []
    save_anthropic_api_key(
        "sk-ant-api03-key",
        save_fn=lambda key, value: writes.append((key, value)),
    )

    assert writes == [
        ("ANTHROPIC_API_KEY", "sk-ant-api03-key"),
        ("ANTHROPIC_TOKEN", ""),
    ]


def test_save_anthropic_api_key_rejects_oauth_shape_before_writing(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path / "fabric"))
    from fabric_cli.config import save_anthropic_api_key

    writes = []
    with pytest.raises(ValueError, match="cannot be used as API keys"):
        save_anthropic_api_key(
            "sk-ant-oat01-retired-token",
            save_fn=lambda key, value: writes.append((key, value)),
        )

    assert writes == []


def test_save_anthropic_api_key_accepts_jwt_for_configured_third_party(
    tmp_path, monkeypatch
):
    home = tmp_path / "fabric"
    home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(home))
    (home / ".env").write_text(
        "ANTHROPIC_BASE_URL=https://gateway.example/anthropic\n",
        encoding="utf-8",
    )

    from fabric_cli.config import save_anthropic_api_key

    save_anthropic_api_key("eyJ.proxy.signature")

    env_vars = load_env()
    assert env_vars["ANTHROPIC_API_KEY"] == "eyJ.proxy.signature"
    assert env_vars["ANTHROPIC_BASE_URL"] == "https://gateway.example/anthropic"


def test_stale_model_base_url_does_not_authorize_jwt_or_doctor_route(
    tmp_path, monkeypatch
):
    home = tmp_path / "fabric"
    home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(home))
    (home / ".env").write_text(
        "ANTHROPIC_API_KEY=eyJ.proxy.signature\n",
        encoding="utf-8",
    )
    (home / "config.yaml").write_text(
        "model:\n"
        "  provider: anthropic\n"
        "  base_url: https://openrouter.ai/api/v1\n",
        encoding="utf-8",
    )

    from fabric_cli.auth import get_api_key_provider_status
    from fabric_cli.config import _configured_anthropic_api_key_base_url

    assert _configured_anthropic_api_key_base_url() == "https://api.anthropic.com"
    status = get_api_key_provider_status("anthropic")
    assert status["configured"] is False
    assert status["base_url"] == "https://api.anthropic.com"


def test_model_reauth_replaces_selected_pool_key(tmp_path, monkeypatch):
    """Re-auth must update the higher-priority source runtime will select."""
    home = tmp_path / "fabric"
    home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(home))
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    (home / ".env").write_text(
        "ANTHROPIC_API_KEY=sk-ant-api03-env-current\n",
        encoding="utf-8",
    )

    from fabric_cli.auth import read_credential_pool, write_credential_pool

    write_credential_pool(
        "anthropic",
        [
            {
                "id": "manual-old",
                "label": "work key",
                "auth_type": "api_key",
                "priority": 0,
                "source": "manual",
                "access_token": "sk-ant-api03-old",
                "last_status": "exhausted",
                "last_error_code": 401,
                "request_count": 7,
            }
        ],
    )
    monkeypatch.setattr(
        "fabric_cli.model_setup_flows._prompt_auth_credentials_choice",
        lambda _prompt, **_kwargs: "reauth",
    )
    monkeypatch.setattr(
        "fabric_cli.secret_prompt.masked_secret_prompt",
        lambda _prompt: "sk-ant-api03-new",
    )
    monkeypatch.setattr(
        "fabric_cli.auth._prompt_model_selection",
        lambda *_args, **_kwargs: None,
    )

    from fabric_cli.model_setup_flows import _model_flow_anthropic

    _model_flow_anthropic({}, current_model="")

    entries = read_credential_pool("anthropic")
    assert len(entries) == 1
    assert entries[0]["access_token"] == "sk-ant-api03-new"
    assert entries[0]["request_count"] == 0
    assert entries[0].get("last_status") is None
    assert entries[0].get("last_error_code") is None
    assert load_env()["ANTHROPIC_API_KEY"] == "sk-ant-api03-env-current"

    from fabric_cli.runtime_provider import resolve_runtime_provider

    runtime = resolve_runtime_provider(requested="anthropic")
    assert runtime["api_key"] == "sk-ant-api03-new"
    assert runtime["source"] == "manual"


def test_model_reauth_native_key_preserves_proxy_pool_tuple(
    tmp_path, monkeypatch
):
    """A Console key must never inherit an existing proxy pool endpoint."""
    home = tmp_path / "fabric"
    home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(home))
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    (home / "config.yaml").write_text(
        "model:\n"
        "  provider: anthropic\n"
        "  base_url: https://gateway.example/anthropic\n",
        encoding="utf-8",
    )

    from fabric_cli.auth import read_credential_pool, write_credential_pool

    proxy_entry = {
        "id": "proxy-key",
        "label": "gateway key",
        "auth_type": "api_key",
        "priority": 0,
        "source": "manual",
        "access_token": "eyJ.proxy.signature",
        "base_url": "https://gateway.example/anthropic",
        "request_count": 4,
    }
    write_credential_pool("anthropic", [proxy_entry])
    monkeypatch.setattr(
        "fabric_cli.model_setup_flows._prompt_auth_credentials_choice",
        lambda _prompt, **kwargs: (
            "reauth"
            if kwargs["reauth_label"] == "Add native Anthropic API key"
            else "cancel"
        ),
    )
    monkeypatch.setattr(
        "fabric_cli.secret_prompt.masked_secret_prompt",
        lambda _prompt: "sk-ant-api03-native-new",
    )
    monkeypatch.setattr(
        "fabric_cli.auth._prompt_model_selection",
        lambda *_args, **_kwargs: None,
    )

    from fabric_cli.config import load_config, save_config
    from fabric_cli.model_setup_flows import _model_flow_anthropic

    _model_flow_anthropic(load_config(), current_model="")

    # The existing third-party tuple is preserved byte-for-byte instead of
    # receiving the native Anthropic secret.
    assert read_credential_pool("anthropic") == [proxy_entry]
    env = load_env()
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-api03-native-new"
    assert env.get("ANTHROPIC_BASE_URL", "") == ""
    model = load_config()["model"]
    assert model["provider"] == "anthropic"
    assert model["base_url"] == "https://api.anthropic.com"

    # Native is a default, not a permanent env override. A later explicit
    # Azure route must therefore become authoritative without asking the user
    # to discover and clear a hidden ANTHROPIC_BASE_URL first.
    azure_url = "https://later.services.ai.azure.com/anthropic"
    updated = load_config()
    updated["model"]["base_url"] = azure_url
    save_config(updated)
    monkeypatch.setenv("AZURE_ANTHROPIC_KEY", "later-azure-key")

    from fabric_cli.runtime_provider import resolve_runtime_provider

    runtime = resolve_runtime_provider(requested="anthropic")
    assert runtime["base_url"] == azure_url
    assert runtime["api_key"] == "later-azure-key"


def test_model_reauth_native_key_snapshots_explicit_env_proxy_tuple(
    tmp_path, monkeypatch
):
    """Replacing the env slot must not destroy its old proxy credential."""
    home = tmp_path / "fabric"
    home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(home))
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    proxy_url = "https://gateway.example/anthropic"
    proxy_key = "eyJ.proxy.signature"
    (home / ".env").write_text(
        f"ANTHROPIC_API_KEY={proxy_key}\n"
        f"ANTHROPIC_BASE_URL={proxy_url}\n",
        encoding="utf-8",
    )
    (home / "config.yaml").write_text(
        "model:\n"
        "  provider: anthropic\n"
        f"  base_url: {proxy_url}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "fabric_cli.model_setup_flows._prompt_auth_credentials_choice",
        lambda _prompt, **kwargs: (
            "reauth"
            if kwargs["reauth_label"] == "Add native Anthropic API key"
            else "cancel"
        ),
    )
    monkeypatch.setattr(
        "fabric_cli.secret_prompt.masked_secret_prompt",
        lambda _prompt: "sk-ant-api03-native-new",
    )
    monkeypatch.setattr(
        "fabric_cli.auth._prompt_model_selection",
        lambda *_args, **_kwargs: None,
    )

    from fabric_cli.auth import read_credential_pool
    from fabric_cli.config import load_config, save_config
    from fabric_cli.model_setup_flows import _model_flow_anthropic

    _model_flow_anthropic(load_config(), current_model="")

    manual_proxy_rows = [
        entry
        for entry in read_credential_pool("anthropic")
        if str(entry.get("source") or "").startswith("manual")
        and entry.get("access_token") == proxy_key
        and entry.get("base_url") == proxy_url
    ]
    assert len(manual_proxy_rows) == 1
    env = load_env()
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-api03-native-new"
    assert env.get("ANTHROPIC_BASE_URL", "") == ""

    # Selecting the old endpoint later resolves the preserved tuple, not the
    # new native env key.
    updated = load_config()
    updated["model"]["base_url"] = proxy_url
    save_config(updated)

    from fabric_cli.runtime_provider import resolve_runtime_provider

    runtime = resolve_runtime_provider(requested="anthropic")
    assert runtime["base_url"] == proxy_url
    assert runtime["api_key"] == proxy_key


def test_model_reauth_deduplicates_explicit_env_proxy_snapshot(
    tmp_path, monkeypatch
):
    home = tmp_path / "fabric"
    home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(home))
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    proxy_url = "https://gateway.example/anthropic"
    proxy_key = "eyJ.proxy.signature"
    (home / ".env").write_text(
        f"ANTHROPIC_API_KEY={proxy_key}\n"
        f"ANTHROPIC_BASE_URL={proxy_url}\n",
        encoding="utf-8",
    )
    (home / "config.yaml").write_text(
        "model:\n"
        "  provider: anthropic\n"
        f"  base_url: {proxy_url}\n",
        encoding="utf-8",
    )

    from fabric_cli.auth import read_credential_pool, write_credential_pool

    write_credential_pool(
        "anthropic",
        [{
            "id": "already-preserved",
            "label": "proxy",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": proxy_key,
            "base_url": f"{proxy_url}/v1",
        }],
    )
    monkeypatch.setattr(
        "fabric_cli.model_setup_flows._prompt_auth_credentials_choice",
        lambda _prompt, **kwargs: (
            "reauth"
            if kwargs["reauth_label"] == "Add native Anthropic API key"
            else "cancel"
        ),
    )
    monkeypatch.setattr(
        "fabric_cli.secret_prompt.masked_secret_prompt",
        lambda _prompt: "sk-ant-api03-native-new",
    )
    monkeypatch.setattr(
        "fabric_cli.auth._prompt_model_selection",
        lambda *_args, **_kwargs: None,
    )

    from fabric_cli.config import load_config
    from fabric_cli.model_setup_flows import _model_flow_anthropic

    _model_flow_anthropic(load_config(), current_model="")

    matching_manual_rows = [
        entry
        for entry in read_credential_pool("anthropic")
        if str(entry.get("source") or "").startswith("manual")
        and entry.get("access_token") == proxy_key
    ]
    assert len(matching_manual_rows) == 1
    assert matching_manual_rows[0]["id"] == "already-preserved"


def test_pool_replacement_backfills_configured_proxy_endpoint(
    tmp_path, monkeypatch
):
    home = tmp_path / "fabric"
    home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(home))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (home / "config.yaml").write_text(
        "model:\n"
        "  provider: anthropic\n"
        "  base_url: https://gateway.example/anthropic\n",
        encoding="utf-8",
    )

    from fabric_cli.auth import (
        _replace_anthropic_pooled_api_key,
        read_credential_pool,
        write_credential_pool,
    )

    write_credential_pool(
        "anthropic",
        [{
            "id": "legacy-proxy",
            "label": "proxy",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "eyJ.old.proxy",
        }],
    )

    assert _replace_anthropic_pooled_api_key(
        "eyJ.old.proxy",
        "eyJ.new.proxy",
    )
    entry = read_credential_pool("anthropic")[0]
    assert entry["access_token"] == "eyJ.new.proxy"
    assert entry["base_url"] == "https://gateway.example/anthropic"


def test_pool_replacement_matches_key_and_endpoint_when_tokens_duplicate(
    tmp_path, monkeypatch
):
    home = tmp_path / "fabric"
    home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(home))

    from fabric_cli.auth import (
        _replace_anthropic_pooled_api_key,
        read_credential_pool,
        write_credential_pool,
    )

    shared_key = "sk-ant-api03-shared-old"
    write_credential_pool(
        "anthropic",
        [
            {
                "id": "proxy",
                "label": "proxy",
                "auth_type": "api_key",
                "priority": 0,
                "source": "manual",
                "access_token": shared_key,
                "base_url": "https://gateway.example/anthropic",
            },
            {
                "id": "native",
                "label": "native",
                "auth_type": "api_key",
                "priority": 1,
                "source": "manual",
                "access_token": shared_key,
                "base_url": "https://api.anthropic.com/v1",
            },
        ],
    )

    assert _replace_anthropic_pooled_api_key(
        shared_key,
        "sk-ant-api03-native-new",
        current_base_url="HTTPS://API.ANTHROPIC.COM",
    )

    entries = {entry["id"]: entry for entry in read_credential_pool("anthropic")}
    assert entries["proxy"]["access_token"] == shared_key
    assert entries["native"]["access_token"] == "sk-ant-api03-native-new"


def test_model_flow_defers_rotating_pool_changes_to_auth_commands(
    tmp_path, monkeypatch, capsys
):
    """A generic replace prompt cannot identify the next rotating pool row."""
    home = tmp_path / "fabric"
    home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(home))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (home / "config.yaml").write_text(
        "credential_pool_strategies:\n  anthropic: least_used\n",
        encoding="utf-8",
    )

    from fabric_cli.auth import read_credential_pool, write_credential_pool

    original = [
        {
            "id": "busy",
            "label": "busy key",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-ant-api03-busy",
            "request_count": 99,
        },
        {
            "id": "quiet",
            "label": "quiet key",
            "auth_type": "api_key",
            "priority": 1,
            "source": "manual",
            "access_token": "sk-ant-api03-quiet",
            "request_count": 0,
        },
    ]
    write_credential_pool("anthropic", original)
    monkeypatch.setattr(
        "fabric_cli.model_setup_flows._prompt_auth_credentials_choice",
        lambda _prompt, **kwargs: (
            "reauth" if kwargs["reauth_label"] == "Manage pooled API keys" else "cancel"
        ),
    )
    monkeypatch.setattr(
        "fabric_cli.secret_prompt.masked_secret_prompt",
        lambda _prompt: pytest.fail("rotating pools must not use generic replacement"),
    )

    from fabric_cli.model_setup_flows import _model_flow_anthropic

    _model_flow_anthropic({}, current_model="")

    assert "least_used" in capsys.readouterr().out
    assert read_credential_pool("anthropic") == original


def test_model_flow_rejects_oauth_shaped_api_key(tmp_path, monkeypatch, capsys):
    home = tmp_path / "fabric"
    home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(home))
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "fabric_cli.secret_prompt.masked_secret_prompt",
        lambda _prompt: "sk-ant-oat01-retired-token",
    )

    from fabric_cli.model_setup_flows import _model_flow_anthropic

    _model_flow_anthropic({}, current_model="")

    assert "cannot be used as API keys" in capsys.readouterr().out
    assert not load_env().get("ANTHROPIC_API_KEY")


def test_model_flow_preserves_third_party_endpoint_required_by_jwt(
    tmp_path, monkeypatch
):
    home = tmp_path / "fabric"
    home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(home))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (home / ".env").write_text(
        "ANTHROPIC_API_KEY=eyJ.proxy.signature\n"
        "ANTHROPIC_BASE_URL=https://gateway.example/anthropic\n",
        encoding="utf-8",
    )
    (home / "config.yaml").write_text(
        "model:\n"
        "  provider: anthropic\n"
        "  default: claude-sonnet-4-6\n"
        "  base_url: https://gateway.example/anthropic\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "fabric_cli.model_setup_flows._prompt_auth_credentials_choice",
        lambda *_args, **_kwargs: "use",
    )
    monkeypatch.setattr(
        "fabric_cli.auth._prompt_model_selection",
        lambda *_args, **_kwargs: "claude-sonnet-4-6",
    )

    from fabric_cli.config import load_config
    from fabric_cli.model_setup_flows import _model_flow_anthropic
    from fabric_cli.runtime_provider import resolve_runtime_provider

    _model_flow_anthropic(load_config(), current_model="claude-sonnet-4-6")

    assert (
        load_config()["model"]["base_url"]
        == "https://gateway.example/anthropic"
    )
    runtime = resolve_runtime_provider(requested="anthropic")
    assert runtime["api_key"] == "eyJ.proxy.signature"
    assert runtime["base_url"] == "https://gateway.example/anthropic"


def test_model_flow_clears_stale_azure_openai_endpoint(tmp_path, monkeypatch):
    home = tmp_path / "fabric"
    home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(home))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-valid")
    (home / "config.yaml").write_text(
        "model:\n"
        "  provider: azure-foundry\n"
        "  default: old-model\n"
        "  base_url: https://demo.openai.azure.com/openai/v1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "fabric_cli.model_setup_flows._prompt_auth_credentials_choice",
        lambda *_args, **_kwargs: "use",
    )
    monkeypatch.setattr(
        "fabric_cli.auth._prompt_model_selection",
        lambda *_args, **_kwargs: "claude-sonnet-4-6",
    )

    from fabric_cli.config import load_config
    from fabric_cli.model_setup_flows import _model_flow_anthropic

    _model_flow_anthropic(load_config(), current_model="old-model")

    model = load_config()["model"]
    assert model["provider"] == "anthropic"
    assert "base_url" not in model
