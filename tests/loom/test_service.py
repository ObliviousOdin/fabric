"""Behavioural tests for LoomService: plan-before-mutation, apply, rollback."""

from __future__ import annotations

import pytest

from fabric_cli.loom.errors import (
    LoomConflictError,
    LoomNotFoundError,
    LoomValidationError,
)
from fabric_cli.loom.models import DeploymentState, HostState
from fabric_cli.loom.service import LoomService
from fabric_cli.loom.store import LoomStore
from tests.loom._fakes import make_factory


def _svc(tmp_path, **driver_kwargs):
    store = LoomStore(db_path=tmp_path / "loom.db")
    factory = make_factory(**driver_kwargs)
    return LoomService(store, driver_factory=factory), factory


# -- hosts / projects validation -------------------------------------------


def test_add_local_host_is_ready(tmp_path):
    svc, _ = _svc(tmp_path)
    host = svc.add_host("here", "local")
    assert host.state == HostState.READY.value


def test_ssh_host_requires_address_and_user(tmp_path):
    svc, _ = _svc(tmp_path)
    with pytest.raises(LoomValidationError):
        svc.add_host("box", "ssh")
    with pytest.raises(LoomValidationError):
        svc.add_host("box", "ssh", address="1.2.3.4")
    host = svc.add_host("box", "ssh", address="1.2.3.4", user="root")
    assert host.state == HostState.NEW.value


def test_duplicate_names_conflict(tmp_path):
    svc, _ = _svc(tmp_path)
    svc.add_host("here", "local")
    with pytest.raises(LoomConflictError):
        svc.add_host("here", "local")
    svc.add_project("app", "compose")
    with pytest.raises(LoomConflictError):
        svc.add_project("app", "compose")


def test_unknown_kinds_rejected(tmp_path):
    svc, _ = _svc(tmp_path)
    with pytest.raises(LoomValidationError):
        svc.add_host("x", "kubernetes")
    with pytest.raises(LoomValidationError):
        svc.add_project("x", "helm")


# -- scan -------------------------------------------------------------------


def test_scan_marks_ready_when_docker_present(tmp_path):
    svc, _ = _svc(tmp_path, docker=True)
    host = svc.add_host("box", "ssh", address="1.2.3.4", user="root")
    scanned = svc.scan_host(host.id)
    assert scanned.state == HostState.READY.value
    assert scanned.meta["scan"]["docker_available"] is True


def test_scan_marks_scanned_when_docker_missing(tmp_path):
    svc, _ = _svc(tmp_path, docker=False)
    host = svc.add_host("box", "ssh", address="1.2.3.4", user="root")
    scanned = svc.scan_host(host.id)
    assert scanned.state == HostState.SCANNED.value


def test_scan_marks_unreachable(tmp_path):
    svc, _ = _svc(tmp_path, reachable=False, docker=False)
    host = svc.add_host("box", "ssh", address="1.2.3.4", user="root")
    scanned = svc.scan_host(host.id)
    assert scanned.state == HostState.UNREACHABLE.value


# -- plan (no mutation) -----------------------------------------------------


def test_plan_does_not_touch_infra(tmp_path):
    svc, factory = _svc(tmp_path)
    svc.add_host("here", "local")
    svc.add_project("app", "compose", source="/srv/app")
    dep = svc.plan_deploy("app", "here")
    assert dep.state == DeploymentState.PLANNED.value
    assert dep.plan is not None and len(dep.plan.steps) >= 2
    # No driver was invoked during planning.
    assert factory.last is None


def test_plan_missing_refs(tmp_path):
    svc, _ = _svc(tmp_path)
    with pytest.raises(LoomNotFoundError):
        svc.plan_deploy("nope", "nope")


# -- apply ------------------------------------------------------------------


def test_apply_happy_path(tmp_path):
    svc, factory = _svc(tmp_path, healthy=True)
    svc.add_host("here", "local")
    svc.add_project("app", "compose", source="/srv/app")
    dep = svc.deploy("app", "here")
    assert dep.state == DeploymentState.ACTIVE.value
    assert dep.active is True
    assert factory.last.calls == ["run_release", "health_check"]
    assert "traffic switched" in dep.logs


