from __future__ import annotations

import ast
import builtins
from argparse import Namespace
from pathlib import Path

import pytest
import yaml

from fabric_cli import doctor


def _restricted_snapshot(mode: str) -> dict:
    return {
        "mode": mode,
        "status": "available" if mode == "local_ai" else "unavailable",
        "available": mode == "local_ai",
        "scope": (
            "ai_inference_routes"
            if mode == "local_ai"
            else "whole_process_network"
        ),
        "reason": (
            None
            if mode == "local_ai"
            else "whole_process_network_boundary_missing"
        ),
        "allowed_private_cidr_count": 0,
    }


def test_doctor_has_no_module_level_dotenv_call():
    source = Path(doctor.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "load_fabric_dotenv"
    ]

    assert len(calls) == 1
    parent_by_child = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    current = calls[0]
    while current in parent_by_child and not isinstance(current, ast.FunctionDef):
        current = parent_by_child[current]
    assert isinstance(current, ast.FunctionDef)
    assert current.name == "run_doctor"


@pytest.mark.parametrize("mode", ["local_ai", "air_gapped"])
def test_restricted_doctor_runs_no_external_bootstrap_or_probe(
    monkeypatch, tmp_path, capsys, mode
):
    home = tmp_path / mode
    home.mkdir()
    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "security": {"egress_mode": mode},
                "memory": {"provider": "honcho"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(doctor, "HERMES_HOME", home)
    monkeypatch.setattr(doctor, "PROJECT_ROOT", tmp_path / "project")
    monkeypatch.setattr(doctor, "_DHH", str(home))
    monkeypatch.setattr(
        doctor,
        "load_fabric_dotenv",
        lambda **_kwargs: pytest.fail("external secret bootstrap must not run"),
    )
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess probe must not run"),
    )

    from fabric_cli import egress_status

    monkeypatch.setattr(
        egress_status,
        "build_egress_status_snapshot",
        lambda: _restricted_snapshot(mode),
    )

    blocked_prefixes = (
        "agent.azure_identity_adapter",
        "agent.bedrock_adapter",
        "httpx",
        "model_tools",
        "plugins.",
    )
    real_import = builtins.__import__

    def _guarded_import(name, *args, **kwargs):
        if name.startswith(blocked_prefixes):
            raise AssertionError(f"external diagnostic import attempted: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)

    doctor.run_doctor(Namespace(fix=True, ack=None))

    output = capsys.readouterr().out
    assert f"security.egress_mode={mode}" in output
    assert "external memory provider unavailable" in output
    assert "probes were skipped" in output
    assert "--fix was intentionally not applied" in output


def test_malformed_policy_uses_local_repair_view(monkeypatch, tmp_path, capsys):
    home = tmp_path / "broken"
    home.mkdir()
    (home / "config.yaml").write_text(
        "security:\n  egress_mode: definitely-not-valid\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(doctor, "HERMES_HOME", home)
    monkeypatch.setattr(doctor, "PROJECT_ROOT", tmp_path / "project")
    monkeypatch.setattr(doctor, "_DHH", str(home))
    monkeypatch.setattr(
        doctor,
        "load_fabric_dotenv",
        lambda **_kwargs: pytest.fail("secret bootstrap must not run"),
    )

    from fabric_cli import egress_status

    monkeypatch.setattr(
        egress_status,
        "build_egress_status_snapshot",
        lambda: {
            "mode": "unknown",
            "status": "unavailable",
            "available": False,
            "scope": "unknown",
            "reason": "invalid_egress_mode",
            "allowed_private_cidr_count": 0,
        },
    )

    doctor.run_doctor(Namespace(fix=False, ack=None))

    output = capsys.readouterr().out
    assert "invalid_egress_mode" in output
    assert "Set security.egress_mode to online or local_ai" in output
