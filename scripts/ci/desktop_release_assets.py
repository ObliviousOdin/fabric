#!/usr/bin/env python3
"""Collect, verify, and immutably attach signed desktop installers to a release.

This is the desktop counterpart to ``release_candidate.py`` / ``publish_release.py``.
The Python release publishes the wheel/sdist with strong provenance; this script
bridges the gap for the desktop installers built by ``desktop-release.yml``:

* ``resolve`` guards the packaging matrix — it validates the production release the
  installers will attach to, binds the dispatched ``$GITHUB_SHA`` to the release
  tag's commit, and decides whether this desktop version already shipped (the
  build-once gate, see the design's §3.5).
* ``collect`` runs on each matrix runner after packaging. It re-implements the
  expected artifact name/architecture matrix that ``desktop-packaging.yml`` pins in
  its frozen inline heredoc, hashes every installer, and writes a per-platform
  manifest fragment plus a per-platform ``SHA256SUMS``.
* ``verify`` runs before anything touches the release: it re-hashes every collected
  installer against the per-platform fragments and merges them into a single
  ``desktop-release-manifest.json`` + ``SHA256SUMS-desktop.txt``.
* ``attach`` uploads with **immutable** semantics — signed/notarized builds are
  never byte-identical across runs, so an already-attached asset is verified and
  skipped; a digest mismatch fails loudly unless ``--force-replace`` is passed, and
  every replacement is recorded in the manifest.

Only the standard library plus the ``gh`` CLI (already required by
``publish_release.py``) are used, so the collect/verify halves run before project
dependencies are installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1

# The public brand's artifact stem. Kept in sync with
# ``apps/desktop/branding/fabric.json`` ``artifactName`` and asserted by the
# desktop brand contract; a drift here is caught by the cross-check test.
ARTIFACT_NAME = "Fabric"

# The ext -> arch matrix, mirrored from ``desktop-packaging.yml``'s frozen
# ``matrix.artifact_arches`` heredoc. ``job_arch`` is the coarse per-runner
# architecture used only in the per-platform ``SHA256SUMS`` file name; the
# per-target ``arch`` embedded in each installer name is finer-grained.
# ``test_desktop_release_assets.py`` asserts this agrees with the workflow, so a
# future edit to either side that drifts them apart fails CI.
PLATFORM_ARTIFACTS: dict[str, dict[str, object]] = {
    "mac": {"job_arch": "arm64", "artifacts": {"dmg": "arm64", "zip": "arm64"}},
    "win": {"job_arch": "x64", "artifacts": {"exe": "x64", "msi": "x64"}},
    "linux": {
        "job_arch": "x64",
        "artifacts": {"AppImage": "x86_64", "deb": "amd64", "rpm": "x86_64"},
    },
}

MANIFEST_NAME = "desktop-release-manifest.json"
# ``.txt`` (not ``.desktop``, which collides with freedesktop launcher files).
COMBINED_SUMS_NAME = "SHA256SUMS-desktop.txt"
PLATFORM_MANIFEST_PREFIX = "desktop-release-manifest."

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
# Same CalVer form the Python publisher enforces (publish_release.TAG_RE).
TAG_RE = re.compile(
    r"^v20\d{2}\.(?:[1-9]|1[0-2])\.(?:[1-9]|[12]\d|3[01])(?:\.[2-9]\d*)?$"
)
# Independent desktop semver (apps/desktop/package.json), e.g. ``0.21.0``.
DESKTOP_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")

# ``["her", "mes"].join("")`` in the frozen heredoc; constructed the same way so
# the literal retired identity never appears in this source (the public audit
# would otherwise flag it).
_FORBIDDEN_ARTIFACT_STEM = "".join(("her", "mes"))
_FORBIDDEN_ARTIFACT_RE = re.compile(
    rf"^{_FORBIDDEN_ARTIFACT_STEM}(?:[-_.]|$)", re.IGNORECASE
)


class DesktopAssetError(RuntimeError):
    """Raised when desktop release assets fail their provenance contract."""


@dataclass(frozen=True)
class ExpectedArtifact:
    name: str
    ext: str
    arch: str


# ── shared helpers ──────────────────────────────────────────────────────────


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_repo_tag(repository: str, tag: str) -> None:
    if not REPOSITORY_RE.fullmatch(repository):
        raise DesktopAssetError("repository must use owner/name form")
    if not TAG_RE.fullmatch(tag):
        raise DesktopAssetError(
            "release tag must use CalVer form vYYYY.M.D or vYYYY.M.D.N"
        )


def _validate_identity(source_sha: str, repository: str, tag: str) -> None:
    if not SHA_RE.fullmatch(source_sha):
        raise DesktopAssetError(
            "source SHA must be a lowercase 40-character commit SHA"
        )
    _validate_repo_tag(repository, tag)


def _validate_desktop_version(version: str) -> None:
    if not DESKTOP_VERSION_RE.fullmatch(version):
        raise DesktopAssetError(
            f"desktop version {version!r} must be a semantic version"
        )


def expected_artifacts(platform: str, version: str) -> list[ExpectedArtifact]:
    """Return the exact installer names a platform must produce for ``version``."""
    if platform not in PLATFORM_ARTIFACTS:
        raise DesktopAssetError(
            f"unknown desktop platform {platform!r}; "
            f"expected one of {sorted(PLATFORM_ARTIFACTS)}"
        )
    artifacts = PLATFORM_ARTIFACTS[platform]["artifacts"]
    assert isinstance(artifacts, dict)
    rows = [
        ExpectedArtifact(
            name=f"{ARTIFACT_NAME}-{version}-{platform}-{arch}.{ext}",
            ext=ext,
            arch=arch,
        )
        for ext, arch in artifacts.items()
    ]
    return sorted(rows, key=lambda row: row.name)


def _files_below(directory: Path) -> list[Path]:
    return [path for path in directory.rglob("*") if path.is_file()]


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_outputs(values: dict[str, str], output_path: Path | None) -> None:
    destination = output_path or (
        Path(os.environ["GITHUB_OUTPUT"]) if os.environ.get("GITHUB_OUTPUT") else None
    )
    if destination is None:
        return
    with destination.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


# ── collect ─────────────────────────────────────────────────────────────────


def collect_platform_assets(
    release_dir: Path,
    *,
    out_dir: Path,
    platform: str,
    repository: str,
    tag: str,
    source_sha: str,
    desktop_version: str,
) -> dict:
    """Verify one platform's installer names, hash them, and stage a manifest."""
    _validate_identity(source_sha, repository, tag)
    _validate_desktop_version(desktop_version)
    if not release_dir.is_dir():
        raise DesktopAssetError(f"release directory is unavailable: {release_dir}")

    produced = _files_below(release_dir)
    forbidden = sorted(
        path.name
        for path in produced
        if _FORBIDDEN_ARTIFACT_RE.match(path.name)
    )
    if forbidden:
        raise DesktopAssetError(
            f"former-product artifacts present: {', '.join(forbidden)}"
        )

    by_name: dict[str, list[Path]] = {}
    for path in produced:
        by_name.setdefault(path.name, []).append(path)

    rows: list[dict] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for artifact in expected_artifacts(platform, desktop_version):
        matches = by_name.get(artifact.name, [])
        if not matches:
            raise DesktopAssetError(f"missing {artifact.name}")
        if len(matches) > 1:
            locations = ", ".join(
                str(match.relative_to(release_dir)) for match in matches
            )
            raise DesktopAssetError(f"duplicate {artifact.name}: {locations}")
        source = matches[0]
        shutil.copyfile(source, out_dir / artifact.name)
        rows.append(
            {
                "name": artifact.name,
                "ext": artifact.ext,
                "arch": artifact.arch,
                "size": source.stat().st_size,
                "sha256": _sha256(source),
            }
        )

    rows.sort(key=lambda row: row["name"])
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "tag": tag,
        "source_sha": source_sha,
        "desktop_app_version": desktop_version,
        "platform": platform,
        "files": rows,
    }
    _write_json(out_dir / f"{PLATFORM_MANIFEST_PREFIX}{platform}.json", manifest)

    job_arch = PLATFORM_ARTIFACTS[platform]["job_arch"]
    sums_name = f"{ARTIFACT_NAME}-{desktop_version}-{platform}-{job_arch}.SHA256SUMS"
    (out_dir / sums_name).write_text(
        "".join(f"{row['sha256']}  {row['name']}\n" for row in rows),
        encoding="utf-8",
    )
    return manifest


