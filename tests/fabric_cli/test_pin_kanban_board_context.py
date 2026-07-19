"""Tests for the chat session's typed active-board snapshot."""

import importlib

from fabric_cli.kanban_runtime import (
    configure_kanban_runtime_context,
    get_kanban_runtime_context,
)


def test_pin_writes_resolved_board_when_context_unset(monkeypatch):
    main_mod = importlib.import_module("fabric_cli.main")
    import fabric_cli.kanban_db as kdb

    monkeypatch.setattr(kdb, "get_current_board", lambda: "space")
    main_mod._pin_kanban_board_context()

    assert get_kanban_runtime_context().board == "space"


def test_pin_does_not_overwrite_existing_context(monkeypatch):
    configure_kanban_runtime_context(board="preset")
    main_mod = importlib.import_module("fabric_cli.main")
    import fabric_cli.kanban_db as kdb

    def _explode():
        raise AssertionError("get_current_board must not run when context is set")

    monkeypatch.setattr(kdb, "get_current_board", _explode)
    main_mod._pin_kanban_board_context()

    assert get_kanban_runtime_context().board == "preset"


def test_pin_swallows_resolution_failures(monkeypatch):
    main_mod = importlib.import_module("fabric_cli.main")
    import fabric_cli.kanban_db as kdb

    def _boom():
        raise RuntimeError("disk gone")

    monkeypatch.setattr(kdb, "get_current_board", _boom)
    main_mod._pin_kanban_board_context()

    assert get_kanban_runtime_context().board == ""
