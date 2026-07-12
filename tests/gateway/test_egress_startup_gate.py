from __future__ import annotations

import builtins
import importlib

import pytest

from agent.egress_policy import EgressPolicyConfigurationError


@pytest.mark.asyncio
async def test_gateway_policy_gate_precedes_boot_fingerprint(monkeypatch):
    # TUI fixtures snapshot/restore sys.modules and can leave a stale package
    # attribute behind. Patch the module that subsequent imports will resolve.
    egress_startup = importlib.import_module("fabric_cli.egress_startup")
    from gateway import code_skew
    from gateway import run as gateway_run

    def _blocked(**_kwargs):
        raise EgressPolicyConfigurationError("invalid_egress_mode")

    monkeypatch.setattr(
        egress_startup, "require_runtime_egress_available", _blocked
    )
    monkeypatch.setattr(
        code_skew,
        "record_boot_fingerprint",
        lambda: pytest.fail("boot fingerprint must be after the policy gate"),
    )

    assert await gateway_run.start_gateway() is False


def test_tui_entry_gate_precedes_sidecar_and_mcp(monkeypatch):
    egress_startup = importlib.import_module("fabric_cli.egress_startup")
    from tui_gateway import entry

    def _blocked(**_kwargs):
        raise EgressPolicyConfigurationError("invalid_egress_mode")

    monkeypatch.setattr(
        egress_startup, "require_runtime_egress_available", _blocked
    )
    monkeypatch.setattr(
        entry,
        "_install_sidecar_publisher",
        lambda: pytest.fail("sidecar must not start"),
    )

    with pytest.raises(SystemExit) as exc_info:
        entry.main()

    assert exc_info.value.code == 78


def _unavailable_egress_snapshot() -> dict:
    return {
        "mode": "air_gapped",
        "status": "unavailable",
        "available": False,
        "scope": "whole_process_network",
        "reason": "whole_process_network_boundary_missing",
        "allowed_private_cidr_count": 0,
    }


@pytest.mark.parametrize(
    ("method_name", "forbidden_imports"),
    [
        ("setup.status", {"fabric_cli.main"}),
        (
            "setup.runtime_check",
            {
                "fabric_cli.auth",
                "fabric_cli.main",
                "fabric_cli.runtime_provider",
            },
        ),
    ],
)
def test_tui_readiness_unavailable_branch_precedes_provider_imports(
    monkeypatch, method_name, forbidden_imports
):
    egress_status = importlib.import_module("fabric_cli.egress_status")
    from tui_gateway import server

    monkeypatch.setattr(
        egress_status,
        "build_egress_status_snapshot",
        _unavailable_egress_snapshot,
    )
    real_import = builtins.__import__

    def _guarded_import(name, *args, **kwargs):
        if name in forbidden_imports:
            raise AssertionError(
                f"{name} imported before unavailable egress returned"
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)

    response = server._methods[method_name](1, {})

    assert response["result"]["egress"] == _unavailable_egress_snapshot()
    assert response["result"].get("ok", False) is False
