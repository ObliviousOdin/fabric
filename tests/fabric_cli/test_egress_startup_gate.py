from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from agent.egress_policy import (
    EgressMode,
    EgressPolicy,
    EgressPolicyConfigurationError,
    EgressPolicyUnavailable,
)
from fabric_cli import egress_startup
from fabric_cli import egress_status


def test_network_bootstrap_is_online_by_default(monkeypatch):
    monkeypatch.setattr(
        egress_startup,
        "load_startup_egress_policy",
        lambda: EgressPolicy(EgressMode.ONLINE),
    )

    assert egress_startup.network_bootstrap_permitted() is True


@pytest.mark.parametrize(
    "failure",
    [
        EgressPolicy(EgressMode.AIR_GAPPED),
        EgressPolicyConfigurationError("invalid_egress_mode"),
    ],
)
def test_network_bootstrap_fails_closed(monkeypatch, failure):
    if isinstance(failure, Exception):
        def _raise():
            raise failure

        monkeypatch.setattr(egress_startup, "load_startup_egress_policy", _raise)
    else:
        monkeypatch.setattr(
            egress_startup, "load_startup_egress_policy", lambda: failure
        )

    assert egress_startup.network_bootstrap_permitted() is False


def test_runtime_requirement_reports_air_gapped_unavailable(monkeypatch):
    monkeypatch.setattr(
        egress_startup,
        "load_startup_egress_policy",
        lambda: EgressPolicy(EgressMode.AIR_GAPPED),
    )

    with pytest.raises(EgressPolicyUnavailable) as exc_info:
        egress_startup.require_runtime_egress_available(surface="cli")

    assert exc_info.value.reason == "whole_process_network_boundary_missing"
    assert "air_gapped" in str(exc_info.value)


def test_egress_status_is_stable_and_does_not_expose_cidrs(monkeypatch):
    from ipaddress import ip_network

    monkeypatch.setattr(
        egress_status,
        "load_startup_egress_policy",
        lambda: EgressPolicy(
            EgressMode.LOCAL_AI,
            allowed_cidrs=(ip_network("10.20.0.0/16"),),
        ),
    )

    snapshot = egress_status.build_egress_status_snapshot()

    assert snapshot == {
        "mode": "local_ai",
        "status": "available",
        "available": True,
        "scope": "ai_inference_routes",
        "reason": None,
        "allowed_private_cidr_count": 1,
    }
    assert "10.20" not in repr(snapshot)


def test_egress_status_sanitizes_configuration_failure(monkeypatch):
    def _raise():
        raise EgressPolicyConfigurationError("managed_config_unreadable")

    monkeypatch.setattr(egress_status, "load_startup_egress_policy", _raise)

    snapshot = egress_status.build_egress_status_snapshot()

    assert snapshot["mode"] == "unknown"
    assert snapshot["available"] is False
    assert snapshot["reason"] == "managed_config_unreadable"


def test_cli_gate_preserves_local_repair_commands(monkeypatch):
    from fabric_cli import main as main_mod

    monkeypatch.setattr(main_mod, "_EARLY_NETWORK_BOOTSTRAP_PERMITTED", False)
    monkeypatch.setattr(main_mod.sys, "argv", ["fabric", "doctor"])
    monkeypatch.setattr(
        egress_startup,
        "require_runtime_egress_available",
        lambda **_kwargs: pytest.fail("repair command must not start runtime preflight"),
    )

    main_mod._enforce_early_runtime_egress_gate()


@pytest.mark.parametrize("command", ["monitor", "top"])
def test_cli_gate_allows_local_monitor_under_air_gap(monkeypatch, command):
    """``fabric monitor`` / ``top`` only read local host stats — allow when air-gapped."""
    from fabric_cli import main as main_mod

    monkeypatch.setattr(main_mod, "_EARLY_NETWORK_BOOTSTRAP_PERMITTED", False)
    monkeypatch.setattr(main_mod.sys, "argv", ["fabric", command])
    monkeypatch.setattr(
        egress_startup,
        "require_runtime_egress_available",
        lambda **_kwargs: pytest.fail("local monitor must not start runtime preflight"),
    )

    main_mod._enforce_early_runtime_egress_gate()
    assert main_mod._egress_repair_command_requested() is True


