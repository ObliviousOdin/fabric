"""``fabric loom`` command implementation.

Thin CLI surface over :class:`fabric_cli.loom.service.LoomService`. Every
command opens a service, does its work, and closes the underlying store in a
``finally`` block. All business rules, state transitions, and the
plan-before-mutation boundary live in the service; this module only parses
namespaces, prints results, and maps :class:`LoomError` to a nonzero exit code.
"""

from __future__ import annotations

from fabric_cli.cli_output import (
    print_error,
    print_header,
    print_info,
    print_success,
    print_warning,
    prompt_yes_no,
)
from fabric_cli.loom import LoomError, open_service
from fabric_cli.loom.models import DeploymentState


def loom_command(args) -> int:
    """Dispatch ``fabric loom <subcommand>``. Returns a process exit code."""
    command = getattr(args, "loom_command", None)
    if command in (None, ""):
        print_info("usage: fabric loom <setup|status|host|project|deploy|rollback|logs>")
        return 1

    handlers = {
        "setup": _cmd_setup,
        "status": _cmd_status,
        "host": _cmd_host,
        "project": _cmd_project,
        "deploy": _cmd_deploy,
        "rollback": _cmd_rollback,
        "logs": _cmd_logs,
    }
    handler = handlers.get(command)
    if handler is None:
        print_error(f"unknown loom command: {command}")
        return 1
    return handler(args)


# -- setup ------------------------------------------------------------------


def _cmd_setup(args) -> int:
    """Guided quick setup: ensure a local host exists and print next steps."""
    service = open_service()
    try:
        print_header("Loom quick setup")
        existing = None
        for host in service.list_hosts():
            if host.name == "this-machine":
                existing = host
                break
        if existing is None:
            host = service.add_host("this-machine", "local")
            print_success(f"Registered local host {host.name!r} ({host.id})")
        else:
            print_info(f"Local host {existing.name!r} already registered")
        print_header("Next steps")
        print_info("1. Register a project:  fabric loom project add myapp --source .")
        print_info("2. Deploy it:           fabric loom deploy myapp this-machine")
        print_info("3. Check status:        fabric loom status")
        return 0
    except LoomError as exc:
        print_error(exc.message)
        return 1
    finally:
        service._store.close()


# -- status -----------------------------------------------------------------


def _cmd_status(args) -> int:
    service = open_service()
    try:
        status = service.status()
        print_header("Loom status")
        print_info(f"Hosts:       {status['hosts']}")
        print_info(f"Projects:    {status['projects']}")
        print_info(f"Deployments: {status['deployments']}")
        active = status.get("active", [])
        if not active:
            print_info("Active deployments: none")
        else:
            print_header(f"Active deployments ({len(active)})")
            for item in active:
                print_info(
                    f"{item['deployment']}  project={item['project_id']}  "
                    f"host={item['host_id']}  state={item['state']}"
                )
        return 0
    except LoomError as exc:
        print_error(exc.message)
        return 1
    finally:
        service._store.close()


# -- hosts ------------------------------------------------------------------


def _cmd_host(args) -> int:
    action = getattr(args, "loom_host_command", None)
    if action in (None, ""):
        print_info("usage: fabric loom host <add|list|scan|remove>")
        return 1
    service = open_service()
    try:
        if action == "add":
            host = service.add_host(
                args.name,
                args.kind,
                address=getattr(args, "address", "") or "",
                user=getattr(args, "user", "") or "",
                port=getattr(args, "port", 22),
                ssh_key_path=getattr(args, "key", "") or "",
            )
            print_success(f"Added host {host.name!r} ({host.id}) [{host.state}]")
            return 0
        if action == "list":
            hosts = service.list_hosts()
            if not hosts:
                print_info("No hosts registered")
                return 0
            print_header(f"Hosts ({len(hosts)})")
            for host in hosts:
                detail = f"kind={host.kind} state={host.state}"
                if host.kind == "ssh":
                    detail += f" address={host.user}@{host.address}:{host.port}"
                print_info(f"{host.id}  {host.name}  {detail}")
            return 0
        if action == "scan":
            host = service.scan_host(args.ref)
            print_success(f"Scanned {host.name!r}: state={host.state}")
            return 0
        if action == "remove":
            service.remove_host(args.ref)
            print_success(f"Removed host {args.ref!r}")
            return 0
        print_error(f"unknown host command: {action}")
        return 1
    except LoomError as exc:
        print_error(exc.message)
        return 1
    finally:
        service._store.close()


