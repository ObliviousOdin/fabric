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
FABRIC_AGENT_NAME = "fabric-agent"
FABRIC_LINK_CORE_NAME = "fabric-link-core"
LINK_CORE_PLATFORMS = ("linux", "macos", "windows")


class CandidateError(ValueError):
    """Raised when a release candidate fails its provenance contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_field(text: str, field: str, *, artifact: Path) -> str:
    matches = re.findall(rf"(?m)^{re.escape(field)}:\s*(\S+)\s*$", text)
    if len(matches) != 1:
        raise CandidateError(
            f"{artifact.name}: expected one package {field} field, found {len(matches)}"
        )
    return matches[0]


def _metadata_texts(path: Path) -> list[str]:
    """Read all authoritative metadata records from one Python artifact."""
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
                return [archive.read(metadata_files[0]).decode("utf-8")]
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
                    embedded_metadata.append(extracted.read().decode("utf-8"))
                return embedded_metadata
        else:
            raise CandidateError(f"unsupported release artifact: {path.name}")
    except CandidateError:
        raise
    except (OSError, UnicodeDecodeError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise CandidateError(f"could not read release artifact {path.name}") from exc


def _normalize_project_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def artifact_identity(path: Path) -> tuple[str, str]:
    """Return the normalized project name and version embedded in ``path``."""
    metadata = _metadata_texts(path)
    names = {_normalize_project_name(_metadata_field(text, "Name", artifact=path)) for text in metadata}
    versions = {_metadata_field(text, "Version", artifact=path) for text in metadata}
    if len(names) != 1:
        raise CandidateError(f"{path.name}: embedded package names disagree")
    if len(versions) != 1:
        raise CandidateError(f"{path.name}: embedded package versions disagree")
    return names.pop(), versions.pop()


def artifact_version(path: Path) -> str:
    """Read the embedded package version from a wheel or source archive."""
    return artifact_identity(path)[1]


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


def _wheel_platform(path: Path) -> str:
    if not path.name.endswith(".whl"):
        raise CandidateError(f"not a wheel: {path.name}")
    parts = path.name.removesuffix(".whl").rsplit("-", 3)
    if len(parts) != 4:
        raise CandidateError(f"invalid wheel filename: {path.name}")
    return parts[-1].lower()


def _link_core_platform(path: Path) -> str | None:
    platform = _wheel_platform(path)
    if platform.startswith("macosx_"):
        return "macos"
    if platform.startswith("win_"):
        return "windows"
    if (
        platform.startswith("linux_")
        or platform.startswith("manylinux")
        or platform.startswith("musllinux")
    ):
        return "linux"
    return None


def _package_artifacts(
    dist_dir: Path,
    *,
    require_link_core: bool,
) -> tuple[list[Path], tuple[str, ...]]:
    """Validate the release family and return every artifact in it.

    The universal Fabric package is intentionally still one wheel plus one
    source archive.  When Link is enabled for a release, its native companion
    is a separate, exact three-platform wheel family; source fallback is never
    accepted for Link crypto.
    """
    wheels = sorted(dist_dir.glob("*.whl"))
    source_archives = sorted(dist_dir.glob("*.tar.gz"))
    agent_wheels: list[Path] = []
    link_core_wheels: list[Path] = []
    for wheel in wheels:
        project_name, _version = artifact_identity(wheel)
        if project_name == FABRIC_AGENT_NAME:
            agent_wheels.append(wheel)
        elif project_name == FABRIC_LINK_CORE_NAME:
            link_core_wheels.append(wheel)
        else:
            raise CandidateError(f"unsupported release wheel project: {wheel.name}")

    if len(agent_wheels) != 1 or len(source_archives) != 1:
        raise CandidateError(
            "candidate must contain exactly one Fabric wheel and one source distribution"
        )
    source_name, _source_version = artifact_identity(source_archives[0])
    if source_name != FABRIC_AGENT_NAME:
        raise CandidateError("candidate source distribution must package fabric-agent")
    if _wheel_platform(agent_wheels[0]) != "any":
        raise CandidateError("Fabric wheel must remain universal (platform tag any)")

    if not require_link_core:
        if link_core_wheels:
            raise CandidateError("candidate includes Link wheels without Link release manifest")
        return [*agent_wheels, *source_archives], ()

    if len(link_core_wheels) != len(LINK_CORE_PLATFORMS):
        raise CandidateError(
            "Link release candidate must contain one native wheel for each supported platform"
        )
    platforms: list[str] = []
    for wheel in link_core_wheels:
        platform = _link_core_platform(wheel)
        if platform is None:
            raise CandidateError(f"unsupported Fabric Link wheel platform: {wheel.name}")
        platforms.append(platform)
    if tuple(sorted(platforms)) != LINK_CORE_PLATFORMS:
        raise CandidateError(
            "Link release candidate must contain exactly Linux, macOS, and Windows wheels"
        )
    return [*agent_wheels, *source_archives, *link_core_wheels], tuple(sorted(platforms))


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
    require_link_core: bool = False,
) -> dict:
    """Write a manifest and checksum file for freshly built artifacts."""
    _validate_identity(source_sha, repository)
    version = _project_version(project_root)
    artifacts, link_core_platforms = _package_artifacts(
        dist_dir,
        require_link_core=require_link_core,
    )

    rows = []
    for artifact in artifacts:
        project_name, embedded_version = artifact_identity(artifact)
        if embedded_version != version:
            raise CandidateError(
                f"{artifact.name}: embedded version {embedded_version!r} "
                f"does not match project version {version!r}"
            )
        if project_name == FABRIC_AGENT_NAME:
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
    if require_link_core:
        manifest["link_core"] = {"platforms": list(link_core_platforms)}
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
    raw_link_core = manifest.get("link_core")
    if raw_link_core is None:
        require_link_core = False
    elif (
        not isinstance(raw_link_core, dict)
        or set(raw_link_core) != {"platforms"}
        or raw_link_core.get("platforms") != list(LINK_CORE_PLATFORMS)
    ):
        raise CandidateError("manifest Link companion platform set is invalid")
    else:
        require_link_core = True

    rows = manifest.get("artifacts")
    expected_rows = 2 + (len(LINK_CORE_PLATFORMS) if require_link_core else 0)
    if not isinstance(rows, list) or len(rows) != expected_rows:
        raise CandidateError(
            f"manifest must describe exactly {expected_rows} package artifacts"
        )

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
    for row in rows:
        if not isinstance(row, dict):
            raise CandidateError("manifest artifact rows must be objects")
        name = row.get("name")
        if not isinstance(name, str) or Path(name).name != name:
            raise CandidateError("manifest artifact names must be plain file names")
        if name in described_files:
            raise CandidateError(f"duplicate manifest artifact: {name}")
        if not (name.endswith(".whl") or name.endswith(".tar.gz")):
            raise CandidateError(f"unsupported manifest artifact: {name}")

        artifact = dist_dir / name
        if not artifact.is_file():
            raise CandidateError(f"manifest artifact is missing: {name}")
        digest = _sha256(artifact)
        if row.get("sha256") != digest:
            raise CandidateError(f"checksum mismatch for {name}")
        if row.get("size") != artifact.stat().st_size:
            raise CandidateError(f"size mismatch for {name}")
        project_name, embedded_version = artifact_identity(artifact)
        if embedded_version != version:
            raise CandidateError(f"embedded version mismatch for {name}")
        if project_name == FABRIC_AGENT_NAME:
            _validate_web_dist(artifact)

        described_files.add(name)
        expected_checksums.append(f"{digest}  {name}\n")

    _artifacts, link_core_platforms = _package_artifacts(
        dist_dir,
        require_link_core=require_link_core,
    )
    if require_link_core and tuple(raw_link_core["platforms"]) != link_core_platforms:
        raise CandidateError("manifest Link companion platforms do not match artifacts")
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
            subparser.add_argument("--require-link-core", action="store_true")
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
                require_link_core=args.require_link_core,
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
