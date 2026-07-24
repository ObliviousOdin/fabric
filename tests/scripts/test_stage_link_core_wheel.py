from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.ci.stage_link_core_wheel import (
    StageLinkCoreError,
    stage_link_core_wheel,
)


SOURCE_SHA = "a" * 40
VERSION = "0.21.0"
REPOSITORY = "ObliviousOdin/fabric"
WHEELS = {
    "linux": f"fabric_link_core-{VERSION}-py3-none-linux_x86_64.whl",
    "mac": f"fabric_link_core-{VERSION}-py3-none-macosx_11_0_universal2.whl",
    "win": f"fabric_link_core-{VERSION}-py3-none-win_amd64.whl",
}


def _release(tmp_path: Path, *, mac_wheel: str | None = None) -> Path:
    release = tmp_path / "release"
    release.mkdir()
    rows = []
    wheels = {**WHEELS, **({"mac": mac_wheel} if mac_wheel else {})}
    for platform, name in wheels.items():
        payload = f"{platform}-native-wheel".encode()
        (release / name).write_bytes(payload)
        rows.append(
            {
                "name": name,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
            }
        )
    manifest = {
        "schema_version": 1,
        "repository": REPOSITORY,
        "source_sha": SOURCE_SHA,
        "version": VERSION,
        "artifacts": rows,
        "link_core": {"platforms": ["linux", "macos", "windows"]},
    }
    (release / "release-manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return release


@pytest.mark.parametrize("platform", ["linux", "mac", "win"])
def test_stage_selects_and_rehashes_exact_platform_wheel(tmp_path, platform):
    release = _release(tmp_path)
    destination = tmp_path / "bundle"

    result = stage_link_core_wheel(
        release,
        destination=destination,
        platform=platform,
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        version=VERSION,
    )

    assert result["wheel"]["name"] == WHEELS[platform]
    assert (destination / WHEELS[platform]).is_file()
    assert len(list(destination.glob("fabric_link_core-*.whl"))) == 1
    assert json.loads(
        (destination / "link-core-manifest.json").read_text(encoding="utf-8")
    ) == result


def test_stage_rejects_tampered_release_wheel(tmp_path):
    release = _release(tmp_path)
    (release / WHEELS["linux"]).write_bytes(b"tampered")

    with pytest.raises(StageLinkCoreError, match="integrity"):
        stage_link_core_wheel(
            release,
            destination=tmp_path / "bundle",
            platform="linux",
            repository=REPOSITORY,
            source_sha=SOURCE_SHA,
            version=VERSION,
        )


def test_stage_accepts_arm64_macos_wheel(tmp_path):
    arm64_wheel = f"fabric_link_core-{VERSION}-py3-none-macosx_15_0_arm64.whl"
    release = _release(tmp_path, mac_wheel=arm64_wheel)

    result = stage_link_core_wheel(
        release,
        destination=tmp_path / "bundle",
        platform="mac",
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        version=VERSION,
    )

    assert result["wheel"]["name"] == arm64_wheel


def test_stage_rejects_manifest_from_another_commit(tmp_path):
    release = _release(tmp_path)

    with pytest.raises(StageLinkCoreError, match="source_sha"):
        stage_link_core_wheel(
            release,
            destination=tmp_path / "bundle",
            platform="mac",
            repository=REPOSITORY,
            source_sha="b" * 40,
            version=VERSION,
        )
