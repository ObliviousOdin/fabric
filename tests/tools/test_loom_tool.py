"""Tests for the ``loom`` deployment-plane agent tool (tools/loom_tool.py).

The core deploy-plane logic lives under ``fabric_cli/loom/`` and is exercised by
``tests/loom/``. These tests cover only the thin agent-tool surface: JSON-string
outputs, per-action arg validation, and the human-approval gate on the mutating
``deploy`` action.

The tool is wired to a real :class:`LoomService` backed by a temp SQLite DB and a
:class:`FakeDriver` (via ``tests.loom._fakes.make_factory``) so no real
Docker/SSH runs, and the approval gate is monkeypatched to avoid a live prompt.
"""

from __future__ import annotations

import json

from fabric_cli.loom.service import LoomService
from fabric_cli.loom.store import LoomStore
from tests.loom._fakes import make_factory
from tools.loom_tool import loom_tool


def _seed_service(tmp_path):
    """Build a LoomService on a temp DB with a local host + compose project."""
    store = LoomStore(db_path=tmp_path / "loom.db")
    service = LoomService(store, driver_factory=make_factory(healthy=True))
    service.add_host("here", "local")
    service.add_project("app", "compose", source="/srv/app")
    return service


def _patch_service(monkeypatch, tmp_path):
    """Point tools.loom_tool.open_service at a freshly seeded temp service.

    A new LoomService is opened per call (mirroring open_service's contract that
    each caller owns its store), all sharing the same on-disk DB so seeded data
    is visible across calls.
    """
    seeded = _seed_service(tmp_path)
    seeded._store.close()

    def _open():
        return LoomService(
            LoomStore(db_path=tmp_path / "loom.db"),
            driver_factory=make_factory(healthy=True),
        )

    monkeypatch.setattr("tools.loom_tool.open_service", _open)


def test_status_returns_json(monkeypatch, tmp_path):
    _patch_service(monkeypatch, tmp_path)
    out = json.loads(loom_tool({"action": "status"}))
    assert out["success"] is True
    assert out["status"]["hosts"] == 1
    assert out["status"]["projects"] == 1


def test_hosts_and_projects_list(monkeypatch, tmp_path):
    _patch_service(monkeypatch, tmp_path)
    hosts = json.loads(loom_tool({"action": "hosts"}))
    assert hosts["success"] is True
    assert [h["name"] for h in hosts["hosts"]] == ["here"]
    assert hosts["hosts"][0]["kind"] == "local"

    projects = json.loads(loom_tool({"action": "projects"}))
    assert [p["name"] for p in projects["projects"]] == ["app"]


def test_plan_returns_plan_dict_and_id(monkeypatch, tmp_path):
    _patch_service(monkeypatch, tmp_path)
    out = json.loads(loom_tool({"action": "plan", "project": "app", "host": "here"}))
    assert out["success"] is True
    assert out["deployment_id"]
    assert out["state"] == "planned"
    assert out["plan"]["steps"]


def test_deploy_with_approval_becomes_active(monkeypatch, tmp_path):
    _patch_service(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "tools.loom_tool.request_tool_approval",
        lambda *a, **k: {"approved": True},
    )
    out = json.loads(loom_tool({"action": "deploy", "project": "app", "host": "here"}))
    assert out["success"] is True
    assert out["deployment"]["state"] == "active"
    assert out["deployment"]["active"] is True


def test_deploy_denied_by_approval_is_blocked(monkeypatch, tmp_path):
    _patch_service(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "tools.loom_tool.request_tool_approval",
        lambda *a, **k: {"approved": False, "message": "no"},
    )
    out = json.loads(loom_tool({"action": "deploy", "project": "app", "host": "here"}))
    assert out["error"] == "no"
    # Nothing was deployed.
    assert "deployment" not in out


def test_missing_args_return_error(monkeypatch, tmp_path):
    _patch_service(monkeypatch, tmp_path)
    # deploy needs both project and host.
    out = json.loads(loom_tool({"action": "deploy", "project": "app"}))
    assert "error" in out
    assert "project and host" in out["error"]

    # logs needs a deployment_id.
    out = json.loads(loom_tool({"action": "logs"}))
    assert "error" in out
    assert "deployment_id" in out["error"]

    # unknown action is rejected.
    out = json.loads(loom_tool({"action": "frobnicate"}))
    assert "error" in out


def test_loom_error_is_returned_as_tool_error(monkeypatch, tmp_path):
    _patch_service(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "tools.loom_tool.request_tool_approval",
        lambda *a, **k: {"approved": True},
    )
    # Rolling back with no history raises LoomConflictError -> structured error.
    out = json.loads(loom_tool({"action": "rollback", "project": "app", "host": "here"}))
    assert "error" in out
    assert out["error"].startswith("[conflict]")


def test_tool_is_registered():
    from tools.registry import registry

    assert "loom" in registry.get_all_tool_names()
    entry = registry.get_entry("loom")
    assert entry is not None
    assert entry.toolset == "loom"
