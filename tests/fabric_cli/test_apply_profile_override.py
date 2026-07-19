"""Regression tests for _apply_profile_override FABRIC_HOME guard (issue #22502).

When FABRIC_HOME is set to the fabric root (e.g. systemd hardcodes
FABRIC_HOME=/root/.fabric), _apply_profile_override must still read
active_profile and update FABRIC_HOME to the profile directory.

When FABRIC_HOME is already a profile directory (.../profiles/<name>),
_apply_profile_override must trust it and return without re-reading
active_profile (child-process inheritance contract).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace



def _run_apply_profile_override(
    tmp_path, monkeypatch, *, fabric_home: str | None, active_profile: str | None,
    argv: list[str] | None = None,
):
    """Run _apply_profile_override in isolation.

    Returns the value of os.environ["FABRIC_HOME"] after the call,
    or None if unset.
    """
    fabric_root = tmp_path / ".fabric"
    fabric_root.mkdir(parents=True, exist_ok=True)

    if active_profile is not None:
        (fabric_root / "active_profile").write_text(active_profile)

    if active_profile and active_profile != "default":
        (fabric_root / "profiles" / active_profile).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    if fabric_home is not None:
        monkeypatch.setenv("FABRIC_HOME", fabric_home)
    else:
        monkeypatch.delenv("FABRIC_HOME", raising=False)

    monkeypatch.setattr(sys, "argv", argv or ["fabric", "gateway", "start"])

    from fabric_cli.main import _apply_profile_override
    _apply_profile_override()

    return os.environ.get("FABRIC_HOME")


class TestApplyProfileOverrideFabricHomeGuard:
    """Regression guard for issue #22502.

    Verifies that FABRIC_HOME pointing to the fabric root does NOT suppress
    the active_profile check, while FABRIC_HOME already pointing to a
    profile directory IS trusted as-is.
    """

    def test_fabric_home_at_root_with_active_profile_is_redirected(
        self, tmp_path, monkeypatch
    ):
        """FABRIC_HOME=/root/.fabric + active_profile=coder must redirect
        FABRIC_HOME to .../profiles/coder.

        Bug scenario from #22502: systemd sets FABRIC_HOME to the fabric root
        and the user switches to a profile via `fabric profile use`.
        Before the fix, the guard returned early and active_profile was ignored.
        """
        fabric_root = tmp_path / ".fabric"
        fabric_root.mkdir(parents=True, exist_ok=True)

        result = _run_apply_profile_override(
            tmp_path,
            monkeypatch,
            fabric_home=str(fabric_root),
            active_profile="coder",
        )

        assert result is not None, "FABRIC_HOME must be set after profile redirect"
        assert "profiles" in result, (
            f"Expected FABRIC_HOME to point into profiles/ dir, got: {result!r}"
        )
        assert result.endswith("coder"), (
            f"Expected FABRIC_HOME to end with 'coder', got: {result!r}"
        )

    def test_fabric_home_already_profile_dir_is_trusted(self, tmp_path, monkeypatch):
        """FABRIC_HOME=.../profiles/coder must not be overridden even when
        active_profile says something different.

        Preserves the child-process inheritance contract: a subprocess spawned
        with FABRIC_HOME already set to a specific profile must stay in that
        profile.
        """
        fabric_root = tmp_path / ".fabric"
        profile_dir = fabric_root / "profiles" / "coder"
        profile_dir.mkdir(parents=True, exist_ok=True)

        (fabric_root / "active_profile").write_text("other")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("FABRIC_HOME", str(profile_dir))
        monkeypatch.setattr(sys, "argv", ["fabric", "gateway", "start"])

        from fabric_cli.main import _apply_profile_override
        _apply_profile_override()

        assert os.environ.get("FABRIC_HOME") == str(profile_dir), (
            "FABRIC_HOME must remain unchanged when already pointing to a profile dir"
        )

    def test_fabric_home_unset_reads_active_profile(self, tmp_path, monkeypatch):
        """FABRIC_HOME unset + active_profile=coder resolves the profile directory."""
        result = _run_apply_profile_override(
            tmp_path,
            monkeypatch,
            fabric_home=None,
            active_profile="coder",
        )

        assert result is not None
        assert "coder" in result
        assert os.environ.get("FABRIC_HOME") == result

    def test_explicit_profile_overrides_inherited_fabric_home(
        self, tmp_path, monkeypatch
    ):
        """An explicit ``-p`` wins over an inherited FABRIC_HOME profile."""
        fabric_root = tmp_path / ".fabric"
        inherited_home = fabric_root / "profiles" / "inherited"
        selected_home = fabric_root / "profiles" / "coder"
        inherited_home.mkdir(parents=True)
        selected_home.mkdir(parents=True)

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("FABRIC_HOME", str(inherited_home))
        monkeypatch.setattr(
            sys,
            "argv",
            ["fabric", "gateway", "start", "-p", "coder"],
        )

        from fabric_cli.main import _apply_profile_override

        _apply_profile_override()

        assert os.environ.get("FABRIC_HOME") == str(selected_home)
        assert sys.argv == ["fabric", "gateway", "start"]

    def test_sudo_explicit_profile_resolves_invoking_users_profile(self, tmp_path, monkeypatch):
        """sudo elias ... should resolve `-p elias` under SUDO_USER, not root."""
        root_home = tmp_path / "root"
        user_home = tmp_path / "home" / "fabric"
        profile_dir = user_home / ".fabric" / "profiles" / "elias"
        profile_dir.mkdir(parents=True, exist_ok=True)
        (root_home / ".fabric").mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(Path, "home", lambda: root_home)
        monkeypatch.setenv("SUDO_USER", "fabric")
        monkeypatch.delenv("FABRIC_HOME", raising=False)
        monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
        monkeypatch.setattr(sys, "argv", ["fabric", "-p", "elias", "gateway", "install", "--system"])

        import pwd

        monkeypatch.setattr(pwd, "getpwnam", lambda name: SimpleNamespace(pw_dir=str(user_home)))

        from fabric_cli.main import _apply_profile_override
        _apply_profile_override()

        assert os.environ.get("FABRIC_HOME") == str(profile_dir)
        assert sys.argv == ["fabric", "gateway", "install", "--system"]

    def test_fabric_home_unset_default_profile_no_redirect(self, tmp_path, monkeypatch):
        """active_profile=default must not redirect FABRIC_HOME."""
        fabric_root = tmp_path / ".fabric"
        fabric_root.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("FABRIC_HOME", raising=False)
        monkeypatch.setattr(sys, "argv", ["fabric", "gateway", "start"])
        (fabric_root / "active_profile").write_text("default")

        from fabric_cli.main import _apply_profile_override
        _apply_profile_override()

        assert os.environ.get("FABRIC_HOME") is None

    def test_subcommand_profile_flag_is_not_consumed(self, tmp_path, monkeypatch):
        """Command argv flags named --profile must stay with that command.

        Docker Desktop's MCP Toolkit uses `docker mcp gateway run --profile ...`.
        When that argv is passed through `fabric mcp add --args`, the early
        profile pre-parser must not interpret the Docker profile as a Fabric
        profile.
        """
        fabric_root = tmp_path / ".fabric"
        fabric_root.mkdir(parents=True, exist_ok=True)
        argv = [
            "fabric",
            "mcp",
            "add",
            "docker-research",
            "--command",
            "docker",
            "--args",
            "mcp",
            "gateway",
            "run",
            "--profile",
            "research",
        ]

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("FABRIC_HOME", raising=False)
        monkeypatch.setattr(sys, "argv", list(argv))

        from fabric_cli.main import _apply_profile_override
        _apply_profile_override()

        assert os.environ.get("FABRIC_HOME") is None
        assert sys.argv == argv

    def test_profile_after_chat_subcommand_is_still_consumed(self, tmp_path, monkeypatch):
        """Profile flags historically work after normal Fabric subcommands."""
        result = _run_apply_profile_override(
            tmp_path,
            monkeypatch,
            fabric_home=None,
            active_profile="coder",
            argv=["fabric", "chat", "-p", "coder", "-q", "hello"],
        )

        assert result is not None
        assert result.endswith("coder")
        assert sys.argv == ["fabric", "chat", "-q", "hello"]

    def test_top_level_profile_after_value_flag_is_consumed(self, tmp_path, monkeypatch):
        """Top-level --profile still works after other top-level value flags."""
        result = _run_apply_profile_override(
            tmp_path,
            monkeypatch,
            fabric_home=None,
            active_profile="coder",
            argv=["fabric", "-m", "gpt-5", "--profile", "coder", "chat"],
        )

        assert result is not None
        assert result.endswith("coder")
        assert sys.argv == ["fabric", "-m", "gpt-5", "chat"]

    def test_top_level_profile_after_continue_flag_is_consumed(self, tmp_path, monkeypatch):
        """--continue has an optional value, so a following --profile is a flag."""
        result = _run_apply_profile_override(
            tmp_path,
            monkeypatch,
            fabric_home=None,
            active_profile="coder",
            argv=["fabric", "--continue", "--profile", "coder"],
        )

        assert result is not None
        assert result.endswith("coder")
        assert sys.argv == ["fabric", "--continue"]


class TestExplicitServiceProfilesIgnoreStickyState:
    """Supervised service slots must select their profile through argv."""

    def test_explicit_default_does_not_follow_active_profile(
        self, tmp_path, monkeypatch
    ):
        """``-p default`` selects the root even when another profile is sticky."""
        fabric_root = tmp_path / ".fabric"
        fabric_root.mkdir(parents=True, exist_ok=True)
        (fabric_root / "active_profile").write_text("briefer")
        (fabric_root / "profiles" / "briefer").mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("FABRIC_HOME", str(fabric_root))
        monkeypatch.setattr(
            sys, "argv", ["fabric", "-p", "default", "gateway", "run", "--replace"]
        )

        from fabric_cli.main import _apply_profile_override
        _apply_profile_override()

        assert os.environ.get("FABRIC_HOME") == str(fabric_root), (
            "Explicit default gateway must stay on the root profile, not be "
            f"hijacked by active_profile; got {os.environ.get('FABRIC_HOME')!r}"
        )

    def test_non_supervised_run_still_follows_active_profile(
        self, tmp_path, monkeypatch
    ):
        """A normal `fabric gateway run` still honors active_profile."""
        result = _run_apply_profile_override(
            tmp_path,
            monkeypatch,
            fabric_home=None,
            active_profile="briefer",
            argv=["fabric", "gateway", "run"],
        )

        assert result is not None
        assert result.endswith("briefer")

    def test_explicit_named_profile_flag_still_wins(self, tmp_path, monkeypatch):
        """A named service slot's explicit profile wins over sticky state."""
        fabric_root = tmp_path / ".fabric"
        fabric_root.mkdir(parents=True, exist_ok=True)
        (fabric_root / "active_profile").write_text("briefer")
        (fabric_root / "profiles" / "briefer").mkdir(parents=True, exist_ok=True)
        (fabric_root / "profiles" / "coder").mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("FABRIC_HOME", raising=False)
        monkeypatch.setattr(
            sys, "argv", ["fabric", "-p", "coder", "gateway", "run", "--replace"]
        )

        from fabric_cli.main import _apply_profile_override
        _apply_profile_override()

        result = os.environ.get("FABRIC_HOME")
        assert result is not None
        assert result.endswith("coder")
