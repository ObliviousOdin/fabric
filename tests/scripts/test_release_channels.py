"""Behavior contracts for immutable release-channel promotion."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path
from unittest import mock

import pytest

from scripts.ci import publish_release
from scripts.ci.release_candidate import (
    CandidateError,
    create_candidate,
    verify_candidate,
)
from scripts.ci.validate_release_run import RunValidationError, validate_run


REPOSITORY = "ObliviousOdin/fabric"
SOURCE_SHA = "a" * 40
VERSION = "1.2.3"


def _write_project(root: Path, version: str = VERSION) -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "fabric-agent"\nversion = "{version}"\n',
        encoding="utf-8",
    )


def _write_artifacts(dist: Path, version: str = VERSION) -> None:
    dist.mkdir()
    wheel = dist / f"fabric_agent-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr(
            f"fabric_agent-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: fabric-agent\nVersion: {version}\n",
        )

    source = dist / f"fabric_agent-{version}.tar.gz"
    payload = (
        f"Metadata-Version: 2.4\nName: fabric-agent\nVersion: {version}\n"
    ).encode()
    info = tarfile.TarInfo(f"fabric_agent-{version}/PKG-INFO")
    info.size = len(payload)
    with tarfile.open(source, mode="w:gz") as archive:
        archive.addfile(info, io.BytesIO(payload))
        egg_info = tarfile.TarInfo(
            f"fabric_agent-{version}/fabric_agent.egg-info/PKG-INFO"
        )
        egg_info.size = len(payload)
        archive.addfile(egg_info, io.BytesIO(payload))


def _candidate(tmp_path: Path) -> Path:
    _write_project(tmp_path)
    dist = tmp_path / "dist"
    _write_artifacts(dist)
    create_candidate(
        dist,
        project_root=tmp_path,
        source_sha=SOURCE_SHA,
        repository=REPOSITORY,
    )
    return dist


def _successful_beta_run(**overrides) -> dict:
    run = {
        "name": "Fabric release channels",
        "path": ".github/workflows/release-channels.yml",
        "event": "push",
        "head_branch": "main",
        "head_sha": SOURCE_SHA,
        "status": "completed",
        "conclusion": "success",
        "head_repository": {"full_name": REPOSITORY},
    }
    run.update(overrides)
    return run


def test_candidate_round_trip_records_and_verifies_exact_bytes(tmp_path):
    output = tmp_path / "github-output"
    _write_project(tmp_path)
    dist = tmp_path / "dist"
    _write_artifacts(dist)

    created = create_candidate(
        dist,
        project_root=tmp_path,
        source_sha=SOURCE_SHA,
        repository=REPOSITORY,
        output_path=output,
    )
    verified = verify_candidate(
        dist,
        source_sha=SOURCE_SHA,
        repository=REPOSITORY,
    )

    assert verified == created
    assert {row["name"] for row in verified["artifacts"]} == {
        f"fabric_agent-{VERSION}-py3-none-any.whl",
        f"fabric_agent-{VERSION}.tar.gz",
    }
    assert output.read_text() == f"source_sha={SOURCE_SHA}\nversion={VERSION}\n"


def test_candidate_rejects_changed_artifact_after_manifest(tmp_path):
    dist = _candidate(tmp_path)
    wheel = next(dist.glob("*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"tampered")

    with pytest.raises(CandidateError, match="checksum mismatch"):
        verify_candidate(
            dist,
            source_sha=SOURCE_SHA,
            repository=REPOSITORY,
        )


def test_candidate_rejects_provenance_or_file_set_changes(tmp_path):
    dist = _candidate(tmp_path)

    with pytest.raises(CandidateError, match="source_sha"):
        verify_candidate(
            dist,
            source_sha="b" * 40,
            repository=REPOSITORY,
        )

    (dist / ".gitignore").write_text("*\n", encoding="utf-8")
    verify_candidate(
        dist,
        source_sha=SOURCE_SHA,
        repository=REPOSITORY,
    )

    (dist / "unexpected.txt").write_text("not promoted", encoding="utf-8")
    with pytest.raises(CandidateError, match="file set mismatch"):
        verify_candidate(
            dist,
            source_sha=SOURCE_SHA,
            repository=REPOSITORY,
        )


def test_candidate_rejects_package_version_drift(tmp_path):
    _write_project(tmp_path, version="9.9.9")
    dist = tmp_path / "dist"
    _write_artifacts(dist, version=VERSION)

    with pytest.raises(CandidateError, match="does not match project version"):
        create_candidate(
            dist,
            project_root=tmp_path,
            source_sha=SOURCE_SHA,
            repository=REPOSITORY,
        )


def test_only_successful_main_push_run_can_feed_production():
    assert (
        validate_run(
            _successful_beta_run(),
            repository=REPOSITORY,
            workflow_name="Fabric release channels",
            workflow_path=".github/workflows/release-channels.yml",
        )
        == SOURCE_SHA
    )

    invalid_runs = (
        _successful_beta_run(event="pull_request"),
        _successful_beta_run(head_branch="feature"),
        _successful_beta_run(conclusion="failure"),
        _successful_beta_run(head_repository={"full_name": "someone/fork"}),
    )
    for run in invalid_runs:
        with pytest.raises(RunValidationError):
            validate_run(
                run,
                repository=REPOSITORY,
                workflow_name="Fabric release channels",
                workflow_path=".github/workflows/release-channels.yml",
            )


def test_production_dry_run_still_verifies_candidate(tmp_path):
    dist = _candidate(tmp_path)

    title = publish_release.publish_release(
        dist,
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        tag="v2026.7.15",
        dry_run=True,
    )

    assert title == f"Fabric v{VERSION} (2026.7.15)"
    with pytest.raises(publish_release.PublishError, match="CalVer"):
        publish_release.publish_release(
            dist,
            repository=REPOSITORY,
            source_sha=SOURCE_SHA,
            tag="latest",
            dry_run=True,
        )
    with pytest.raises(publish_release.PublishError, match="calendar date"):
        publish_release.publish_release(
            dist,
            repository=REPOSITORY,
            source_sha=SOURCE_SHA,
            tag="v2026.2.31",
            dry_run=True,
        )


def test_production_publish_creates_annotated_tag_before_release(tmp_path):
    dist = _candidate(tmp_path)
    responses = [
        subprocess.CompletedProcess([], 1, "", "not found"),
        subprocess.CompletedProcess([], 1, "", "not found"),
        subprocess.CompletedProcess([], 0, json.dumps({"sha": "c" * 40}), ""),
        subprocess.CompletedProcess([], 0, "{}", ""),
        subprocess.CompletedProcess([], 0, "release-url", ""),
    ]

    with (
        mock.patch.object(publish_release.shutil, "which", return_value="/usr/bin/gh"),
        mock.patch.dict(os.environ, {"GH_TOKEN": "test-token"}),
        mock.patch.object(publish_release, "_run_gh", side_effect=responses) as run_gh,
    ):
        title = publish_release.publish_release(
            dist,
            repository=REPOSITORY,
            source_sha=SOURCE_SHA,
            tag="v2026.7.15",
        )

    assert title == f"Fabric v{VERSION} (2026.7.15)"
    calls = [call.args[0] for call in run_gh.call_args_list]
    assert calls[2][:4] == [
        "api",
        "--method",
        "POST",
        f"repos/{REPOSITORY}/git/tags",
    ]
    assert calls[3][:4] == [
        "api",
        "--method",
        "POST",
        f"repos/{REPOSITORY}/git/refs",
    ]
    assert calls[4][:3] == ["release", "create", "v2026.7.15"]


def test_failed_release_removes_only_the_tag_created_by_this_attempt(tmp_path):
    dist = _candidate(tmp_path)
    responses = [
        subprocess.CompletedProcess([], 1, "", "not found"),
        subprocess.CompletedProcess([], 1, "", "not found"),
        subprocess.CompletedProcess([], 0, json.dumps({"sha": "c" * 40}), ""),
        subprocess.CompletedProcess([], 0, "{}", ""),
        publish_release.PublishError("release upload failed"),
        subprocess.CompletedProcess([], 0, "", ""),
    ]

    with (
        mock.patch.object(publish_release.shutil, "which", return_value="/usr/bin/gh"),
        mock.patch.dict(os.environ, {"GH_TOKEN": "test-token"}),
        mock.patch.object(publish_release, "_run_gh", side_effect=responses) as run_gh,
        pytest.raises(publish_release.PublishError, match="upload failed"),
    ):
        publish_release.publish_release(
            dist,
            repository=REPOSITORY,
            source_sha=SOURCE_SHA,
            tag="v2026.7.15",
        )

    cleanup = run_gh.call_args_list[-1].args[0]
    assert cleanup == [
        "api",
        "--method",
        "DELETE",
        f"repos/{REPOSITORY}/git/refs/tags/v2026.7.15",
    ]
