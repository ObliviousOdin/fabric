"""Tests for the setup wizard's returning-user behavior.

On an existing install:
- Bare `fabric setup` drops straight into the full reconfigure wizard
  (every prompt shows the current value as its default).
- `fabric setup --quick` runs the narrower "fill in missing items" flow.
- `fabric setup --reconfigure` is a backwards-compat alias for the
  bare-setup default.

On a fresh install, all three are no-ops — fall through to first-time setup.
"""

from argparse import Namespace
from contextlib import ExitStack
from unittest.mock import patch

import pytest


def _make_setup_args(**overrides):
    return Namespace(
        non_interactive=overrides.get("non_interactive", False),
        section=overrides.get("section", None),
        reset=overrides.get("reset", False),
        reconfigure=overrides.get("reconfigure", False),
        quick=overrides.get("quick", False),
    )


@pytest.fixture
def existing_install(tmp_path, monkeypatch):
    """Simulate a returning user with an existing configured install."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


@pytest.fixture
def fresh_install(tmp_path, monkeypatch):
    """Simulate a first-time user with no existing configuration."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    # The global test harness exposes the full upstream catalog for broad
    # compatibility tests. First-run Fabric tests must exercise the actual
    # curated customer default instead.
    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
    monkeypatch.delenv("FABRIC_MODEL_PROVIDERS", raising=False)
    return home


def _enter_existing_install_patches(stack, **extra):
    """Apply standard existing-install mocks via an ExitStack.

    Returns a dict of mocks from the `extra` kwargs (which map mock-name to
    target path) so callers can assert on them.
    """
    # Unconditional mocks (no return values to assert against).
    for target, kwargs in [
        ("fabric_cli.setup.ensure_fabric_home", {}),
        ("fabric_cli.setup.is_interactive_stdin", {"return_value": True}),
        ("fabric_cli.config.is_managed", {"return_value": False}),
        ("fabric_cli.setup.load_config", {"return_value": {}}),
        ("fabric_cli.setup.save_config", {}),
        ("fabric_cli.setup.get_env_value", {"return_value": None}),
        ("fabric_cli.auth.get_active_provider", {"return_value": "openrouter"}),
        ("fabric_cli.setup._print_setup_summary", {}),
        ("fabric_cli.setup._offer_openclaw_migration", {"return_value": False}),
    ]:
        stack.enter_context(patch(target, **kwargs))

    # Named mocks caller wants to assert on.
    named = {}
    for name, target in extra.items():
        named[name] = stack.enter_context(patch(target))
    return named


def _enter_fresh_install_patches(stack, **extra):
    for target, kwargs in [
        ("fabric_cli.setup.ensure_fabric_home", {}),
        ("fabric_cli.setup.is_interactive_stdin", {"return_value": True}),
        ("fabric_cli.config.is_managed", {"return_value": False}),
        ("fabric_cli.setup.load_config", {"return_value": {}}),
        ("fabric_cli.setup.save_config", {}),
        ("fabric_cli.auth.get_active_provider", {"return_value": None}),
        ("fabric_cli.setup.get_env_value", {"return_value": None}),
        ("fabric_cli.setup._offer_openclaw_migration", {"return_value": False}),
    ]:
        stack.enter_context(patch(target, **kwargs))

    named = {}
    for name, target_spec in extra.items():
        if isinstance(target_spec, tuple):
            target, kwargs = target_spec
            named[name] = stack.enter_context(patch(target, **kwargs))
        else:
            named[name] = stack.enter_context(patch(target_spec))
    return named


class TestExistingInstallDefault:
    """Bare `fabric setup` on an existing install = full reconfigure wizard."""

    def test_bare_setup_runs_full_reconfigure_without_menu(self, existing_install):
        """No menu, no prompt_choice — just run every section in sequence."""
        args = _make_setup_args()  # no flags

        with ExitStack() as stack:
            m = _enter_existing_install_patches(
                stack,
                prompt_choice="fabric_cli.setup.prompt_choice",
                quick="fabric_cli.setup._run_quick_setup",
                model="fabric_cli.setup.setup_model_provider",
                terminal="fabric_cli.setup.setup_terminal_backend",
                agent="fabric_cli.setup.setup_agent_settings",
                gateway="fabric_cli.setup.setup_gateway",
                tools="fabric_cli.setup.setup_tools",
            )
            from fabric_cli.setup import run_setup_wizard
            run_setup_wizard(args)

        # No menu shown.
        m["prompt_choice"].assert_not_called()
        # Quick-setup path NOT taken.
        m["quick"].assert_not_called()
        # Model/terminal/gateway/tools run; agent settings are no longer
        # prompted on existing installs (they keep their tuned values).
        m["model"].assert_called_once()
        m["terminal"].assert_called_once()
        m["agent"].assert_not_called()
        m["gateway"].assert_called_once()
        m["tools"].assert_called_once()

    def test_reconfigure_flag_is_backwards_compat_noop(self, existing_install):
        """`fabric setup --reconfigure` behaves the same as bare `fabric setup`."""
        args = _make_setup_args(reconfigure=True)

        with ExitStack() as stack:
            m = _enter_existing_install_patches(
                stack,
                prompt_choice="fabric_cli.setup.prompt_choice",
                model="fabric_cli.setup.setup_model_provider",
                terminal="fabric_cli.setup.setup_terminal_backend",
                agent="fabric_cli.setup.setup_agent_settings",
                gateway="fabric_cli.setup.setup_gateway",
                tools="fabric_cli.setup.setup_tools",
            )
            from fabric_cli.setup import run_setup_wizard
            run_setup_wizard(args)

        m["prompt_choice"].assert_not_called()
        m["model"].assert_called_once()
        m["terminal"].assert_called_once()
        m["agent"].assert_not_called()
        m["gateway"].assert_called_once()
        m["tools"].assert_called_once()


