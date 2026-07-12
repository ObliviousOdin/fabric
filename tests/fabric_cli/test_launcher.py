"""Tests for the top-level ./fabric launcher script."""

import runpy
import subprocess
import sys
import types
from pathlib import Path


def test_launcher_delegates_to_argparse_entrypoint(monkeypatch):
    """./fabric should use fabric_cli.main, not the legacy Fire wrapper."""
    launcher_path = Path(__file__).resolve().parents[2] / "fabric"
    called = []

    fake_main_module = types.ModuleType("fabric_cli.main")

    def fake_main():
        called.append("fabric_cli.main")

    fake_main_module.main = fake_main
    monkeypatch.setitem(sys.modules, "fabric_cli.main", fake_main_module)

    fake_cli_module = types.ModuleType("cli")

    def legacy_cli_main(*args, **kwargs):
        raise AssertionError("launcher should not import cli.main")

    fake_cli_module.main = legacy_cli_main
    monkeypatch.setitem(sys.modules, "cli", fake_cli_module)

    fake_fire_module = types.ModuleType("fire")

    def legacy_fire(*args, **kwargs):
        raise AssertionError("launcher should not invoke fire.Fire")

    fake_fire_module.Fire = legacy_fire
    monkeypatch.setitem(sys.modules, "fire", fake_fire_module)

    monkeypatch.setattr(sys, "argv", [str(launcher_path), "gateway", "status"])

    runpy.run_path(str(launcher_path), run_name="__main__")

    assert called == ["fabric_cli.main"]


def test_fabric_help_is_customer_silent():
    repo = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "fabric_cli.main", "--help"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "usage: fabric" in result.stdout
    assert "Fabric - AI assistant" in result.stdout
    for forbidden in (
        "usage: hermes",
        "~/.hermes/config.yaml",
        "Uninstall Hermes",
        "Update Hermes",
        "anthropic/claude",
        "openrouter, anthropic",
        "HERMES_INFERENCE_MODEL",
    ):
        assert forbidden not in result.stdout
