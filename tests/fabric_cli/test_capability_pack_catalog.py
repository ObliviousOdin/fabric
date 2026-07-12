"""Contract tests for the offline capability-pack catalog compiler."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
from dataclasses import FrozenInstanceError, dataclass, replace
from pathlib import Path, PurePosixPath

import pytest
import yaml

from fabric_cli import capability_packs as pack_module
from fabric_cli.capability_packs import (
    CapabilityPackValidationError,
    PackIssueCode,
    SourceRepository,
    build_catalog_bytes,
    compile_catalog,
    load_authoring_manifest,
    load_compiled_catalog,
)
from fabric_cli.capability_pack_transactions import (
    PackMutationStatus,
    _apply_pack_strict,
)
from tools.skill_install import sha256_tree


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_capability_pack_catalog.py"
SOURCE_URL = "https://github.com/example/fabric"
SOURCE_REPOSITORY_REF = "refs/remotes/origin/main"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _trusted_fixture_platform_verifier(path: Path, raw: bytes, evidence) -> None:
    assert json.loads(raw) == evidence
    if evidence.get("artifact") not in {"product-design", "design-brief"}:
        raise ValueError(f"untrusted fixture evidence: {path}")


def _fixture_verifier_script(fixture: "CatalogFixture") -> Path:
    verifier = fixture.repo / "verify_platform_fixture.py"
    verifier.write_text(
        """import json, sys
