"""Behavior contracts for desktop release asset collection, verify, and attach."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.ci import desktop_release_assets as dra


REPOSITORY = "ObliviousOdin/fabric"
SOURCE_SHA = "a" * 40
TAG = "v2026.7.15"
DESKTOP_VERSION = "0.21.0"
WORKFLOW = Path(".github/workflows/desktop-packaging.yml")


def _write_installers(release_dir: Path, platform: str, version: str) -> None:
    release_dir.mkdir(parents=True, exist_ok=True)
    for artifact in dra.expected_artifacts(platform, version):
        # Distinct bytes per file so digests differ and collisions surface.
        (release_dir / artifact.name).write_bytes(artifact.name.encode() + b"-payload")


def _collect(tmp_path: Path, platform: str, *, version: str = DESKTOP_VERSION) -> Path:
    release_dir = tmp_path / f"release-{platform}"
    out_dir = tmp_path / f"staged-{platform}"
    _write_installers(release_dir, platform, version)
    dra.collect_platform_assets(
        release_dir,
        out_dir=out_dir,
        platform=platform,
        repository=REPOSITORY,
        tag=TAG,
        source_sha=SOURCE_SHA,
        desktop_version=version,
    )
    return out_dir


# ── the ext -> arch matrix must never drift from the frozen workflow heredoc ──


def test_platform_matrix_matches_desktop_packaging_workflow():
    text = WORKFLOW.read_text(encoding="utf-8")
    entries = re.findall(
        r"platform:\s*(?P<platform>\S+)\s*\n"
        r"\s*arch:\s*(?P<arch>\S+)\s*\n"
        r"\s*artifact_arches:\s*'(?P<arches>[^']+)'",
        text,
    )
    workflow_matrix = {
        platform: (arch, json.loads(arches)) for platform, arch, arches in entries
    }

    assert set(workflow_matrix) == set(dra.PLATFORM_ARTIFACTS)
    for platform, (job_arch, arches) in workflow_matrix.items():
        spec = dra.PLATFORM_ARTIFACTS[platform]
        assert spec["job_arch"] == job_arch
        assert spec["artifacts"] == arches


def test_expected_artifacts_rejects_unknown_platform():
    with pytest.raises(dra.DesktopAssetError, match="unknown desktop platform"):
        dra.expected_artifacts("solaris", DESKTOP_VERSION)


# ── collect ───────────────────────────────────────────────────────────────


def test_collect_records_names_hashes_and_platform_sums(tmp_path):
    out_dir = _collect(tmp_path, "mac")

    manifest = json.loads(
        (out_dir / "desktop-release-manifest.mac.json").read_text(encoding="utf-8")
    )
    assert manifest["platform"] == "mac"
    assert manifest["desktop_app_version"] == DESKTOP_VERSION
    assert {row["name"] for row in manifest["files"]} == {
        f"Fabric-{DESKTOP_VERSION}-mac-arm64.dmg",
        f"Fabric-{DESKTOP_VERSION}-mac-arm64.zip",
    }
    # Per-platform SHA256SUMS keyed on the coarse job arch (arm64 for mac).
    sums = out_dir / f"Fabric-{DESKTOP_VERSION}-mac-arm64.SHA256SUMS"
    assert sums.is_file()
    for row in manifest["files"]:
        assert f"{row['sha256']}  {row['name']}" in sums.read_text(encoding="utf-8")
        assert (out_dir / row["name"]).is_file()


def test_collect_fails_when_an_expected_installer_is_missing(tmp_path):
    release_dir = tmp_path / "release"
    _write_installers(release_dir, "win", DESKTOP_VERSION)
    (release_dir / f"Fabric-{DESKTOP_VERSION}-win-x64.msi").unlink()

    with pytest.raises(dra.DesktopAssetError, match="missing Fabric-.*-win-x64.msi"):
        dra.collect_platform_assets(
            release_dir,
            out_dir=tmp_path / "out",
            platform="win",
            repository=REPOSITORY,
            tag=TAG,
            source_sha=SOURCE_SHA,
            desktop_version=DESKTOP_VERSION,
        )


def test_collect_rejects_duplicate_installer(tmp_path):
    release_dir = tmp_path / "release"
    _write_installers(release_dir, "linux", DESKTOP_VERSION)
    nested = release_dir / "nested"
    nested.mkdir()
    dup = f"Fabric-{DESKTOP_VERSION}-linux-x86_64.AppImage"
    (nested / dup).write_bytes(b"dup")

    with pytest.raises(dra.DesktopAssetError, match="duplicate"):
        dra.collect_platform_assets(
            release_dir,
            out_dir=tmp_path / "out",
            platform="linux",
            repository=REPOSITORY,
            tag=TAG,
            source_sha=SOURCE_SHA,
            desktop_version=DESKTOP_VERSION,
        )


def test_collect_rejects_former_product_artifacts(tmp_path):
    release_dir = tmp_path / "release"
    _write_installers(release_dir, "mac", DESKTOP_VERSION)
    (release_dir / (("her" + "mes") + "-0.1.0.dmg")).write_bytes(b"nope")

    with pytest.raises(dra.DesktopAssetError, match="former-product"):
        dra.collect_platform_assets(
            release_dir,
            out_dir=tmp_path / "out",
            platform="mac",
            repository=REPOSITORY,
            tag=TAG,
            source_sha=SOURCE_SHA,
            desktop_version=DESKTOP_VERSION,
        )


def test_collect_rejects_bad_identity(tmp_path):
    release_dir = tmp_path / "release"
    _write_installers(release_dir, "mac", DESKTOP_VERSION)
    with pytest.raises(dra.DesktopAssetError, match="CalVer"):
        dra.collect_platform_assets(
            release_dir,
            out_dir=tmp_path / "out",
            platform="mac",
            repository=REPOSITORY,
            tag="latest",
            source_sha=SOURCE_SHA,
            desktop_version=DESKTOP_VERSION,
        )


# ── verify (merge) ────────────────────────────────────────────────────────


def _stage_all_platforms(tmp_path: Path, *, version: str = DESKTOP_VERSION) -> Path:
    staging = tmp_path / "staging"
    staging.mkdir()
    for platform in dra.PLATFORM_ARTIFACTS:
        out_dir = _collect(tmp_path, platform, version=version)
        for path in out_dir.iterdir():
            if path.is_file():
                (staging / path.name).write_bytes(path.read_bytes())
    return staging


def test_verify_merges_all_platforms_into_one_manifest(tmp_path):
    staging = _stage_all_platforms(tmp_path)
    out_dir = tmp_path / "release-out"

    combined = dra.verify_release_assets(
        staging,
        out_dir=out_dir,
        repository=REPOSITORY,
        tag=TAG,
        source_sha=SOURCE_SHA,
        desktop_version=DESKTOP_VERSION,
    )

    assert combined["platforms"] == ["linux", "mac", "win"]
    assert len(combined["files"]) == 7  # 2 mac + 2 win + 3 linux
    assert (out_dir / dra.MANIFEST_NAME).is_file()
    sums = (out_dir / dra.COMBINED_SUMS_NAME).read_text(encoding="utf-8")
    assert sums.count("\n") == 7
    on_disk = json.loads((out_dir / dra.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert on_disk == combined


def test_verify_detects_a_tampered_installer(tmp_path):
    staging = _stage_all_platforms(tmp_path)
    target = next(staging.glob("Fabric-*-linux-x86_64.AppImage"))
    target.write_bytes(target.read_bytes() + b"tampered")

    with pytest.raises(dra.DesktopAssetError, match="checksum mismatch"):
        dra.verify_release_assets(
            staging,
            out_dir=tmp_path / "out",
            repository=REPOSITORY,
            tag=TAG,
            source_sha=SOURCE_SHA,
            desktop_version=DESKTOP_VERSION,
        )


def test_verify_requires_every_platform(tmp_path):
    staging = _stage_all_platforms(tmp_path)
    for path in staging.glob("*win*"):
        path.unlink()

    with pytest.raises(dra.DesktopAssetError, match="missing installers.*win"):
        dra.verify_release_assets(
            staging,
            out_dir=tmp_path / "out",
            repository=REPOSITORY,
            tag=TAG,
            source_sha=SOURCE_SHA,
            desktop_version=DESKTOP_VERSION,
        )


def test_verify_rejects_source_sha_mismatch(tmp_path):
    staging = _stage_all_platforms(tmp_path)

    with pytest.raises(dra.DesktopAssetError, match="does not match"):
        dra.verify_release_assets(
            staging,
            out_dir=tmp_path / "out",
            repository=REPOSITORY,
            tag=TAG,
            source_sha="b" * 40,
            desktop_version=DESKTOP_VERSION,
        )


# ── decide_should_package (the build-once gate) ──────────────────────────────


def test_decide_should_package_skips_already_shipped_version():
    assert not dra.decide_should_package(
        DESKTOP_VERSION,
        prior_versions=frozenset({DESKTOP_VERSION}),
        force_rebuild=False,
    )


def test_decide_should_package_builds_new_version():
    assert dra.decide_should_package(
        "0.22.0",
        prior_versions=frozenset({DESKTOP_VERSION}),
        force_rebuild=False,
    )


def test_decide_should_package_force_rebuild_overrides_skip():
    assert dra.decide_should_package(
        DESKTOP_VERSION,
        prior_versions=frozenset({DESKTOP_VERSION}),
        force_rebuild=True,
    )


# ── attach (immutable upload) ────────────────────────────────────────────────


class _FakeRelease:
    """In-memory stand-in for a GitHub release's attached assets."""

    def __init__(self, monkeypatch, *, attached: dict[str, str] | None = None):
        # name -> sha256 recorded in the previously-attached manifest
        self.recorded = dict(attached or {})
        self.asset_names = set(self.recorded)
        if self.recorded:
            self.asset_names.update({dra.MANIFEST_NAME, dra.COMBINED_SUMS_NAME})
        self.uploads: list[tuple[str, bool]] = []
        monkeypatch.setattr(dra, "_release_asset_names", self._names)
        monkeypatch.setattr(dra, "_download_attached_manifest", self._manifest)
        monkeypatch.setattr(dra, "_upload_asset", self._upload)

    def _names(self, repository, tag):
        return set(self.asset_names)

    def _manifest(self, repository, tag, dest):
        if not self.recorded:
            return None
        return {"files": [{"name": n, "sha256": s} for n, s in self.recorded.items()]}

    def _upload(self, repository, tag, path, *, replace):
        self.uploads.append((path.name, replace))
        self.asset_names.add(path.name)


