"""Unit tests for the ``fabric loom`` parser builder.

Confirms ``build_loom_parser`` wires up every subcommand, the nested
host/project actions, their options, and the single ``func=cmd_loom`` dispatch.
"""

from __future__ import annotations

import argparse

from fabric_cli.subcommands.loom import build_loom_parser


def _sentinel(args):  # pragma: no cover - only identity is asserted
    return "loom-handler"


def _build():
    parser = argparse.ArgumentParser(prog="fabric")
    subparsers = parser.add_subparsers(dest="command")
    build_loom_parser(subparsers, cmd_loom=_sentinel)
    return parser


def test_top_level_subcommands_present():
    parser = _build()
    cases = {
        "setup": ["loom", "setup"],
        "status": ["loom", "status"],
        "host": ["loom", "host", "list"],
        "project": ["loom", "project", "list"],
        "deploy": ["loom", "deploy", "app", "here"],
        "rollback": ["loom", "rollback", "app", "here"],
        "logs": ["loom", "logs", "dep_1"],
    }
    for expected, argv in cases.items():
        ns = parser.parse_args(argv)
        assert ns.command == "loom"
        assert ns.loom_command == expected


def test_host_nested_actions_set_dest():
    parser = _build()
    for action, argv in (
        ("add", ["loom", "host", "add", "box"]),
        ("list", ["loom", "host", "list"]),
        ("scan", ["loom", "host", "scan", "box"]),
        ("remove", ["loom", "host", "remove", "box"]),
    ):
        ns = parser.parse_args(argv)
        assert ns.loom_command == "host"
        assert ns.loom_host_command == action


def test_project_nested_actions_set_dest():
    parser = _build()
    for action, argv in (
        ("add", ["loom", "project", "add", "app"]),
        ("list", ["loom", "project", "list"]),
        ("remove", ["loom", "project", "remove", "app"]),
    ):
        ns = parser.parse_args(argv)
        assert ns.loom_command == "project"
        assert ns.loom_project_command == action


def test_host_add_options():
    parser = _build()
    ns = parser.parse_args(
        [
            "loom", "host", "add", "box",
            "--kind", "ssh",
            "--address", "1.2.3.4",
            "--user", "root",
            "--port", "2222",
            "--key", "/tmp/id_ed25519",
        ]
    )
    assert ns.name == "box"
    assert ns.kind == "ssh"
    assert ns.address == "1.2.3.4"
    assert ns.user == "root"
    assert ns.port == 2222
    assert ns.key == "/tmp/id_ed25519"


def test_host_add_defaults():
    parser = _build()
    ns = parser.parse_args(["loom", "host", "add", "here"])
    assert ns.kind == "local"
    assert ns.port == 22


def test_project_add_options():
    parser = _build()
    ns = parser.parse_args(
        [
            "loom", "project", "add", "app",
            "--kind", "fabric-hosted",
            "--source", "/srv/app",
            "--compose-file", "docker-compose.yml",
            "--health-url", "http://localhost:8080/health",
            "--env-file", ".env",
        ]
    )
    assert ns.name == "app"
    assert ns.kind == "fabric-hosted"
    assert ns.source == "/srv/app"
    assert ns.compose_file == "docker-compose.yml"
    assert ns.health_url == "http://localhost:8080/health"
    assert ns.env_file == ".env"


def test_deploy_options():
    parser = _build()
    ns = parser.parse_args(
        [
            "loom", "deploy", "app", "here",
            "--source-ref", "v2",
            "--yes",
            "--allow-destructive",
        ]
    )
    assert ns.project == "app"
    assert ns.host == "here"
    assert ns.source_ref == "v2"
    assert ns.yes is True
    assert ns.allow_destructive is True


def test_deploy_defaults():
    parser = _build()
    ns = parser.parse_args(["loom", "deploy", "app", "here"])
    assert ns.yes is False
    assert ns.allow_destructive is False
    assert ns.source_ref == ""


def test_rollback_options():
    parser = _build()
    ns = parser.parse_args(["loom", "rollback", "app", "here", "--to", "dep_9"])
    assert ns.project == "app"
    assert ns.host == "here"
    assert ns.to == "dep_9"


def test_dispatch_func_is_injected_handler():
    parser = _build()
    ns = parser.parse_args(["loom", "status"])
    assert ns.func is _sentinel