data = json.loads(sys.stdin.buffer.read())
raise SystemExit(0 if data.get("artifact") in {"product-design", "design-brief"} else 1)
""",
        encoding="utf-8",
    )
    return verifier


@dataclass
class CatalogFixture:
    repo: Path
    packs: Path
    skills: Path
    optional: Path
    release: Path
    manifest: Path
    provenance: Path
    catalog: Path

    def load_manifest(self) -> dict:
        return yaml.safe_load(self.manifest.read_text(encoding="utf-8"))

    def write_manifest(self, value: dict) -> None:
        _write_yaml(self.manifest, value)

    def load_provenance(self) -> dict:
        return yaml.safe_load(self.provenance.read_text(encoding="utf-8"))

    def write_provenance(self, value: dict) -> None:
        _write_yaml(self.provenance, value)

    def compile(self) -> dict:
        return compile_catalog(
            self.packs,
            bundled_skills_root=self.skills,
            optional_skills_root=self.optional,
            repository_root=self.repo,
            source_repositories={
                SOURCE_URL: SourceRepository(self.repo, SOURCE_REPOSITORY_REF)
            },
            platform_evidence_verifier=_trusted_fixture_platform_verifier,
        )

    def build(self) -> bytes:
        return build_catalog_bytes(
            self.packs,
            bundled_skills_root=self.skills,
            optional_skills_root=self.optional,
            repository_root=self.repo,
            source_repositories={
                SOURCE_URL: SourceRepository(self.repo, SOURCE_REPOSITORY_REF)
            },
            platform_evidence_verifier=_trusted_fixture_platform_verifier,
        )


@pytest.fixture
def catalog_fixture(tmp_path: Path) -> CatalogFixture:
    repo = tmp_path / "repo"
    packs = repo / "capability-packs"
    skills = repo / "skills"
    optional = repo / "optional-skills"
    release = packs / "example.product-design" / "1.0.0"
    router = release / "router"
    member = release / "members" / "design-brief"
    router.mkdir(parents=True)
    member.mkdir(parents=True)
    skills.mkdir(parents=True)
    optional.mkdir(parents=True)
    (router / "SKILL.md").write_text(
        "---\nname: product-design\ndescription: Route design work.\n---\n# Router\n",
        encoding="utf-8",
    )
    (member / "SKILL.md").write_text(
        "---\nname: design-brief\ndescription: Define the design contract.\n---\n# Brief\n",
        encoding="utf-8",
    )
    license_text = "MIT License\nCopyright Example\n"
    (repo / "LICENSE").write_text(license_text, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "fixture@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Fixture"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", f"{SOURCE_URL}.git"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "add", "capability-packs", "LICENSE"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "fixture sources"],
        check=True,
    )
    pin = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "update-ref",
            "refs/remotes/origin/main",
            pin,
        ],
        check=True,
    )
    evidence = release / "evidence"
    router_result = evidence / "results" / "product-design-linux.json"
    member_result = evidence / "results" / "design-brief-linux.json"
    _write_json(router_result, {"artifact": "product-design", "result": "passed"})
    _write_json(member_result, {"artifact": "design-brief", "result": "passed"})
    _write_json(
        evidence / "product-design.json",
        {
            "schema_version": 1,
            "artifact": "product-design",
            "source_tree_sha256": sha256_tree(router),
            "results": [
                {
                    "host_os": "linux",
                    "runner": "ubuntu-latest",
                    "source_revision": pin,
                    "run_url": "https://github.com/example/fabric/actions/runs/1",
                    "checks": [
                        {
                            "id": "router-load",
                            "status": "passed",
                            "evidence_path": "evidence/results/product-design-linux.json",
                            "evidence_sha256": _sha256(router_result),
                        }
                    ],
                }
            ],
        },
    )
    _write_json(
        evidence / "design-brief.json",
        {
            "schema_version": 1,
            "artifact": "design-brief",
            "source_tree_sha256": sha256_tree(member),
            "results": [
                {
                    "host_os": "linux",
                    "runner": "ubuntu-latest",
                    "source_revision": pin,
                    "run_url": "https://github.com/example/fabric/actions/runs/1",
                    "checks": [
                        {
                            "id": "brief-contract",
                            "status": "passed",
                            "evidence_path": "evidence/results/design-brief-linux.json",
                            "evidence_sha256": _sha256(member_result),
                        }
                    ],
                }
            ],
        },
    )
    evidence_dir = release / "provenance"
    evidence_dir.mkdir(parents=True)
    license_file = evidence_dir / "LICENSE"
    notice_file = evidence_dir / "NOTICE"
    license_file.write_text(license_text, encoding="utf-8")
    notice_file.write_text(
        "\n".join([
            "Example-authored capability-pack fixtures.",
            SOURCE_URL,
            pin,
            "MIT",
            "Example, Inc.",
            "",
        ]),
        encoding="utf-8",
    )
    provenance = evidence_dir / "original.yaml"
    common = {
        "canonical_source_url": SOURCE_URL,
        "pinned_revision": pin,
        "copyright_holders": ["Example, Inc."],
        "spdx_expression": "MIT",
        "license_file": "provenance/LICENSE",
        "license_source_path": "LICENSE",
        "license_file_sha256": _sha256(license_file),
        "adaptation_type": "original",
        "changes": [],
        "nested_assets": [],
        "notice_output": "provenance/NOTICE",
    }
    _write_yaml(
        provenance,
        {
            "schema_version": 1,
            "records": {
                "product-design": {
                    **common,
                    "source_path": "capability-packs/example.product-design/1.0.0/router",
                    "source_tree_sha256": sha256_tree(router),
                    "platform_evidence": ["evidence/product-design.json"],
                },
                "design-brief": {
                    **common,
                    "source_path": (
                        "capability-packs/example.product-design/1.0.0/members/design-brief"
                    ),
                    "source_tree_sha256": sha256_tree(member),
                    "platform_evidence": ["evidence/design-brief.json"],
                },
            },
        },
    )
    manifest = release / "pack.yaml"
    _write_yaml(
        manifest,
        {
            "schema_version": 1,
            "id": "example.product-design",
            "name": "Example Product Design",
            "version": "1.0.0",
            "fabric_requires": ">=0.18.2",
            "summary": "A synthetic compiler fixture, not a shipped Fabric capability.",
            "router": {
                "name": "product-design",
                "version": "1.0.0",
                "ownership": "pack",
                "source_kind": "pack",
                "source_path": "router",
                "install_path": "workflows/product-design",
                "author": "Example",
                "license": "MIT",
                "provenance_ref": "provenance/original.yaml#product-design",
                "host_os": ["linux"],
                "platform_evidence": ["evidence/product-design.json"],
                "required_toolsets": ["skills"],
            },
            "members": [
                {
                    "name": "design-brief",
                    "version": "1.0.0",
                    "role": "required",
                    "default": "enabled",
                    "ownership": "pack",
                    "source_kind": "pack",
                    "source_path": "members/design-brief",
                    "install_path": "product-design/design-brief",
                    "author": "Example",
                    "license": "MIT",
                    "provenance_ref": "provenance/original.yaml#design-brief",
                    "host_os": ["linux"],
                    "platform_evidence": ["evidence/design-brief.json"],
                    "required_toolsets": ["file"],
                }
            ],
            "excluded_candidates": [],
            "permissions": {
                "required_toolsets": ["file", "skills"],
                "optional_toolsets": [],
                "secrets": [],
                "network": "inherited",
            },
            "provenance": {
                "publisher": "Example",
                "source_repository": "example/fabric",
                "adaptation_policy": "original",
            },
        },
    )
    catalog = packs / "catalog.yaml"
    _write_yaml(
        catalog,
        {
            "schema_version": 1,
            "packs": [
                {
                    "id": "example.product-design",
                    "releases": [
                        {"manifest": "example.product-design/1.0.0/pack.yaml"}
                    ],
                }
            ],
        },
    )
    return CatalogFixture(
        repo, packs, skills, optional, release, manifest, provenance, catalog
    )


def _assert_code(
    exc: pytest.ExceptionInfo[CapabilityPackValidationError], code: PackIssueCode
) -> None:
    assert exc.value.code is code, str(exc.value)


def _add_release(fixture: CatalogFixture, version: str) -> None:
    target = fixture.packs / "example.product-design" / version
    shutil.copytree(fixture.release, target)
    manifest_path = target / "pack.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = version
    _write_yaml(manifest_path, manifest)
    catalog = yaml.safe_load(fixture.catalog.read_text(encoding="utf-8"))
    catalog["packs"][0]["releases"].insert(
        0,
        {"manifest": f"example.product-design/{version}/pack.yaml"},
    )
    _write_yaml(fixture.catalog, catalog)


def test_valid_catalog_compiles_frozen_typed_authoring(
    catalog_fixture: CatalogFixture,
) -> None:
    authoring = load_authoring_manifest(catalog_fixture.manifest)
    assert authoring.members[0].optional_toolsets == ()
    assert isinstance(authoring.members, tuple)
    with pytest.raises(FrozenInstanceError):
        authoring.version = "2.0.0"  # type: ignore[misc]

    compiled = catalog_fixture.compile()
    release = compiled["packs"][0]["releases"][0]
    assert release["id"] == "example.product-design"
    assert release["router"]["source_tree_sha256"] == sha256_tree(
        catalog_fixture.release / "router"
    )
    assert len(release["notice_tree_sha256"]) == 64
    assert len(release["release_tree_sha256"]) == 64
    assert release["members"][0]["optional_toolsets"] == []
    assert release["members"][0]["effective_host_os"] == ["linux"]
    assert release["members"][0]["platform_evidence_records"][0]["sha256"] == _sha256(
        catalog_fixture.release / "evidence" / "design-brief.json"
    )
    assert release["router"]["platform_evidence_records"][0]["check_evidence"] == [
        {
            "path": "evidence/results/product-design-linux.json",
            "sha256": _sha256(
                catalog_fixture.release
                / "evidence"
                / "results"
                / "product-design-linux.json"
            ),
        }
    ]


def test_strict_catalog_loader_to_profile_apply_is_provenance_bound_e2e(
    catalog_fixture: CatalogFixture, tmp_path: Path
) -> None:
    """The future mutation adapter has no unverified-catalog shortcut."""

    compiled_path = catalog_fixture.packs / "catalog.json"
    compiled_path.write_bytes(catalog_fixture.build())
    home = tmp_path / "profile"

    applied = _apply_pack_strict(
        "example.product-design",
        home=home,
        catalog_path=compiled_path,
        capability_packs_root=catalog_fixture.packs,
        bundled_skills_root=catalog_fixture.skills,
        optional_skills_root=catalog_fixture.optional,
        repository_root=catalog_fixture.repo,
        target_version="1.0.0",
        host_os="linux",
        available_toolsets=frozenset({"file", "skills"}),
        expected_revision=0,
    )

    assert applied.status == PackMutationStatus.APPLIED
    assert applied.revision == 1
    assert applied.plan is not None
    assert applied.plan.context_health.value == "healthy"
    assert (home / "skills" / "workflows" / "product-design").is_dir()
    assert (home / "skills" / "product-design" / "design-brief").is_dir()

    state_path = home / "capability-packs" / "state.json"
    router_mtime = (
        (home / "skills" / "workflows" / "product-design" / "SKILL.md")
        .stat()
        .st_mtime_ns
    )
    state_mtime = state_path.stat().st_mtime_ns
    unchanged = _apply_pack_strict(
        "example.product-design",
        home=home,
        catalog_path=compiled_path,
        capability_packs_root=catalog_fixture.packs,
        bundled_skills_root=catalog_fixture.skills,
        optional_skills_root=catalog_fixture.optional,
        repository_root=catalog_fixture.repo,
        target_version="1.0.0",
        host_os="linux",
        available_toolsets=frozenset({"file", "skills"}),
        expected_revision=1,
    )

    assert unchanged.status == PackMutationStatus.UNCHANGED
    assert unchanged.revision == 1
    assert state_path.stat().st_mtime_ns == state_mtime
    assert (
        home / "skills" / "workflows" / "product-design" / "SKILL.md"
    ).stat().st_mtime_ns == router_mtime


def test_public_admission_compiler_has_no_upstream_verification_bypass() -> None:
    signature = inspect.signature(compile_catalog)
    assert "verify_upstream_sources" not in signature.parameters
    assert (
        signature.parameters["platform_evidence_verifier"].default
        is inspect.Parameter.empty
    )


def test_skill_identity_accepts_nonempty_yaml_block_description(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "---\n"
        "name: block-description\n"
        "description: |\n"
        "  Use this skill for a real workflow.\n"
        "  It intentionally spans two lines.\n"
        "---\n"
        "# Instructions\n",
        encoding="utf-8",
    )

    pack_module._validate_skill_identity(skill, "block-description")


def test_pack_owned_install_roots_must_not_overlap(
    catalog_fixture: CatalogFixture,
) -> None:
    data = catalog_fixture.load_manifest()
    data["members"][0].update({
        "ownership": "pack",
        "source_kind": "pack",
        "source_path": "members/design-brief",
        "install_path": "workflows/product-design/design-brief",
    })
    data["router"]["install_path"] = "workflows/product-design"
    catalog_fixture.write_manifest(data)

    with pytest.raises(CapabilityPackValidationError) as exc:
        load_authoring_manifest(catalog_fixture.manifest)
    _assert_code(exc, PackIssueCode.DUPLICATE_INSTALL_PATH)


def test_resolved_source_overlap_detects_ancestor_and_descendant(
    tmp_path: Path,
) -> None:
    parent = (tmp_path / "skill").resolve()
    child = (parent / "nested").resolve()
    sibling = (tmp_path / "other").resolve()

    assert pack_module._resolved_paths_overlap(parent, child)
    assert pack_module._resolved_paths_overlap(child, parent)
    assert not pack_module._resolved_paths_overlap(parent, sibling)


def test_public_admission_rejects_missing_platform_attestation_verifier(
    catalog_fixture: CatalogFixture,
) -> None:
    with pytest.raises(CapabilityPackValidationError) as exc:
        compile_catalog(
            catalog_fixture.packs,
            bundled_skills_root=catalog_fixture.skills,
            optional_skills_root=catalog_fixture.optional,
            repository_root=catalog_fixture.repo,
            source_repositories={
                SOURCE_URL: SourceRepository(
                    catalog_fixture.repo, SOURCE_REPOSITORY_REF
                )
            },
            platform_evidence_verifier=None,  # type: ignore[arg-type]
        )
    _assert_code(exc, PackIssueCode.PLATFORM_EVIDENCE_INVALID)


def test_public_admission_maps_rejecting_platform_attestation_verifier(
    catalog_fixture: CatalogFixture,
) -> None:
    def reject(_path: Path, _raw: bytes, _evidence) -> None:
        raise ValueError("signature rejected")

    with pytest.raises(CapabilityPackValidationError) as exc:
        compile_catalog(
            catalog_fixture.packs,
            bundled_skills_root=catalog_fixture.skills,
            optional_skills_root=catalog_fixture.optional,
            repository_root=catalog_fixture.repo,
            source_repositories={
                SOURCE_URL: SourceRepository(
                    catalog_fixture.repo, SOURCE_REPOSITORY_REF
                )
            },
            platform_evidence_verifier=reject,
        )
    _assert_code(exc, PackIssueCode.PLATFORM_EVIDENCE_INVALID)
    assert "signature rejected" in str(exc.value)


def test_platform_evidence_cannot_change_during_trusted_verification(
    catalog_fixture: CatalogFixture,
) -> None:
    changed = False

    def swap_after_read(path: Path, raw: bytes, _evidence) -> None:
        nonlocal changed
        if not changed:
            path.write_bytes(raw + b" ")
            changed = True

    with pytest.raises(CapabilityPackValidationError) as exc:
        compile_catalog(
            catalog_fixture.packs,
            bundled_skills_root=catalog_fixture.skills,
            optional_skills_root=catalog_fixture.optional,
            repository_root=catalog_fixture.repo,
            source_repositories={
                SOURCE_URL: SourceRepository(
                    catalog_fixture.repo, SOURCE_REPOSITORY_REF
                )
            },
            platform_evidence_verifier=swap_after_read,
        )
    _assert_code(exc, PackIssueCode.PLATFORM_EVIDENCE_INVALID)
    assert "changed during trusted verification" in str(exc.value)


def test_non_utf8_git_origin_maps_to_stable_provenance_error(
    catalog_fixture: CatalogFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_run_git = pack_module._run_git

    def invalid_origin(repository: Path, *args: str, **kwargs) -> bytes:
        if args == ("remote", "get-url", "--all", "origin"):
            return b"\xff"
        return original_run_git(repository, *args, **kwargs)

    monkeypatch.setattr(pack_module, "_run_git", invalid_origin)
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.PROVENANCE_EVIDENCE_MISSING)
    assert "not UTF-8" in str(exc.value)


def test_source_backed_compile_rejects_wrong_git_origin(
    catalog_fixture: CatalogFixture,
) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(catalog_fixture.repo),
            "remote",
            "set-url",
            "origin",
            "https://github.com/attacker/repository.git",
        ],
        check=True,
    )

    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.PROVENANCE_EVIDENCE_MISSING)
    assert "origin does not match" in str(exc.value)


def test_source_backed_compile_rejects_pin_unreachable_from_trusted_ref(
    catalog_fixture: CatalogFixture,
) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(catalog_fixture.repo),
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "untrusted branch-only object",
        ],
        check=True,
    )
    untrusted_pin = subprocess.run(
        ["git", "-C", str(catalog_fixture.repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    data = catalog_fixture.load_provenance()
    data["records"]["product-design"]["pinned_revision"] = untrusted_pin
    catalog_fixture.write_provenance(data)

    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.PROVENANCE_EVIDENCE_MISSING)


def test_source_backed_compile_rejects_revision_expression_as_trusted_ref(
    catalog_fixture: CatalogFixture,
) -> None:
    with pytest.raises(CapabilityPackValidationError) as exc:
        compile_catalog(
            catalog_fixture.packs,
            bundled_skills_root=catalog_fixture.skills,
            optional_skills_root=catalog_fixture.optional,
            repository_root=catalog_fixture.repo,
            source_repositories={
                SOURCE_URL: SourceRepository(
                    catalog_fixture.repo,
                    "refs/remotes/origin/main^{commit}",
                )
            },
            platform_evidence_verifier=_trusted_fixture_platform_verifier,
        )
    _assert_code(exc, PackIssueCode.PROVENANCE_EVIDENCE_MISSING)


def test_source_backed_compile_requires_explicit_trusted_ref(
    catalog_fixture: CatalogFixture,
) -> None:
    with pytest.raises(CapabilityPackValidationError) as exc:
        compile_catalog(
            catalog_fixture.packs,
            bundled_skills_root=catalog_fixture.skills,
            optional_skills_root=catalog_fixture.optional,
            repository_root=catalog_fixture.repo,
            source_repositories={SOURCE_URL: catalog_fixture.repo},
            platform_evidence_verifier=_trusted_fixture_platform_verifier,
        )
    _assert_code(exc, PackIssueCode.PROVENANCE_EVIDENCE_MISSING)
    assert "explicit trusted remote ref" in str(exc.value)


def test_git_source_tree_rejects_missing_pinned_tree(
    catalog_fixture: CatalogFixture,
) -> None:
    records, _digest = pack_module._load_provenance_file(catalog_fixture.provenance)
    record = replace(
        records["product-design"],
        source_path=PurePosixPath("does-not-exist"),
    )

    with pytest.raises(CapabilityPackValidationError) as exc:
        pack_module._git_source_tree_sha256(catalog_fixture.repo, record)
    _assert_code(exc, PackIssueCode.PROVENANCE_EVIDENCE_MISSING)


@pytest.mark.skipif(os.name == "nt", reason="Git symlink mode fixture requires POSIX")
def test_git_source_tree_rejects_symlink_mode(
    catalog_fixture: CatalogFixture,
) -> None:
    source = catalog_fixture.repo / "git-source-symlink"
    source.mkdir()
    (source / "SKILL.md").write_text("source\n", encoding="utf-8")
    (source / "link").symlink_to("SKILL.md")
    subprocess.run(
        ["git", "-C", str(catalog_fixture.repo), "add", "git-source-symlink"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(catalog_fixture.repo), "commit", "-q", "-m", "symlink tree"],
        check=True,
    )
    pin = subprocess.run(
        ["git", "-C", str(catalog_fixture.repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    records, _digest = pack_module._load_provenance_file(catalog_fixture.provenance)
    record = replace(
        records["product-design"],
        pinned_revision=pin,
        source_path=PurePosixPath("git-source-symlink"),
    )

    with pytest.raises(CapabilityPackValidationError) as exc:
        pack_module._git_source_tree_sha256(catalog_fixture.repo, record)
    _assert_code(exc, PackIssueCode.PROVENANCE_EVIDENCE_MISSING)
    assert "redirect/submodule/non-file" in str(exc.value)


def test_git_source_tree_rejects_submodule_mode(
    catalog_fixture: CatalogFixture,
) -> None:
    source = catalog_fixture.repo / "git-source-submodule"
    source.mkdir()
    (source / "SKILL.md").write_text("source\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(catalog_fixture.repo), "add", "git-source-submodule"],
        check=True,
    )
    object_id = subprocess.run(
        ["git", "-C", str(catalog_fixture.repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(catalog_fixture.repo),
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{object_id},git-source-submodule/vendor",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(catalog_fixture.repo), "commit", "-q", "-m", "gitlink tree"],
        check=True,
    )
    pin = subprocess.run(
        ["git", "-C", str(catalog_fixture.repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    records, _digest = pack_module._load_provenance_file(catalog_fixture.provenance)
    record = replace(
        records["product-design"],
        pinned_revision=pin,
        source_path=PurePosixPath("git-source-submodule"),
    )

    with pytest.raises(CapabilityPackValidationError) as exc:
        pack_module._git_source_tree_sha256(catalog_fixture.repo, record)
    _assert_code(exc, PackIssueCode.PROVENANCE_EVIDENCE_MISSING)
    assert "redirect/submodule/non-file" in str(exc.value)


def test_git_source_tree_enforces_entry_cap(
    catalog_fixture: CatalogFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records, _digest = pack_module._load_provenance_file(catalog_fixture.provenance)
    record = records["product-design"]
    original_run_git = pack_module._run_git

    def oversized_listing(repository: Path, *args: str, **kwargs) -> bytes:
        if args and args[0] == "ls-tree":
            prefix = record.source_path.as_posix().encode() + b"/"
            return b"".join(
                b"100644 blob "
                + b"1" * 40
                + b"\t"
                + prefix
                + f"file-{index}.txt".encode()
                + b"\0"
                for index in range(10_001)
            )
        return original_run_git(repository, *args, **kwargs)

    monkeypatch.setattr(pack_module, "_run_git", oversized_listing)
    with pytest.raises(CapabilityPackValidationError) as exc:
        pack_module._git_source_tree_sha256(catalog_fixture.repo, record)
    _assert_code(exc, PackIssueCode.PROVENANCE_EVIDENCE_MISSING)
    assert "exceeds 10,000 entries" in str(exc.value)


def test_git_inspection_disables_lazy_fetch_and_replace_refs() -> None:
    environment = pack_module._git_environment()
    assert environment["GIT_NO_LAZY_FETCH"] == "1"
    assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert environment["GIT_ALLOW_PROTOCOL"] == ""
    assert environment["GIT_TERMINAL_PROMPT"] == "0"


@pytest.mark.parametrize(
    "value",
    [
        "https://[::1",
        "https://example.com:notaport/repo",
        "HTTPS://EXAMPLE.COM/repo",
        "https://example.com:443/repo",
        "https://example.com/a/../repo",
        "https://example.com//repo",
        "https://example.com/repo/",
        "https://example.com/%72epo",
    ],
)
def test_source_urls_require_stable_canonical_identity(value: str) -> None:
    with pytest.raises(CapabilityPackValidationError) as exc:
        pack_module._canonical_source_url(value, "source")
    _assert_code(exc, PackIssueCode.PROVENANCE_EVIDENCE_MISSING)


def test_source_url_accepts_canonical_nondefault_port() -> None:
    assert (
        pack_module._canonical_source_url(
            "https://example.com:8443/repository", "source"
        )
        == "https://example.com:8443/repository"
    )


def test_manifest_rejects_duplicate_canonical_platform_evidence_paths(
    catalog_fixture: CatalogFixture,
) -> None:
    data = catalog_fixture.load_manifest()
    data["router"]["platform_evidence"] = [
        "evidence/router.json",
        "evidence/./router.json",
    ]
    catalog_fixture.write_manifest(data)

    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.DUPLICATE_ID)


def test_provenance_rejects_duplicate_canonical_platform_evidence_paths(
    catalog_fixture: CatalogFixture,
) -> None:
    data = catalog_fixture.load_provenance()
    data["records"]["product-design"]["platform_evidence"] = [
        "evidence/router.json",
        r"evidence\router.json",
    ]
    catalog_fixture.write_provenance(data)

    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.DUPLICATE_ID)


def test_build_is_byte_deterministic_and_canonical(
    catalog_fixture: CatalogFixture,
) -> None:
    first = catalog_fixture.build()
    second = catalog_fixture.build()
    assert first == second
    assert first.endswith(b"\n")
    parsed = json.loads(first)
    assert (
        first
        == (
            json.dumps(
                parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            + "\n"
        ).encode()
    )


def test_source_backed_git_rejects_noncanonical_backslash_path(
    catalog_fixture: CatalogFixture,
) -> None:
    collision = catalog_fixture.repo / "collision"
    collision.mkdir()
    (collision / "a\\b").write_text("payload", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(catalog_fixture.repo), "add", "collision"], check=True
    )
    subprocess.run(
        ["git", "-C", str(catalog_fixture.repo), "commit", "-q", "-m", "collision"],
        check=True,
    )
    pin = subprocess.run(
        ["git", "-C", str(catalog_fixture.repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    records, _digest = pack_module._load_provenance_file(catalog_fixture.provenance)
    record = replace(
        records["product-design"],
        pinned_revision=pin,
        source_path=PurePosixPath("collision"),
    )

    with pytest.raises(CapabilityPackValidationError) as exc:
        pack_module._git_source_tree_sha256(catalog_fixture.repo, record)
    _assert_code(exc, PackIssueCode.PROVENANCE_EVIDENCE_MISSING)
    assert "not canonical/portable" in str(exc.value)


def test_non_git_release_digest_authenticates_source_and_license(
    catalog_fixture: CatalogFixture,
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "immutable-release"
    source = release_root / "source"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: product-design\ndescription: Release.\n---\n# Release\n",
        encoding="utf-8",
    )
    license_file = release_root / "LICENSE"
    license_file.write_text("MIT release license\n", encoding="utf-8")
    source_digest = sha256_tree(source)
    release_pin = f"sha256:{sha256_tree(release_root)}"
    records, _digest = pack_module._load_provenance_file(catalog_fixture.provenance)
    record = replace(
        records["product-design"],
        canonical_source_url="https://downloads.example.com/release",
        pinned_revision=release_pin,
        source_path=PurePosixPath("source"),
        source_tree_sha256=source_digest,
        license_source_path=PurePosixPath("LICENSE"),
        license_file_sha256=_sha256(license_file),
    )

    pack_module._verify_pinned_source(
        record,
        local_source_tree_sha256=source_digest,
        source_repositories={record.canonical_source_url: release_root},
    )


def test_compile_accepts_explicit_symlinked_root_boundary(
    catalog_fixture: CatalogFixture,
) -> None:
    if os.name == "nt":
        pytest.skip("symlink creation is privilege-dependent on Windows")
    alias = catalog_fixture.repo.parent / "repo-alias"
    alias.symlink_to(catalog_fixture.repo, target_is_directory=True)

    compiled = compile_catalog(
        alias / "capability-packs",
        bundled_skills_root=alias / "skills",
        optional_skills_root=alias / "optional-skills",
        repository_root=alias,
        source_repositories={
            SOURCE_URL: SourceRepository(catalog_fixture.repo, SOURCE_REPOSITORY_REF)
        },
        platform_evidence_verifier=_trusted_fixture_platform_verifier,
    )
    assert compiled["packs"][0]["id"] == "example.product-design"


def test_releases_are_sorted_by_semver_not_declaration_order(
    catalog_fixture: CatalogFixture,
) -> None:
    _add_release(catalog_fixture, "2.0.0")
    _add_release(catalog_fixture, "1.0.0-alpha.1")
    versions = [
        release["version"]
        for release in catalog_fixture.compile()["packs"][0]["releases"]
    ]
    assert versions == ["1.0.0-alpha.1", "1.0.0", "2.0.0"]


def test_equal_semver_precedence_with_build_metadata_is_rejected(
    catalog_fixture: CatalogFixture,
) -> None:
    _add_release(catalog_fixture, "1.0.0+second-build")
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.DUPLICATE_ID)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda data: data.update({"surprise": True}), PackIssueCode.UNKNOWN_FIELD),
        (
            lambda data: data.update({"schema_version": 2}),
            PackIssueCode.SCHEMA_VERSION_UNSUPPORTED,
        ),
        (lambda data: data.update({"version": "1.0"}), PackIssueCode.VERSION_INVALID),
        (
            lambda data: data.update({"fabric_requires": "banana"}),
            PackIssueCode.SPECIFIER_INVALID,
        ),
        (
            lambda data: data["router"].update({"license": "Definitely-Not-SPDX"}),
            PackIssueCode.SPDX_INVALID,
        ),
        (
            lambda data: data["router"].update({"source_path": "../escape"}),
            PackIssueCode.PATH_UNSAFE,
        ),
        (
            lambda data: data["router"].update({"source_path": "C:\\escape"}),
            PackIssueCode.PATH_UNSAFE,
        ),
    ],
)
def test_manifest_rejects_invalid_contracts(
    catalog_fixture: CatalogFixture,
    mutate,
    code: PackIssueCode,
) -> None:
    data = catalog_fixture.load_manifest()
    mutate(data)
    catalog_fixture.write_manifest(data)
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, code)


def test_duplicate_yaml_key_is_rejected(catalog_fixture: CatalogFixture) -> None:
    text = catalog_fixture.manifest.read_text(encoding="utf-8")
    catalog_fixture.manifest.write_text(
        text.replace(
            "schema_version: 1\n", "schema_version: 1\nschema_version: 1\n", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.DUPLICATE_KEY)


def test_empty_catalog_is_not_a_shipped_capability(
    catalog_fixture: CatalogFixture,
) -> None:
    _write_yaml(catalog_fixture.catalog, {"schema_version": 1, "packs": []})
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.TYPE_INVALID)


def test_manifest_path_must_be_exact_identity_version_layout(
    catalog_fixture: CatalogFixture,
) -> None:
    archived = catalog_fixture.packs / "archive" / "example.product-design" / "1.0.0"
    archived.parent.mkdir(parents=True)
    catalog_fixture.release.rename(archived)
    _write_yaml(
        catalog_fixture.catalog,
        {
            "schema_version": 1,
            "packs": [
                {
                    "id": "example.product-design",
                    "releases": [
                        {"manifest": ("archive/example.product-design/1.0.0/pack.yaml")}
                    ],
                }
            ],
        },
    )
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.INVARIANT_VIOLATION)


@pytest.mark.parametrize("pack_id", ["fabric..x", "fabric.-x", "fabric-.x", "a...b"])
def test_pack_id_requires_canonical_dot_segments(
    catalog_fixture: CatalogFixture,
    pack_id: str,
) -> None:
    data = catalog_fixture.load_manifest()
    data["id"] = pack_id
    catalog_fixture.write_manifest(data)
    with pytest.raises(CapabilityPackValidationError) as exc:
        load_authoring_manifest(catalog_fixture.manifest)
    _assert_code(exc, PackIssueCode.TYPE_INVALID)


def test_oversized_semver_is_a_controlled_error(
    catalog_fixture: CatalogFixture,
) -> None:
    data = catalog_fixture.load_manifest()
    data["version"] = f"{'9' * 5000}.0.0"
    catalog_fixture.write_manifest(data)
    with pytest.raises(CapabilityPackValidationError) as exc:
        load_authoring_manifest(catalog_fixture.manifest)
    _assert_code(exc, PackIssueCode.VERSION_INVALID)


@pytest.mark.parametrize(
    ("skill_text", "code"),
    [
        (
            "---\nname: wrong-name\ndescription: Wrong.\n---\n# Body\n",
            PackIssueCode.INVARIANT_VIOLATION,
        ),
        ("---\nname: product-design\n---\n# Body\n", PackIssueCode.TYPE_INVALID),
        (
            "---\nname: product-design\ndescription: Route.\n---\n",
            PackIssueCode.INVARIANT_VIOLATION,
        ),
    ],
)
def test_catalog_identity_requires_usable_matching_skill_metadata(
    catalog_fixture: CatalogFixture,
    skill_text: str,
    code: PackIssueCode,
) -> None:
    (catalog_fixture.release / "router" / "SKILL.md").write_text(
        skill_text,
        encoding="utf-8",
    )
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, code)


def test_duplicate_member_and_mismatched_install_path_are_rejected(
    catalog_fixture: CatalogFixture,
) -> None:
    data = catalog_fixture.load_manifest()
    duplicate = dict(data["members"][0])
    duplicate["source_path"] = "router"
    data["members"].append(duplicate)
    catalog_fixture.write_manifest(data)
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.DUPLICATE_MEMBER)

    data = catalog_fixture.load_manifest()
    data["members"][1]["name"] = "design-review"
    catalog_fixture.write_manifest(data)
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.PATH_UNSAFE)


def test_reference_ownership_cannot_claim_install_path(
    catalog_fixture: CatalogFixture,
) -> None:
    data = catalog_fixture.load_manifest()
    member = data["members"][0]
    member["ownership"] = "reference"
    member["source_kind"] = "bundled"
    catalog_fixture.write_manifest(data)
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.INVARIANT_VIOLATION)


def test_router_requires_skills_toolset(catalog_fixture: CatalogFixture) -> None:
    data = catalog_fixture.load_manifest()
    data["router"]["required_toolsets"] = []
    catalog_fixture.write_manifest(data)
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.INVARIANT_VIOLATION)


def test_default_disabled_optional_member_toolset_is_pack_optional(
    catalog_fixture: CatalogFixture,
) -> None:
    data = catalog_fixture.load_manifest()
    optional_member = dict(data["members"][0])
    optional_member.update({
        "name": "optional-review",
        "role": "optional",
        "default": "disabled",
        "source_path": "members/optional-review",
        "install_path": "product-design/optional-review",
        "provenance_ref": "provenance/original.yaml#optional-review",
        "required_toolsets": ["browser"],
    })
    data["members"].append(optional_member)
    data["permissions"]["optional_toolsets"] = ["browser"]
    catalog_fixture.write_manifest(data)

    loaded = load_authoring_manifest(catalog_fixture.manifest)
    assert loaded.members[1].role == "optional"
    assert loaded.permissions.required_toolsets == ("file", "skills")
    assert loaded.permissions.optional_toolsets == ("browser",)


@pytest.mark.parametrize(
    "pin", ["main", "latest", "1234567", "0" * 40, "sha256:" + "0" * 64]
)
def test_provenance_requires_immutable_nonzero_pin(
    catalog_fixture: CatalogFixture,
    pin: str,
) -> None:
    data = catalog_fixture.load_provenance()
    data["records"]["product-design"]["pinned_revision"] = pin
    catalog_fixture.write_provenance(data)
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.PROVENANCE_PIN_INVALID)


def test_missing_provenance_record_is_rejected(catalog_fixture: CatalogFixture) -> None:
    data = catalog_fixture.load_manifest()
    data["router"]["provenance_ref"] = "provenance/original.yaml#missing"
    catalog_fixture.write_manifest(data)
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.PROVENANCE_EVIDENCE_MISSING)


def test_license_and_notice_are_verified(catalog_fixture: CatalogFixture) -> None:
    license_file = catalog_fixture.release / "provenance" / "LICENSE"
    license_file.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.DIGEST_MISMATCH)

    # Restore the pinned license bytes, then remove NOTICE.
    license_file.write_text("MIT License\nCopyright Example\n", encoding="utf-8")
    (catalog_fixture.release / "provenance" / "NOTICE").unlink()
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.NOTICE_EVIDENCE_MISSING)


def test_empty_license_and_notice_are_not_evidence(
    catalog_fixture: CatalogFixture,
) -> None:
    license_file = catalog_fixture.release / "provenance" / "LICENSE"
    license_file.write_bytes(b"")
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.LICENSE_EVIDENCE_MISSING)

    license_file.write_text("MIT License\nCopyright Example\n", encoding="utf-8")
    notice_file = catalog_fixture.release / "provenance" / "NOTICE"
    notice_file.write_bytes(b"")
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.NOTICE_EVIDENCE_MISSING)


def test_release_rejects_unreferenced_regular_file(
    catalog_fixture: CatalogFixture,
) -> None:
    (catalog_fixture.release / "unsealed.bin").write_bytes(b"not declared")

    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.INVARIANT_VIOLATION)
    assert "undeclared file" in str(exc.value)


def test_catalog_rejects_files_beneath_unlisted_release(
    catalog_fixture: CatalogFixture,
) -> None:
    stray = catalog_fixture.packs / "unlisted.product-design" / "9.9.9" / "payload.bin"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"not catalogued")

    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.INVARIANT_VIOLATION)
    assert "outside declared releases" in str(exc.value)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO not supported")
def test_release_rejects_unreferenced_nonregular_entry(
    catalog_fixture: CatalogFixture,
) -> None:
    os.mkfifo(catalog_fixture.release / "unsealed-pipe")

    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.SOURCE_NOT_REGULAR)


@pytest.mark.skipif(os.name == "nt", reason="case-only names alias on Windows")
def test_release_rejects_case_colliding_notice_paths(
    catalog_fixture: CatalogFixture,
) -> None:
    notice = catalog_fixture.release / "provenance" / "NOTICE"
    alias = catalog_fixture.release / "provenance" / "notice"
    if alias.exists():
        pytest.skip("test filesystem is case-insensitive")
    shutil.copyfile(notice, alias)
    data = catalog_fixture.load_provenance()
    data["records"]["design-brief"]["notice_output"] = "provenance/notice"
    catalog_fixture.write_provenance(data)

    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    assert exc.value.code in {
        PackIssueCode.PATH_UNSAFE,
        PackIssueCode.SOURCE_NOT_REGULAR,
    }


def test_nested_asset_digest_is_verified(catalog_fixture: CatalogFixture) -> None:
    nested = catalog_fixture.release / "router" / "references" / "contract.md"
    nested.parent.mkdir()
    nested.write_text("contract\n", encoding="utf-8")
    data = catalog_fixture.load_provenance()
    data["records"]["product-design"]["nested_assets"] = [
        {
            "path": "references/contract.md",
            "canonical_source_url": "https://github.com/example/contracts",
            "pinned_revision": "2" * 40,
            "source_path": "contract.md",
            "copyright_holders": ["Contract Authors"],
            "spdx_expression": "MIT",
            "license_file": "provenance/LICENSE",
            "license_source_path": "LICENSE",
            "license_file_sha256": _sha256(
                catalog_fixture.release / "provenance" / "LICENSE"
            ),
            "sha256": "3" * 64,
        }
    ]
    catalog_fixture.write_provenance(data)
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.DIGEST_MISMATCH)


def _add_nested_router_skill_asset(
    fixture: CatalogFixture,
    *,
    pinned_revision: str,
    source_path: str,
) -> None:
    local_asset = fixture.release / "router" / "SKILL.md"
    data = fixture.load_provenance()
    record = data["records"]["product-design"]
    record["nested_assets"] = [
        {
            "path": "SKILL.md",
            "canonical_source_url": SOURCE_URL,
            "pinned_revision": pinned_revision,
            "source_path": source_path,
            "copyright_holders": ["Example, Inc."],
            "spdx_expression": "MIT",
            "license_file": "provenance/LICENSE",
            "license_source_path": "LICENSE",
            "license_file_sha256": _sha256(fixture.release / "provenance" / "LICENSE"),
            "sha256": _sha256(local_asset),
        }
    ]
    fixture.write_provenance(data)
    notice = fixture.release / "provenance" / "NOTICE"
    notice.write_text(
        notice.read_text(encoding="utf-8") + f"{pinned_revision}\n",
        encoding="utf-8",
    )


def test_nested_asset_is_verified_against_pinned_regular_git_blob(
    catalog_fixture: CatalogFixture,
) -> None:
    pin = catalog_fixture.load_provenance()["records"]["product-design"][
        "pinned_revision"
    ]
    _add_nested_router_skill_asset(
        catalog_fixture,
        pinned_revision=pin,
        source_path="capability-packs/example.product-design/1.0.0/router/SKILL.md",
    )

    compiled = catalog_fixture.compile()
    nested = compiled["packs"][0]["releases"][0]["router"]["provenance"][
        "nested_assets"
    ]
    assert nested[0]["source_path"].endswith("router/SKILL.md")


@pytest.mark.skipif(os.name == "nt", reason="Git symlink fixture requires POSIX")
def test_nested_asset_rejects_pinned_git_symlink_mode(
    catalog_fixture: CatalogFixture,
) -> None:
    nested_source = catalog_fixture.repo / "nested-source"
    nested_source.mkdir()
    (nested_source / "target").write_text("target", encoding="utf-8")
    (nested_source / "link").symlink_to("target")
    subprocess.run(
        ["git", "-C", str(catalog_fixture.repo), "add", "nested-source"], check=True
    )
    subprocess.run(
        ["git", "-C", str(catalog_fixture.repo), "commit", "-q", "-m", "symlink"],
        check=True,
    )
    pin = subprocess.run(
        ["git", "-C", str(catalog_fixture.repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(catalog_fixture.repo),
            "update-ref",
            "refs/remotes/origin/main",
            pin,
        ],
        check=True,
    )
    _add_nested_router_skill_asset(
        catalog_fixture,
        pinned_revision=pin,
        source_path="nested-source/link",
    )

    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.NESTED_ASSET_EVIDENCE_MISSING)
    assert "regular Git file" in str(exc.value)


def test_platform_evidence_is_bound_and_must_pass(
    catalog_fixture: CatalogFixture,
) -> None:
    evidence = catalog_fixture.release / "evidence" / "product-design.json"
    data = json.loads(evidence.read_text(encoding="utf-8"))
    data["artifact"] = "other-router"
    _write_json(evidence, data)
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.PLATFORM_EVIDENCE_INVALID)

    data["artifact"] = "product-design"
    data["results"][0]["checks"][0]["status"] = "failed"
    _write_json(evidence, data)
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.PLATFORM_EVIDENCE_INVALID)


def test_declared_host_must_have_passing_evidence(
    catalog_fixture: CatalogFixture,
) -> None:
    data = catalog_fixture.load_manifest()
    data["router"]["host_os"] = ["linux", "windows"]
    catalog_fixture.write_manifest(data)
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.PLATFORM_EVIDENCE_MISSING)


def test_source_symlink_and_fifo_are_rejected(catalog_fixture: CatalogFixture) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO not supported")
    fifo = catalog_fixture.release / "router" / "unsafe-pipe"
    os.mkfifo(fifo)
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.SOURCE_NOT_REGULAR)


def test_excluded_candidate_digest_is_recalculated(
    catalog_fixture: CatalogFixture,
) -> None:
    excluded = catalog_fixture.repo / "skills" / "creative" / "excluded"
    excluded.mkdir(parents=True)
    (excluded / "SKILL.md").write_text(
        "---\nname: excluded\ndescription: Excluded fixture.\n---\n# Excluded\n",
        encoding="utf-8",
    )
    data = catalog_fixture.load_manifest()
    data["excluded_candidates"] = [
        {
            "name": "excluded",
            "audited_source_path": "skills/creative/excluded",
            "audited_tree_sha256": "4" * 64,
            "disposition": "quarantined",
            "gate_issue_codes": ["PROVENANCE_EVIDENCE_MISSING"],
        }
    ]
    catalog_fixture.write_manifest(data)
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.DIGEST_MISMATCH)


def test_excluded_candidate_identity_is_bound_to_audited_source(
    catalog_fixture: CatalogFixture,
) -> None:
    excluded = catalog_fixture.repo / "skills" / "creative" / "unrelated"
    excluded.mkdir(parents=True)
    (excluded / "SKILL.md").write_text(
        "---\nname: unrelated\ndescription: Different skill.\n---\n# Unrelated\n",
        encoding="utf-8",
    )
    data = catalog_fixture.load_manifest()
    data["excluded_candidates"] = [
        {
            "name": "claimed-excluded",
            "audited_source_path": "skills/creative/unrelated",
            "audited_tree_sha256": sha256_tree(excluded),
            "disposition": "quarantined",
            "gate_issue_codes": ["PROVENANCE_EVIDENCE_MISSING"],
        }
    ]
    catalog_fixture.write_manifest(data)
    with pytest.raises(CapabilityPackValidationError) as exc:
        catalog_fixture.compile()
    _assert_code(exc, PackIssueCode.INVARIANT_VIOLATION)


def test_runtime_loader_rejects_noncanonical_and_drifted_catalog(
    catalog_fixture: CatalogFixture,
) -> None:
    output = catalog_fixture.packs / "catalog.json"
    output.write_bytes(catalog_fixture.build())
    loaded = load_compiled_catalog(
        output,
        capability_packs_root=catalog_fixture.packs,
        bundled_skills_root=catalog_fixture.skills,
        optional_skills_root=catalog_fixture.optional,
        repository_root=catalog_fixture.repo,
    )
    assert loaded["packs"][0]["id"] == "example.product-design"

    output.write_text(json.dumps(loaded, indent=2), encoding="utf-8")
    with pytest.raises(CapabilityPackValidationError) as exc:
        load_compiled_catalog(
            output,
            capability_packs_root=catalog_fixture.packs,
            bundled_skills_root=catalog_fixture.skills,
            optional_skills_root=catalog_fixture.optional,
            repository_root=catalog_fixture.repo,
        )
    _assert_code(exc, PackIssueCode.CATALOG_NOT_CANONICAL)

    output.write_bytes(catalog_fixture.build())
    skill_file = catalog_fixture.release / "members" / "design-brief" / "SKILL.md"
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8") + "\nDrift.\n",
        encoding="utf-8",
    )
    with pytest.raises(CapabilityPackValidationError) as exc:
        load_compiled_catalog(
            output,
            capability_packs_root=catalog_fixture.packs,
            bundled_skills_root=catalog_fixture.skills,
            optional_skills_root=catalog_fixture.optional,
            repository_root=catalog_fixture.repo,
        )
    _assert_code(exc, PackIssueCode.DIGEST_MISMATCH)


def test_runtime_loader_never_requires_git_or_upstream_objects(
    catalog_fixture: CatalogFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = catalog_fixture.packs / "catalog.json"
    output.write_bytes(catalog_fixture.build())

    def forbidden_git(*_args, **_kwargs):
        raise AssertionError("installed-runtime validation called Git")

    monkeypatch.setattr(pack_module, "_run_git", forbidden_git)
    loaded = load_compiled_catalog(
        output,
        capability_packs_root=catalog_fixture.packs,
        bundled_skills_root=catalog_fixture.skills,
        optional_skills_root=catalog_fixture.optional,
        repository_root=catalog_fixture.repo,
    )
    assert loaded["packs"][0]["id"] == "example.product-design"


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":NaN}\n',
        ('{"schema_version":' + "9" * 5000 + "}\n").encode(),
    ],
)
def test_runtime_loader_maps_invalid_json_scalars_to_stable_error(
    catalog_fixture: CatalogFixture,
    raw: bytes,
) -> None:
    output = catalog_fixture.packs / "invalid.json"
    output.write_bytes(raw)
    with pytest.raises(CapabilityPackValidationError) as exc:
        load_compiled_catalog(
            output,
            capability_packs_root=catalog_fixture.packs,
            bundled_skills_root=catalog_fixture.skills,
            optional_skills_root=catalog_fixture.optional,
            repository_root=catalog_fixture.repo,
        )
    _assert_code(exc, PackIssueCode.CATALOG_NOT_CANONICAL)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO not supported")
def test_authoring_and_runtime_readers_reject_fifo_without_blocking(
    catalog_fixture: CatalogFixture,
) -> None:
    catalog_fixture.manifest.unlink()
    os.mkfifo(catalog_fixture.manifest)
    with pytest.raises(CapabilityPackValidationError) as exc:
        load_authoring_manifest(catalog_fixture.manifest)
    _assert_code(exc, PackIssueCode.SOURCE_NOT_REGULAR)

    output = catalog_fixture.packs / "fifo-catalog.json"
    os.mkfifo(output)
    with pytest.raises(CapabilityPackValidationError) as exc:
        load_compiled_catalog(
            output,
            capability_packs_root=catalog_fixture.packs,
            bundled_skills_root=catalog_fixture.skills,
            optional_skills_root=catalog_fixture.optional,
            repository_root=catalog_fixture.repo,
        )
    _assert_code(exc, PackIssueCode.SOURCE_NOT_REGULAR)


def test_provenance_file_byte_drift_stales_compiled_catalog(
    catalog_fixture: CatalogFixture,
) -> None:
    output = catalog_fixture.packs / "catalog.json"
    output.write_bytes(catalog_fixture.build())
    catalog_fixture.provenance.write_text(
        catalog_fixture.provenance.read_text(encoding="utf-8") + "# review note\n",
        encoding="utf-8",
    )
    with pytest.raises(CapabilityPackValidationError) as exc:
        load_compiled_catalog(
            output,
            capability_packs_root=catalog_fixture.packs,
            bundled_skills_root=catalog_fixture.skills,
            optional_skills_root=catalog_fixture.optional,
            repository_root=catalog_fixture.repo,
        )
    _assert_code(exc, PackIssueCode.DIGEST_MISMATCH)


def test_build_script_check_detects_one_byte_drift(
    catalog_fixture: CatalogFixture,
) -> None:
    output = catalog_fixture.packs / "catalog.json"
    verifier = _fixture_verifier_script(catalog_fixture)
    base = [
        sys.executable,
        str(BUILD_SCRIPT),
        "--root",
        str(catalog_fixture.packs),
        "--repository-root",
        str(catalog_fixture.repo),
        "--bundled-skills-root",
        str(catalog_fixture.skills),
        "--optional-skills-root",
        str(catalog_fixture.optional),
        "--output",
        str(output),
        "--source-repository",
        f"{SOURCE_URL}={catalog_fixture.repo}",
        "--source-ref",
        f"{SOURCE_URL}={SOURCE_REPOSITORY_REF}",
        "--platform-evidence-verifier",
        str(verifier),
    ]
    built = subprocess.run(base, capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stderr
    if os.name != "nt":
        assert output.stat().st_mode & 0o777 == 0o644
    checked = subprocess.run(
        [*base, "--check"], capture_output=True, text=True, timeout=30
    )
    assert checked.returncode == 0, checked.stderr
    output.write_bytes(output.read_bytes() + b" ")
    drifted = subprocess.run(
        [*base, "--check"], capture_output=True, text=True, timeout=30
    )
    assert drifted.returncode == 1
    assert "stale" in drifted.stderr


def test_build_script_rejects_redirected_output(
    catalog_fixture: CatalogFixture,
) -> None:
    if os.name == "nt":
        pytest.skip("symlink creation is privilege-dependent on Windows")
    outside = catalog_fixture.repo.parent / "outside.json"
    outside.write_text("sentinel\n", encoding="utf-8")
    redirected = catalog_fixture.packs / "catalog.json"
    redirected.symlink_to(outside)
    verifier = _fixture_verifier_script(catalog_fixture)
    run = subprocess.run(
        [
            sys.executable,
            str(BUILD_SCRIPT),
            "--root",
            str(catalog_fixture.packs),
            "--repository-root",
            str(catalog_fixture.repo),
            "--bundled-skills-root",
            str(catalog_fixture.skills),
            "--optional-skills-root",
            str(catalog_fixture.optional),
            "--output",
            str(redirected),
            "--source-repository",
            f"{SOURCE_URL}={catalog_fixture.repo}",
            "--source-ref",
            f"{SOURCE_URL}={SOURCE_REPOSITORY_REF}",
            "--platform-evidence-verifier",
            str(verifier),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 2
    assert outside.read_text(encoding="utf-8") == "sentinel\n"


@pytest.mark.parametrize(
    "relative_output",
    [
        "catalog.yaml",
        "example.product-design/1.0.0/pack.yaml",
        "example.product-design/1.0.0/router/catalog.json",
    ],
)
def test_build_script_cannot_overwrite_authoring_or_write_inside_release(
    catalog_fixture: CatalogFixture,
    relative_output: str,
) -> None:
    protected = catalog_fixture.packs / relative_output
    before = protected.read_bytes() if protected.is_file() else None
    run = subprocess.run(
        [
            sys.executable,
            str(BUILD_SCRIPT),
            "--root",
            str(catalog_fixture.packs),
            "--output",
            str(protected),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert run.returncode == 2
    assert "--output must be exactly" in run.stderr
    if before is not None:
        assert protected.read_bytes() == before
    else:
        assert not protected.exists()
