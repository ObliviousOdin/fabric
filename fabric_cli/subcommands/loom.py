"""``fabric loom`` subcommand parser.

Builds the ``loom`` command group (Fabric's built-in deployment plane) and its
nested sub-actions. The single handler is injected as ``cmd_loom`` so this
module does not import ``fabric_cli.main`` (cycle avoidance), mirroring the
other extracted parser builders under ``fabric_cli/subcommands/``.
"""

from __future__ import annotations

from typing import Callable


def build_loom_parser(subparsers, *, cmd_loom: Callable) -> None:
    """Attach the ``loom`` command group (and its sub-actions) to ``subparsers``."""
    loom_parser = subparsers.add_parser(
        "loom",
        help="Deployment plane (hosts, projects, deploys)",
        description=(
            "Loom — Fabric's built-in deployment plane. Register hosts and "
            "projects, then plan, apply, and roll back deployments."
        ),
    )
    loom_subparsers = loom_parser.add_subparsers(dest="loom_command")

    # loom setup — guided quick start
    loom_subparsers.add_parser(
        "setup",
        help="Guided quick setup (registers this machine and prints next steps)",
    )

    # loom status
    loom_subparsers.add_parser("status", help="Show hosts, projects, and active deploys")

    # loom host ...
    host_parser = loom_subparsers.add_parser("host", help="Manage deployment hosts")
    host_subparsers = host_parser.add_subparsers(dest="loom_host_command")

    host_add = host_subparsers.add_parser("add", help="Register a host")
    host_add.add_argument("name", help="Host name")
    host_add.add_argument(
        "--kind",
        choices=("local", "ssh"),
        default="local",
        help="Host kind (default: local)",
    )
    host_add.add_argument("--address", default="", help="SSH address (ssh hosts)")
    host_add.add_argument("--user", default="", help="SSH user (ssh hosts)")
    host_add.add_argument(
        "--port", type=int, default=22, help="SSH port (default: 22)"
    )
    host_add.add_argument(
        "--key", dest="key", default="", help="Path to the SSH private key (ssh hosts)"
    )

    host_subparsers.add_parser("list", help="List registered hosts")

    host_scan = host_subparsers.add_parser(
        "scan", help="Run a read-only adoption scan of a host"
    )
    host_scan.add_argument("ref", help="Host id or name")

    host_remove = host_subparsers.add_parser("remove", help="Remove a host")
    host_remove.add_argument("ref", help="Host id or name")

    # loom project ...
    project_parser = loom_subparsers.add_parser(
        "project", help="Manage deployable projects"
    )
    project_subparsers = project_parser.add_subparsers(dest="loom_project_command")

    project_add = project_subparsers.add_parser("add", help="Register a project")
    project_add.add_argument("name", help="Project name")
    project_add.add_argument(
        "--kind",
        choices=("compose", "fabric-hosted"),
        default="compose",
        help="Project kind (default: compose)",
    )
    project_add.add_argument(
        "--source", default="", help="Source path or reference for the project"
    )
    project_add.add_argument(
        "--compose-file", dest="compose_file", help="Compose file name"
    )
    project_add.add_argument(
        "--health-url", dest="health_url", help="Health-check URL"
    )
    project_add.add_argument("--env-file", dest="env_file", help="Env file path")

    project_subparsers.add_parser("list", help="List registered projects")

    project_remove = project_subparsers.add_parser("remove", help="Remove a project")
    project_remove.add_argument("ref", help="Project id or name")

    # loom deploy
    deploy_parser = loom_subparsers.add_parser(
        "deploy", help="Plan and apply a deployment"
    )
    deploy_parser.add_argument("project", help="Project id or name")
    deploy_parser.add_argument("host", help="Host id or name")
    deploy_parser.add_argument(
        "--source-ref", dest="source_ref", default="", help="Source ref to deploy"
    )
    deploy_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the plan confirmation and apply immediately",
    )
    deploy_parser.add_argument(
        "--allow-destructive",
        dest="allow_destructive",
        action="store_true",
        help="Allow a plan that contains destructive steps",
    )

    # loom rollback
    rollback_parser = loom_subparsers.add_parser(
        "rollback", help="Roll a project back to a prior release"
    )
    rollback_parser.add_argument("project", help="Project id or name")
    rollback_parser.add_argument("host", help="Host id or name")
    rollback_parser.add_argument(
        "--to", default="", help="Deployment id to roll back to (default: previous)"
    )

    # loom logs
    logs_parser = loom_subparsers.add_parser("logs", help="Show a deployment's logs")
    logs_parser.add_argument("deployment_id", help="Deployment id")

    loom_parser.set_defaults(func=cmd_loom)
