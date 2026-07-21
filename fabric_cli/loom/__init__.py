"""Loom — Fabric's built-in deployment plane.

Loom turns a source (a Docker Compose project, a folder, or the built-in
"hosted Fabric" template) into a running application on infrastructure the
operator chooses: **this machine** or **a Linux host reached over SSH**. It is
Fabric's own, Python-native answer to the Dockplane/OpenShip deployment control
plane described in ``docs/dockplane-integration`` — the same product goals
(plan-before-mutation, one source of truth, least-privilege agents,
recoverability) implemented natively so it can be driven from the Fabric CLI,
the dashboard, the desktop app, and Fabric agents through one code path.

Layers (each importable in isolation, so surfaces stay thin):

- :mod:`fabric_cli.loom.brand`   — central brand/config constants.
- :mod:`fabric_cli.loom.models`  — domain entities and state machines.
- :mod:`fabric_cli.loom.store`   — the per-profile SQLite store (``loom.db``).
- :mod:`fabric_cli.loom.drivers` — runtime drivers (local / SSH) + factory.
- :mod:`fabric_cli.loom.service` — orchestration: plan, apply, roll back.
- :mod:`fabric_cli.loom.cli`     — ``fabric loom`` command implementation.

The design goal is that the CLI, the dashboard API, and the agent tools all
call :class:`fabric_cli.loom.service.LoomService` — never the store or drivers
directly — so business rules and audit live in exactly one place.
"""

from __future__ import annotations

from fabric_cli.loom.brand import BRAND
from fabric_cli.loom.errors import (
    LoomConflictError,
    LoomDriverError,
    LoomError,
    LoomNotFoundError,
    LoomValidationError,
)
from fabric_cli.loom.models import (
    Deployment,
    DeploymentState,
    Host,
    HostState,
    Plan,
    PlanStep,
    Project,
)
from fabric_cli.loom.service import LoomService, open_service

__all__ = [
    "BRAND",
    "Deployment",
    "DeploymentState",
    "Host",
    "HostState",
    "LoomConflictError",
    "LoomDriverError",
    "LoomError",
    "LoomNotFoundError",
    "LoomService",
    "LoomValidationError",
    "Plan",
    "PlanStep",
    "Project",
    "open_service",
]
