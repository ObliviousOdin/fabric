"""Tests for setup.py configuration flows."""
import sys
import types
from types import SimpleNamespace

import pytest


from fabric_cli.config import load_config, save_config
from fabric_cli.fallback_config import get_fallback_chain
from fabric_cli import setup as setup_mod
from fabric_cli.setup import setup_model_provider


def _maybe_keep_current_tts(question, choices):
    if question != "Select TTS provider:":
        return None
    assert choices[-1].startswith("Keep current (")
    return len(choices) - 1


def _clear_provider_env(monkeypatch):
    for key in (
        "NOUS_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "LLM_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


def _stub_tts(monkeypatch):
    """Stub out TTS prompts so setup_model_provider doesn't block."""
    monkeypatch.setattr("fabric_cli.setup.prompt_choice", lambda q, c, d=0: (
        _maybe_keep_current_tts(q, c) if _maybe_keep_current_tts(q, c) is not None
        else d
    ))
    monkeypatch.setattr("fabric_cli.setup.prompt_yes_no", lambda *a, **kw: False)


def _write_model_config(tmp_path, provider, base_url="", model_name="test-model"):
    """Simulate what a _model_flow_* function writes to disk."""
    cfg = load_config()
    m = cfg.get("model")
    if not isinstance(m, dict):
        m = {"default": m} if m else {}
        cfg["model"] = m
    m["provider"] = provider
    if base_url:
        m["base_url"] = base_url
    if model_name:
        m["default"] = model_name
    save_config(cfg)


def test_first_time_setup_is_fabric_branded_and_offers_gpt_or_grok(
    tmp_path, monkeypatch, capsys
):
    """The default setup front door must not advertise upstream Nous services."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    monkeypatch.setattr(setup_mod, "is_interactive_stdin", lambda: True)
    monkeypatch.setattr("fabric_cli.auth.get_active_provider", lambda: None)
    monkeypatch.setattr(setup_mod, "_offer_openclaw_migration", lambda home: False)

    captured = {}

    class StopSetup(Exception):
        pass

    def capture_mode(question, choices, default=0):
        captured["question"] = question
        captured["choices"] = choices
        captured["default"] = default
        raise StopSetup

    monkeypatch.setattr(setup_mod, "prompt_choice", capture_mode)

    with pytest.raises(StopSetup):
        setup_mod.run_setup_wizard(SimpleNamespace())

    output = capsys.readouterr().out
    rendered = "\n".join([output, captured["question"], *captured["choices"]])

    assert "Fabric Setup Wizard" in output
    assert captured["question"] == "How would you like to set up Fabric?"
    assert any("ChatGPT, Grok, or both" in choice for choice in captured["choices"])
    assert captured["default"] == 0
    assert "Nous" not in rendered
    assert "⚕" not in rendered
    assert "nousresearch" not in rendered.lower()
    assert setup_mod._DOCS_BASE == "https://obliviousodin.github.io/fabric"


def test_completed_default_guided_setup_transcript_is_customer_clean(
    tmp_path, monkeypatch, capsys
):
    """Exercise the complete default wizard, not just its opening picker."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    monkeypatch.setattr("fabric_cli.config.is_managed", lambda: False)
    monkeypatch.setattr(setup_mod, "is_interactive_stdin", lambda: True)
    monkeypatch.setattr("fabric_cli.auth.get_active_provider", lambda: None)
    monkeypatch.setattr(setup_mod, "_offer_openclaw_migration", lambda _home: False)
    monkeypatch.setattr(setup_mod, "prompt_choice", lambda *_a, **_k: 0)
    monkeypatch.setattr(setup_mod, "prompt_yes_no", lambda *_a, **_k: False)
    monkeypatch.setattr(setup_mod, "prompt_checklist", lambda *_a, **_k: [])

    def leave_model_unchanged(choices, default=0, **_kwargs):
        return next(
            index
            for index, label in enumerate(choices)
            if "Leave unchanged" in label
        )

    monkeypatch.setattr(
        "fabric_cli.main._prompt_provider_choice",
        leave_model_unchanged,
    )
    monkeypatch.setattr(
        "fabric_cli.tools_config._prompt_toolset_checklist",
        lambda *_a, **_k: set(),
    )

    setup_mod.run_setup_wizard(SimpleNamespace())

    rendered = capsys.readouterr().out
    assert "Tool Availability Summary" in rendered
    assert "Fabric Setup Wizard" in rendered
    assert "Nous" not in rendered
    assert "⚕" not in rendered
    assert "nousresearch" not in rendered.lower()
    assert "OpenRouter" not in rendered
    assert "Anthropic" not in rendered


def test_guided_setup_connects_chatgpt_then_grok_as_fallback(
    tmp_path, monkeypatch
):
    """Both subscription logins run once and preserve the chosen primary."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    config = load_config()
    calls = []
    active = []

    monkeypatch.setattr(setup_mod, "prompt_checklist", lambda *_a, **_k: [0, 1])
    monkeypatch.setattr(setup_mod, "prompt_choice", lambda *_a, **_k: 0)
    monkeypatch.setattr(
        "fabric_cli.auth.get_codex_auth_status",
        lambda: {"logged_in": False},
    )
    monkeypatch.setattr(
        "fabric_cli.auth.get_xai_oauth_auth_status",
        lambda: {"logged_in": False},
    )

    def connect_chatgpt(_config, _current_model=""):
        calls.append("openai-codex")
        _write_model_config(
            tmp_path,
            "openai-codex",
            "https://chatgpt.example/v1",
            "gpt-5.4",
        )

    def connect_grok(_config, _current_model="", *, args=None):
        assert args is None
        calls.append("xai-oauth")
        _write_model_config(
            tmp_path,
            "xai-oauth",
            "https://grok.example/v1",
            "grok-4.1",
        )

    monkeypatch.setattr(
        "fabric_cli.main._model_flow_openai_codex",
        connect_chatgpt,
    )
    monkeypatch.setattr("fabric_cli.main._model_flow_xai_oauth", connect_grok)
    monkeypatch.setattr(
        "fabric_cli.fallback_cmd._restore_auth_active_provider",
        active.append,
    )

    setup_mod._setup_guided_subscription_models(config)

    reloaded = load_config()
    assert calls == ["openai-codex", "xai-oauth"]
    assert active == ["openai-codex"]
    assert reloaded["model"]["provider"] == "openai-codex"
    assert reloaded["model"]["default"] == "gpt-5.4"
    assert get_fallback_chain(reloaded) == [
        {
            "provider": "xai-oauth",
            "model": "grok-4.1",
            "base_url": "https://grok.example/v1",
        }
    ]
    assert config == reloaded


def test_guided_setup_can_make_grok_primary_and_chatgpt_fallback(
    tmp_path, monkeypatch
):
    """Primary selection controls sign-in order and the persisted route order."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    config = load_config()
    calls = []

    monkeypatch.setattr(setup_mod, "prompt_checklist", lambda *_a, **_k: [0, 1])
    monkeypatch.setattr(setup_mod, "prompt_choice", lambda *_a, **_k: 1)
    monkeypatch.setattr(
        "fabric_cli.auth.get_codex_auth_status",
        lambda: {"logged_in": False},
    )
    monkeypatch.setattr(
        "fabric_cli.auth.get_xai_oauth_auth_status",
        lambda: {"logged_in": False},
    )

    def connect_chatgpt(_config, _current_model=""):
        calls.append("openai-codex")
        _write_model_config(tmp_path, "openai-codex", model_name="gpt-5.4")

    def connect_grok(_config, _current_model="", *, args=None):
        calls.append("xai-oauth")
        _write_model_config(tmp_path, "xai-oauth", model_name="grok-4.1")

    monkeypatch.setattr(
        "fabric_cli.main._model_flow_openai_codex",
        connect_chatgpt,
    )
    monkeypatch.setattr("fabric_cli.main._model_flow_xai_oauth", connect_grok)
    monkeypatch.setattr(
        "fabric_cli.fallback_cmd._restore_auth_active_provider",
        lambda _provider: None,
    )

    setup_mod._setup_guided_subscription_models(config)

    reloaded = load_config()
    assert calls == ["xai-oauth", "openai-codex"]
    assert reloaded["model"]["provider"] == "xai-oauth"
    assert get_fallback_chain(reloaded)[0]["provider"] == "openai-codex"


def test_full_setup_defers_gateway_service_until_after_tools(
    tmp_path, monkeypatch
):
    """Platforms are known to tools, but service restart happens afterward."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    monkeypatch.setattr(setup_mod, "is_interactive_stdin", lambda: True)
    monkeypatch.setattr("fabric_cli.auth.get_active_provider", lambda: None)
    monkeypatch.setattr(setup_mod, "_offer_openclaw_migration", lambda _home: False)
    monkeypatch.setattr(setup_mod, "prompt_choice", lambda *_a, **_k: 1)
    monkeypatch.setattr(setup_mod, "prompt_yes_no", lambda *_a, **_k: False)
    monkeypatch.setattr(setup_mod, "_print_setup_summary", lambda *_a, **_k: None)

    calls = []
    monkeypatch.setattr(
        setup_mod,
        "setup_model_provider",
        lambda _config, **_kwargs: calls.append("model"),
    )
    monkeypatch.setattr(
        setup_mod,
        "setup_terminal_backend",
        lambda _config: calls.append("terminal"),
    )
    monkeypatch.setattr(
        setup_mod,
        "_apply_default_agent_settings",
        lambda _config: calls.append("agent"),
    )
    monkeypatch.setattr(
        setup_mod,
        "setup_tools",
        lambda _config, **_kwargs: calls.append("tools"),
    )

    def setup_gateway(_config, **kwargs):
        if kwargs.get("defer_service_setup"):
            calls.append("gateway-platforms")
            return True
        if kwargs.get("service_only"):
            calls.append("gateway-service")
            return True
        calls.append("gateway")
        return True

    monkeypatch.setattr(setup_mod, "setup_gateway", setup_gateway)

    setup_mod.run_setup_wizard(SimpleNamespace())

    assert calls.index("gateway-platforms") < calls.index("tools")
    assert calls.index("tools") < calls.index("gateway-service")
    assert "gateway" not in calls


def test_quick_setup_tool_labels_do_not_expose_upstream_branding(
    tmp_path, monkeypatch
):
    from fabric_cli.config import OPTIONAL_ENV_VARS

    gateway_keys = (
        "FIRECRAWL_GATEWAY_URL",
        "TOOL_GATEWAY_DOMAIN",
        "TOOL_GATEWAY_SCHEME",
        "TOOL_GATEWAY_USER_TOKEN",
    )
    missing = [
        {"name": key, **OPTIONAL_ENV_VARS[key], "is_required": False}
        for key in gateway_keys
    ]
    captured = []

    monkeypatch.setattr(
        "fabric_cli.config.get_missing_env_vars", lambda **kwargs: missing
    )
    monkeypatch.setattr("fabric_cli.config.get_missing_config_fields", lambda: [])
    monkeypatch.setattr("fabric_cli.config.check_config_version", lambda: (1, 1))

    def capture_checklist(question, choices):
        captured.extend(choices)
        return []

    monkeypatch.setattr(setup_mod, "prompt_checklist", capture_checklist)

    setup_mod._run_quick_setup({}, tmp_path)

    rendered = "\n".join(captured)
    assert "Nous" not in rendered
    assert "nousresearch" not in rendered.lower()


def test_setup_portal_namespace_is_blocked_when_provider_is_hidden(
    tmp_path, monkeypatch, capsys
):
    """A direct Namespace cannot bypass the parser-level capability gate."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {},
    )
    monkeypatch.setattr("fabric_cli.config.is_managed", lambda: False)
    monkeypatch.setattr(setup_mod, "is_interactive_stdin", lambda: True)

    calls = []
    monkeypatch.setattr(setup_mod, "_run_portal_one_shot", calls.append)

    setup_mod.run_setup_wizard(SimpleNamespace(portal=True))

    assert calls == []
    assert "Nous Portal setup is not enabled" in capsys.readouterr().out