# ── verify (merge per-platform fragments before attach) ─────────────────────


def _load_platform_manifests(staging_dir: Path) -> list[dict]:
    fragments = sorted(
        path
        for path in staging_dir.rglob(f"{PLATFORM_MANIFEST_PREFIX}*.json")
        if path.is_file() and path.name != MANIFEST_NAME
    )
    if not fragments:
        raise DesktopAssetError(
            f"no per-platform desktop manifests found under {staging_dir}"
        )
    manifests = []
    for fragment in fragments:
        try:
            manifests.append(json.loads(fragment.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            raise DesktopAssetError(
                f"could not read platform manifest {fragment.name}"
            ) from exc
    return manifests


def verify_release_assets(
    staging_dir: Path,
    *,
    out_dir: Path,
    repository: str,
    tag: str,
    source_sha: str,
    desktop_version: str,
    expected_platforms: frozenset[str] | None = None,
) -> dict:
    """Re-hash every collected installer and merge platform fragments into one."""
    _validate_identity(source_sha, repository, tag)
    _validate_desktop_version(desktop_version)
    required = (
        frozenset(PLATFORM_ARTIFACTS)
        if expected_platforms is None
        else expected_platforms
    )

    manifests = _load_platform_manifests(staging_dir)
    header = {
        "repository": repository,
        "tag": tag,
        "source_sha": source_sha,
        "desktop_app_version": desktop_version,
    }
    seen_platforms: set[str] = set()
    merged_files: dict[str, dict] = {}
    staged = {path.name: path for path in _files_below(staging_dir)}

    for manifest in manifests:
        for key, expected in header.items():
            if manifest.get(key) != expected:
                raise DesktopAssetError(
                    f"platform manifest {key} {manifest.get(key)!r} "
                    f"does not match {expected!r}"
                )
        platform = manifest.get("platform")
        if platform not in PLATFORM_ARTIFACTS:
            raise DesktopAssetError(f"unknown platform in manifest: {platform!r}")
        if platform in seen_platforms:
            raise DesktopAssetError(f"duplicate platform manifest: {platform}")
        seen_platforms.add(platform)

        expected_names = {
            artifact.name for artifact in expected_artifacts(platform, desktop_version)
        }
        recorded_names = {row["name"] for row in manifest.get("files", [])}
        if recorded_names != expected_names:
            missing = sorted(expected_names - recorded_names)
            extra = sorted(recorded_names - expected_names)
            raise DesktopAssetError(
                f"{platform} manifest file set mismatch "
                f"(missing={missing}, extra={extra})"
            )

        for row in manifest["files"]:
            name = row["name"]
            artifact = staged.get(name)
            if artifact is None:
                raise DesktopAssetError(f"collected installer is missing: {name}")
            digest = _sha256(artifact)
            if digest != row.get("sha256"):
                raise DesktopAssetError(f"checksum mismatch for {name}")
            if artifact.stat().st_size != row.get("size"):
                raise DesktopAssetError(f"size mismatch for {name}")
            if name in merged_files:
                raise DesktopAssetError(f"duplicate installer across platforms: {name}")
            merged_files[name] = {
                "name": name,
                "ext": row["ext"],
                "arch": row["arch"],
                "platform": platform,
                "size": row["size"],
                "sha256": row["sha256"],
            }

    missing_platforms = sorted(required - seen_platforms)
    if missing_platforms:
        raise DesktopAssetError(
            f"missing installers for platform(s): {', '.join(missing_platforms)}"
        )

    files = [merged_files[name] for name in sorted(merged_files)]
    combined = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "tag": tag,
        "source_sha": source_sha,
        "desktop_app_version": desktop_version,
        "platforms": sorted(seen_platforms),
        "files": files,
        "replacements": [],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, path in staged.items():
        if path.parent != out_dir:
            shutil.copyfile(path, out_dir / name)
    _write_json(out_dir / MANIFEST_NAME, combined)
    (out_dir / COMBINED_SUMS_NAME).write_text(
        "".join(f"{row['sha256']}  {row['name']}\n" for row in files),
        encoding="utf-8",
    )
    return combined


# ── attach (immutable upload to the GitHub Release) ─────────────────────────


def _run_gh(
    args: list[str],
    *,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["gh", *args],
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise DesktopAssetError(f"gh {' '.join(args)} failed: {detail}")
    return completed


def _release_asset_names(repository: str, tag: str) -> set[str]:
    completed = _run_gh(
        ["api", f"repos/{repository}/releases/tags/{tag}", "--jq", ".assets[].name"],
    )
    return {line for line in completed.stdout.splitlines() if line.strip()}


def _download_attached_manifest(repository: str, tag: str, dest: Path) -> dict | None:
    completed = _run_gh(
        [
            "release",
            "download",
            tag,
            "--repo",
            repository,
            "--pattern",
            MANIFEST_NAME,
            "--dir",
            str(dest),
            "--clobber",
        ],
        check=False,
    )
    if completed.returncode != 0:
        return None
    manifest_path = dest / MANIFEST_NAME
    if not manifest_path.is_file():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DesktopAssetError("attached desktop manifest is unreadable") from exc


def _recorded_digests(manifest: dict | None) -> dict[str, str]:
    if not manifest:
        return {}
    return {
        row["name"]: row["sha256"]
        for row in manifest.get("files", [])
        if isinstance(row, dict) and "name" in row and "sha256" in row
    }


def attach_release_assets(
    assets_dir: Path,
    *,
    repository: str,
    tag: str,
    force_replace: bool = False,
    work_dir: Path | None = None,
) -> dict:
    """Attach installers immutably: skip identical, refuse or record replacements."""
    _validate_repo_tag(repository, tag)
    manifest_path = assets_dir / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DesktopAssetError(f"{MANIFEST_NAME} is missing or invalid") from exc

    local_digests = {row["name"]: row["sha256"] for row in manifest["files"]}
    installer_names = sorted(local_digests)
    # Derived metadata (per-platform sums, the combined sums, and the manifest) is
    # uploaded AFTER every installer, with the manifest strictly last, so a partial
    # run is never advertised as complete. These are re-derived each run, never a
    # byte a prior downloader already received, so overwriting them is safe.
    per_platform_sums = sorted(
        path.name for path in assets_dir.glob("*.SHA256SUMS")
    )
    trailing = [*per_platform_sums, COMBINED_SUMS_NAME, MANIFEST_NAME]
    for name in [*installer_names, *trailing]:
        if not (assets_dir / name).is_file():
            raise DesktopAssetError(f"asset to attach is missing locally: {name}")

    existing_names = _release_asset_names(repository, tag)
    staging = work_dir or (assets_dir / ".attached-manifest")
    attached = _download_attached_manifest(repository, tag, staging)
    attached_digests = _recorded_digests(attached)

    # Decide the full plan before any upload: a mismatch without force_replace must
    # abort before mutating the release at all.
    replacements: list[dict] = []
    installer_uploads: list[tuple[str, bool]] = []
    for name in installer_names:
        if name not in existing_names:
            installer_uploads.append((name, False))
            continue
        recorded = attached_digests.get(name)
        if recorded == local_digests[name]:
            continue  # already attached, byte-for-byte identical -> skip
        if not force_replace:
            raise DesktopAssetError(
                f"{name} is already attached with a different digest "
                f"(recorded={recorded}, new={local_digests[name]}); "
                "re-dispatch with force_replace to overwrite"
            )
        replacements.append(
            {"name": name, "old_sha256": recorded, "new_sha256": local_digests[name]}
        )
        installer_uploads.append((name, True))

    if replacements:
        manifest["replacements"] = [*manifest.get("replacements", []), *replacements]
        _write_json(manifest_path, manifest)

    for name, replace in installer_uploads:
        _upload_asset(repository, tag, assets_dir / name, replace=replace)
    # Trailing metadata always (re)uploads last — it is derived, never a byte a
    # prior downloader received, so overwriting it is safe and keeps the manifest
    # advertising the complete set only after every installer is present.
    for name in trailing:
        _upload_asset(
            repository, tag, assets_dir / name, replace=name in existing_names
        )

    final_names = _release_asset_names(repository, tag)
    required = {*installer_names, *trailing}
    missing = sorted(required - final_names)
    if missing:
        raise DesktopAssetError(
            f"release is missing attached assets after upload: {', '.join(missing)}"
        )
    return {
        "attached": sorted(required),
        "uploaded": [name for name, _ in installer_uploads],
        "replacements": replacements,
    }


def _upload_asset(repository: str, tag: str, path: Path, *, replace: bool) -> None:
    args = ["release", "upload", tag, "--repo", repository, str(path)]
    if replace:
        args.append("--clobber")
    _run_gh(args)


# ── resolve (guard the packaging matrix) ────────────────────────────────────


def _desktop_version_from_package(package_json: Path) -> str:
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
        version = data["version"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise DesktopAssetError(
            f"could not read desktop version from {package_json}"
        ) from exc
    if not isinstance(version, str) or not version.strip():
        raise DesktopAssetError("desktop package version must be a non-empty string")
    return version.strip()


def decide_should_package(
    desktop_version: str,
    *,
    prior_versions: frozenset[str],
    force_rebuild: bool,
) -> bool:
    """Return whether the packaging matrix should run for this desktop version.

    The build-once gate (§3.5): a desktop version already shipped in a prior
    release must not be repackaged (its installer names would collide with
    different bytes), unless the dispatcher explicitly forces a rebuild.
    """
    if force_rebuild:
        return True
    return desktop_version not in prior_versions


def _tag_commit_sha(repository: str, tag: str) -> str:
    ref = _run_gh(["api", f"repos/{repository}/git/ref/tags/{tag}"])
    try:
        obj = json.loads(ref.stdout)["object"]
        sha, obj_type = obj["sha"], obj["type"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise DesktopAssetError(f"could not resolve tag ref for {tag}") from exc
    if obj_type == "commit":
        return sha
    # Annotated tag: dereference to the commit it points at.
    annotated = _run_gh(["api", f"repos/{repository}/git/tags/{sha}"])
    try:
        return json.loads(annotated.stdout)["object"]["sha"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise DesktopAssetError(
            f"could not dereference annotated tag {tag}"
        ) from exc


def _prior_desktop_manifests(
    repository: str, *, exclude_tag: str | None = None
) -> list[dict]:
    """Return the desktop manifests attached to prior releases (best effort)."""
    listed = _run_gh(
        ["api", f"repos/{repository}/releases?per_page=100", "--jq", ".[].tag_name"],
    )
    manifests: list[dict] = []
    for other in (line.strip() for line in listed.stdout.splitlines()):
        if not other or other == exclude_tag:
            continue
        manifest = _download_attached_manifest(repository, other, Path(".prior-manifest"))
        if isinstance(manifest, dict) and manifest.get("desktop_app_version"):
            manifests.append({**manifest, "tag": manifest.get("tag", other)})
    return manifests


def _prior_desktop_versions(repository: str, *, exclude_tag: str) -> frozenset[str]:
    return frozenset(
        manifest["desktop_app_version"]
        for manifest in _prior_desktop_manifests(repository, exclude_tag=exclude_tag)
    )


def evaluate_preflight(
    desktop_version: str,
    source_sha: str,
    *,
    prior: list[dict],
    inputs_changed,
) -> dict | None:
    """Return a conflicting prior release, or ``None`` when promotion is safe.

    The pre-publish gate (§3.5) blocks a promotion *before the Python release
    exists* only when the same desktop version already shipped from a different
    commit **and** the desktop build inputs changed since — the exact case where
    two releases would otherwise carry same-named, different-byte installers. A
    Python-only release (identical desktop inputs) is intentionally allowed; the
    in-pipeline gate then skips repackaging.
    """
    for manifest in prior:
        if manifest.get("desktop_app_version") != desktop_version:
            continue
        prior_sha = manifest.get("source_sha")
        if not isinstance(prior_sha, str) or prior_sha == source_sha:
            continue
        if inputs_changed(prior_sha, source_sha):
            return manifest
    return None


# Desktop build inputs, mirrored from ``desktop-packaging.yml``'s path filter: a
# change under any of these since the last release of the same desktop version
# means the installers would differ and the version must be bumped.
DESKTOP_INPUT_PATHS = (
    "apps/desktop",
    "apps/shared",
    "package.json",
    "package-lock.json",
)


def _git_inputs_changed(old_sha: str, new_sha: str) -> bool:
    completed = subprocess.run(
        ["git", "diff", "--quiet", old_sha, new_sha, "--", *DESKTOP_INPUT_PATHS],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in (0, 1):
        raise DesktopAssetError(
            f"could not diff desktop inputs {old_sha}..{new_sha}: "
            f"{completed.stderr.strip()}"
        )
    return completed.returncode == 1


def preflight_version_gate(
    *,
    repository: str,
    desktop_version: str,
    source_sha: str,
    inputs_changed=_git_inputs_changed,
) -> dict | None:
    if not REPOSITORY_RE.fullmatch(repository):
        raise DesktopAssetError("repository must use owner/name form")
    if not SHA_RE.fullmatch(source_sha):
        raise DesktopAssetError("source SHA must be a 40-character commit SHA")
    _validate_desktop_version(desktop_version)
    prior = _prior_desktop_manifests(repository)
    conflict = evaluate_preflight(
        desktop_version, source_sha, prior=prior, inputs_changed=inputs_changed
    )
    if conflict is not None:
        raise DesktopAssetError(
            f"desktop version {desktop_version} already shipped in "
            f"{conflict.get('tag')} from a different commit and the desktop build "
            "inputs changed since; bump apps/desktop/package.json before promoting"
        )
    return None


def resolve_release(
    *,
    repository: str,
    tag: str,
    github_sha: str,
    desktop_version: str,
    force_rebuild: bool,
) -> dict:
    """Validate the release, bind the dispatched SHA, and decide packaging."""
    if not REPOSITORY_RE.fullmatch(repository):
        raise DesktopAssetError("repository must use owner/name form")
    if not TAG_RE.fullmatch(tag):
        raise DesktopAssetError("release tag must use CalVer form")
    if not SHA_RE.fullmatch(github_sha):
        raise DesktopAssetError("github SHA must be a 40-character commit SHA")
    _validate_desktop_version(desktop_version)

    release = _run_gh(["api", f"repos/{repository}/releases/tags/{tag}"])
    try:
        payload = json.loads(release.stdout)
    except json.JSONDecodeError as exc:
        raise DesktopAssetError(f"could not read release {tag}") from exc
    if payload.get("draft"):
        raise DesktopAssetError(f"release {tag} is a draft; refusing to attach")
    if payload.get("prerelease"):
        raise DesktopAssetError(f"release {tag} is a prerelease; refusing to attach")

    tag_sha = _tag_commit_sha(repository, tag)
    if tag_sha != github_sha:
        raise DesktopAssetError(
            f"dispatched SHA {github_sha} does not match tag {tag} commit {tag_sha}; "
            "dispatch desktop-release.yml at ref: <tag>, not main"
        )

    prior = _prior_desktop_versions(repository, exclude_tag=tag)
    should_package = decide_should_package(
        desktop_version, prior_versions=prior, force_rebuild=force_rebuild
    )
    return {
        "source_sha": tag_sha,
        "desktop_version": desktop_version,
        "should_package": should_package,
    }


# ── CLI ─────────────────────────────────────────────────────────────────────


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser("resolve", help="Validate the release and gate packaging")
    resolve.add_argument("--repository", required=True)
    resolve.add_argument("--tag", required=True)
    resolve.add_argument("--github-sha", required=True)
    resolve.add_argument(
        "--desktop-package",
        type=Path,
        default=Path("apps/desktop/package.json"),
    )
    resolve.add_argument("--force-rebuild", action="store_true")
    resolve.add_argument("--output", type=Path)

    collect = sub.add_parser("collect", help="Hash one platform's installers")
    collect.add_argument("--release-dir", type=Path, required=True)
    collect.add_argument("--out-dir", type=Path, required=True)
    collect.add_argument("--platform", required=True, choices=sorted(PLATFORM_ARTIFACTS))
    collect.add_argument("--repository", required=True)
    collect.add_argument("--tag", required=True)
    collect.add_argument("--source-sha", required=True)
    collect.add_argument("--desktop-version", required=True)

    verify = sub.add_parser("verify", help="Merge and re-verify platform fragments")
    verify.add_argument("--staging-dir", type=Path, required=True)
    verify.add_argument("--out-dir", type=Path, required=True)
    verify.add_argument("--repository", required=True)
    verify.add_argument("--tag", required=True)
    verify.add_argument("--source-sha", required=True)
    verify.add_argument("--desktop-version", required=True)

    attach = sub.add_parser("attach", help="Immutably attach assets to the release")
    attach.add_argument("--assets-dir", type=Path, required=True)
    attach.add_argument("--repository", required=True)
    attach.add_argument("--tag", required=True)
    attach.add_argument("--force-replace", action="store_true")

    preflight = sub.add_parser(
        "preflight", help="Fail promotion when the desktop version must be bumped"
    )
    preflight.add_argument("--repository", required=True)
    preflight.add_argument("--source-sha", required=True)
    preflight.add_argument(
        "--desktop-package",
        type=Path,
        default=Path("apps/desktop/package.json"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "resolve":
            desktop_version = _desktop_version_from_package(args.desktop_package)
            result = resolve_release(
                repository=args.repository,
                tag=args.tag,
                github_sha=args.github_sha,
                desktop_version=desktop_version,
                force_rebuild=args.force_rebuild,
            )
            _write_outputs(
                {
                    "source_sha": result["source_sha"],
                    "desktop_version": result["desktop_version"],
                    "should_package": "true" if result["should_package"] else "false",
                },
                args.output,
            )
            print(
                f"resolve: {args.tag} -> desktop v{result['desktop_version']} "
                f"(package={'yes' if result['should_package'] else 'skip'})"
            )
        elif args.command == "collect":
            manifest = collect_platform_assets(
                args.release_dir,
                out_dir=args.out_dir,
                platform=args.platform,
                repository=args.repository,
                tag=args.tag,
                source_sha=args.source_sha,
                desktop_version=args.desktop_version,
            )
            print(
                f"collect: {args.platform} -> {len(manifest['files'])} installer(s)"
            )
        elif args.command == "verify":
            combined = verify_release_assets(
                args.staging_dir,
                out_dir=args.out_dir,
                repository=args.repository,
                tag=args.tag,
                source_sha=args.source_sha,
                desktop_version=args.desktop_version,
            )
            print(
                f"verify: {len(combined['files'])} installer(s) across "
                f"{', '.join(combined['platforms'])}"
            )
        elif args.command == "attach":
            result = attach_release_assets(
                args.assets_dir,
                repository=args.repository,
                tag=args.tag,
                force_replace=args.force_replace,
            )
            replaced = len(result["replacements"])
            print(
                f"attach: {len(result['attached'])} asset(s) attached to {args.tag}"
                + (f", {replaced} replaced" if replaced else "")
            )
        else:  # preflight
            desktop_version = _desktop_version_from_package(args.desktop_package)
            preflight_version_gate(
                repository=args.repository,
                desktop_version=desktop_version,
                source_sha=args.source_sha,
            )
            print(f"preflight: desktop v{desktop_version} is safe to promote")
    except DesktopAssetError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
