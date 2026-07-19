from types import SimpleNamespace
from unittest.mock import patch

from fabric_cli.config import (
    format_managed_message,
    get_managed_system,
    recommended_update_command,
)
from fabric_cli.main import cmd_update
from tools.skills_hub import OptionalSkillSource


def test_get_managed_system_homebrew(monkeypatch):
    monkeypatch.setenv("FABRIC_MANAGED", "homebrew")

    assert get_managed_system() == "Homebrew"
    assert recommended_update_command() == "brew upgrade fabric-agent"


def test_format_managed_message_homebrew(monkeypatch):
    monkeypatch.setenv("FABRIC_MANAGED", "homebrew")

    message = format_managed_message("update Fabric")

    assert "update Fabric" in message
    assert "Fabric installation" in message
    assert "managed by Homebrew" in message
    assert "brew upgrade fabric-agent" in message


def test_recommended_update_command_defaults_to_fabric_update(monkeypatch):
    monkeypatch.delenv("FABRIC_MANAGED", raising=False)

    # Also short-circuit the .managed marker path — CI runners may have an
    # ambient ~/.fabric/.managed if a prior test left FABRIC_HOME pointing
    # somewhere with that marker, which would make get_managed_update_command()
    # return "Update your Nix flake input ..." instead of falling through to
    # detect_install_method().
    with patch("fabric_cli.config.get_managed_update_command", return_value=None), \
         patch("fabric_cli.config.detect_install_method", return_value="git"):
        assert recommended_update_command() == "fabric update"


def test_cmd_update_blocks_managed_homebrew(monkeypatch, capsys):
    monkeypatch.setenv("FABRIC_MANAGED", "homebrew")

    with patch("fabric_cli.main.subprocess.run") as mock_run:
        cmd_update(SimpleNamespace())

    assert not mock_run.called
    captured = capsys.readouterr()
    assert "managed by Homebrew" in captured.err
    assert "brew upgrade fabric-agent" in captured.err


def test_optional_skill_source_uses_distribution_for_builtin_trust(tmp_path):
    distribution = tmp_path / "distribution"
    official_dir = distribution / "optional-skills"
    official_dir.mkdir(parents=True)
    with (
        patch("fabric_constants._get_packaged_data_dir", return_value=None),
        patch(
            "tools.skills_hub.__file__",
            str(distribution / "tools" / "skills_hub.py"),
        ),
    ):
        source = OptionalSkillSource()

    assert source._optional_dir == official_dir
