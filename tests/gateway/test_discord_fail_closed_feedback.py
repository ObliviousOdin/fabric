"""Fail-closed messaging for Discord interactive setup."""

from plugins.platforms.discord.adapter import interactive_setup
from plugins.platforms.discord.setup_wizard import DiscordBotIdentity


def test_discord_setup_existing_token_warns_fail_closed_not_fail_open(monkeypatch):
    info_lines: list[str] = []
    yes_no_answers = iter([False, False])  # no reconfigure; no add allowlist

    def fake_get_env_value(key: str):
        return "token" if key == "DISCORD_BOT_TOKEN" else ""

    monkeypatch.setattr("fabric_cli.config.get_env_value", fake_get_env_value)
    monkeypatch.setattr("fabric_cli.config.save_env_value", lambda *_a, **_k: None)
    monkeypatch.setattr("fabric_cli.cli_output.print_header", lambda *_a, **_k: None)
    monkeypatch.setattr("fabric_cli.cli_output.print_success", lambda *_a, **_k: None)
    monkeypatch.setattr("fabric_cli.cli_output.print_warning", lambda *_a, **_k: None)
    monkeypatch.setattr("fabric_cli.cli_output.print_error", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "fabric_cli.cli_output.print_info",
        lambda msg="", **_k: info_lines.append(str(msg)),
    )
    monkeypatch.setattr("fabric_cli.cli_output.prompt", lambda *_a, **_k: "")
    monkeypatch.setattr(
        "fabric_cli.cli_output.prompt_yes_no",
        lambda *_a, **_k: next(yes_no_answers),
    )
    monkeypatch.setattr(
        "plugins.platforms.discord.setup_wizard.validate_bot_token",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("skip")),
    )

    interactive_setup()

    joined = "\n".join(info_lines)
    assert "anyone can use your bot" not in joined
    assert "fail-closed default" in joined
    assert "DISCORD_ALLOW_ALL_USERS=true" in joined


def test_discord_setup_new_token_empty_allowlist_warns_denied_until_configured(monkeypatch):
    info_lines: list[str] = []
    # agent name, token, post-invite enter, empty allowlist, empty home
    prompts = iter(["Ops Bot", "MTIz." + ("a" * 30) + "." + ("b" * 30), "", "", ""])
    yes_no = iter([False])  # decline allow-all

    monkeypatch.setattr("fabric_cli.config.get_env_value", lambda _key: "")
    monkeypatch.setattr("fabric_cli.config.save_env_value", lambda *_a, **_k: None)
    monkeypatch.setattr("fabric_cli.cli_output.print_header", lambda *_a, **_k: None)
    monkeypatch.setattr("fabric_cli.cli_output.print_success", lambda *_a, **_k: None)
    monkeypatch.setattr("fabric_cli.cli_output.print_warning", lambda *_a, **_k: None)
    monkeypatch.setattr("fabric_cli.cli_output.print_error", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "fabric_cli.cli_output.print_info",
        lambda msg="", **_k: info_lines.append(str(msg)),
    )
    monkeypatch.setattr(
        "fabric_cli.cli_output.prompt",
        lambda *_a, **_k: next(prompts),
    )
    monkeypatch.setattr(
        "fabric_cli.cli_output.prompt_yes_no",
        lambda *_a, **_k: next(yes_no, False),
    )
    monkeypatch.setattr(
        "plugins.platforms.discord.setup_wizard.validate_bot_token",
        lambda *_a, **_k: DiscordBotIdentity(id="123456789012345678", username="OpsBot"),
    )
    monkeypatch.setattr(
        "plugins.platforms.discord.setup_wizard.write_agent_name_soul",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "fabric_constants.get_fabric_home",
        lambda: __import__("pathlib").Path("/tmp/test-home"),
    )

    interactive_setup()

    joined = "\n".join(info_lines)
    assert "anyone in servers with your bot can use it" not in joined
    assert "Discord will deny messages" in joined
    assert "DISCORD_ALLOWED_ROLES" in joined
    assert "DISCORD_ALLOW_ALL_USERS=true" in joined
