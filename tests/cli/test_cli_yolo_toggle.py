"""Regression tests for the CLI ``/yolo`` in-chat toggle.

The CLI toggle routes through ``enable_session_yolo`` /
``disable_session_yolo`` (matching the gateway and TUI ``/yolo`` paths) and
binds ``self.session_id`` as the active approval session key around each
``run_conversation`` call so ``is_current_session_yolo_enabled()`` resolves
against the same key the toggle writes under.

We test ``_toggle_yolo`` and ``_is_session_yolo_active`` as unbound methods
against a minimal stand-in object that exposes only the attribute they
read (``session_id``). This avoids the heavy ``FabricCLI`` construction
path used in ``test_cli_init.py``, which is incompatible with this test
file's path layout — ``FabricCLI.__init__`` imports a lot of optional
state we don't need here.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import tools.approval as approval_module
from cli import FabricCLI


SESSION_KEY = "test-cli-yolo-session"


@pytest.fixture(autouse=True)
def _clear_approval_state(monkeypatch):
    """Clear the session-scoped YOLO bypass around every test."""
    approval_module.clear_session(SESSION_KEY)
    approval_module.clear_session("default")
    yield
    approval_module.clear_session(SESSION_KEY)
    approval_module.clear_session("default")


def _make_stand_in(session_id: str = SESSION_KEY) -> SimpleNamespace:
    """Minimal stand-in exposing only ``session_id``.

    ``_toggle_yolo`` and ``_is_session_yolo_active`` are both pure methods
    that only read ``self.session_id`` — no other CLI state is touched.
    Calling them as unbound functions against this stand-in is equivalent
    to invoking them on a fully-constructed ``FabricCLI`` for the
    behaviour under test, and avoids the brittle prompt_toolkit / config
    stubbing required to instantiate ``FabricCLI`` from this test file.
    """
    return SimpleNamespace(session_id=session_id)


class TestToggleYoloIsSessionScoped:
    """The CLI /yolo handler mutates only the target session's state."""

    def test_toggle_yolo_enables_session_bypass(self):
        stand_in = _make_stand_in()

        assert approval_module.is_session_yolo_enabled(SESSION_KEY) is False

        with patch("cli._cprint"):
            FabricCLI._toggle_yolo(stand_in)

        assert approval_module.is_session_yolo_enabled(SESSION_KEY) is True

    def test_toggle_yolo_disables_session_bypass_on_second_call(self):
        stand_in = _make_stand_in()
        with patch("cli._cprint"):
            FabricCLI._toggle_yolo(stand_in)  # ON
            assert approval_module.is_session_yolo_enabled(SESSION_KEY) is True
            FabricCLI._toggle_yolo(stand_in)  # OFF
            assert approval_module.is_session_yolo_enabled(SESSION_KEY) is False

    def test_toggle_yolo_falls_back_to_default_when_session_id_missing(self):
        """An edge case during CLI bootstrap: a ``/yolo`` triggered before the
        session id is set should not blow up, and should land under the
        ``default`` session key so the bypass still takes effect for any code
        that resolves against the default key."""
        stand_in = _make_stand_in(session_id="")
        with patch("cli._cprint"):
            FabricCLI._toggle_yolo(stand_in)

        assert approval_module.is_session_yolo_enabled("default") is True

    def test_two_independent_sessions_are_isolated(self):
        """``/yolo`` toggled in one session must not bypass approvals in
        another session — mirrors the gateway-side invariant."""
        cli_a = _make_stand_in(session_id="session-yolo-a")
        cli_b = _make_stand_in(session_id="session-yolo-b")

        try:
            with patch("cli._cprint"):
                FabricCLI._toggle_yolo(cli_a)

            assert approval_module.is_session_yolo_enabled("session-yolo-a") is True
            assert approval_module.is_session_yolo_enabled("session-yolo-b") is False
        finally:
            approval_module.clear_session("session-yolo-a")
            approval_module.clear_session("session-yolo-b")


