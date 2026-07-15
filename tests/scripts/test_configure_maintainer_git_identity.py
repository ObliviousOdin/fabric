from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "configure-maintainer-git-identity.py"
CANONICAL_NAME = "PrimeOdin"
CANONICAL_EMAIL = "11676741+ObliviousOdin@users.noreply.github.com"


class ConfigureMaintainerGitIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.global_config = self.root / "gitconfig"
        self.env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": str(self.global_config),
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": str(self.root),
        }
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, env=self.env)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _config(self, scope: str, key: str) -> str:
        return subprocess.run(
            ["git", "config", f"--{scope}", "--get", key],
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def test_configures_and_checks_both_scopes(self) -> None:
        configured = self._script("--scope", "both")
        checked = self._script("--scope", "both", "--check")

        self.assertEqual(configured.returncode, 0, configured.stderr)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        for scope in ("local", "global"):
            self.assertEqual(self._config(scope, "user.name"), CANONICAL_NAME)
            self.assertEqual(self._config(scope, "user.email"), CANONICAL_EMAIL)
        self.assertEqual(self._config("global", "user.useConfigOnly"), "true")

    def test_check_reports_mismatches_without_echoing_existing_values(self) -> None:
        subprocess.run(
            ["git", "config", "--global", "user.name", "Wrong Name"],
            cwd=self.repo,
            env=self.env,
            check=True,
        )
        subprocess.run(
            ["git", "config", "--global", "user.email", "private@example.com"],
            cwd=self.repo,
            env=self.env,
            check=True,
        )

        result = self._script("--scope", "global", "--check")

        self.assertEqual(result.returncode, 1)
        self.assertIn("global user.name is not canonical", result.stderr)
        self.assertIn("global user.email is not canonical", result.stderr)
        self.assertNotIn("Wrong Name", result.stderr)
        self.assertNotIn("private@example.com", result.stderr)

    def test_global_scope_does_not_overwrite_repository_identity(self) -> None:
        subprocess.run(
            ["git", "config", "--local", "user.name", "Repository Contributor"],
            cwd=self.repo,
            env=self.env,
            check=True,
        )

        result = self._script("--scope", "global")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._config("local", "user.name"), "Repository Contributor")
        self.assertEqual(self._config("global", "user.name"), CANONICAL_NAME)


if __name__ == "__main__":
    unittest.main()
