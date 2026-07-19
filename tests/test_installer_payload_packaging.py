"""Artifact contracts for Fabric's lazy dependency installers."""

from __future__ import annotations

import shutil
import stat
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from csv import reader
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_SCRIPT_NAMES = ("install.sh", "install.ps1")


def test_installer_payload_metadata_uses_canonical_root_scripts():
    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    for name in INSTALLER_SCRIPT_NAMES:
        assert (REPO_ROOT / "scripts" / name).is_file()
        assert f"include scripts/{name}" in manifest

    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = data["tool"]["setuptools"]["package-data"]["fabric_cli"]
    assert not any(pattern.startswith("scripts/") for pattern in package_data), (
        "installer scripts are copied from their canonical root location by build_py; "
        "package-data entries under fabric_cli/scripts would describe duplicate sources"
    )


def _copy_source_tree(destination: Path) -> None:
    shutil.copytree(
        REPO_ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            ".gradle",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "*.egg-info",
            "venv",
            "node_modules",
            "build",
            "dist",
            "target",
            "__pycache__",
        ),
    )


def _run_build(source: Path, out_dir: Path, *args: str) -> None:
    result = subprocess.run(
        ["uv", "build", *args, "--out-dir", str(out_dir)],
        cwd=source,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (
        f"uv build {' '.join(args)} failed:\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def _assert_wheel_payload(wheel_path: Path, expected: dict[str, bytes]) -> None:
    with zipfile.ZipFile(wheel_path) as wheel:
        names = wheel.namelist()
        record_name = next(
            name for name in names if name.endswith(".dist-info/RECORD")
        )
        record_paths = {
            row[0]
            for row in reader(StringIO(wheel.read(record_name).decode("utf-8")))
        }
        for name, content in expected.items():
            archive_name = f"fabric_cli/scripts/{name}"
            assert names.count(archive_name) == 1
            assert wheel.read(archive_name) == content
            assert archive_name in record_paths
            if name == "install.sh":
                mode = (wheel.getinfo(archive_name).external_attr >> 16) & 0o777
                assert mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH) == 0o111
            matching_locations = {
                path
                for path in names
                if path == f"scripts/{name}" or path.endswith(f"/scripts/{name}")
            }
            assert matching_locations == {archive_name}


@pytest.mark.integration
@pytest.mark.timeout(900)
def test_direct_and_sdist_wheels_install_canonical_installer_payload(tmp_path):
    source = tmp_path / "source"
    _copy_source_tree(source)
    expected = {
        name: (source / "scripts" / name).read_bytes()
        for name in INSTALLER_SCRIPT_NAMES
    }

    sdist_dir = tmp_path / "sdist"
    _run_build(source, sdist_dir, "--sdist", ".")
    sdists = list(sdist_dir.glob("*.tar.gz"))
    assert len(sdists) == 1

    with tarfile.open(sdists[0], mode="r:gz") as sdist:
        file_members = [member for member in sdist.getmembers() if member.isfile()]
        relative_names = [member.name.split("/", 1)[-1] for member in file_members]
        members = {
            member.name.split("/", 1)[-1]: member
            for member in file_members
        }
        for name, content in expected.items():
            archive_name = f"scripts/{name}"
            assert relative_names.count(archive_name) == 1
            extracted = sdist.extractfile(members[archive_name])
            assert extracted is not None
            assert extracted.read() == content
            if name == "install.sh":
                assert (
                    members[archive_name].mode
                    & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                    == 0o111
                )
            assert f"fabric_cli/scripts/{name}" not in members

    direct_dir = tmp_path / "direct-wheel"
    _run_build(source, direct_dir, "--wheel", ".")
    direct_wheels = list(direct_dir.glob("*.whl"))
    assert len(direct_wheels) == 1
    _assert_wheel_payload(direct_wheels[0], expected)

    rebuilt_dir = tmp_path / "sdist-wheel"
    _run_build(source, rebuilt_dir, "--wheel", str(sdists[0]))
    rebuilt_wheels = list(rebuilt_dir.glob("*.whl"))
    assert len(rebuilt_wheels) == 1
    _assert_wheel_payload(rebuilt_wheels[0], expected)

    installed = tmp_path / "installed"
    install = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-deps",
            "--target",
            str(installed),
            str(rebuilt_wheels[0]),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert install.returncode == 0, (
        f"wheel install failed:\nstdout:\n{install.stdout}\nstderr:\n{install.stderr}"
    )

    package_dir = installed / "fabric_cli"
    for name, content in expected.items():
        assert (package_dir / "scripts" / name).read_bytes() == content

    from fabric_cli.dep_ensure import _find_install_script

    missing_checkout = tmp_path / "missing-checkout"
    with patch("fabric_cli.dep_ensure._IS_WINDOWS", False):
        assert _find_install_script(package_dir, missing_checkout) == (
            package_dir / "scripts" / "install.sh",
            "bash",
        )
    with patch("fabric_cli.dep_ensure._IS_WINDOWS", True):
        assert _find_install_script(package_dir, missing_checkout) == (
            package_dir / "scripts" / "install.ps1",
            "powershell",
        )