class TestQuickFlag:
    """`--quick` on an existing install runs the fill-missing flow."""

    def test_quick_flag_runs_quick_setup_only(self, existing_install):
        args = _make_setup_args(quick=True)

        with ExitStack() as stack:
            m = _enter_existing_install_patches(
                stack,
                quick="fabric_cli.setup._run_quick_setup",
                model="fabric_cli.setup.setup_model_provider",
                terminal="fabric_cli.setup.setup_terminal_backend",
                agent="fabric_cli.setup.setup_agent_settings",
                gateway="fabric_cli.setup.setup_gateway",
                tools="fabric_cli.setup.setup_tools",
            )
            from fabric_cli.setup import run_setup_wizard
            run_setup_wizard(args)

        m["quick"].assert_called_once()
        # Full reconfigure sections must NOT run.
        m["model"].assert_not_called()
        m["terminal"].assert_not_called()
        m["agent"].assert_not_called()
        m["gateway"].assert_not_called()
        m["tools"].assert_not_called()


class TestFreshInstall:
    """On a fresh install (no active provider), flags are no-ops."""

    @staticmethod
    def _guided_flow_patches(stack):
        return _enter_fresh_install_patches(
            stack,
            prompt=("fabric_cli.setup.prompt_choice", {"return_value": 0}),
            model="fabric_cli.setup.setup_model_provider",
            terminal="fabric_cli.setup.setup_terminal_backend",
            defaults="fabric_cli.setup._apply_default_agent_settings",
            gateway="fabric_cli.setup.setup_gateway",
            tools="fabric_cli.setup.setup_tools",
        )

    @staticmethod
    def _assert_guided_flow(m):
        m["prompt"].assert_called_once()
        m["model"].assert_called_once()
        m["terminal"].assert_not_called()
        m["defaults"].assert_called_once()
        m["gateway"].assert_called_once()
        m["tools"].assert_called_once()

    def test_bare_setup_runs_first_time_flow(self, fresh_install):
        args = _make_setup_args()

        with ExitStack() as stack:
            m = self._guided_flow_patches(stack)
            from fabric_cli.setup import run_setup_wizard
            run_setup_wizard(args)

        self._assert_guided_flow(m)

    def test_reconfigure_on_fresh_install_falls_through(self, fresh_install):
        args = _make_setup_args(reconfigure=True)

        with ExitStack() as stack:
            m = self._guided_flow_patches(stack)
            from fabric_cli.setup import run_setup_wizard
            run_setup_wizard(args)

        self._assert_guided_flow(m)

    def test_quick_on_fresh_install_falls_through(self, fresh_install):
        args = _make_setup_args(quick=True)

        with ExitStack() as stack:
            m = self._guided_flow_patches(stack)
            from fabric_cli.setup import run_setup_wizard
            run_setup_wizard(args)

        self._assert_guided_flow(m)

    def test_full_setup_runs_terminal_configuration(self, fresh_install):
        args = _make_setup_args()

        with ExitStack() as stack:
            m = _enter_fresh_install_patches(
                stack,
                prompt=("fabric_cli.setup.prompt_choice", {"return_value": 1}),
                model="fabric_cli.setup.setup_model_provider",
                terminal="fabric_cli.setup.setup_terminal_backend",
                defaults="fabric_cli.setup._apply_default_agent_settings",
                gateway="fabric_cli.setup.setup_gateway",
                tools="fabric_cli.setup.setup_tools",
            )
            from fabric_cli.setup import run_setup_wizard

            run_setup_wizard(args)

        m["prompt"].assert_called_once()
        m["model"].assert_called_once()
        m["terminal"].assert_called_once()
        m["defaults"].assert_called_once()
        m["gateway"].assert_called_once()
        m["tools"].assert_called_once()


class TestArgparse:
    """The flags are plumbed through argparse to cmd_setup."""

    def test_reconfigure_flag_reaches_cmd_setup(self, monkeypatch):
        import sys
        from fabric_cli.main import main

        captured = {}
        monkeypatch.setattr(
            "fabric_cli.setup.run_setup_wizard",
            lambda args: captured.setdefault("args", args),
        )
        monkeypatch.setattr(sys, "argv", ["hermes", "setup", "--reconfigure"])
        try:
            main()
        except SystemExit:
            pass
        assert captured["args"].reconfigure is True
        assert captured["args"].quick is False

    def test_quick_flag_reaches_cmd_setup(self, monkeypatch):
        import sys
        from fabric_cli.main import main

        captured = {}
        monkeypatch.setattr(
            "fabric_cli.setup.run_setup_wizard",
            lambda args: captured.setdefault("args", args),
        )
        monkeypatch.setattr(sys, "argv", ["hermes", "setup", "--quick"])
        try:
            main()
        except SystemExit:
            pass
        assert captured["args"].quick is True
        assert captured["args"].reconfigure is False

    def test_bare_setup_has_both_flags_false(self, monkeypatch):
        import sys
        from fabric_cli.main import main

        captured = {}
        monkeypatch.setattr(
            "fabric_cli.setup.run_setup_wizard",
            lambda args: captured.setdefault("args", args),
        )
        monkeypatch.setattr(sys, "argv", ["hermes", "setup"])
        try:
            main()
        except SystemExit:
            pass
        assert captured["args"].reconfigure is False
        assert captured["args"].quick is False
