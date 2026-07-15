#!/usr/bin/env python3
"""Create and verify immutable Fabric release-candidate manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tarfile
import tomllib
import zipfile
from pathlib import Path


SCHEMA_VERSION = 1
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
IGNORED_BUILD_FILES = frozenset({".gitignore"})
WEB_DIST_INDEX = "fabric_cli/web_dist/index.html"
WEB_DIST_ASSET_PREFIX = "fabric_cli/web_dist/assets/"


class CandidateError(ValueError):
    """Raised when a release candidate fails its provenance contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_version(text: str, *, artifact: Path) -> str:
    matches = re.findall(r"(?m)^Version:\s*(\S+)\s*$", text)
    if len(matches) != 1:
        raise CandidateError(
            f"{artifact.name}: expected one package Version field, found {len(matches)}"
        )
    return matches[0]


def artifact_version(path: Path) -> str:
    """Read the embedded package version from a wheel or source archive."""
    try:
        if path.name.endswith(".whl"):
            with zipfile.ZipFile(path) as archive:
                corrupt_member = archive.testzip()
                if corrupt_member is not None:
                    raise CandidateError(
                        f"{path.name}: corrupt wheel member {corrupt_member}"
                    )
                metadata_files = [
                    name
                    for name in archive.namelist()
                    if name.endswith(".dist-info/METADATA")
                ]
                if len(metadata_files) != 1:
                    raise CandidateError(
                        f"{path.name}: expected one wheel METADATA file, "
                        f"found {len(metadata_files)}"
                    )
                metadata = archive.read(metadata_files[0]).decode("utf-8")
        elif path.name.endswith(".tar.gz"):
            with tarfile.open(path, mode="r:gz") as archive:
                metadata_files = [
                    member
                    for member in archive.getmembers()
                    if member.isfile() and member.name.endswith("/PKG-INFO")
                ]
                canonical = [
                    member for member in metadata_files if member.name.count("/") == 1
                ]
                if len(canonical) != 1:
                    raise CandidateError(
                        f"{path.name}: expected one root source PKG-INFO file, "
                        f"found {len(canonical)}"
                    )
                embedded_metadata = []
                for member in metadata_files:
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise CandidateError(
                            f"{path.name}: could not read {member.name}"
                        )
                    embedded_metadata.append((member, extracted.read().decode("utf-8")))
                embedded_versions = {
                    _metadata_version(text, artifact=path)
                    for _member, text in embedded_metadata
                }
                if len(embedded_versions) != 1:
                    raise CandidateError(
                        f"{path.name}: embedded PKG-INFO versions disagree"
                    )
                metadata = next(
                    text for member, text in embedded_metadata if member == canonical[0]
                )
        else:
            raise CandidateError(f"unsupported release artifact: {path.name}")
    except CandidateError:
        raise
    except (OSError, UnicodeDecodeError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise CandidateError(f"could not read release artifact {path.name}") from exc

    return _metadata_version(metadata, artifact=path)


def _validate_web_dist(path: Path) -> None:
    """Require the prebuilt dashboard in every distributable archive."""
    try:
        if path.name.endswith(".whl"):
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
        elif path.name.endswith(".tar.gz"):
            with tarfile.open(path, mode="r:gz") as archive:
                names = [
                    member.name.split("/", 1)[1]
                    for member in archive.getmembers()
                    if "/" in member.name
                ]
        else:
            raise CandidateError(f"unsupported release artifact: {path.name}")
    except CandidateError:
        raise
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise CandidateError(f"could not inspect dashboard assets in {path.name}") from exc

    if WEB_DIST_INDEX not in names:
        raise CandidateError(f"{path.name}: packaged dashboard index is missing")
    asset_names = [name for name in names if name.startswith(WEB_DIST_ASSET_PREFIX)]
    if not any(name.endswith(".js") for name in asset_names):
        raise CandidateError(f"{path.name}: packaged dashboard JavaScript is missing")
    if not any(name.endswith(".css") for name in asset_names):
        raise CandidateError(f"{path.name}: packaged dashboard CSS is missing")


def _project_version(project_root: Path) -> str:
    pyproject = project_root / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        version = data["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise CandidateError(
            f"could not read project version from {pyproject}"
        ) from exc
    if not isinstance(version, str) or not version.strip():
        raise CandidateError("project.version must be a non-empty string")
    return version.strip()


def _validate_identity(source_sha: str, repository: str) -> None:
    if not SHA_RE.fullmatch(source_sha):
        raise CandidateError("source SHA must be a lowercase 40-character commit SHA")
    if not REPOSITORY_RE.fullmatch(repository):
        raise CandidateError("repository must use owner/name form")


def _package_artifacts(dist_dir: Path) -> list[Path]:
    wheels = sorted(dist_dir.glob("*.whl"))
    source_archives = sorted(dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(source_archives) != 1:
        raise CandidateError(
            "candidate must contain exactly one wheel and one source distribution"
        )
    return [*wheels, *source_archives]


def _write_outputs(values: dict[str, str], output_path: Path | None = None) -> None:
    destination = output_path or (
        Path(os.environ["GITHUB_OUTPUT"]) if os.environ.get("GITHUB_OUTPUT") else None
    )
    if destination is None:
        return
    with destination.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def create_candidate(
    dist_dir: Path,
    *,
    project_root: Path,
    source_sha: str,
    repository: str,
    output_path: Path | None = None,
) -> dict:
    """Write a manifest and checksum file for freshly built artifacts."""
    _validate_identity(source_sha, repository)
    version = _project_version(project_root)
    artifacts = _package_artifacts(dist_dir)

    rows = []
    for artifact in artifacts:
        embedded_version = artifact_version(artifact)
        if embedded_version != version:
            raise CandidateError(
                f"{artifact.name}: embedded version {embedded_version!r} "
                f"does not match project version {version!r}"
            )
        _validate_web_dist(artifact)
        rows.append({
            "name": artifact.name,
            "sha256": _sha256(artifact),
            "size": artifact.stat().st_size,
        })

    rows.sort(key=lambda row: row["name"])
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "source_sha": source_sha,
        "version": version,
        "artifacts": rows,
    }
    manifest_path = dist_dir / "release-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (dist_dir / "SHA256SUMS").write_text(
        "".join(f"{row['sha256']}  {row['name']}\n" for row in rows),
        encoding="utf-8",
    )
    _write_outputs(
        {"source_sha": source_sha, "version": version},
        output_path,
    )
    return manifest


