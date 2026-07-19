"""Tests for agent/file_safety.py read guards — env file blocking.

Run with:  python -m pytest tests/agent/test_file_safety.py -v
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.file_safety import (
    _BLOCKED_PROJECT_ENV_BASENAMES,
    get_read_block_error,
)


# ---------------------------------------------------------------------------
# Project-local .env file blocking (issue #20734)
# ---------------------------------------------------------------------------


class TestEnvFileReadBlocking:
    """Secret-bearing .env files must be blocked by get_read_block_error."""

    @pytest.mark.parametrize("basename", [
        ".env",
        ".env.local",
        ".env.development",
        ".env.production",
        ".env.test",
        ".env.staging",
        ".envrc",
    ])
    def test_blocked_env_basenames(self, basename):
        """All secret-bearing .env basenames are blocked regardless of directory."""
        path = f"/tmp/project/{basename}"
        error = get_read_block_error(path)
        assert error is not None, f"{basename} should be blocked"
        assert "Access denied" in error
        assert "secret-bearing" in error.lower() or "environment file" in error.lower()

    def test_blocked_env_in_subdirectory(self):
        """Nested .env files are also blocked."""
        error = get_read_block_error("/home/user/app/services/api/.env.production")
        assert error is not None

    @pytest.mark.parametrize("basename", [
        ".ENV",
        ".Env.Local",
        ".ENV.PRODUCTION",
        ".ENVRC",
    ])
    def test_blocked_env_basenames_case_insensitive(self, basename):
        """Secret-bearing .env basenames are blocked regardless of case."""
        error = get_read_block_error(f"/tmp/project/{basename}")
        assert error is not None, f"{basename} should be blocked"
        assert "Access denied" in error
        assert "environment file" in error.lower()

    def test_blocked_env_absolute_path(self):
        """Absolute paths to .env files are blocked."""
        error = get_read_block_error("/opt/myapp/.env")
        assert error is not None

    def test_allowed_env_example(self):
        """"The .env.example file is explicitly allowed — it's documentation, not a secret."""
        error = get_read_block_error("/tmp/project/.env.example")
        assert error is None

    def test_allowed_env_sample(self):
        """Other .env variants like .env.sample are allowed."""
        error = get_read_block_error("/tmp/project/.env.sample")
        assert error is None

    def test_allowed_non_env_files(self):
        """Regular files are not affected by the env guard."""
        for path in ["/tmp/project/config.yaml", "/tmp/project/main.py",
                     "/tmp/project/README.md", "/tmp/project/.gitignore"]:
            error = get_read_block_error(path)
            assert error is None, f"{path} should be allowed"

    def test_allowed_fabric_env(self):
        """Fabric's own .env inside FABRIC_HOME is NOT blocked by this rule
        (it's handled by other mechanisms). Only project-local .env is blocked."""
        # Note: fabric internal .env is in ~/.fabric/.env which is NOT a project-local
        # path, but the basename check applies to ANY .env. This is intentional —
        # even ~/.fabric/.env should not be readable via read_file.
        error = get_read_block_error(os.path.expanduser("~/.fabric/.env"))
        assert error is not None

    def test_blocked_set_is_lowercase(self):
        """All entries in the blocked set are lowercase for case-insensitive matching."""
        for name in _BLOCKED_PROJECT_ENV_BASENAMES:
            assert name == name.lower(), f"{name} should be lowercase"


# ---------------------------------------------------------------------------
# Existing cache-file blocking (regression — must still work)
# ---------------------------------------------------------------------------


class TestCacheFileReadBlocking:
    """Internal Fabric cache files must remain blocked."""

    def test_hub_index_cache_blocked(self, tmp_path):
        """Hub index-cache reads are blocked."""
        fabric_home = tmp_path / ".fabric"
        cache = fabric_home / "skills" / ".hub" / "index-cache" / "data.json"
        cache.parent.mkdir(parents=True)
        cache.write_text("{}")

        with patch("agent.file_safety._fabric_home_path", return_value=fabric_home):
            error = get_read_block_error(str(cache))
            assert error is not None
            assert "internal Fabric cache" in error

    def test_hub_directory_blocked(self, tmp_path):
        """Hub directory reads are blocked."""
        fabric_home = tmp_path / ".fabric"
        hub = fabric_home / "skills" / ".hub" / "metadata.json"
        hub.parent.mkdir(parents=True)
        hub.write_text("{}")

        with patch("agent.file_safety._fabric_home_path", return_value=fabric_home):
            error = get_read_block_error(str(hub))
            assert error is not None


