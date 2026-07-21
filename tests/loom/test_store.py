"""Round-trip tests for the Loom SQLite store."""

from __future__ import annotations

from fabric_cli.loom.models import Deployment, Host, Plan, PlanStep, Project
from fabric_cli.loom.store import LoomStore


def _store(tmp_path):
    return LoomStore(db_path=tmp_path / "loom.db")


def test_host_crud(tmp_path):
    with _store(tmp_path) as store:
        host = store.create_host(Host(id="", name="box", kind="ssh", address="1.2.3.4", user="root"))
        assert host.id.startswith("host_")
        assert host.created_at > 0

        got = store.get_host(host.id)
        assert got is not None
        assert got.name == "box"
        assert got.address == "1.2.3.4"

        assert store.get_host_by_name("box").id == host.id

        host.meta = {"scan": {"docker_available": True}}
        store.update_host(host)
        assert store.get_host(host.id).meta["scan"]["docker_available"] is True

        assert len(store.list_hosts()) == 1
        store.delete_host(host.id)
        assert store.get_host(host.id) is None


def test_project_crud(tmp_path):
    with _store(tmp_path) as store:
        proj = store.create_project(
            Project(id="", name="site", kind="compose", source="/srv/site",
                    config={"compose_file": "docker-compose.yml"})
        )
        assert proj.id.startswith("proj_")
        got = store.get_project_by_name("site")
        assert got.config["compose_file"] == "docker-compose.yml"
        assert len(store.list_projects()) == 1
        store.delete_project(proj.id)
        assert store.get_project(proj.id) is None


def test_deployment_crud_and_plan_persistence(tmp_path):
    with _store(tmp_path) as store:
        plan = Plan(summary="deploy", steps=[PlanStep("up", "compose up", "create")])
        dep = store.create_deployment(
            Deployment(id="", project_id="p1", host_id="h1", plan=plan, source_ref="abc123")
        )
        assert dep.id.startswith("dep_")
        got = store.get_deployment(dep.id)
        assert got.plan is not None
        assert got.plan.summary == "deploy"
        assert got.plan.steps[0].action == "up"
        assert got.source_ref == "abc123"

        got.state = "active"
        got.active = True
        store.update_deployment(got)
        active = store.get_active_deployment("p1", "h1")
        assert active is not None
        assert active.id == dep.id

        assert len(store.list_deployments(project_id="p1")) == 1
        assert store.list_deployments(project_id="p1", limit=1)[0].id == dep.id


def test_reopening_db_is_safe(tmp_path):
    path = tmp_path / "loom.db"
    with LoomStore(db_path=path) as store:
        store.create_project(Project(id="", name="a", kind="compose"))
    # Reopen: schema is idempotent, data persists.
    with LoomStore(db_path=path) as store:
        assert len(store.list_projects()) == 1
