"""Loom deployment-plane tool for Fabric agents.

Exposes a single compressed action-oriented ``loom`` tool so agents can drive
Fabric's built-in deployment plane (:class:`fabric_cli.loom.service.LoomService`)
without touching the store or drivers directly. Read-only actions return plain
data; mutating actions (``deploy``/``rollback``) are gated behind the same
human-approval gate that Tier-2 dangerous commands use, so a prompt-injected
agent cannot silently mutate infrastructure.

The core deploy-plane logic lives under ``fabric_cli/loom/`` and is not touched
here — this module is a thin, schema-bearing surface over it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fabric_cli.loom import LoomError, open_service
from tools.approval import request_tool_approval
from tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclass -> plain-dict converters
#
# Handlers must return JSON strings built from plain dicts — never dataclass
# objects (json.dumps can't serialize them). Convert explicitly so the wire
# shape is stable regardless of internal model changes.
# ---------------------------------------------------------------------------


def _host_to_dict(host) -> Dict[str, Any]:
    return {
        "id": host.id,
        "name": host.name,
        "kind": host.kind,
        "state": host.state,
    }


def _project_to_dict(project) -> Dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "kind": project.kind,
    }


def _deployment_to_dict(dep) -> Dict[str, Any]:
    return {
        "id": dep.id,
        "state": dep.state,
        "active": dep.active,
        "message": dep.message,
    }


# Enumerated actions. Mutating actions require human approval before running.
_MUTATING_ACTIONS = frozenset({"deploy", "rollback"})
_VALID_ACTIONS = frozenset(
    {
        "status",
        "hosts",
        "projects",
        "deployments",
        "plan",
        "deploy",
        "rollback",
        "logs",
    }
)


def loom_tool(args, **kwargs) -> str:
    """Dispatch a single Loom deployment-plane action.

    Read-only actions (``status``/``hosts``/``projects``/``deployments``/
    ``logs``/``plan``) call the service and return plain-dict data. Mutating
    actions (``deploy``/``rollback``) first escalate to the human-approval gate
    and only run when approved. ``LoomError`` is caught and returned as a
    structured tool error carrying the stable ``code``.
    """
    action = (args.get("action") or "").strip().lower()
    if not action:
        return tool_error("action is required")
    if action not in _VALID_ACTIONS:
        return tool_error(
            f"unknown action {action!r}; expected one of "
            f"{', '.join(sorted(_VALID_ACTIONS))}"
        )

    project = (args.get("project") or "").strip()
    host = (args.get("host") or "").strip()
    deployment_id = (args.get("deployment_id") or "").strip()
    source_ref = (args.get("source_ref") or "").strip()
    to = (args.get("to") or "").strip()

    # Per-action required-arg validation, before opening the service.
    if action in ("plan", "deploy", "rollback") and (not project or not host):
        return tool_error(f"action {action!r} requires both project and host")
    if action == "logs" and not deployment_id:
        return tool_error("action 'logs' requires deployment_id")

    service = None
    try:
        service = open_service()

        if action == "status":
            return tool_result({"success": True, "status": service.status()})

        if action == "hosts":
            return tool_result(
                {
                    "success": True,
                    "hosts": [_host_to_dict(h) for h in service.list_hosts()],
                }
            )

        if action == "projects":
            return tool_result(
                {
                    "success": True,
                    "projects": [
                        _project_to_dict(p) for p in service.list_projects()
                    ],
                }
            )

        if action == "deployments":
            deps = service.list_deployments(project_ref=project)
            return tool_result(
                {
                    "success": True,
                    "deployments": [_deployment_to_dict(d) for d in deps],
                }
            )

        if action == "logs":
            return tool_result(
                {
                    "success": True,
                    "deployment_id": deployment_id,
                    "logs": service.logs(deployment_id),
                }
            )

        if action == "plan":
            dep = service.plan_deploy(project, host, source_ref=source_ref)
            plan_dict = dep.plan.to_dict() if dep.plan is not None else {}
            return tool_result(
                {
                    "success": True,
                    "deployment_id": dep.id,
                    "state": dep.state,
                    "plan": plan_dict,
                }
            )

        if action == "deploy":
            decision = request_tool_approval(
                "loom",
                f"Deploy {project} to {host}?",
                approval_callback=kwargs.get("approval_callback"),
            )
            if not decision.get("approved"):
                return tool_error(decision.get("message") or "deploy denied")
            dep = service.deploy(project, host, source_ref=source_ref)
            return tool_result(
                {"success": True, "deployment": _deployment_to_dict(dep)}
            )

        if action == "rollback":
            target_msg = f" to {to}" if to else ""
            decision = request_tool_approval(
                "loom",
                f"Roll back {project} on {host}{target_msg}?",
                approval_callback=kwargs.get("approval_callback"),
            )
            if not decision.get("approved"):
                return tool_error(decision.get("message") or "rollback denied")
            dep = service.rollback(project, host, to=to)
            return tool_result(
                {"success": True, "deployment": _deployment_to_dict(dep)}
            )

        # Unreachable: action was validated against _VALID_ACTIONS above.
        return tool_error(f"unknown action {action!r}")

    except LoomError as e:
        return tool_error(f"[{e.code}] {e.message}")
    finally:
        if service is not None:
            try:
                service._store.close()
            except Exception:
                logger.debug("loom: failed to close store", exc_info=True)


LOOM_SCHEMA = {
    "name": "loom",
    "description": """Drive Fabric's built-in deployment plane (Loom).

Inspect and operate deployments through a single action-oriented tool.

Read-only actions:
  - status: compact summary (host/project/deployment counts + active releases).
  - hosts: list deployment target hosts.
  - projects: list deployable projects.
  - deployments: list deployments (optionally filter by project).
  - logs: fetch the log stream for one deployment (needs deployment_id).
  - plan: produce a plan WITHOUT touching infrastructure (needs project + host).

Mutating actions (require human approval before they run):
  - deploy: plan then apply a release (needs project + host).
  - rollback: roll back a project on a host to a prior release (needs project + host;
    optional 'to' deployment id).

Prefer 'plan' first to preview what a deploy will do. Deploy/rollback pause for a
human to confirm and are blocked when no approver is present.""",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "status",
                    "hosts",
                    "projects",
                    "deployments",
                    "plan",
                    "deploy",
                    "rollback",
                    "logs",
                ],
                "description": (
                    "The operation to perform. deploy/rollback mutate "
                    "infrastructure and require approval."
                ),
            },
            "project": {
                "type": "string",
                "description": (
                    "Project id or name. Required for plan/deploy/rollback; "
                    "optional filter for deployments."
                ),
            },
            "host": {
                "type": "string",
                "description": (
                    "Host id or name. Required for plan/deploy/rollback."
                ),
            },
            "deployment_id": {
                "type": "string",
                "description": "Deployment id. Required for logs.",
            },
            "source_ref": {
                "type": "string",
                "description": (
                    "Optional source reference (e.g. a git ref) to record on "
                    "plan/deploy."
                ),
            },
            "to": {
                "type": "string",
                "description": (
                    "Optional target deployment id for rollback. When omitted, "
                    "rolls back to the most recent superseded release."
                ),
            },
        },
        "required": ["action"],
    },
}


def _loom_available() -> bool:
    """Loom is always available — it is an internal, Python-native plane with
    no external daemon or credential to gate on (drivers are resolved per-host
    at apply time). Return True unconditionally."""
    return True


registry.register(
    name="loom",
    toolset="loom",
    schema=LOOM_SCHEMA,
    handler=loom_tool,
    check_fn=_loom_available,
    emoji="🧵",
)
