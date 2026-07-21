"""Functional tests for ``loom_command`` (the ``fabric loom`` dispatcher).

These exercise the real CLI logic against a temp-backed :class:`LoomService`
with a fake driver factory, so no Docker/SSH is touched. ``open_service`` is
monkeypatched to hand back that service.
"""

from __future__ import annotations

import argparse

import pytest

import fabric_cli.loom.cli as loom_cli
from fabric_cli.loom.cli import loom_command
from fabric_cli.loom.service import LoomService
from fabric_cli.loom.store import LoomStore
from fabric_cli.subcommands.loom import build_loom_parser
from tests.loom._fakes import make_factory


def _parse(argv):
    parser = argparse.ArgumentParser(prog="fabric")
    subparsers = parser.add_subparsers(dest="command")
    build_loom_parser(subparsers, cmd_loom=lambda a: 0)
    return parser.parse_args(argv)


@pytest.fixture
def patched_service(tmp_path, monkeypatch):
    """Point ``open_service`` at a fresh temp-backed service each call."""
    factory = make_factory(healthy=True)

    def _open():
        store = LoomStore(db_path=tmp_path / "loom.db")
        return LoomService(store, driver_factory=factory)

    monkeypatch.setattr(loom_cli, "open_service", _open)
    return factory


def test_host_add_then_status(patched_service, capsys):
    rc = loom_command(_parse(["loom", "host", "add", "here", "--kind", "local"]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "here" in out

    rc = loom_command(_parse(["loom", "status"]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Hosts" in out


def test_host_list(patched_service, capsys):
    assert loom_command(_parse(["loom", "host", "add", "here"])) == 0
    capsys.readouterr()
    rc = loom_command(_parse(["loom", "host", "list"]))
    assert rc == 0
    assert "here" in capsys.readouterr().out


def test_project_add(patched_service, capsys):
    rc = loom_command(
        _parse(["loom", "project", "add", "app", "--source", "/srv/app"])
    )
    assert rc == 0
    assert "app" in capsys.readouterr().out


def test_deploy_yes_reaches_active(patched_service, capsys):
    assert loom_command(_parse(["loom", "host", "add", "here"])) == 0
    assert loom_command(_parse(["loom", "project", "add", "app"])) == 0
    capsys.readouterr()

    rc = loom_command(_parse(["loom", "deploy", "app", "here", "--yes"]))
    assert rc == 0
    assert "active" in capsys.readouterr().out.lower()


def test_deploy_with_plan_confirmation(patched_service, monkeypatch, capsys):
    assert loom_command(_parse(["loom", "host", "add", "here"])) == 0
    assert loom_command(_parse(["loom", "project", "add", "app"])) == 0
    capsys.readouterr()

    monkeypatch.setattr(loom_cli, "prompt_yes_no", lambda *a, **k: True)
    rc = loom_command(_parse(["loom", "deploy", "app", "here"]))
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "active" in out


def test_deploy_plan_declined_makes_no_change(patched_service, monkeypatch, capsys):
    assert loom_command(_parse(["loom", "host", "add", "here"])) == 0
    assert loom_command(_parse(["loom", "project", "add", "app"])) == 0
    capsys.readouterr()

    monkeypatch.setattr(loom_cli, "prompt_yes_no", lambda *a, **k: False)
    rc = loom_command(_parse(["loom", "deploy", "app", "here"]))
    assert rc == 0
    assert "abort" in capsys.readouterr().out.lower()
    # Nothing became active.
    rc = loom_command(_parse(["loom", "status"]))
    assert "none" in capsys.readouterr().out.lower()


def test_deploy_unknown_project_returns_error(patched_service, capsys):
    assert loom_command(_parse(["loom", "host", "add", "here"])) == 0
    capsys.readouterr()

    rc = loom_command(_parse(["loom", "deploy", "ghost", "here", "--yes"]))
    assert rc == 1
    err = capsys.readouterr().out.lower()
    assert "no such project" in err


def test_setup_registers_local_host(patched_service, capsys):
    rc = loom_command(_parse(["loom", "setup"]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "this-machine" in out

    # Idempotent: second run does not error or duplicate.
    rc = loom_command(_parse(["loom", "setup"]))
    assert rc == 0
    rc = loom_command(_parse(["loom", "status"]))
    assert rc == 0
    assert "Hosts:       1" in capsys.readouterr().out