class TestIsSessionYoloActiveHelper:
    """The status-bar helper reads the live session-yolo state."""

    def test_helper_reflects_toggle(self):
        stand_in = _make_stand_in()

        assert FabricCLI._is_session_yolo_active(stand_in) is False

        with patch("cli._cprint"):
            FabricCLI._toggle_yolo(stand_in)

        assert FabricCLI._is_session_yolo_active(stand_in) is True

        with patch("cli._cprint"):
            FabricCLI._toggle_yolo(stand_in)

        assert FabricCLI._is_session_yolo_active(stand_in) is False

class TestToggleYoloEndToEnd:
    """End-to-end: a dangerous command must auto-approve through the same
    ``check_all_command_guards`` path the terminal tool uses."""

    def test_toggle_yolo_bypasses_dangerous_command_check(self):
        stand_in = _make_stand_in()

        token = approval_module.set_current_session_key(SESSION_KEY)
        try:
            with patch("cli._cprint"):
                FabricCLI._toggle_yolo(stand_in)  # YOLO ON

            result = approval_module.check_all_command_guards(
                "rm -rf /tmp/scratch-xyzzy", "local",
            )
            assert result["approved"] is True, (
                f"YOLO toggle should auto-approve dangerous commands, got: {result}"
            )
        finally:
            approval_module.reset_current_session_key(token)


class TestIsSessionYoloActiveAttrSafety:
    """The status-bar helper runs against partially-constructed CLI fixtures
    (tests use ``FabricCLI.__new__(FabricCLI)`` to skip ``__init__``). It must
    not raise ``AttributeError`` when ``session_id`` is absent — the
    status-bar builders swallow exceptions silently and lose every field
    after the failure, producing a regression that's hard to track back to
    the helper."""

    def test_helper_survives_missing_session_id_attr(self):
        # SimpleNamespace WITHOUT session_id mimics __new__-built fixtures.
        from types import SimpleNamespace
        no_attr = SimpleNamespace()
        # Must return False, not raise.
        assert FabricCLI._is_session_yolo_active(no_attr) is False


class TestSessionRotationTransfersYolo:
    """When the CLI's ``session_id`` rotates mid-run (``/branch``, auto
    compression continuation), YOLO state keyed under the old id must move
    to the new id. Otherwise the user's ``/yolo ON`` silently reverts on
    the next turn — the same UX failure mode this PR set out to fix.
    Mirrors ``tui_gateway/server.py`` ~line 1297-1305."""

    def test_transfer_moves_yolo_to_new_session(self):
        stand_in = _make_stand_in(session_id="old-id")
        try:
            approval_module.enable_session_yolo("old-id")
            assert approval_module.is_session_yolo_enabled("old-id") is True

            FabricCLI._transfer_session_yolo(stand_in, "old-id", "new-id")

            assert approval_module.is_session_yolo_enabled("new-id") is True
            assert approval_module.is_session_yolo_enabled("old-id") is False
        finally:
            approval_module.clear_session("old-id")
            approval_module.clear_session("new-id")

    def test_transfer_is_noop_when_yolo_was_off(self):
        stand_in = _make_stand_in(session_id="old-id")
        try:
            FabricCLI._transfer_session_yolo(stand_in, "old-id", "new-id")
            assert approval_module.is_session_yolo_enabled("new-id") is False
            assert approval_module.is_session_yolo_enabled("old-id") is False
        finally:
            approval_module.clear_session("old-id")
            approval_module.clear_session("new-id")

    def test_transfer_is_noop_when_ids_match(self):
        stand_in = _make_stand_in(session_id="same-id")
        try:
            approval_module.enable_session_yolo("same-id")
            FabricCLI._transfer_session_yolo(stand_in, "same-id", "same-id")
            # Must NOT have been disabled — same-id == same-id is a no-op,
            # not a "disable then re-enable" round-trip.
            assert approval_module.is_session_yolo_enabled("same-id") is True
        finally:
            approval_module.clear_session("same-id")

    def test_transfer_handles_empty_inputs_safely(self):
        stand_in = _make_stand_in(session_id="x")
        # Both directions of empty input should be safe no-ops; nothing
        # to transfer from "" / to "".
        FabricCLI._transfer_session_yolo(stand_in, "", "new")
        FabricCLI._transfer_session_yolo(stand_in, "old", "")
        # Neither key should have been touched.
        assert approval_module.is_session_yolo_enabled("new") is False
        assert approval_module.is_session_yolo_enabled("old") is False