@pytest.mark.parametrize(
    "capabilities",
    [
        {"model_providers": ["nous"]},
        {"enabled": False},
    ],
)
def test_setup_portal_namespace_dispatches_under_explicit_nous_opt_in(
    tmp_path, monkeypatch, capabilities
):
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: capabilities,
    )
    monkeypatch.setattr("fabric_cli.config.is_managed", lambda: False)
    monkeypatch.setattr(setup_mod, "is_interactive_stdin", lambda: True)

    calls = []

    def _capture_portal(config, *, args=None):
        calls.append((config, args))

    monkeypatch.setattr(setup_mod, "_run_portal_one_shot", _capture_portal)

    args = SimpleNamespace(
        portal=True,
        client_id="registered-nous-client",
    )
    setup_mod.run_setup_wizard(args)

    assert len(calls) == 1
    assert isinstance(calls[0][0], dict)
    assert calls[0][1] is args


def test_webhook_setup_points_to_fabric_docs(monkeypatch, capsys):
    monkeypatch.setattr(setup_mod, "get_env_value", lambda _key: None)
    monkeypatch.setattr(setup_mod, "save_env_value", lambda *_args: None)
    monkeypatch.setattr(setup_mod, "prompt", lambda *_args, **_kwargs: "")

    setup_mod._setup_webhooks()

    output = capsys.readouterr().out
    assert "https://obliviousodin.github.io/fabric" in output
    assert "nousresearch" not in output.lower()
    assert output.count("Open config in your editor:  fabric config edit") == 1