# -- projects ---------------------------------------------------------------


def _cmd_project(args) -> int:
    action = getattr(args, "loom_project_command", None)
    if action in (None, ""):
        print_info("usage: fabric loom project <add|list|remove>")
        return 1
    service = open_service()
    try:
        if action == "add":
            config = {}
            compose_file = getattr(args, "compose_file", None)
            health_url = getattr(args, "health_url", None)
            env_file = getattr(args, "env_file", None)
            if compose_file:
                config["compose_file"] = compose_file
            if health_url:
                config["health_url"] = health_url
            if env_file:
                config["env_file"] = env_file
            project = service.add_project(
                args.name,
                args.kind,
                source=getattr(args, "source", "") or "",
                config=config or None,
            )
            print_success(f"Added project {project.name!r} ({project.id}) [{project.kind}]")
            return 0
        if action == "list":
            projects = service.list_projects()
            if not projects:
                print_info("No projects registered")
                return 0
            print_header(f"Projects ({len(projects)})")
            for project in projects:
                detail = f"kind={project.kind}"
                if project.source:
                    detail += f" source={project.source}"
                print_info(f"{project.id}  {project.name}  {detail}")
            return 0
        if action == "remove":
            service.remove_project(args.ref)
            print_success(f"Removed project {args.ref!r}")
            return 0
        print_error(f"unknown project command: {action}")
        return 1
    except LoomError as exc:
        print_error(exc.message)
        return 1
    finally:
        service._store.close()


# -- deploy -----------------------------------------------------------------


def _print_plan(plan) -> None:
    """Print the steps of a plan, flagging conflicts and destructive actions."""
    print_header(plan.summary or "Deployment plan")
    for step in plan.steps:
        line = f"{step.action}"
        if step.detail:
            line += f" — {step.detail}"
        if step.kind == "destructive":
            print_warning(f"[destructive] {line}")
        elif step.kind == "conflict":
            print_warning(f"[conflict] {line}")
        else:
            print_info(line)


def _report_deployment(dep) -> int:
    """Print a deployment's resulting state; return exit code (1 on FAILED)."""
    if dep.state == DeploymentState.ACTIVE.value:
        print_success(f"Deployment {dep.id} is active")
        return 0
    if dep.state == DeploymentState.FAILED.value:
        print_error(f"Deployment {dep.id} failed: {dep.message or 'unknown error'}")
        return 1
    print_info(f"Deployment {dep.id} is {dep.state}")
    return 0


def _cmd_deploy(args) -> int:
    service = open_service()
    try:
        if getattr(args, "yes", False):
            dep = service.deploy(
                args.project,
                args.host,
                source_ref=getattr(args, "source_ref", "") or "",
                allow_destructive=getattr(args, "allow_destructive", False),
            )
            return _report_deployment(dep)

        planned = service.plan_deploy(
            args.project,
            args.host,
            source_ref=getattr(args, "source_ref", "") or "",
        )
        if planned.plan is not None:
            _print_plan(planned.plan)
        if not prompt_yes_no("Apply this plan?"):
            print_info("Aborted; no changes made")
            return 0
        dep = service.apply_deploy(
            planned.id,
            allow_destructive=getattr(args, "allow_destructive", False),
        )
        return _report_deployment(dep)
    except LoomError as exc:
        print_error(exc.message)
        return 1
    finally:
        service._store.close()


# -- rollback ---------------------------------------------------------------


def _cmd_rollback(args) -> int:
    service = open_service()
    try:
        dep = service.rollback(
            args.project, args.host, to=getattr(args, "to", "") or ""
        )
        return _report_deployment(dep)
    except LoomError as exc:
        print_error(exc.message)
        return 1
    finally:
        service._store.close()


# -- logs -------------------------------------------------------------------


def _cmd_logs(args) -> int:
    service = open_service()
    try:
        text = service.logs(args.deployment_id)
        if text:
            print(text.rstrip())
        else:
            print_info("No logs for this deployment")
        return 0
    except LoomError as exc:
        print_error(exc.message)
        return 1
    finally:
        service._store.close()