def _build_release_assets(tmp_path: Path) -> Path:
    staging = _stage_all_platforms(tmp_path)
    out_dir = tmp_path / "release-out"
    dra.verify_release_assets(
        staging,
        out_dir=out_dir,
        repository=REPOSITORY,
        tag=TAG,
        source_sha=SOURCE_SHA,
        desktop_version=DESKTOP_VERSION,
    )
    return out_dir


def _installer_digests(assets_dir: Path) -> dict[str, str]:
    manifest = json.loads(
        (assets_dir / dra.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    return {row["name"]: row["sha256"] for row in manifest["files"]}


def test_attach_uploads_installers_then_trailing_metadata(tmp_path, monkeypatch):
    assets = _build_release_assets(tmp_path)
    release = _FakeRelease(monkeypatch)

    result = dra.attach_release_assets(assets, repository=REPOSITORY, tag=TAG)

    uploaded = [name for name, _ in release.uploads]
    # Manifest strictly last; combined sums immediately before it.
    assert uploaded[-2:] == [dra.COMBINED_SUMS_NAME, dra.MANIFEST_NAME]
    assert result["replacements"] == []
    # 7 installers + 3 per-platform sums + combined sums + manifest.
    assert len(uploaded) == 7 + 3 + 2


def test_attach_skips_installers_already_attached_with_same_digest(tmp_path, monkeypatch):
    assets = _build_release_assets(tmp_path)
    release = _FakeRelease(monkeypatch, attached=_installer_digests(assets))

    result = dra.attach_release_assets(assets, repository=REPOSITORY, tag=TAG)

    # No installer re-uploaded; only the derived checksums/manifest refresh.
    assert result["uploaded"] == []
    uploaded = [name for name, _ in release.uploads]
    assert not any(name.startswith("Fabric-") and "SHA256SUMS" not in name
                   for name in uploaded)
    assert uploaded[-2:] == [dra.COMBINED_SUMS_NAME, dra.MANIFEST_NAME]


def test_attach_fails_loudly_on_digest_mismatch_without_force(tmp_path, monkeypatch):
    assets = _build_release_assets(tmp_path)
    stale = {name: "0" * 64 for name in _installer_digests(assets)}
    release = _FakeRelease(monkeypatch, attached=stale)

    with pytest.raises(dra.DesktopAssetError, match="already attached with a different"):
        dra.attach_release_assets(assets, repository=REPOSITORY, tag=TAG)

    assert release.uploads == []  # aborted before mutating the release


def test_attach_records_replacements_under_force(tmp_path, monkeypatch):
    assets = _build_release_assets(tmp_path)
    stale = {name: "0" * 64 for name in _installer_digests(assets)}
    release = _FakeRelease(monkeypatch, attached=stale)

    result = dra.attach_release_assets(
        assets, repository=REPOSITORY, tag=TAG, force_replace=True
    )

    assert len(result["replacements"]) == 7
    assert all(entry["old_sha256"] == "0" * 64 for entry in result["replacements"])
    persisted = json.loads(
        (assets / dra.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert len(persisted["replacements"]) == 7
    # Replaced installers re-upload with clobber (per-platform sums are derived).
    assert all(
        replace
        for name, replace in release.uploads
        if name.startswith("Fabric-") and "SHA256SUMS" not in name
    )


# ── preflight (pre-publish version gate) ─────────────────────────────────────


def _prior(version: str, sha: str, tag: str = "v2026.6.1") -> dict:
    return {"tag": tag, "desktop_app_version": version, "source_sha": sha}


def test_preflight_blocks_reused_version_when_inputs_changed():
    conflict = dra.evaluate_preflight(
        DESKTOP_VERSION,
        "b" * 40,
        prior=[_prior(DESKTOP_VERSION, "a" * 40)],
        inputs_changed=lambda old, new: True,
    )
    assert conflict is not None and conflict["tag"] == "v2026.6.1"


def test_preflight_allows_reused_version_when_inputs_unchanged():
    # Python-only release: same desktop version, no desktop diff -> allowed.
    conflict = dra.evaluate_preflight(
        DESKTOP_VERSION,
        "b" * 40,
        prior=[_prior(DESKTOP_VERSION, "a" * 40)],
        inputs_changed=lambda old, new: False,
    )
    assert conflict is None


def test_preflight_allows_new_version():
    conflict = dra.evaluate_preflight(
        "0.22.0",
        "b" * 40,
        prior=[_prior(DESKTOP_VERSION, "a" * 40)],
        inputs_changed=lambda old, new: True,
    )
    assert conflict is None


def test_preflight_ignores_same_commit_reuse():
    # Re-dispatching the identical commit is not a bump violation.
    conflict = dra.evaluate_preflight(
        DESKTOP_VERSION,
        "a" * 40,
        prior=[_prior(DESKTOP_VERSION, "a" * 40)],
        inputs_changed=lambda old, new: True,
    )
    assert conflict is None


# ── resolve (guard the packaging matrix) ─────────────────────────────────────


def _fake_gh(monkeypatch, responses: dict[str, str]):
    """Route ``_run_gh`` calls to canned stdout keyed by a matching substring."""

    class _Completed:
        def __init__(self, stdout):
            self.stdout = stdout
            self.returncode = 0

    def fake(args, *, input_text=None, check=True):
        joined = " ".join(args)
        for needle, stdout in responses.items():
            if needle in joined:
                return _Completed(stdout)
        raise AssertionError(f"unexpected gh call: {joined}")

    monkeypatch.setattr(dra, "_run_gh", fake)


def test_resolve_binds_dispatched_sha_and_gates_packaging(monkeypatch):
    tag_sha = "c" * 40
    _fake_gh(
        monkeypatch,
        {
            f"releases/tags/{TAG}": json.dumps({"draft": False, "prerelease": False}),
            f"git/ref/tags/{TAG}": json.dumps(
                {"object": {"sha": tag_sha, "type": "commit"}}
            ),
            "releases?per_page": "",  # no prior releases
        },
    )

    result = dra.resolve_release(
        repository=REPOSITORY,
        tag=TAG,
        github_sha=tag_sha,
        desktop_version=DESKTOP_VERSION,
        force_rebuild=False,
    )

    assert result == {
        "source_sha": tag_sha,
        "desktop_version": DESKTOP_VERSION,
        "should_package": True,
    }


def test_resolve_rejects_wrong_dispatched_sha(monkeypatch):
    _fake_gh(
        monkeypatch,
        {
            f"releases/tags/{TAG}": json.dumps({"draft": False, "prerelease": False}),
            f"git/ref/tags/{TAG}": json.dumps(
                {"object": {"sha": "c" * 40, "type": "commit"}}
            ),
        },
    )

    with pytest.raises(dra.DesktopAssetError, match="does not match tag"):
        dra.resolve_release(
            repository=REPOSITORY,
            tag=TAG,
            github_sha="d" * 40,
            desktop_version=DESKTOP_VERSION,
            force_rebuild=False,
        )


def test_resolve_rejects_draft_release(monkeypatch):
    _fake_gh(
        monkeypatch,
        {f"releases/tags/{TAG}": json.dumps({"draft": True, "prerelease": False})},
    )

    with pytest.raises(dra.DesktopAssetError, match="draft"):
        dra.resolve_release(
            repository=REPOSITORY,
            tag=TAG,
            github_sha="c" * 40,
            desktop_version=DESKTOP_VERSION,
            force_rebuild=False,
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