def test_apply_unhealthy_fails_and_keeps_previous(tmp_path):
    # First deploy succeeds and is active.
    svc, _ = _svc(tmp_path, healthy=True)
    svc.add_host("here", "local")
    svc.add_project("app", "compose")
    first = svc.deploy("app", "here")
    assert first.active

    # Second deploy is unhealthy: it fails, first stays active.
    svc2 = LoomService(svc._store, driver_factory=make_factory(healthy=False))
    second = svc2.deploy("app", "here")
    assert second.state == DeploymentState.FAILED.value
    assert second.active is False
    still = svc2._store.get_active_deployment(first.project_id, first.host_id)
    assert still is not None and still.id == first.id


def test_apply_driver_error_fails_closed(tmp_path):
    svc, _ = _svc(tmp_path, raise_on_run=True)
    svc.add_host("here", "local")
    svc.add_project("app", "compose")
    dep = svc.deploy("app", "here")
    assert dep.state == DeploymentState.FAILED.value
    assert "compose up failed" in dep.message


def test_second_deploy_supersedes_first(tmp_path):
    svc, _ = _svc(tmp_path, healthy=True)
    svc.add_host("here", "local")
    svc.add_project("app", "compose")
    first = svc.deploy("app", "here")
    second = svc.deploy("app", "here")
    assert second.active is True
    assert second.previous_id == first.id
    refreshed_first = svc._store.get_deployment(first.id)
    assert refreshed_first.state == DeploymentState.SUPERSEDED.value
    assert refreshed_first.active is False


def test_apply_twice_is_conflict(tmp_path):
    svc, _ = _svc(tmp_path, healthy=True)
    svc.add_host("here", "local")
    svc.add_project("app", "compose")
    planned = svc.plan_deploy("app", "here")
    svc.apply_deploy(planned.id)
    with pytest.raises(LoomConflictError):
        svc.apply_deploy(planned.id)  # no longer 'planned'


def test_apply_blocks_unresolved_conflict_plans(tmp_path):
    svc, factory = _svc(tmp_path, healthy=True)
    host = svc.add_host("box", "ssh", address="1.2.3.4", user="root")
    svc.add_project("app", "compose")

    planned = svc.plan_deploy("app", host.id)
    assert planned.plan is not None
    assert planned.plan.has_conflict

    with pytest.raises(LoomConflictError, match="unresolved conflicts"):
        svc.apply_deploy(planned.id)
    assert factory.last is None


# -- rollback ---------------------------------------------------------------


def test_rollback_reactivates_previous(tmp_path):
    svc, _ = _svc(tmp_path, healthy=True)
    svc.add_host("here", "local")
    svc.add_project("app", "compose")
    first = svc.deploy("app", "here", source_ref="v1")
    svc.deploy("app", "here", source_ref="v2")  # now active, first superseded

    rolled = svc.rollback("app", "here")
    assert rolled.state == DeploymentState.ACTIVE.value
    assert rolled.active is True
    assert "rollback to" in rolled.message
    # Exactly one active deployment remains.
    actives = [d for d in svc.list_deployments("app") if d.active]
    assert len(actives) == 1
    assert actives[0].id == rolled.id


def test_rollback_without_history_conflicts(tmp_path):
    svc, _ = _svc(tmp_path, healthy=True)
    svc.add_host("here", "local")
    svc.add_project("app", "compose")
    svc.deploy("app", "here")  # only one release
    with pytest.raises(LoomConflictError):
        svc.rollback("app", "here")


# -- status -----------------------------------------------------------------


def test_status_summary(tmp_path):
    svc, _ = _svc(tmp_path, healthy=True)
    svc.add_host("here", "local")
    svc.add_project("app", "compose")
    svc.deploy("app", "here")
    status = svc.status()
    assert status["hosts"] == 1
    assert status["projects"] == 1
    assert status["deployments"] == 1
    assert len(status["active"]) == 1