def test_blocked_version_command_skips_remote_update_check(monkeypatch):
    from fabric_cli import main as main_mod

    calls = []
    monkeypatch.setattr(main_mod, "_EARLY_NETWORK_BOOTSTRAP_PERMITTED", False)
    monkeypatch.setattr(
        main_mod,
        "_print_version_info",
        lambda *, check_updates: calls.append(check_updates),
    )

    main_mod.cmd_version(SimpleNamespace())

    assert calls == [False]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["fabric", "--model", "status", "chat"], False),
        (["fabric", "--model=qwen-local", "status"], True),
        (["fabric", "chat", "--", "status"], False),
        (["fabric", "--provider", "custom", "doctor"], True),
    ],
)
def test_local_ai_diagnostic_preparser_skips_flag_values_and_delimited_data(
    monkeypatch, argv, expected
):
    from fabric_cli import main as main_mod

    monkeypatch.setattr(main_mod.sys, "argv", argv)

    assert main_mod._early_local_diagnostic_command() is expected


def test_cli_gate_blocks_runtime_before_bootstrap(monkeypatch, capsys):
    from fabric_cli import main as main_mod

    monkeypatch.setattr(main_mod, "_EARLY_NETWORK_BOOTSTRAP_PERMITTED", False)
    monkeypatch.setattr(main_mod.sys, "argv", ["fabric", "chat"])

    def _blocked(**_kwargs):
        raise EgressPolicyUnavailable(
            "whole_process_network_boundary_missing",
            mode=EgressMode.AIR_GAPPED,
            purpose="cli",
            provider="none",
            origin_digest="000000000000",
        )

    monkeypatch.setattr(
        egress_startup, "require_runtime_egress_available", _blocked
    )
    monkeypatch.setattr(
        main_mod,
        "load_fabric_dotenv",
        lambda **_kwargs: pytest.fail("credentials must not load"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main_mod._enforce_early_runtime_egress_gate()

    assert exc_info.value.code == 78
    stderr = capsys.readouterr().err
    assert "whole_process_network_boundary_missing" in stderr
    assert "fabric doctor" in stderr


def test_cli_gate_does_not_treat_unknown_help_token_as_repair(
    monkeypatch, capsys
):
    from fabric_cli import main as main_mod

    monkeypatch.setattr(main_mod, "_EARLY_NETWORK_BOOTSTRAP_PERMITTED", False)
    monkeypatch.setattr(
        main_mod.sys,
        "argv",
        ["fabric", "third-party-command", "--help"],
    )

    def _blocked(**_kwargs):
        raise EgressPolicyUnavailable(
            "whole_process_network_boundary_missing",
            mode=EgressMode.AIR_GAPPED,
            purpose="cli",
            provider="none",
            origin_digest="000000000000",
        )

    monkeypatch.setattr(
        egress_startup,
        "require_runtime_egress_available",
        _blocked,
    )

    with pytest.raises(SystemExit) as exc_info:
        main_mod._enforce_early_runtime_egress_gate()

    assert exc_info.value.code == 78
    assert "whole_process_network_boundary_missing" in capsys.readouterr().err


def test_gateway_repair_gate_requires_the_lifecycle_subcommand(monkeypatch):
    from fabric_cli import main as main_mod

    monkeypatch.setattr(main_mod.sys, "argv", ["fabric", "gateway", "status"])
    assert main_mod._egress_repair_command_requested() is True

    monkeypatch.setattr(
        main_mod.sys,
        "argv",
        ["fabric", "gateway", "run", "--note", "stop"],
    )
    assert main_mod._egress_repair_command_requested() is False

    monkeypatch.setattr(
        main_mod.sys,
        "argv",
        ["fabric", "gateway", "run", "gateway", "stop"],
    )
    assert main_mod._egress_repair_command_requested() is False


@pytest.mark.parametrize(
    "argv",
    [
        ["fabric", "chat", "--", "--help"],
        ["fabric", "dashboard", "--", "--stop"],
        ["fabric", "--", "gateway", "stop"],
    ],
)
def test_repair_gate_never_interprets_post_delimiter_data(monkeypatch, argv):
    from fabric_cli import main as main_mod

    monkeypatch.setattr(main_mod.sys, "argv", argv)

    assert main_mod._egress_repair_command_requested() is False


def test_dashboard_direct_call_blocks_before_runtime_work(monkeypatch):
    from fabric_cli import main as main_mod

    def _blocked(**_kwargs):
        raise EgressPolicyConfigurationError("invalid_egress_mode")

    monkeypatch.setattr(
        egress_startup, "require_runtime_egress_available", _blocked
    )
    monkeypatch.setattr(
        main_mod,
        "_find_stale_dashboard_pids",
        lambda: pytest.fail("runtime work must not begin"),
    )
    args = SimpleNamespace(
        status=False,
        stop=False,
        headless_backend=False,
    )

    with pytest.raises(SystemExit, match="invalid_egress_mode"):
        main_mod.cmd_dashboard(args)


def test_status_repair_view_runs_no_provider_or_plugin_work(
    monkeypatch, capsys, tmp_path
):
    from fabric_cli import status as status_mod

    monkeypatch.setattr(status_mod, "get_env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(
        status_mod,
        "build_egress_status_snapshot",
        lambda: {
            "mode": "air_gapped",
            "status": "unavailable",
            "available": False,
            "scope": "whole_process_network",
            "reason": "whole_process_network_boundary_missing",
            "allowed_private_cidr_count": 0,
        },
    )
    monkeypatch.setattr(
        status_mod,
        "load_config",
        lambda: pytest.fail("config expansion must not run"),
    )
    monkeypatch.setattr(
        status_mod,
        "_effective_provider_label",
        lambda: pytest.fail("provider resolution must not run"),
    )
    monkeypatch.setattr(
        status_mod,
        "get_nous_portal_account_info",
        lambda: pytest.fail("account probe must not run"),
    )

    status_mod.show_status(SimpleNamespace(all=False, deep=True))

    output = capsys.readouterr().out
    assert "air_gapped" in output
    assert "whole_process_network_boundary_missing" in output
    assert "checks were skipped" in output


def test_local_ai_status_is_remote_probe_free(monkeypatch, capsys, tmp_path):
    from fabric_cli import config as config_mod
    from fabric_cli import status as status_mod

    monkeypatch.setattr(status_mod, "get_env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(
        status_mod,
        "build_egress_status_snapshot",
        lambda: {
            "mode": "local_ai",
            "status": "available",
            "available": True,
            "scope": "ai_inference_routes",
            "reason": None,
            "allowed_private_cidr_count": 0,
        },
    )
    monkeypatch.setattr(
        config_mod,
        "load_egress_policy_config",
        lambda: {
            "security": {"egress_mode": "local_ai"},
            "model": {
                "default": "qwen-local:latest",
                "provider": "custom:ollama",
                "base_url": "http://127.0.0.1:11434/v1",
            },
            "providers": {},
            "custom_providers": [],
        },
    )
    monkeypatch.setattr(
        status_mod,
        "load_config",
        lambda: pytest.fail("expanded config must not load"),
    )
    monkeypatch.setattr(
        status_mod,
        "_effective_provider_label",
        lambda: pytest.fail("provider/auth resolution must not run"),
    )
    monkeypatch.setattr(
        status_mod,
        "get_nous_portal_account_info",
        lambda: pytest.fail("account probe must not run"),
    )
    monkeypatch.setattr(
        status_mod,
        "_show_deep_checks",
        lambda _config: pytest.fail("remote deep checks must not run"),
    )

    status_mod.show_status(SimpleNamespace(all=False, deep=False))

    output = capsys.readouterr().out
    assert "qwen-local:latest" in output
    assert "custom:ollama" in output
    assert "Remote credential, OAuth, provider-catalog" in output
    assert "status --deep" in output


def test_local_ai_deep_status_only_uses_ollama_probe(
    monkeypatch, capsys, tmp_path
):
    from fabric_cli import config as config_mod
    from fabric_cli import status as status_mod

    monkeypatch.setattr(status_mod, "get_env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(
        status_mod,
        "build_egress_status_snapshot",
        lambda: {
            "mode": "local_ai",
            "status": "available",
            "available": True,
            "scope": "ai_inference_routes",
            "reason": None,
            "allowed_private_cidr_count": 0,
        },
    )
    raw = {
        "security": {"egress_mode": "local_ai"},
        "model": {
            "default": "qwen-local:latest",
            "provider": "custom:ollama",
            "base_url": "http://127.0.0.1:11434/v1",
        },
        "providers": {},
        "custom_providers": [],
    }
    monkeypatch.setattr(config_mod, "load_egress_policy_config", lambda: raw)
    calls = []
    monkeypatch.setattr(
        status_mod, "_show_ollama_deep_status", lambda config: calls.append(config)
    )
    monkeypatch.setattr(
        status_mod,
        "_show_deep_checks",
        lambda _config: pytest.fail("cloud deep checks must not run"),
    )

    status_mod.show_status(SimpleNamespace(all=False, deep=True))

    assert calls == [raw]


def test_real_cli_air_gapped_status_repairs_and_chat_fails_closed(tmp_path):
    home = tmp_path / "profile"
    home.mkdir()
    (home / "config.yaml").write_text(
        "security:\n  egress_mode: air_gapped\n",
        encoding="utf-8",
    )
    secret = "must-not-appear-in-air-gapped-status"
    (home / ".env").write_text(
        f"OPENAI_API_KEY={secret}\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "FABRIC_HOME": str(home),
            "NO_COLOR": "1",
        }
    )
    project_root = Path(__file__).resolve().parents[2]

    status = subprocess.run(
        [sys.executable, "-m", "fabric_cli.main", "status"],
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )

    assert status.returncode == 0, status.stderr
    assert "Mode:         air_gapped" in status.stdout
    assert "whole_process_network_boundary_missing" in status.stdout
    assert "Runtime/network checks were skipped" in status.stdout
    assert secret not in status.stdout + status.stderr

    chat = subprocess.run(
        [sys.executable, "-m", "fabric_cli.main", "chat", "hello"],
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )

    assert chat.returncode == 78
    assert "Fabric runtime startup blocked" in chat.stderr
    assert "whole_process_network_boundary_missing" in chat.stderr
    assert secret not in chat.stdout + chat.stderr


def test_web_dependency_install_is_after_air_gapped_import_gate(tmp_path):
    home = tmp_path / "profile"
    home.mkdir()
    (home / "config.yaml").write_text(
        "security:\n  egress_mode: air_gapped\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "FABRIC_HOME": str(home),
        }
    )
    script = """
import builtins
import sys
import types

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name == "fastapi" or name.startswith("fastapi."):
        raise ImportError("forced missing dashboard dependency")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
lazy_deps = types.ModuleType("tools.lazy_deps")

def ensure(*args, **kwargs):
    print("LAZY_INSTALL_CALLED")

lazy_deps.ensure = ensure
sys.modules["tools.lazy_deps"] = lazy_deps

try:
    import fabric_cli.web_server
except SystemExit as exc:
    print(f"BLOCKED:{exc}")
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "BLOCKED:Fabric web runtime startup blocked" in result.stdout
    assert "whole_process_network_boundary_missing" in result.stdout
    assert "LAZY_INSTALL_CALLED" not in result.stdout + result.stderr


def test_real_cli_local_ai_status_uses_restricted_view(tmp_path):
    home = tmp_path / "local-profile"
    home.mkdir()
    (home / "config.yaml").write_text(
        "security:\n"
        "  egress_mode: local_ai\n"
        "model:\n"
        "  provider: custom:ollama\n"
        "  default: qwen-local:latest\n"
        "  base_url: http://127.0.0.1:11434/v1\n",
        encoding="utf-8",
    )
    secret = "must-not-appear-in-local-ai-status"
    (home / ".env").write_text(
        f"OPENAI_API_KEY={secret}\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "FABRIC_HOME": str(home),
            "NO_COLOR": "1",
            "HTTP_PROXY": "http://proxy.invalid:9999",
            "HTTPS_PROXY": "http://proxy.invalid:9999",
        }
    )

    status = subprocess.run(
        [sys.executable, "-m", "fabric_cli.main", "status"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )

    assert status.returncode == 0, status.stderr
    assert "Mode:         local_ai" in status.stdout
    assert "qwen-local:latest" in status.stdout
    assert "Remote credential, OAuth, provider-catalog" in status.stdout
    assert secret not in status.stdout + status.stderr
