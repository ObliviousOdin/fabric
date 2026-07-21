"""LoomService — the single source of product truth.

The CLI, the dashboard API, and the agent tools all call this class; none of
them touch the store or drivers directly. That keeps business rules, state
transitions, and the plan-before-mutation boundary in one testable place, in
the spirit of the Dockplane spec's "the API is the source of product truth".

Injectable seams for tests:

- ``store``: a :class:`~fabric_cli.loom.store.LoomStore` (pass a temp DB path).
- ``driver_factory``: ``Callable[[Host], RuntimeDriver]`` — tests pass a fake so
  no real Docker/SSH runs while the plan/apply/rollback logic is exercised.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

from fabric_cli.loom.drivers import ReleaseSpec, RuntimeDriver, default_driver_factory
from fabric_cli.loom.errors import (
    LoomConflictError,
    LoomNotFoundError,
    LoomValidationError,
)
from fabric_cli.loom.models import (
    HOST_KINDS,
    PROJECT_KINDS,
    Deployment,
    DeploymentState,
    Host,
    HostState,
    Plan,
    PlanStep,
    Project,
    can_transition,
)
from fabric_cli.loom.store import LoomStore

DriverFactory = Callable[[Host], RuntimeDriver]


def open_service() -> "LoomService":
    """Open a :class:`LoomService` backed by the active profile's ``loom.db``.

    The convenience constructor every surface (CLI, dashboard API, agent tools)
    uses so store wiring lives in exactly one place. Callers own the returned
    service's store and should call ``service._store.close()`` when done, or use
    it within a short-lived request/command scope.
    """
    return LoomService(LoomStore())

# Deployment states that represent an in-flight mutation. At most one of these
# may exist per (project, host) at a time (spec DEP-004).
_IN_FLIGHT = frozenset(
    {
        DeploymentState.BUILDING.value,
        DeploymentState.STARTING.value,
        DeploymentState.HEALTH_CHECKING.value,
    }
)


class LoomService:
    def __init__(
        self,
        store: LoomStore,
        driver_factory: Optional[DriverFactory] = None,
    ) -> None:
        self._store = store
        self._driver_factory = driver_factory or default_driver_factory

    # -- validation helpers ------------------------------------------------

    @staticmethod
    def _require_name(name: str) -> str:
        name = (name or "").strip()
        if not name:
            raise LoomValidationError("name is required")
        if len(name) > 64:
            raise LoomValidationError("name must be 64 characters or fewer")
        return name

    def _resolve_host(self, ref: str) -> Host:
        host = self._store.get_host(ref) or self._store.get_host_by_name(ref)
        if host is None:
            raise LoomNotFoundError(f"no such host: {ref!r}")
        return host

    def _resolve_project(self, ref: str) -> Project:
        project = self._store.get_project(ref) or self._store.get_project_by_name(ref)
        if project is None:
            raise LoomNotFoundError(f"no such project: {ref!r}")
        return project

    # -- hosts -------------------------------------------------------------

    def add_host(
        self,
        name: str,
        kind: str,
        *,
        address: str = "",
        user: str = "",
        port: int = 22,
        ssh_key_path: str = "",
    ) -> Host:
        name = self._require_name(name)
        if kind not in HOST_KINDS:
            raise LoomValidationError(
                f"unknown host kind {kind!r}; expected one of {', '.join(HOST_KINDS)}"
            )
        if kind == "ssh" and not address:
            raise LoomValidationError("ssh hosts require an address")
        if kind == "ssh" and not user:
            raise LoomValidationError("ssh hosts require a user")
        if self._store.get_host_by_name(name) is not None:
            raise LoomConflictError(f"a host named {name!r} already exists")
        host = Host(
            id="",
            name=name,
            kind=kind,
            state=(HostState.READY.value if kind == "local" else HostState.NEW.value),
            address=address,
            user=user,
            port=port,
            ssh_key_path=ssh_key_path,
        )
        return self._store.create_host(host)

    def list_hosts(self) -> List[Host]:
        return self._store.list_hosts()

    def get_host(self, ref: str) -> Host:
        return self._resolve_host(ref)

    def remove_host(self, ref: str) -> None:
        host = self._resolve_host(ref)
        self._store.delete_host(host.id)

    def scan_host(self, ref: str) -> Host:
        """Run a read-only adoption scan and record what we learned.

        Never mutates the host; only updates Loom's record of its state.
        """
        host = self._resolve_host(ref)
        host.state = HostState.SCANNING.value
        self._store.update_host(host)
        driver = self._driver_factory(host)
        scan = driver.scan()
        host.meta["scan"] = {
            "os": scan.os,
            "arch": scan.arch,
            "docker_available": scan.docker_available,
            "notes": scan.notes,
            "at": int(time.time()),
        }
        if not scan.reachable:
            host.state = HostState.UNREACHABLE.value
        elif scan.docker_available:
            host.state = HostState.READY.value
        else:
            host.state = HostState.SCANNED.value
        self._store.update_host(host)
        return host

    # -- projects ----------------------------------------------------------

    def add_project(
        self,
        name: str,
        kind: str,
        *,
        source: str = "",
        config: Optional[Dict] = None,
    ) -> Project:
        name = self._require_name(name)
        if kind not in PROJECT_KINDS:
            raise LoomValidationError(
                f"unknown project kind {kind!r}; expected one of "
                f"{', '.join(PROJECT_KINDS)}"
            )
        if self._store.get_project_by_name(name) is not None:
            raise LoomConflictError(f"a project named {name!r} already exists")
        project = Project(
            id="",
            name=name,
            kind=kind,
            source=source,
            config=dict(config or {}),
        )
        return self._store.create_project(project)

    def list_projects(self) -> List[Project]:
        return self._store.list_projects()

    def get_project(self, ref: str) -> Project:
        return self._resolve_project(ref)

    def remove_project(self, ref: str) -> None:
        project = self._resolve_project(ref)
        self._store.delete_project(project.id)

    # -- release spec ------------------------------------------------------

    @staticmethod
    def _release_spec(project: Project) -> ReleaseSpec:
        cfg = project.config or {}
        if project.kind == "fabric-hosted":
            # The built-in template: bring up the always-on gateway + dashboard
            # + Caddy stack from the repo's deploy/ assets.
            return ReleaseSpec(
                name=project.name,
                kind=project.kind,
                workdir=cfg.get("workdir", project.source or "deploy"),
                compose_file=cfg.get("compose_file", "docker-compose.hosted.yml"),
                health_url=cfg.get("health_url", ""),
                env_file=cfg.get("env_file", ".env"),
            )
        return ReleaseSpec(
            name=project.name,
            kind=project.kind,
            workdir=cfg.get("workdir", project.source or "."),
            compose_file=cfg.get("compose_file", "docker-compose.yml"),
            health_url=cfg.get("health_url", ""),
            env_file=cfg.get("env_file", ""),
        )

    # -- planning (no mutation) -------------------------------------------

    def plan_deploy(
        self, project_ref: str, host_ref: str, *, source_ref: str = ""
    ) -> Deployment:
        """Produce a plan and persist a ``PLANNED`` deployment.

        No infrastructure is touched. Call :meth:`apply_deploy` to execute.
        """
        project = self._resolve_project(project_ref)
        host = self._resolve_host(host_ref)
        spec = self._release_spec(project)

        steps: List[PlanStep] = [
            PlanStep(
                action=f"Deploy project {project.name!r} to host {host.name!r}",
                detail=f"host kind: {host.kind}",
                kind="info",
            ),
            PlanStep(
                action="Bring up container services",
                detail=(
                    f"docker compose -f {spec.compose_file} up -d "
                    f"(workdir: {spec.workdir})"
                ),
                kind="create",
            ),
        ]
        if spec.health_url:
            steps.append(
                PlanStep(
                    action="Verify health before switching traffic",
                    detail=f"GET {spec.health_url}",
                    kind="info",
                )
            )
        else:
            steps.append(
                PlanStep(
                    action="No health probe configured",
                    detail="the release is marked active on a successful bring-up",
                    kind="info",
                )
            )
        existing = self._store.get_active_deployment(project.id, host.id)
        if existing is not None:
            steps.append(
                PlanStep(
                    action="Supersede the current active release",
                    detail=f"deployment {existing.id} will be marked superseded",
                    kind="reuse",
                )
            )
        if host.kind == "ssh" and host.state not in (
            HostState.READY.value,
            HostState.SCANNED.value,
        ):
            steps.append(
                PlanStep(
                    action="Host has not passed a scan",
                    detail=f"host state is {host.state!r}; run `loom host scan` first",
                    kind="conflict",
                )
            )

        plan = Plan(
            steps=steps,
            summary=f"Deploy {project.name} -> {host.name} ({len(steps)} steps)",
        )
        dep = Deployment(
            id="",
            project_id=project.id,
            host_id=host.id,
            state=DeploymentState.PLANNED.value,
            source_ref=source_ref,
            plan=plan,
        )
        return self._store.create_deployment(dep)

    # -- applying (mutation) ----------------------------------------------

    def _advance(self, dep: Deployment, dst: DeploymentState, log_line: str) -> None:
        src = DeploymentState(dep.state)
        if not can_transition(src, dst):
            raise LoomConflictError(
                f"illegal deployment transition {src.value} -> {dst.value}"
            )
        dep.state = dst.value
        if log_line:
            dep.logs = (dep.logs + log_line.rstrip() + "\n") if dep.logs else (
                log_line.rstrip() + "\n"
            )
        self._store.update_deployment(dep)

    def apply_deploy(
        self, deployment_id: str, *, allow_destructive: bool = False
    ) -> Deployment:
        """Execute a previously planned deployment.

        Walks ``PLANNED -> BUILDING -> STARTING -> HEALTH_CHECKING -> ACTIVE``.
        On failure before the traffic switch, the previous active release is
        left untouched (spec DEP-010).
        """
        dep = self._store.get_deployment(deployment_id)
        if dep is None:
            raise LoomNotFoundError(f"no such deployment: {deployment_id!r}")
        if dep.state != DeploymentState.PLANNED.value:
            raise LoomConflictError(
                f"deployment {dep.id} is {dep.state!r}, expected 'planned'"
            )
        if dep.plan is not None:
            if dep.plan.has_conflict:
                conflicts = [
                    step.action
                    for step in dep.plan.steps
                    if step.kind == "conflict"
                ]
                detail = "; ".join(conflicts) or "unresolved conflict"
                raise LoomConflictError(f"plan contains unresolved conflicts: {detail}")
            if dep.plan.has_destructive and not allow_destructive:
                raise LoomConflictError(
                    "plan contains destructive steps; confirm with "
                    "allow_destructive=True"
                )
        # One in-flight mutation per (project, host).
        for other in self._store.list_deployments(dep.project_id):
            if (
                other.id != dep.id
                and other.host_id == dep.host_id
                and other.state in _IN_FLIGHT
            ):
                raise LoomConflictError(
                    f"another deployment ({other.id}) is already in progress "
                    f"for this project/host"
                )

        project = self._store.get_project(dep.project_id)
        host = self._store.get_host(dep.host_id)
        if project is None or host is None:
            raise LoomNotFoundError("deployment references a missing project or host")
        spec = self._release_spec(project)
        driver = self._driver_factory(host)

        try:
            self._advance(dep, DeploymentState.BUILDING, "build: preparing release")
            self._advance(dep, DeploymentState.STARTING, "start: bringing services up")
            run_log = driver.run_release(spec)
            if run_log:
                dep.logs += run_log.rstrip() + "\n"
                self._store.update_deployment(dep)
            self._advance(
                dep, DeploymentState.HEALTH_CHECKING, "health: checking release"
            )
            healthy = driver.health_check(spec)
        except Exception as exc:  # driver failure -> fail closed, keep old release
            dep.message = str(exc)
            self._fail(dep, f"error: {exc}")
            return dep

        if not healthy:
            dep.message = "health check failed"
            self._fail(dep, "health: candidate unhealthy; previous release retained")
            return dep

        # Traffic switch: supersede the previous active release, activate this one.
        previous = self._store.get_active_deployment(dep.project_id, dep.host_id)
        if previous is not None and previous.id != dep.id:
            previous.active = False
            if DeploymentState(previous.state) == DeploymentState.ACTIVE:
                previous.state = DeploymentState.SUPERSEDED.value
            self._store.update_deployment(previous)
            dep.previous_id = previous.id
        self._advance(dep, DeploymentState.ACTIVE, "active: traffic switched")
        dep.active = True
        self._store.update_deployment(dep)
        return dep

    def _fail(self, dep: Deployment, log_line: str) -> None:
        dep.state = DeploymentState.FAILED.value
        dep.logs = (dep.logs + log_line.rstrip() + "\n") if dep.logs else (
            log_line.rstrip() + "\n"
        )
        self._store.update_deployment(dep)

    def deploy(
        self,
        project_ref: str,
        host_ref: str,
        *,
        source_ref: str = "",
        allow_destructive: bool = False,
    ) -> Deployment:
        """Convenience: plan then apply in one call."""
        planned = self.plan_deploy(project_ref, host_ref, source_ref=source_ref)
        return self.apply_deploy(planned.id, allow_destructive=allow_destructive)

    # -- rollback ----------------------------------------------------------

    def rollback(
        self, project_ref: str, host_ref: str, *, to: str = ""
    ) -> Deployment:
        """Roll back to a prior release as a new, audited operation.

        Reactivates the target release by redeploying its configuration. Not a
        silent mutation of history (spec Journey F): a fresh deployment record
        is created with the rollback intent recorded.
        """
        project = self._resolve_project(project_ref)
        host = self._resolve_host(host_ref)
        current = self._store.get_active_deployment(project.id, host.id)

        target: Optional[Deployment] = None
        if to:
            target = self._store.get_deployment(to)
            if target is None or target.project_id != project.id:
                raise LoomNotFoundError(f"no such deployment for this project: {to!r}")
        else:
            for dep in self._store.list_deployments(project.id):
                if (
                    dep.host_id == host.id
                    and not dep.active
                    and dep.state
                    in (
                        DeploymentState.SUPERSEDED.value,
                        DeploymentState.ROLLED_BACK.value,
                    )
                ):
                    target = dep
                    break
        if target is None:
            raise LoomConflictError("no previous release available to roll back to")

        new = self.deploy(
            project.id,
            host.id,
            source_ref=target.source_ref or (current.source_ref if current else ""),
        )
        if new.state == DeploymentState.ACTIVE.value:
            new.message = f"rollback to {target.id}"
            if current is not None and current.id != new.id:
                # Mark the release we rolled away from as rolled_back for clarity.
                fresh_current = self._store.get_deployment(current.id)
                if fresh_current is not None and DeploymentState(
                    fresh_current.state
                ) in (DeploymentState.SUPERSEDED, DeploymentState.ACTIVE):
                    fresh_current.state = DeploymentState.ROLLED_BACK.value
                    fresh_current.active = False
                    self._store.update_deployment(fresh_current)
            self._store.update_deployment(new)
        return new

    # -- reads -------------------------------------------------------------

    def logs(self, deployment_id: str) -> str:
        dep = self._store.get_deployment(deployment_id)
        if dep is None:
            raise LoomNotFoundError(f"no such deployment: {deployment_id!r}")
        return dep.logs

    def list_deployments(
        self, project_ref: str = "", limit: Optional[int] = None
    ) -> List[Deployment]:
        project_id = self._resolve_project(project_ref).id if project_ref else None
        return self._store.list_deployments(project_id=project_id, limit=limit)

    def status(self) -> Dict:
        """A compact summary for dashboards and ``loom status``."""
        hosts = self._store.list_hosts()
        projects = self._store.list_projects()
        deployments = self._store.list_deployments()
        active = [d for d in deployments if d.active]
        return {
            "hosts": len(hosts),
            "projects": len(projects),
            "deployments": len(deployments),
            "active": [
                {
                    "deployment": d.id,
                    "project_id": d.project_id,
                    "host_id": d.host_id,
                    "state": d.state,
                }
                for d in active
            ],
        }
