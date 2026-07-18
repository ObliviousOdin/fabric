"""Installed-wheel regression coverage for bundled Fabric skills."""

from __future__ import annotations

import glob
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_installed_wheel_contains_fabric_contribute_skill(tmp_path):
    wheel_dir = tmp_path / "dist"
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            ".",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert build.returncode == 0, f"wheel build failed:\n{build.stderr}"
    wheels = glob.glob(str(wheel_dir / "*.whl"))
    assert len(wheels) == 1

    installed_root = tmp_path / "installed"
    install = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-deps",
            "--target",
            str(installed_root),
            wheels[0],
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert install.returncode == 0, f"wheel install failed:\n{install.stderr}"

    skill = installed_root / "skills" / "github" / "fabric-contribute"
    required = [
        skill / "SKILL.md",
        skill / "skill.contract.yaml",
        skill / "evals" / "cases.yaml",
        skill / "scripts" / "fabric_issue.py",
        skill / "templates" / "bug-report.md",
        skill / "templates" / "feature-request.md",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    assert not missing, f"installed wheel lost bundled skill files: {missing}"