def verify_candidate(
    dist_dir: Path,
    *,
    source_sha: str,
    repository: str,
    output_path: Path | None = None,
) -> dict:
    """Verify archive integrity, checksums, version, and source provenance."""
    _validate_identity(source_sha, repository)
    manifest_path = dist_dir / "release-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateError("release-manifest.json is missing or invalid") from exc

    expected_header = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "source_sha": source_sha,
    }
    for key, expected in expected_header.items():
        if manifest.get(key) != expected:
            raise CandidateError(
                f"manifest {key} {manifest.get(key)!r} does not match {expected!r}"
            )

    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        raise CandidateError("manifest version must be a non-empty string")
    rows = manifest.get("artifacts")
    if not isinstance(rows, list) or len(rows) != 2:
        raise CandidateError("manifest must describe exactly two package artifacts")

    try:
        actual_files = {
            path.name
            for path in dist_dir.iterdir()
            if path.is_file() and path.name not in IGNORED_BUILD_FILES
        }
    except OSError as exc:
        raise CandidateError(f"candidate directory is unavailable: {dist_dir}") from exc
    described_files: set[str] = set()
    expected_checksums: list[str] = []
    suffixes: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise CandidateError("manifest artifact rows must be objects")
        name = row.get("name")
        if not isinstance(name, str) or Path(name).name != name:
            raise CandidateError("manifest artifact names must be plain file names")
        if name in described_files:
            raise CandidateError(f"duplicate manifest artifact: {name}")
        if name.endswith(".whl"):
            suffixes.add("wheel")
        elif name.endswith(".tar.gz"):
            suffixes.add("sdist")
        else:
            raise CandidateError(f"unsupported manifest artifact: {name}")

        artifact = dist_dir / name
        if not artifact.is_file():
            raise CandidateError(f"manifest artifact is missing: {name}")
        digest = _sha256(artifact)
        if row.get("sha256") != digest:
            raise CandidateError(f"checksum mismatch for {name}")
        if row.get("size") != artifact.stat().st_size:
            raise CandidateError(f"size mismatch for {name}")
        if artifact_version(artifact) != version:
            raise CandidateError(f"embedded version mismatch for {name}")
        _validate_web_dist(artifact)

        described_files.add(name)
        expected_checksums.append(f"{digest}  {name}\n")

    if suffixes != {"wheel", "sdist"}:
        raise CandidateError(
            "manifest must contain one wheel and one source distribution"
        )
    allowed_files = described_files | {"release-manifest.json", "SHA256SUMS"}
    if actual_files != allowed_files:
        extras = sorted(actual_files - allowed_files)
        missing = sorted(allowed_files - actual_files)
        raise CandidateError(
            f"candidate file set mismatch (extra={extras}, missing={missing})"
        )

    checksums_path = dist_dir / "SHA256SUMS"
    try:
        checksum_text = checksums_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CandidateError("SHA256SUMS is missing") from exc
    if checksum_text != "".join(expected_checksums):
        raise CandidateError("SHA256SUMS does not match the manifest")

    _write_outputs(
        {"source_sha": source_sha, "version": version},
        output_path,
    )
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("create", "verify"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--dist", type=Path, default=Path("dist"))
        subparser.add_argument("--source-sha", required=True)
        subparser.add_argument("--repository", required=True)
        subparser.add_argument("--output", type=Path)
        if command == "create":
            subparser.add_argument("--project-root", type=Path, default=Path("."))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            manifest = create_candidate(
                args.dist,
                project_root=args.project_root,
                source_sha=args.source_sha,
                repository=args.repository,
                output_path=args.output,
            )
        else:
            manifest = verify_candidate(
                args.dist,
                source_sha=args.source_sha,
                repository=args.repository,
                output_path=args.output,
            )
    except CandidateError as exc:
        parser = _parser()
        parser.error(str(exc))
    print(
        f"release candidate verified: v{manifest['version']} "
        f"from {manifest['source_sha']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
