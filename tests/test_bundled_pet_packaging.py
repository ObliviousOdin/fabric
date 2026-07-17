"""Packaging contracts for first-party pet assets."""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_bundled_pet_assets_ship_in_both_wheel_and_sdist():
    pet_dir = REPO_ROOT / "agent" / "pet" / "assets" / "fabric-mascot"
    assert (pet_dir / "pet.json").is_file()
    assert (pet_dir / "spritesheet.webp").is_file()

    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    agent_pkg_data = data["tool"]["setuptools"]["package-data"].get("agent", [])
    assert any(pattern.startswith("pet/assets/") for pattern in agent_pkg_data), (
        "pyproject package-data 'agent' must ship bundled pet assets in wheels"
    )

    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "recursive-include agent/pet/assets" in manifest, (
        "MANIFEST.in must ship bundled pet assets in source distributions"
    )


@pytest.mark.integration
def test_built_artifacts_contain_bundled_pet_assets(tmp_path):
    # Setuptools writes an untracked ``build/`` tree next to the source even
    # when artifacts go elsewhere. Build from a clean temporary copy so this
    # integration test is hermetic and safe to run beside other test shards.
    source = tmp_path / "source"
    shutil.copytree(
        REPO_ROOT,
        source,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "venv", "node_modules", "build", "dist", "__pycache__"
        ),
    )
    dist = tmp_path / "dist"
    build = subprocess.run(
        ["uv", "build", "--sdist", "--wheel", "--out-dir", str(dist), "."],
        cwd=source,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert build.returncode == 0, f"uv build failed:\n{build.stderr}"

    expected = {
        "agent/pet/assets/fabric-mascot/pet.json",
        "agent/pet/assets/fabric-mascot/spritesheet.webp",
    }
    wheels = list(dist.glob("*.whl"))
    sdists = list(dist.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1

    with zipfile.ZipFile(wheels[0]) as wheel:
        wheel_names = set(wheel.namelist())
    assert expected <= wheel_names

    with tarfile.open(sdists[0]) as sdist:
        sdist_names = {name.split("/", 1)[-1] for name in sdist.getnames()}
    assert expected <= sdist_names
