"""Tests for Anthropic credential persistence helpers.

Fabric authenticates to native Anthropic with an API key only — there is no
OAuth/subscription token slot or Claude Code credential handoff (see NOTICE).
"""

from fabric_cli.config import load_env


def test_save_anthropic_api_key_uses_api_key_slot(tmp_path, monkeypatch):
    home = tmp_path / "fabric"
    home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(home))

    from fabric_cli.config import save_anthropic_api_key

    save_anthropic_api_key("sk-ant-api03-key")

    env_vars = load_env()
    assert env_vars["ANTHROPIC_API_KEY"] == "sk-ant-api03-key"
