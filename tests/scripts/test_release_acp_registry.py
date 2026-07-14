"""Tests for the ACP Registry version-lockstep bump in scripts/release.py.

The official ACP Registry manifest must match ``pyproject.toml`` exactly —
``tests/acp/test_registry_manifest.py`` enforces this at lint time, and the
upstream registry CI rejects ``@latest`` / floating pins. The release script
is the single place that bumps the manifest in lockstep with pyproject; if
that bump ever silently breaks, weekly releases fail the manifest test
until someone hand-edits the JSON.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_release_module(monkeypatch, tmp_root: Path):
    """Import scripts/release.py with REPO_ROOT pinned to a temp tree."""
    spec = importlib.util.spec_from_file_location(
        "_release_under_test",
        Path(__file__).resolve().parents[2] / "scripts" / "release.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "REPO_ROOT", tmp_root)
    monkeypatch.setattr(
        module, "ACP_REGISTRY_MANIFEST", tmp_root / "acp_registry" / "agent.json"
    )
    return module


def _write_manifest(root: Path, version: str) -> None:
    manifest_dir = root / "acp_registry"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "agent.json").write_text(
        json.dumps(
            {
                "id": "fabric-agent",
                "name": "Fabric",
                "version": version,
                "description": "test",
                "distribution": {
                    "uvx": {
                        "package": f"fabric-agent[acp]=={version}",
                        "args": ["hermes-acp"],
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_update_acp_registry_versions_bumps_manifest_and_pin(monkeypatch, tmp_path):
    _write_manifest(tmp_path, "0.13.0")
    module = _load_release_module(monkeypatch, tmp_path)

    module._update_acp_registry_versions("0.14.0")

    manifest = json.loads(
        (tmp_path / "acp_registry" / "agent.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == "0.14.0"
    assert manifest["distribution"]["uvx"]["package"] == "fabric-agent[acp]==0.14.0"
    # args stay untouched so we don't accidentally rewrite them.
    assert manifest["distribution"]["uvx"]["args"] == ["hermes-acp"]


def _write_release_artifacts(
    root: Path,
    version: str,
    *,
    metadata_version: str | None = None,
) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    embedded_version = metadata_version or version
    wheel = root / f"fabric_agent-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr(
            f"fabric_agent-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: fabric-agent\nVersion: {embedded_version}\n",
        )

    sdist = root / f"fabric_agent-{version}.tar.gz"
    metadata = (
        f"Metadata-Version: 2.4\nName: fabric-agent\nVersion: {embedded_version}\n"
    ).encode("utf-8")
    with tarfile.open(sdist, mode="w:gz") as archive:
        member = tarfile.TarInfo(f"fabric_agent-{version}/PKG-INFO")
        member.size = len(metadata)
        archive.addfile(member, io.BytesIO(metadata))

    return [wheel, sdist]


def _configure_publish_test(
    module,
    monkeypatch,
    tmp_path,
    events,
    *,
    valid=True,
    push_ok=True,
):
    artifacts = [
        tmp_path / "dist" / "fabric_agent-0.19.0-py3-none-any.whl",
        tmp_path / "dist" / "fabric_agent-0.19.0.tar.gz",
    ]
    monkeypatch.setattr(
        sys,
        "argv",
        ["release.py", "--publish", "--date", "2026.7.14"],
    )
    monkeypatch.setattr(
        module,
        "next_available_tag",
        lambda base: ("v2026.7.14", "2026.7.14"),
    )
    monkeypatch.setattr(module, "get_current_version", lambda: "0.19.0")
    monkeypatch.setattr(module, "get_last_tag", lambda: "v2026.7.7")
    monkeypatch.setattr(
        module,
        "get_commits",
        lambda since_tag: [{"github_author": "@fabric-test"}],
    )
    monkeypatch.setattr(module, "generate_changelog", lambda *args, **kwargs: "notes")

    def build(version):
        events.append("build")
        assert version == "0.19.0"
        return artifacts

    def validate(built, version):
        events.append("validate")
        assert built == artifacts
        assert version == "0.19.0"
        return valid

    def git_result(*args, **kwargs):
        command = args[0]
        events.append(command)
        if command == "push":
            return SimpleNamespace(
                returncode=0 if push_ok else 1,
                stdout="",
                stderr="push rejected" if not push_ok else "",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module, "build_release_artifacts", build)
    monkeypatch.setattr(module, "validate_release_artifacts", validate)
    monkeypatch.setattr(module, "git_result", git_result)


def test_release_artifact_validation_checks_both_embedded_versions(
    monkeypatch, tmp_path
):
    module = _load_release_module(monkeypatch, tmp_path)
    artifacts = _write_release_artifacts(tmp_path / "dist", "0.19.0")
    stale_artifacts = _write_release_artifacts(
        tmp_path / "stale-dist",
        "0.19.0",
        metadata_version="0.18.2",
    )

    assert module.validate_release_artifacts(artifacts, "0.19.0") is True
    assert module.validate_release_artifacts(stale_artifacts, "0.19.0") is False


def test_publish_builds_and_validates_before_tag_and_push(monkeypatch, tmp_path):
    module = _load_release_module(monkeypatch, tmp_path)
    events = []
    _configure_publish_test(module, monkeypatch, tmp_path, events)
    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda command: events.append(command) or None,
    )

    module.main()

    assert events == ["build", "validate", "tag", "push", "gh"]


def test_publish_does_not_create_tag_when_artifact_validation_fails(
    monkeypatch, tmp_path
):
    module = _load_release_module(monkeypatch, tmp_path)
    events = []
    _configure_publish_test(module, monkeypatch, tmp_path, events, valid=False)

    with pytest.raises(SystemExit, match="1"):
        module.main()

    assert events == ["build", "validate"]
    assert not (tmp_path / ".release_notes.md").exists()


def test_publish_push_failure_aborts_before_github_release(monkeypatch, tmp_path):
    module = _load_release_module(monkeypatch, tmp_path)
    events = []
    _configure_publish_test(module, monkeypatch, tmp_path, events, push_ok=False)

    def unexpected_gh_lookup(command):
        raise AssertionError(f"GitHub release lookup ran after push failure: {command}")

    monkeypatch.setattr(module.shutil, "which", unexpected_gh_lookup)

    with pytest.raises(SystemExit, match="1"):
        module.main()

    assert events == ["build", "validate", "tag", "push"]
    assert not (tmp_path / ".release_notes.md").exists()


def test_repository_release_versions_and_license_are_in_lockstep():
    root = Path(__file__).resolve().parents[2]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    expected = pyproject["project"]["version"]

    python_source = (root / "fabric_cli" / "__init__.py").read_text(
        encoding="utf-8"
    )
    python_match = re.search(r'^__version__\s*=\s*"([^"]+)"', python_source, re.M)
    assert python_match is not None

    desktop = json.loads(
        (root / "apps" / "desktop" / "package.json").read_text(encoding="utf-8")
    )
    npm_package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    npm_lock = json.loads(
        (root / "package-lock.json").read_text(encoding="utf-8")
    )
    acp = json.loads(
        (root / "acp_registry" / "agent.json").read_text(encoding="utf-8")
    )
    uv_lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    uv_packages = [
        package
        for package in uv_lock["package"]
        if package.get("name") == "fabric-agent"
    ]
    assert len(uv_packages) == 1

    versions = {
        "fabric_cli.__version__": python_match.group(1),
        "desktop package": desktop["version"],
        "package-lock desktop workspace": npm_lock["packages"]["apps/desktop"][
            "version"
        ],
        "ACP manifest": acp["version"],
        "uv.lock editable package": uv_packages[0]["version"],
    }
    assert versions == {name: expected for name in versions}
    assert acp["distribution"]["uvx"]["package"] == f"fabric-agent[acp]=={expected}"
    assert npm_package["license"] == "Apache-2.0"
    assert npm_lock["packages"][""]["license"] == npm_package["license"]


def test_update_acp_registry_versions_is_silent_when_manifest_missing(
    monkeypatch, tmp_path
):
    """Older release branches predate the ACP Registry asset — must no-op."""
    module = _load_release_module(monkeypatch, tmp_path)

    # No fixture written; function should not raise.
    module._update_acp_registry_versions("0.14.0")


def test_update_version_files_bumps_manifest_alongside_pyproject(
    monkeypatch, tmp_path
):
    """End-to-end: update_version_files() is the function release.py actually
    calls, so it must drive the manifest bump too."""
    _write_manifest(tmp_path, "0.13.0")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fabric-agent"\nversion = "0.13.0"\n', encoding="utf-8"
    )
    version_dir = tmp_path / "fabric_cli"
    version_dir.mkdir()
    (version_dir / "__init__.py").write_text(
        '__version__ = "0.13.0"\n__release_date__ = "2026-05-14"\n',
        encoding="utf-8",
    )
    desktop_dir = tmp_path / "apps" / "desktop"
    desktop_dir.mkdir(parents=True)
    (desktop_dir / "package.json").write_text(
        '{\n  "name": "fabric-desktop",\n  "version": "0.12.0"\n}\n',
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "fabric-agent",
                "packages": {
                    "": {"name": "fabric-agent", "version": "1.0.0"},
                    "apps/desktop": {
                        "name": "fabric-desktop",
                        "version": "0.12.0",
                    },
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text(
        'version = 1\n\n[[package]]\nname = "fabric-agent"\nversion = "0.13.0"\nsource = { editable = "." }\n',
        encoding="utf-8",
    )

    module = _load_release_module(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "VERSION_FILE", version_dir / "__init__.py")
    monkeypatch.setattr(module, "PYPROJECT_FILE", tmp_path / "pyproject.toml")

    module.update_version_files("0.14.0", "2026-05-21")

    pyproject_text = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.14.0"' in pyproject_text

    desktop = json.loads(
        (desktop_dir / "package.json").read_text(encoding="utf-8")
    )
    assert desktop["version"] == "0.14.0"

    npm_lock = json.loads(
        (tmp_path / "package-lock.json").read_text(encoding="utf-8")
    )
    assert npm_lock["packages"][""]["version"] == "1.0.0"
    assert npm_lock["packages"]["apps/desktop"]["version"] == "0.14.0"
    assert 'name = "fabric-agent"\nversion = "0.14.0"' in (
        tmp_path / "uv.lock"
    ).read_text(encoding="utf-8")

    manifest = json.loads(
        (tmp_path / "acp_registry" / "agent.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == "0.14.0"
    assert manifest["distribution"]["uvx"]["package"] == "fabric-agent[acp]==0.14.0"