def test_setup_delegates_to_select_provider_and_model(tmp_path, monkeypatch):
    """setup_model_provider calls select_provider_and_model and syncs config."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    config = load_config()

    def fake_select():
        _write_model_config(tmp_path, "custom", "http://localhost:11434/v1", "qwen3.5:32b")

    monkeypatch.setattr("fabric_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)
    save_config(config)

    reloaded = load_config()
    assert isinstance(reloaded["model"], dict)
    assert reloaded["model"]["provider"] == "custom"
    assert reloaded["model"]["base_url"] == "http://localhost:11434/v1"
    assert reloaded["model"]["default"] == "qwen3.5:32b"


def test_setup_syncs_openrouter_from_disk(tmp_path, monkeypatch):
    """When select_provider_and_model saves OpenRouter config to disk,
    the wizard's config dict picks it up."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    config = load_config()
    assert isinstance(config.get("model"), str)  # fresh install

    def fake_select():
        _write_model_config(tmp_path, "openrouter", model_name="anthropic/claude-opus-4.6")

    monkeypatch.setattr("fabric_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)
    save_config(config)

    reloaded = load_config()
    assert isinstance(reloaded["model"], dict)
    assert reloaded["model"]["provider"] == "openrouter"


def test_setup_syncs_nous_from_disk(tmp_path, monkeypatch):
    """Nous OAuth writes config to disk; wizard config dict must pick it up."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    config = load_config()

    def fake_select():
        _write_model_config(tmp_path, "nous", "https://inference.example.com/v1", "gemini-3-flash")

    monkeypatch.setattr("fabric_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)
    save_config(config)

    reloaded = load_config()
    assert isinstance(reloaded["model"], dict)
    assert reloaded["model"]["provider"] == "nous"
    assert reloaded["model"]["base_url"] == "https://inference.example.com/v1"


def test_setup_custom_providers_synced(tmp_path, monkeypatch):
    """custom_providers written by select_provider_and_model must survive."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    config = load_config()

    def fake_select():
        _write_model_config(tmp_path, "custom", "http://localhost:8080/v1", "llama3")
        cfg = load_config()
        cfg["custom_providers"] = [{"name": "Local", "base_url": "http://localhost:8080/v1"}]
        save_config(cfg)

    monkeypatch.setattr("fabric_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)
    save_config(config)

    reloaded = load_config()
    assert reloaded.get("custom_providers") == [{"name": "Local", "base_url": "http://localhost:8080/v1"}]


def test_setup_gateway_can_defer_service_restart(monkeypatch):
    """Platform credentials are configured without touching service lifecycle."""
    import fabric_cli.gateway as gateway_mod

    platform = {"emoji": "💬", "label": "Test", "key": "test"}
    configured = []
    monkeypatch.setattr(gateway_mod, "_all_platforms", lambda: [platform])
    monkeypatch.setattr(gateway_mod, "_platform_status", lambda _platform: "configured")
    monkeypatch.setattr(
        gateway_mod,
        "_configure_platform",
        lambda selected: configured.append(selected["key"]),
    )
    monkeypatch.setattr(setup_mod, "prompt_checklist", lambda *_a, **_k: [0])
    monkeypatch.setattr(
        setup_mod,
        "prompt_yes_no",
        lambda *_a, **_k: pytest.fail("service prompt must be deferred"),
    )

    result = setup_mod.setup_gateway({}, defer_service_setup=True)

    assert result is True
    assert configured == ["test"]


def test_setup_gateway_skips_service_install_when_systemctl_missing(monkeypatch, capsys):
    env = {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_HOME_CHANNEL": "",
        "DISCORD_BOT_TOKEN": "",
        "DISCORD_HOME_CHANNEL": "",
        "SLACK_BOT_TOKEN": "",
        "SLACK_HOME_CHANNEL": "",
        "MATRIX_HOMESERVER": "https://matrix.example.com",
        "MATRIX_USER_ID": "@alice:example.com",
        "MATRIX_PASSWORD": "",
        "MATRIX_ACCESS_TOKEN": "token",
        "BLUEBUBBLES_SERVER_URL": "",
        "BLUEBUBBLES_HOME_CHANNEL": "",
        "WHATSAPP_ENABLED": "",
        "WEBHOOK_ENABLED": "",
    }

    import fabric_cli.gateway as gateway_mod

    monkeypatch.setattr(setup_mod, "get_env_value", lambda key: env.get(key, ""))
    monkeypatch.setattr(gateway_mod, "get_env_value", lambda key: env.get(key, ""))
    monkeypatch.setattr(setup_mod, "prompt_yes_no", lambda *args, **kwargs: False)
    # Keep the checklist pre-selection (so matrix stays "configured" and the
    # post-config service guidance runs), but stub the migrated plugins'
    # interactive_setup so their wizards don't read real stdin. #41112.
    monkeypatch.setattr(setup_mod, "prompt_checklist", lambda _q, _items, pre=(), **k: list(pre))
    import fabric_cli.gateway as _gw_mod
    monkeypatch.setattr(_gw_mod, "_configure_platform", lambda *a, **k: None)
    monkeypatch.setattr("platform.system", lambda: "Linux")

    monkeypatch.setattr(gateway_mod, "supports_systemd_services", lambda: False)
    monkeypatch.setattr(gateway_mod, "is_macos", lambda: False)
    monkeypatch.setattr(gateway_mod, "_is_service_installed", lambda: False)
    monkeypatch.setattr(gateway_mod, "_is_service_running", lambda: False)

    setup_mod.setup_gateway({})

    out = capsys.readouterr().out
    assert "Messaging platforms configured!" in out
    assert "Start the gateway to bring your bots online:" in out
    assert "fabric gateway" in out


def test_setup_gateway_in_container_shows_docker_guidance(monkeypatch, capsys):
    """setup_gateway() in a Docker container shows Docker-specific restart instructions."""
    env = {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_HOME_CHANNEL": "",
        "DISCORD_BOT_TOKEN": "",
        "DISCORD_HOME_CHANNEL": "",
        "SLACK_BOT_TOKEN": "",
        "SLACK_HOME_CHANNEL": "",
        "MATRIX_HOMESERVER": "https://matrix.example.com",
        "MATRIX_USER_ID": "@alice:example.com",
        "MATRIX_PASSWORD": "",
        "MATRIX_ACCESS_TOKEN": "token",
        "BLUEBUBBLES_SERVER_URL": "",
        "BLUEBUBBLES_HOME_CHANNEL": "",
        "WHATSAPP_ENABLED": "",
        "WEBHOOK_ENABLED": "",
    }

    import fabric_cli.gateway as gateway_mod

    monkeypatch.setattr(setup_mod, "get_env_value", lambda key: env.get(key, ""))
    monkeypatch.setattr(gateway_mod, "get_env_value", lambda key: env.get(key, ""))
    monkeypatch.setattr(setup_mod, "prompt_yes_no", lambda *args, **kwargs: False)
    # Keep the checklist pre-selection (so matrix stays "configured" and the
    # post-config service guidance runs), but stub the migrated plugins'
    # interactive_setup so their wizards don't read real stdin. #41112.
    monkeypatch.setattr(setup_mod, "prompt_checklist", lambda _q, _items, pre=(), **k: list(pre))
    import fabric_cli.gateway as _gw_mod
    monkeypatch.setattr(_gw_mod, "_configure_platform", lambda *a, **k: None)
    monkeypatch.setattr("platform.system", lambda: "Linux")

    monkeypatch.setattr(gateway_mod, "supports_systemd_services", lambda: False)
    monkeypatch.setattr(gateway_mod, "is_macos", lambda: False)
    monkeypatch.setattr(gateway_mod, "_is_service_installed", lambda: False)
    monkeypatch.setattr(gateway_mod, "_is_service_running", lambda: False)

    # Patch is_container at the import location in setup.py
    import fabric_constants
    monkeypatch.setattr(fabric_constants, "is_container", lambda: True)

    setup_mod.setup_gateway({})

    out = capsys.readouterr().out
    assert "Messaging platforms configured!" in out
    assert "docker" in out.lower() or "Docker" in out
    assert "restart" in out.lower()


def test_setup_syncs_custom_provider_removal_from_disk(tmp_path, monkeypatch):
    """Removing the last custom provider in model setup should persist."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    config = load_config()
    config["custom_providers"] = [{"name": "Local", "base_url": "http://localhost:8080/v1"}]
    save_config(config)

    def fake_select():
        cfg = load_config()
        cfg["model"] = {"provider": "openrouter", "default": "anthropic/claude-opus-4.6"}
        cfg["custom_providers"] = []
        save_config(cfg)

    monkeypatch.setattr("fabric_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)
    save_config(config)

    reloaded = load_config()
    assert reloaded.get("custom_providers") == []


def test_setup_cancel_preserves_existing_config(tmp_path, monkeypatch):
    """When the user cancels provider selection, existing config is preserved."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    # Pre-set a provider
    _write_model_config(tmp_path, "openrouter", model_name="gpt-4o")

    config = load_config()
    assert config["model"]["provider"] == "openrouter"

    def fake_select():
        pass  # user cancelled — nothing written to disk

    monkeypatch.setattr("fabric_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)
    save_config(config)

    reloaded = load_config()
    assert isinstance(reloaded["model"], dict)
    assert reloaded["model"]["provider"] == "openrouter"
    assert reloaded["model"]["default"] == "gpt-4o"


def test_setup_exception_in_select_gracefully_handled(tmp_path, monkeypatch):
    """If select_provider_and_model raises, setup continues with existing config."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    config = load_config()

    def fake_select():
        raise RuntimeError("something broke")

    monkeypatch.setattr("fabric_cli.main.select_provider_and_model", fake_select)

    # Should not raise
    setup_model_provider(config)


def test_setup_keyboard_interrupt_gracefully_handled(tmp_path, monkeypatch):
    """KeyboardInterrupt during provider selection is handled."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    config = load_config()

    def fake_select():
        raise KeyboardInterrupt()

    monkeypatch.setattr("fabric_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)


def test_select_provider_and_model_warns_if_named_custom_provider_disappears(
    tmp_path, monkeypatch, capsys
):
    """If a saved custom provider is deleted mid-selection, show a warning instead of silently doing nothing."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)

    cfg = load_config()
    cfg["custom_providers"] = [{"name": "Local", "base_url": "http://localhost:8080/v1"}]
    save_config(cfg)

    def fake_prompt_provider_choice(choices, default=0):
        current = load_config()
        current["custom_providers"] = []
        save_config(current)
        return next(i for i, label in enumerate(choices) if label.startswith("Local (localhost:8080/v1)"))

    monkeypatch.setattr("fabric_cli.auth.resolve_provider", lambda provider: None)
    monkeypatch.setattr("fabric_cli.main._prompt_provider_choice", fake_prompt_provider_choice)
    monkeypatch.setattr(
        "fabric_cli.main._model_flow_named_custom",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("named custom flow should not run")),
    )

    from fabric_cli.main import select_provider_and_model

    select_provider_and_model()

    out = capsys.readouterr().out
    assert "selected saved custom provider is no longer available" in out


def test_select_provider_and_model_accepts_named_provider_from_providers_section(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)

    cfg = load_config()
    cfg["model"] = {
        "provider": "volcengine-plan",
        "default": "doubao-seed-2.0-code",
    }
    cfg["providers"] = {
        "volcengine-plan": {
            "name": "volcengine-plan",
            "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
            "default_model": "doubao-seed-2.0-code",
            "models": {"doubao-seed-2.0-code": {}},
        }
    }
    save_config(cfg)

    monkeypatch.setattr(
        "fabric_cli.main._prompt_provider_choice",
        lambda choices, default=0: len(choices) - 1,
    )

    from fabric_cli.main import select_provider_and_model

    select_provider_and_model()

    out = capsys.readouterr().out
    assert "Warning: Unknown provider 'volcengine-plan'" not in out
    assert "Active provider:  volcengine-plan" in out


def test_select_provider_and_model_neutralizes_hidden_opt_in_active_provider(
    tmp_path, monkeypatch, capsys
):
    """A hidden opt-in config must not leak its provider/model into setup."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {},
    )
    _clear_provider_env(monkeypatch)

    cfg = load_config()
    cfg["model"] = {
        "provider": "nous",
        "default": "stale-test-model",
    }
    save_config(cfg)
    captured_picker = {}

    def accept_default(choices, default=0):
        captured_picker["choices"] = choices
        captured_picker["default"] = default
        return default

    monkeypatch.setattr("fabric_cli.main._prompt_provider_choice", accept_default)

    from fabric_cli.main import select_provider_and_model

    select_provider_and_model()
    out = capsys.readouterr().out

    assert "Configured provider (not in Fabric catalog)" in out
    assert "configured model hidden" in out
    assert "Nous" not in out
    assert "stale-test-model" not in out
    assert captured_picker["choices"][-1] == "Leave unchanged"
    assert captured_picker["default"] == len(captured_picker["choices"]) - 1
    assert load_config()["model"]["provider"] == "nous"


def test_select_provider_and_model_restores_legacy_active_provider_with_opt_in(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    monkeypatch.setattr("fabric_cli.fabric_capabilities._load_capabilities_config", lambda: {"model_providers": "nous".split(",")})
    _clear_provider_env(monkeypatch)

    cfg = load_config()
    cfg["model"] = {
        "provider": "nous",
        "default": "stale-test-model",
    }
    save_config(cfg)
    monkeypatch.setattr(
        "fabric_cli.main._prompt_provider_choice",
        lambda choices, default=0: len(choices) - 1,
    )

    from fabric_cli.main import select_provider_and_model

    select_provider_and_model()
    out = capsys.readouterr().out

    assert "Active provider:  Nous Portal" in out
    assert "Current model:    stale-test-model" in out


def test_codex_setup_uses_runtime_access_token_for_live_model_list(tmp_path, monkeypatch):
    """Codex model list fetching uses the runtime access token."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")

    config = load_config()
    _stub_tts(monkeypatch)

    def fake_select():
        _write_model_config(tmp_path, "openai-codex", "https://api.openai.com/v1", "gpt-4o")

    monkeypatch.setattr("fabric_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)
    save_config(config)

    reloaded = load_config()
    assert isinstance(reloaded["model"], dict)
    assert reloaded["model"]["provider"] == "openai-codex"


def test_modal_setup_can_use_nous_subscription_without_modal_creds(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("fabric_cli.setup.managed_nous_tools_enabled", lambda: True)
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    config = load_config()

    def fake_prompt_choice(question, choices, default=0):
        if question == "Select terminal backend:":
            return 2
        if question == "Select how Modal execution should be billed:":
            return 0
        raise AssertionError(f"Unexpected prompt_choice call: {question}")

    def fake_prompt(message, *args, **kwargs):
        assert "Modal Token" not in message
        raise AssertionError(f"Unexpected prompt call: {message}")

    monkeypatch.setattr("fabric_cli.setup.prompt_choice", fake_prompt_choice)
    monkeypatch.setattr("fabric_cli.setup.prompt", fake_prompt)
    monkeypatch.setattr("fabric_cli.setup._prompt_container_resources", lambda config: None)
    monkeypatch.setattr(
        "fabric_cli.setup.get_nous_subscription_features",
        lambda config: type("Features", (), {"nous_auth_present": True})(),
    )
    monkeypatch.setitem(
        sys.modules,
        "tools.managed_tool_gateway",
        types.SimpleNamespace(
            is_managed_tool_gateway_ready=lambda vendor: vendor == "modal",
            resolve_managed_tool_gateway=lambda vendor: None,
        ),
    )

    from fabric_cli.setup import setup_terminal_backend

    setup_terminal_backend(config)

    out = capsys.readouterr().out
    assert config["terminal"]["backend"] == "modal"
    assert config["terminal"]["modal_mode"] == "managed"
    assert "bill to your subscription" in out


def test_modal_setup_persists_direct_mode_when_user_chooses_their_own_account(tmp_path, monkeypatch):
    monkeypatch.setattr("fabric_cli.setup.managed_nous_tools_enabled", lambda: True)
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
    monkeypatch.delenv("MODAL_TOKEN_SECRET", raising=False)
    config = load_config()

    def fake_prompt_choice(question, choices, default=0):
        if question == "Select terminal backend:":
            return 2
        if question == "Select how Modal execution should be billed:":
            return 1
        raise AssertionError(f"Unexpected prompt_choice call: {question}")

    prompt_values = iter(["token-id", "token-secret", ""])

    monkeypatch.setattr("fabric_cli.setup.prompt_choice", fake_prompt_choice)
    monkeypatch.setattr("fabric_cli.setup.prompt", lambda *args, **kwargs: next(prompt_values))
    monkeypatch.setattr("fabric_cli.setup._prompt_container_resources", lambda config: None)
    monkeypatch.setattr(
        "fabric_cli.setup.get_nous_subscription_features",
        lambda config: type("Features", (), {"nous_auth_present": True})(),
    )
    monkeypatch.setitem(
        sys.modules,
        "tools.managed_tool_gateway",
        types.SimpleNamespace(
            is_managed_tool_gateway_ready=lambda vendor: vendor == "modal",
            resolve_managed_tool_gateway=lambda vendor: None,
        ),
    )
    monkeypatch.setitem(sys.modules, "swe_rex", object())

    from fabric_cli.setup import setup_terminal_backend

    setup_terminal_backend(config)

    assert config["terminal"]["backend"] == "modal"
    assert config["terminal"]["modal_mode"] == "direct"


def test_modal_setup_hides_nous_billing_when_catalog_is_not_opted_in(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr("fabric_cli.setup.managed_nous_tools_enabled", lambda: True)
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {},
    )
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    monkeypatch.setenv("MODAL_TOKEN_ID", "token-id")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "token-secret")
    config = load_config()

    def fake_prompt_choice(question, choices, default=0):
        if question == "Select terminal backend:":
            return 2
        raise AssertionError(f"Unexpected prompt_choice call: {question}: {choices}")

    monkeypatch.setattr("fabric_cli.setup.prompt_choice", fake_prompt_choice)
    monkeypatch.setattr("fabric_cli.setup.prompt_yes_no", lambda *args, **kwargs: False)
    monkeypatch.setattr("fabric_cli.setup._prompt_container_resources", lambda config: None)
    monkeypatch.setattr(
        "fabric_cli.setup.get_nous_subscription_features",
        lambda config: type("Features", (), {"nous_auth_present": True})(),
    )
    monkeypatch.setitem(
        sys.modules,
        "tools.managed_tool_gateway",
        types.SimpleNamespace(
            is_managed_tool_gateway_ready=lambda vendor: vendor == "modal",
            resolve_managed_tool_gateway=lambda vendor: None,
        ),
    )
    monkeypatch.setitem(sys.modules, "modal", object())

    from fabric_cli.setup import setup_terminal_backend

    setup_terminal_backend(config)

    assert config["terminal"]["modal_mode"] == "direct"
    assert "Nous" not in capsys.readouterr().out


# test_setup_slack_* moved to tests/gateway/test_slack_plugin_setup.py — the
# _setup_slack wizard migrated to the slack plugin's interactive_setup (#41112).


def test_prompt_yes_no_eof_returns_default_instead_of_exiting(monkeypatch):
    """A closed/redirected stdin (EOFError) must yield the default, not abort.

    Regression: the Windows gateway start path asks "Install it now?" when the
    service is not installed; spawned from the desktop app (stdin=DEVNULL) the
    EOFError used to sys.exit(1), killing every desktop-triggered restart."""
    def _eof(*_a, **_k):
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)

    assert setup_mod.prompt_yes_no("Install it now?", True) is True
    assert setup_mod.prompt_yes_no("Install it now?", False) is False


def test_prompt_yes_no_keyboard_interrupt_still_exits(monkeypatch):
    """Ctrl+C is an explicit user abort and must keep exiting."""
    def _interrupt(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", _interrupt)

    import pytest

    with pytest.raises(SystemExit):
        setup_mod.prompt_yes_no("Install it now?", True)
