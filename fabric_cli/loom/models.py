"""Loom domain entities and state machines.

These are plain dataclasses plus two enums with explicit legal transitions.
They hold no I/O — the store persists them and the service transitions them —
so the state machine can be unit-tested in isolation.

The state names follow the deployment/host state machines in
``docs/dockplane-integration/source-spec/PRODUCT_SPEC.md`` (sections 12.1 and
12.2), reduced to the subset the MVP actually drives.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Recognised kinds ----------------------------------------------------------

HOST_KINDS = ("local", "ssh")
PROJECT_KINDS = ("compose", "fabric-hosted")

# Plan step classification (mirrors the spec's create/reuse/conflict/destructive
# classification for host mutations, so a plan is honest about what it touches).
PLAN_STEP_KINDS = ("create", "reuse", "conflict", "destructive", "info")


class DeploymentState(str, enum.Enum):
    """Top-level deployment states.

    A ``PLANNED`` deployment has a plan but has not touched infrastructure —
    this is the plan-before-mutation boundary. ``apply`` walks it forward
    through the build/start/health phases to ``ACTIVE``. Terminal failure and
    lifecycle states never leave a healthy release running when a candidate
    fails before traffic switch.
    """

    PLANNED = "planned"
    BUILDING = "building"
    STARTING = "starting"
    HEALTH_CHECKING = "health_checking"
    ACTIVE = "active"
    FAILED = "failed"
    CANCELED = "canceled"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_DEPLOYMENT_STATES


_TERMINAL_DEPLOYMENT_STATES = frozenset(
    {
        DeploymentState.FAILED,
        DeploymentState.CANCELED,
        DeploymentState.SUPERSEDED,
        DeploymentState.ROLLED_BACK,
    }
)

# Legal forward transitions for the happy path plus failure/cancel edges.
_DEPLOYMENT_TRANSITIONS: Dict[DeploymentState, frozenset] = {
    DeploymentState.PLANNED: frozenset(
        {DeploymentState.BUILDING, DeploymentState.CANCELED}
    ),
    DeploymentState.BUILDING: frozenset(
        {DeploymentState.STARTING, DeploymentState.FAILED, DeploymentState.CANCELED}
    ),
    DeploymentState.STARTING: frozenset(
        {
            DeploymentState.HEALTH_CHECKING,
            DeploymentState.FAILED,
            DeploymentState.CANCELED,
        }
    ),
    DeploymentState.HEALTH_CHECKING: frozenset(
        {DeploymentState.ACTIVE, DeploymentState.FAILED, DeploymentState.CANCELED}
    ),
    DeploymentState.ACTIVE: frozenset(
        {DeploymentState.SUPERSEDED, DeploymentState.ROLLED_BACK}
    ),
    # Terminal states have no outgoing edges.
    DeploymentState.FAILED: frozenset(),
    DeploymentState.CANCELED: frozenset(),
    DeploymentState.SUPERSEDED: frozenset(
        # A superseded release can be reactivated by an explicit rollback.
        {DeploymentState.ACTIVE}
    ),
    DeploymentState.ROLLED_BACK: frozenset({DeploymentState.ACTIVE}),
}


def can_transition(src: DeploymentState, dst: DeploymentState) -> bool:
    """True when ``src -> dst`` is a legal deployment transition."""
    return dst in _DEPLOYMENT_TRANSITIONS.get(src, frozenset())


class HostState(str, enum.Enum):
    """Host lifecycle states (read-only scan precedes any provisioning)."""

    NEW = "new"
    SCANNING = "scanning"
    SCANNED = "scanned"
    READY = "ready"
    UNREACHABLE = "unreachable"
    CREDENTIAL_ERROR = "credential_error"


@dataclass
class PlanStep:
    """One line of a deployment plan: what Loom intends to do, and how risky.

    ``kind`` is one of :data:`PLAN_STEP_KINDS`. ``destructive`` steps require
    explicit confirmation before :meth:`LoomService.apply_deploy` will run.
    """

    action: str
    detail: str = ""
    kind: str = "info"

    def to_dict(self) -> Dict[str, Any]:
        return {"action": self.action, "detail": self.detail, "kind": self.kind}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanStep":
        return cls(
            action=str(data.get("action", "")),
            detail=str(data.get("detail", "")),
            kind=str(data.get("kind", "info")),
        )


@dataclass
class Plan:
    """An ordered set of steps produced before any mutation occurs."""

    steps: List[PlanStep] = field(default_factory=list)
    summary: str = ""

    @property
    def has_destructive(self) -> bool:
        return any(step.kind == "destructive" for step in self.steps)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "steps": [s.to_dict() for s in self.steps],
            "has_destructive": self.has_destructive,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Plan":
        return cls(
            summary=str(data.get("summary", "")),
            steps=[PlanStep.from_dict(s) for s in data.get("steps", [])],
        )


@dataclass
class Host:
    """A deployment target: this machine, or a Linux host reached over SSH."""

    id: str
    name: str
    kind: str
    state: str = HostState.NEW.value
    address: str = ""
    user: str = ""
    port: int = 22
    ssh_key_path: str = ""
    host_key_fingerprint: str = ""
    created_at: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Project:
    """A deployable unit and how to build/run it.

    ``config`` holds kind-specific settings, e.g. for ``compose``:
    ``{"compose_file": "docker-compose.yml", "health_url": "http://...",
    "env_file": ".env"}``.
    """

    id: str
    name: str
    kind: str
    source: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    created_at: int = 0


@dataclass
class Deployment:
    """An immutable release attempt bound to one project + host.

    The plan is snapshotted at creation and does not change after ``apply``
    starts; a changed plan is a new deployment (spec DEP-002).
    """

    id: str
    project_id: str
    host_id: str
    state: str = DeploymentState.PLANNED.value
    source_ref: str = ""
    plan: Optional[Plan] = None
    active: bool = False
    previous_id: str = ""
    message: str = ""
    logs: str = ""
    created_at: int = 0
    updated_at: int = 0