class TestProviderAccountReadBlocking:
    """Provider ownership metadata and repair copies stay model-inaccessible."""

    @pytest.mark.parametrize(
        "relative",
        [
            "provider-accounts.json",
            "provider-accounts.lock",
            ".provider-accounts.json.tmp.1234.abcdef",
            ".provider-account-repair/provider-accounts.invalid-20260711.json",
            "profiles/ops/provider-accounts.json",
            "profiles/ops/provider-accounts.lock",
            "profiles/ops/.provider-accounts.json.tmp.5678.abcdef",
            "profiles/ops/.provider-account-repair/provider-accounts.invalid.json",
            "state-snapshots/snap-a/provider-accounts.json",
            "state-snapshots/snap-a/.provider-account-repair/invalid.json",
            "profiles/ops/state-snapshots/snap-b/provider-accounts.json",
            "profiles/ops/state-snapshots/snap-b/.provider-account-repair/invalid.json",
            "backups/fabric-backup-default.zip",
            "profiles/ops/backups/fabric-backup-ops.zip",
        ],
    )
    def test_blocks_default_and_named_profile_artifacts(self, tmp_path, relative):
        fabric_root = tmp_path / ".fabric"
        target = fabric_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("private-provider-account-state")

        with (
            patch("agent.file_safety._fabric_home_path", return_value=fabric_root),
            patch("agent.file_safety._fabric_root_path", return_value=fabric_root),
        ):
            error = get_read_block_error(str(target))

        assert error is not None
        assert "provider-account" in error

    def test_named_profile_denial_does_not_enumerate_profiles(
        self, tmp_path, monkeypatch
    ):
        fabric_root = tmp_path / ".fabric"
        target = (
            fabric_root
            / "profiles/ops/state-snapshots/snap/provider-accounts.json"
        )
        target.parent.mkdir(parents=True)
        target.write_text("private")
        monkeypatch.setattr(
            Path,
            "iterdir",
            lambda _path: (_ for _ in ()).throw(PermissionError("denied listing")),
        )

        with (
            patch("agent.file_safety._fabric_home_path", return_value=fabric_root),
            patch("agent.file_safety._fabric_root_path", return_value=fabric_root),
        ):
            error = get_read_block_error(str(target))

        assert error is not None

    def test_backup_like_basename_alone_is_not_blocked_outside_backup_tree(
        self, tmp_path
    ):
        fabric_root = tmp_path / ".fabric"
        fabric_root.mkdir()
        archive = tmp_path / "fabric-backup-2026-07-11.payload"
        archive.write_bytes(b"ordinary project report")

        with (
            patch("agent.file_safety._fabric_home_path", return_value=fabric_root),
            patch("agent.file_safety._fabric_root_path", return_value=fabric_root),
        ):
            error = get_read_block_error(str(archive))

        assert error is None


# ---------------------------------------------------------------------------
# Combined: env guard + cache guard don't interfere
# ---------------------------------------------------------------------------


class TestCombinedGuards:
    """Both guards should work independently without interference."""

    def test_env_guard_works_regardless_of_fabric_home(self, tmp_path):
        """The env basename guard does not depend on FABRIC_HOME resolution."""
        fabric_home = tmp_path / ".fabric"
        fabric_home.mkdir()

        with patch("agent.file_safety._fabric_home_path", return_value=fabric_home):
            # Regular project .env should still be blocked
            error = get_read_block_error("/workspace/.env")
            assert error is not None

            # .env.example should still be allowed
            error = get_read_block_error("/workspace/.env.example")
            assert error is None

    def test_cache_guard_still_works_with_env_guard(self, tmp_path):
        """Cache file blocking still works when env guard is active."""
        fabric_home = tmp_path / ".fabric"
        cache = fabric_home / "skills" / ".hub" / "index-cache" / "x"
        cache.parent.mkdir(parents=True)
        cache.write_text("")

        with patch("agent.file_safety._fabric_home_path", return_value=fabric_home):
            error = get_read_block_error(str(cache))
            assert error is not None
            assert "internal Fabric cache" in error
