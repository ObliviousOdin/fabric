"""Doctor must not execute external-memory diagnostics in restricted modes."""

from __future__ import annotations

import builtins
import contextlib
import io
import os
import sys
import types
from argparse import Namespace

import pytest
import yaml

from fabric_cli import doctor


def _run_restricted_doctor(
    monkeypatch,
    tmp_path,
    *,
    provider: str,
    mode: str,
) -> tuple[str, list[str]]:
    home = tmp_path / f"{mode}-{provider}"
    project = tmp_path / "project"
    home.mkdir(parents=True)
    project.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "security": {"egress_mode": mode},
                "memory": {
                    "provider": provider,
                    "memory_enabled": True,
                    "user_profile_enabled": True,
                },
            }
        ),
        encoding="utf-8",
    )
    memories = home / "memories"
    memories.mkdir()
    (memories / "MEMORY.md").write_text("built in", encoding="utf-8")

    monkeypatch.setattr(doctor, "FABRIC_HOME", home)
    monkeypatch.setattr(doctor, "PROJECT_ROOT", project)
    monkeypatch.setattr(doctor, "_DHH", str(home))
    monkeypatch.setattr(doctor, "_APIKEY_PROVIDERS_CACHE", [])

    honcho_probe_calls: list[str] = []

    def honcho_probe_bomb():
        honcho_probe_calls.append("honcho")
        raise AssertionError("doctor probed Honcho configuration")

    monkeypatch.setattr(doctor, "_honcho_is_configured_for_doctor", honcho_probe_bomb)
    fake_model_tools = types.SimpleNamespace(
        check_tool_availability=lambda *args, **kwargs: (
            [],
            [
                {
                    "name": "honcho",
                    "env_vars": [],
                    "tools": ["honcho_search"],
                }
            ],
        ),
        TOOLSET_REQUIREMENTS={},
    )
    monkeypatch.setitem(sys.modules, "model_tools", fake_model_tools)

    # Keep unrelated connectivity diagnostics inert even on a developer host
    # that happens to have cloud credentials in its inherited environment.
    for name in set(doctor._PROVIDER_ENV_HINTS) | {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_PROFILE",
        "AZURE_CLIENT_ID",
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_SECRET",
    }:
        monkeypatch.delenv(name, raising=False)

    try:
        from fabric_cli import auth

        monkeypatch.setattr(auth, "get_nous_auth_status", lambda: {})
        monkeypatch.setattr(auth, "get_codex_auth_status", lambda: {})
        monkeypatch.setattr(auth, "get_minimax_oauth_auth_status", lambda: {})
        monkeypatch.setattr(auth, "get_xai_oauth_auth_status", lambda: {})
    except Exception:
        pass

    attempted_adapter_imports: list[str] = []
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "plugins.memory" or name.startswith("plugins.memory."):
            attempted_adapter_imports.append(name)
            raise AssertionError("doctor imported an external memory adapter")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        doctor.run_doctor(Namespace(fix=False, ack=None))

    assert honcho_probe_calls == []
    return output.getvalue(), attempted_adapter_imports


@pytest.mark.parametrize("provider", ["honcho", "mem0", "user-memory"])
def test_local_ai_doctor_reports_external_memory_without_any_probe(
    monkeypatch,
    tmp_path,
    provider,
):
    output, imports = _run_restricted_doctor(
        monkeypatch,
        tmp_path,
        provider=provider,
        mode="local_ai",
    )

    assert imports == []
    assert "Built-in memory active" in output
    assert f"{provider} external memory provider unavailable" in output
    assert "not yet integrated with the local_ai egress policy" in output
    assert "provider active" not in output
    assert "connection failed" not in output.lower()


def test_air_gapped_doctor_reports_configured_unavailable_without_probe(
    monkeypatch,
    tmp_path,
):
    output, imports = _run_restricted_doctor(
        monkeypatch,
        tmp_path,
        provider="honcho",
        mode="air_gapped",
    )

    assert imports == []
    assert "Built-in memory active" in output
    assert "honcho external memory provider unavailable" in output
    assert "no verified whole-process network boundary" in output


def test_air_gapped_doctor_is_unavailable_without_external_provider(
    monkeypatch,
    tmp_path,
):
    output, imports = _run_restricted_doctor(
        monkeypatch,
        tmp_path,
        provider="",
        mode="air_gapped",
    )

    assert imports == []
    assert "Built-in memory active" in output
    assert "security.egress_mode=air_gapped configured but unavailable" in output
    assert "no verified whole-process network boundary" in output


def test_tool_override_does_not_probe_honcho_in_restricted_mode(monkeypatch):
    def bomb():
        raise AssertionError("Honcho config was probed")

    monkeypatch.setattr(doctor, "_honcho_is_configured_for_doctor", bomb)
    entry = {"name": "honcho", "env_vars": [], "tools": ["honcho_search"]}

    available, unavailable = doctor._apply_doctor_tool_availability_overrides(
        [],
        [entry],
        egress_mode="local_ai",
    )

    assert available == []
    assert unavailable == [entry]


def test_doctor_policy_snapshot_does_not_bleed_between_profiles(
    monkeypatch,
    tmp_path,
):
    local_home = tmp_path / "local"
    online_home = tmp_path / "online"
    local_home.mkdir()
    online_home.mkdir()
    (local_home / "config.yaml").write_text(
        "security:\n  egress_mode: local_ai\n",
        encoding="utf-8",
    )
    (online_home / "config.yaml").write_text(
        "security:\n  egress_mode: online\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(doctor, "FABRIC_HOME", local_home)
    first = doctor._doctor_egress_mode(doctor._read_doctor_profile_config())
    monkeypatch.setattr(doctor, "FABRIC_HOME", online_home)
    second = doctor._doctor_egress_mode(doctor._read_doctor_profile_config())

    assert (first, second) == ("local_ai", "online")
