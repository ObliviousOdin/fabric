#!/usr/bin/env python3
"""Verify and stage one release-native Fabric Link wheel for Desktop."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


class StageLinkCoreError(ValueError):
    pass


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_PLATFORM_MARKERS = {
    "mac": ("macosx", "arm64"),
    "win": ("win_amd64",),
    "linux": ("linux_x86_64",),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage_link_core_wheel(
    release_dir: Path,
    *,
    destination: Path,
    platform: str,
    repository: str,
    source_sha: str,
    version: str,
) -> dict[str, object]:
    if platform not in _PLATFORM_MARKERS:
        raise StageLinkCoreError(f"unsupported desktop platform: {platform}")
    if not _SHA_RE.fullmatch(source_sha):
        raise StageLinkCoreError("source SHA must be 40 lowercase hex characters")
    try:
        manifest = json.loads(
            (release_dir / "release-manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise StageLinkCoreError("release manifest is missing or invalid") from exc
    expected_header = {
        "schema_version": 1,
        "repository": repository,
        "source_sha": source_sha,
        "version": version,
    }
    for key, expected in expected_header.items():
        if manifest.get(key) != expected:
            raise StageLinkCoreError(
                f"release manifest {key} does not match the desktop build"
            )
    link_core = manifest.get("link_core")
    if (
        not isinstance(link_core, dict)
        or link_core.get("platforms") != ["linux", "macos", "windows"]
    ):
        raise StageLinkCoreError("release does not attest every Link core platform")

    rows = manifest.get("artifacts")
    if not isinstance(rows, list):
        raise StageLinkCoreError("release artifact manifest is invalid")
    markers = _PLATFORM_MARKERS[platform]
    candidates = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if (
            isinstance(name, str)
            and name.startswith(f"fabric_link_core-{version}-")
            and name.endswith(".whl")
            and all(marker in name.lower() for marker in markers)
        ):
            candidates.append(row)
    if len(candidates) != 1:
        raise StageLinkCoreError(
            f"expected one {platform} Link core wheel, found {len(candidates)}"
        )
    row = candidates[0]
    name = row["name"]
    if Path(name).name != name:
        raise StageLinkCoreError("release wheel name must be a plain file name")
    source = release_dir / name
    if not source.is_file() or source.is_symlink():
        raise StageLinkCoreError(f"release wheel is missing or unsafe: {name}")
    actual_sha = _sha256(source)
    if actual_sha != row.get("sha256") or source.stat().st_size != row.get("size"):
        raise StageLinkCoreError(f"release wheel failed integrity verification: {name}")

    if destination.exists() and destination.is_symlink():
        raise StageLinkCoreError("desktop Link core destination cannot be a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    for stale in destination.glob("fabric_link_core-*.whl"):
        if stale.is_file() and not stale.is_symlink():
            stale.unlink()
        else:
            raise StageLinkCoreError(f"unsafe stale Link core artifact: {stale.name}")
    staged = destination / name
    shutil.copyfile(source, staged)
    if _sha256(staged) != actual_sha:
        raise StageLinkCoreError("staged Link core wheel checksum mismatch")

    bundle = {
        "schema_version": 1,
        "source_sha": source_sha,
        "version": version,
        "platform": platform,
        "wheel": {
            "name": name,
            "sha256": actual_sha,
            "size": staged.stat().st_size,
        },
    }
    (destination / "link-core-manifest.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--platform", required=True, choices=tuple(_PLATFORM_MARKERS))
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    stage_link_core_wheel(
        args.release_dir,
        destination=args.destination,
        platform=args.platform,
        repository=args.repository,
        source_sha=args.source_sha,
        version=args.version,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
