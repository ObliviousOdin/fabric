"""Contracts for the read-only capability-pack planner/status foundation."""

from __future__ import annotations

import json
import os
import copy
from pathlib import Path

import pytest

from fabric_cli.capability_pack_lifecycle import (
    MemberClassification,
    MutationPlanStatus,
    PackContextHealth,
    PackLifecycleIssueCode,
    PackLifecycleValidationError,
    load_effective_disabled_skills,
    plan_pack,
)
from tools.skill_install import sha256_tree


PACK_ID = "fabric.test-pack"
VERSION = "1.0.0"
MANIFEST_SHA256 = "1" * 64
RELEASE_SHA256 = "2" * 64


def _write_skill(path: Path, name: str, body: str = "# Skill\n") -> str:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test {name}.\n---\n{body}",
        encoding="utf-8",
    )
    return sha256_tree(path)


def _artifact(
    name: str,
    digest: str,
    *,
    ownership: str,
    source_kind: str,
    source_path: str,
    install_path: str | None,
    role: str | None = None,
    default: str | None = None,
    host_os: tuple[str, ...] = ("linux", "macos", "windows"),
    required_toolsets: tuple[str, ...] = ("skills",),
) -> dict:
    result = {
        "name": name,
        "ownership": ownership,
        "source_kind": source_kind,
        "source_path": source_path,
        "install_path": install_path,
        "source_tree_sha256": digest,
        "effective_host_os": list(host_os),
        "required_toolsets": list(required_toolsets),
    }
    if role is not None:
        result["role"] = role
    if default is not None:
        result["default"] = default
    return result


def _catalog(
    *,
    router_digest: str,
    required_digest: str,
    optional_digest: str,
    optional_host_os: tuple[str, ...] = ("linux", "macos", "windows"),
) -> dict:
    return {
        "schema_version": 1,
        "source_catalog": {"path": "catalog.yaml", "sha256": "3" * 64},
        "packs": [
            {
                "id": PACK_ID,
                "releases": [
                    {
                        "id": PACK_ID,
                        "version": VERSION,
                        "release_tree_sha256": RELEASE_SHA256,
                        "authoring_manifest": {
                            "path": f"{PACK_ID}/{VERSION}/pack.yaml",
                            "sha256": MANIFEST_SHA256,
                        },
                        "router": _artifact(
                            "test-pack",
                            router_digest,
                            ownership="pack",
                            source_kind="pack",
                            source_path="router",
                            install_path="workflows/test-pack",
                        ),
                        "members": [
                            _artifact(
                                "required-skill",
                                required_digest,
                                ownership="reference",
                                source_kind="bundled",
                                source_path="engineering/required-skill",
                                install_path=None,
                                role="required",
                                default="enabled",
                                required_toolsets=("file", "skills"),
                            ),
                            _artifact(
                                "optional-skill",
                                optional_digest,
                                ownership="reference",
                                source_kind="optional",
                                source_path="design/optional-skill",
                                install_path=None,
                                role="optional",
                                default="disabled",
                                host_os=optional_host_os,
                            ),
                        ],
                    }
                ],
            }
        ],
    }


def _write_state(
    home: Path,
    router_digest: str,
    *,
    required_digest: str,
    optional_digest: str,
    manifest_sha256: str = MANIFEST_SHA256,
) -> None:
    path = home / "capability-packs" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "revision": 7,
                "last_transaction_id": None,
                "installed": {
                    PACK_ID: {
                        "version": VERSION,
                        "manifest_sha256": manifest_sha256,
                        "installed_at": "2026-07-11T00:00:00+00:00",
                        "updated_at": "2026-07-11T00:00:00+00:00",
                        "owned": {
                            "workflows/test-pack": {
                                "kind": "router",
                                "sha256": router_digest,
                            }
                        },
                        "members": {
                            "required-skill": {
                                "ownership": "reference",
                                "effective_path": "engineering/required-skill",
                                "source_sha256": required_digest,
                                "installed_sha256": None,
                            },
                            "optional-skill": {
                                "ownership": "reference",
                                "effective_path": "design/optional-skill",
                                "source_sha256": optional_digest,
                                "installed_sha256": None,
                            },
                        },
                    }
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _installed_fixture(home: Path) -> tuple[dict, str, str, str]:
    router_digest = _write_skill(
        home / "skills" / "workflows" / "test-pack", "test-pack"
    )
    required_digest = _write_skill(
        home / "skills" / "engineering" / "required-skill", "required-skill"
    )
    optional_digest = _write_skill(
        home / "skills" / "design" / "optional-skill", "optional-skill"
    )
    catalog = _catalog(
        router_digest=router_digest,
        required_digest=required_digest,
        optional_digest=optional_digest,
    )
    _write_state(
        home,
        router_digest,
        required_digest=required_digest,
        optional_digest=optional_digest,
    )
    return catalog, router_digest, required_digest, optional_digest


def _plan(
    home: Path,
    catalog: dict,
    *,
    operation: str = "apply",
    target_version: str = VERSION,
    session_platform: str | None = None,
    overrides: dict[str, str] | None = None,
    toolsets: frozenset[str] = frozenset({"file", "skills"}),
    external_skill_roots: tuple[Path, ...] = (),
):
    return plan_pack(
        PACK_ID,
        home=home,
        catalog=catalog,
        operation=operation,
        target_version=target_version,
        host_os="linux",
        session_platform=session_platform,
        available_toolsets=toolsets,
        overrides=overrides or {},
        external_skill_roots=external_skill_roots,
    )


def test_disabled_skills_are_profile_scoped_global_plus_exact_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "profile"
    home.mkdir()
    (home / "config.yaml").write_text(
        """skills:
  disabled: [global-skill]
  platform_disabled:
    telegram: [telegram-skill]
    discord: [discord-skill]
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("FABRIC_PLATFORM", "discord")
    monkeypatch.setenv("FABRIC_SESSION_PLATFORM", "discord")

    assert load_effective_disabled_skills(home, None) == {"global-skill"}
    assert load_effective_disabled_skills(home, "telegram") == {
        "global-skill",
        "telegram-skill",
    }
    assert load_effective_disabled_skills(home, "TELEGRAM") == {"global-skill"}


def test_fresh_plan_is_neutral_and_does_not_install_or_sync_all_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "profile"
    required_digest = _write_skill(
        home / "skills" / "engineering" / "required-skill", "required-skill"
    )
    catalog = _catalog(
        router_digest="a" * 64,
        required_digest=required_digest,
        optional_digest="b" * 64,
    )
    import tools.skills_sync as skills_sync

    monkeypatch.setattr(
        skills_sync,
        "sync_skills",
        lambda *args, **kwargs: pytest.fail("planning called all-skill sync"),
    )
    before = sorted(str(path.relative_to(home)) for path in home.rglob("*"))

    result = _plan(home, catalog)

    after = sorted(str(path.relative_to(home)) for path in home.rglob("*"))
    by_name = {member.name: member for member in result.members}
    assert result.mutation_status == MutationPlanStatus.READY
    assert result.context_health == PackContextHealth.BLOCKED
    assert by_name["test-pack"].inventory_status == MemberClassification.MISSING
    assert by_name["required-skill"].inventory_status == MemberClassification.READY
    assert by_name["optional-skill"].status == MemberClassification.DISABLED
    assert [operation.kind for operation in result.operations] == [
        "promote",
        "preserve",
        "preserve",
    ]
    assert before == after


def test_session_disabled_optional_changes_context_not_mutation_plan(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    catalog, *_ = _installed_fixture(home)
    (home / "config.yaml").write_text(
        """skills:
  platform_disabled:
    telegram: [optional-skill]
""",
        encoding="utf-8",
    )
    overrides = {"optional-skill": "enabled"}

    cli = _plan(home, catalog, overrides=overrides)
    telegram = _plan(
        home,
        catalog,
        session_platform="telegram",
        overrides=overrides,
    )

    assert (
        cli.mutation_status == telegram.mutation_status == MutationPlanStatus.UNCHANGED
    )
    assert cli.mutation_plan_digest == telegram.mutation_plan_digest
    assert cli.context_health == PackContextHealth.HEALTHY
    assert telegram.context_health == PackContextHealth.DEGRADED
    assert cli.context_digest != telegram.context_digest
    optional = {member.name: member for member in telegram.members}["optional-skill"]
    assert optional.inventory_status == MemberClassification.READY
    assert optional.status == MemberClassification.DISABLED
    assert PackLifecycleIssueCode.SKILL_DISABLED in {
        issue.code for issue in optional.issues
    }


def test_global_disabled_required_blocks_context_but_not_neutral_disk_plan(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    catalog, *_ = _installed_fixture(home)
    (home / "config.yaml").write_text(
        "skills:\n  disabled: [required-skill]\n",
        encoding="utf-8",
    )

    result = _plan(home, catalog)

    assert result.mutation_status == MutationPlanStatus.UNCHANGED
    assert result.context_health == PackContextHealth.BLOCKED
    required = {member.name: member for member in result.members}["required-skill"]
    assert required.inventory_status == MemberClassification.READY
    assert required.status == MemberClassification.DISABLED


def test_toolset_context_change_does_not_change_mutation_digest(tmp_path: Path) -> None:
    home = tmp_path / "profile"
    catalog, *_ = _installed_fixture(home)

    complete = _plan(home, catalog)
    missing = _plan(home, catalog, toolsets=frozenset({"skills"}))

    assert complete.mutation_plan_digest == missing.mutation_plan_digest
    assert complete.context_digest != missing.context_digest
    assert missing.mutation_status == MutationPlanStatus.UNCHANGED
    assert missing.context_health == PackContextHealth.BLOCKED
    required = {member.name: member for member in missing.members}["required-skill"]
    assert required.status == MemberClassification.UNAVAILABLE_TOOLSET
    assert required.missing_toolsets == ("file",)


def test_external_reference_is_reported_as_shadow_without_writing_profile(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    external = tmp_path / "external"
    required_digest = _write_skill(
        external / "engineering" / "required-skill", "required-skill"
    )
    catalog = _catalog(
        router_digest="a" * 64,
        required_digest=required_digest,
        optional_digest="b" * 64,
    )

    result = _plan(home, catalog, external_skill_roots=(external,))

    required = {member.name: member for member in result.members}["required-skill"]
    assert required.inventory_status == MemberClassification.EXTERNAL_SHADOW
    assert result.mutation_status == MutationPlanStatus.CONFLICT
    assert result.context_health == PackContextHealth.BLOCKED
    assert not (home / "skills").exists()


def test_external_collision_after_install_blocks_pack_owned_router(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    external = tmp_path / "external"
    catalog, *_ = _installed_fixture(home)
    _write_skill(external / "elsewhere" / "test-pack", "test-pack")

    result = _plan(home, catalog, external_skill_roots=(external,))

    router = {member.name: member for member in result.members}["test-pack"]
    assert router.inventory_status == MemberClassification.EXTERNAL_SHADOW
    assert result.mutation_status == MutationPlanStatus.CONFLICT
    assert result.context_health == PackContextHealth.BLOCKED


def test_pack_owned_digest_drift_is_distinct_from_context_prerequisites(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    catalog, router_digest, required_digest, _ = _installed_fixture(home)
    router_file = home / "skills" / "workflows" / "test-pack" / "SKILL.md"
    router_file.write_text(
        router_file.read_text(encoding="utf-8") + "changed\n", encoding="utf-8"
    )

    result = _plan(home, catalog)

    router = {member.name: member for member in result.members}["test-pack"]
    assert router.current_sha256 != router_digest
    assert router.inventory_status == MemberClassification.USER_MODIFIED
    assert result.mutation_status == MutationPlanStatus.CONFLICT
    assert result.context_health == PackContextHealth.DRIFTED
    assert PackLifecycleIssueCode.USER_MODIFIED_CONFLICT in {
        issue.code for issue in result.issues
    }


def test_required_override_cannot_silently_disable_member(tmp_path: Path) -> None:
    home = tmp_path / "profile"
    catalog, *_ = _installed_fixture(home)

    result = _plan(home, catalog, overrides={"required-skill": "disabled"})

    required = {member.name: member for member in result.members}["required-skill"]
    assert required.enabled is False
    assert required.status == MemberClassification.DISABLED
    assert result.mutation_status == MutationPlanStatus.BLOCKED
    assert result.context_health == PackContextHealth.BLOCKED


def test_disabled_pack_owned_optional_member_plans_guarded_removal(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    catalog, router_digest, required_digest, _ = _installed_fixture(home)
    optional_path = home / "skills" / "extras" / "optional-skill"
    optional_digest = _write_skill(optional_path, "optional-skill")
    optional = catalog["packs"][0]["releases"][0]["members"][1]
    optional.update({
        "ownership": "pack",
        "source_kind": "pack",
        "source_path": "members/optional-skill",
        "install_path": "extras/optional-skill",
        "source_tree_sha256": optional_digest,
    })
    _write_state(
        home,
        router_digest,
        required_digest=required_digest,
        optional_digest=optional_digest,
    )
    state_path = home / "capability-packs" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    installed = state["installed"][PACK_ID]
    installed["owned"]["extras/optional-skill"] = {
        "kind": "member",
        "sha256": optional_digest,
    }
    installed["members"]["optional-skill"].update({
        "ownership": "pack",
        "effective_path": "extras/optional-skill",
        "source_sha256": optional_digest,
        "installed_sha256": optional_digest,
    })
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")

    result = _plan(home, catalog)

    operation = {operation.member: operation for operation in result.operations}[
        "optional-skill"
    ]
    assert operation.kind == "remove"
    assert operation.before_sha256 == optional_digest
    assert operation.after_sha256 is None
    assert result.mutation_status == MutationPlanStatus.READY
    assert result.context_health == PackContextHealth.HEALTHY


def test_enabled_missing_pack_owned_optional_is_installable_not_neutral_degradation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    catalog, *_ = _installed_fixture(home)
    optional = catalog["packs"][0]["releases"][0]["members"][1]
    optional.update({
        "ownership": "pack",
        "source_kind": "pack",
        "source_path": "members/optional-skill",
        "install_path": "extras/optional-skill",
    })
    state_path = home / "capability-packs" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["installed"][PACK_ID]["members"].pop("optional-skill")
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    skill_file = home / "skills" / "design" / "optional-skill" / "SKILL.md"
    skill_file.unlink()
    skill_file.parent.rmdir()

    result = _plan(home, catalog, overrides={"optional-skill": "enabled"})

    optional_status = {member.name: member for member in result.members}[
        "optional-skill"
    ]
    operation = {operation.member: operation for operation in result.operations}[
        "optional-skill"
    ]
    assert optional_status.inventory_status == MemberClassification.MISSING
    assert operation.kind == "promote"
    assert result.mutation_status == MutationPlanStatus.READY
    assert result.context_health == PackContextHealth.DEGRADED


@pytest.mark.parametrize(
    ("role", "mutation_status", "context_health"),
    [
        ("required", MutationPlanStatus.BLOCKED, PackContextHealth.BLOCKED),
        ("optional", MutationPlanStatus.DEGRADED, PackContextHealth.DEGRADED),
    ],
)
def test_missing_reference_required_vs_optional_classification(
    tmp_path: Path,
    role: str,
    mutation_status: MutationPlanStatus,
    context_health: PackContextHealth,
) -> None:
    home = tmp_path / role
    router_digest = _write_skill(
        home / "skills" / "workflows" / "test-pack", "test-pack"
    )
    catalog = _catalog(
        router_digest=router_digest,
        required_digest="a" * 64,
        optional_digest="b" * 64,
    )
    target = catalog["packs"][0]["releases"][0]["members"][0]
    target["role"] = role
    target["default"] = "enabled"
    _write_state(
        home,
        router_digest,
        required_digest="a" * 64,
        optional_digest="b" * 64,
    )

    result = _plan(home, catalog)

    target_status = {member.name: member for member in result.members}["required-skill"]
    assert target_status.inventory_status == MemberClassification.MISSING
    assert result.mutation_status == mutation_status
    assert result.context_health == context_health


def test_host_support_remains_neutral_when_same_member_is_session_disabled(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    catalog, *_ = _installed_fixture(home)
    required = catalog["packs"][0]["releases"][0]["members"][0]
    required["effective_host_os"] = ["macos", "windows"]
    (home / "config.yaml").write_text(
        "skills:\n  platform_disabled:\n    telegram: [required-skill]\n",
        encoding="utf-8",
    )

    cli = _plan(home, catalog)
    telegram = _plan(home, catalog, session_platform="telegram")

    assert cli.mutation_status == telegram.mutation_status == MutationPlanStatus.BLOCKED
    assert cli.mutation_plan_digest == telegram.mutation_plan_digest
    assert cli.context_health == telegram.context_health == PackContextHealth.BLOCKED
    cli_required = {member.name: member for member in cli.members}["required-skill"]
    telegram_required = {member.name: member for member in telegram.members}[
        "required-skill"
    ]
    assert cli_required.status == MemberClassification.UNSUPPORTED
    assert telegram_required.status == MemberClassification.DISABLED
    assert cli_required.host_supported is telegram_required.host_supported is False


def test_invalid_or_unknown_override_fails_with_stable_code(tmp_path: Path) -> None:
    home = tmp_path / "profile"
    catalog, *_ = _installed_fixture(home)

    with pytest.raises(PackLifecycleValidationError) as exc_info:
        _plan(home, catalog, overrides={"not-a-member": "enabled"})

    assert exc_info.value.code == PackLifecycleIssueCode.OVERRIDE_INVALID


def test_unbound_installed_manifest_identity_is_rejected(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    catalog, router_digest, required_digest, optional_digest = _installed_fixture(home)
    original = _plan(home, catalog)
    _write_state(
        home,
        router_digest,
        required_digest=required_digest,
        optional_digest=optional_digest,
        manifest_sha256="f" * 64,
    )

    with pytest.raises(PackLifecycleValidationError) as exc_info:
        _plan(home, catalog)

    assert original.mutation_status == MutationPlanStatus.UNCHANGED
    assert exc_info.value.code == PackLifecycleIssueCode.STATE_INVALID


def test_planning_does_not_mutate_ambient_profile_or_platform_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "profile"
    catalog, *_ = _installed_fixture(home)
    monkeypatch.setenv("FABRIC_HOME", "/unrelated/fabric")
    monkeypatch.setenv("FABRIC_HOME", "/unrelated/hermes")
    monkeypatch.setenv("FABRIC_PLATFORM", "discord")
    before = dict(os.environ)

    _plan(home, catalog, session_platform=None)

    assert dict(os.environ) == before


def test_operation_verb_is_bound_into_digest_and_remove_plan(tmp_path: Path) -> None:
    home = tmp_path / "profile"
    catalog, *_ = _installed_fixture(home)

    plans = {
        verb: _plan(home, catalog, operation=verb)
        for verb in ("apply", "update", "downgrade", "remove", "override")
    }

    assert len({plan.mutation_plan_digest for plan in plans.values()}) == 5
    assert {verb: plan.operation for verb, plan in plans.items()} == {
        verb: verb for verb in plans
    }
    assert plans["apply"].mutation_status == MutationPlanStatus.UNCHANGED
    assert plans["remove"].mutation_status == MutationPlanStatus.READY
    remove_operations = {
        operation.member: operation for operation in plans["remove"].operations
    }
    assert remove_operations["test-pack"].kind == "remove"


def test_same_name_local_collision_blocks_pack_owned_promotion(tmp_path: Path) -> None:
    home = tmp_path / "profile"
    required_digest = _write_skill(
        home / "skills" / "engineering" / "required-skill", "required-skill"
    )
    _write_skill(home / "skills" / "custom" / "test-pack", "test-pack")
    catalog = _catalog(
        router_digest="a" * 64,
        required_digest=required_digest,
        optional_digest="b" * 64,
    )

    result = _plan(home, catalog)

    router = {member.name: member for member in result.members}["test-pack"]
    assert router.inventory_status == MemberClassification.EXTERNAL_SHADOW
    assert result.mutation_status == MutationPlanStatus.CONFLICT
    assert not (home / "skills" / "workflows" / "test-pack").exists()


@pytest.mark.parametrize("corruption", ["owned_kind", "member_digest", "timestamp"])
def test_persisted_ownership_schema_and_catalog_binding_fail_closed(
    tmp_path: Path, corruption: str
) -> None:
    home = tmp_path / corruption
    catalog, *_ = _installed_fixture(home)
    state_path = home / "capability-packs" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    installed = state["installed"][PACK_ID]
    if corruption == "owned_kind":
        installed["owned"]["workflows/test-pack"]["kind"] = "not-a-kind"
    elif corruption == "member_digest":
        installed["members"]["required-skill"]["source_sha256"] = "f" * 64
    else:
        installed.pop("updated_at")
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")

    with pytest.raises(PackLifecycleValidationError) as exc_info:
        _plan(home, catalog)

    assert exc_info.value.code == PackLifecycleIssueCode.STATE_INVALID


def test_redirected_pack_destination_returns_stable_lifecycle_error(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    required_digest = _write_skill(
        home / "skills" / "engineering" / "required-skill", "required-skill"
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    workflows = home / "skills" / "workflows"
    try:
        workflows.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    catalog = _catalog(
        router_digest="a" * 64,
        required_digest=required_digest,
        optional_digest="b" * 64,
    )

    with pytest.raises(PackLifecycleValidationError) as exc_info:
        _plan(home, catalog)

    assert exc_info.value.code == PackLifecycleIssueCode.SYMLINK_REJECTED


def test_derived_profile_state_root_cannot_redirect_outside_home(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    home.mkdir()
    outside = tmp_path / "outside-state"
    outside.mkdir()
    try:
        (home / "capability-packs").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    catalog = _catalog(
        router_digest="a" * 64,
        required_digest="b" * 64,
        optional_digest="c" * 64,
    )

    with pytest.raises(PackLifecycleValidationError) as exc_info:
        _plan(home, catalog)

    assert exc_info.value.code == PackLifecycleIssueCode.SYMLINK_REJECTED


def test_external_skill_roots_must_be_explicit_absolute_authorized_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "profile"
    catalog = _catalog(
        router_digest="a" * 64,
        required_digest="b" * 64,
        optional_digest="c" * 64,
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(PackLifecycleValidationError) as exc_info:
        _plan(home, catalog, external_skill_roots=(Path("relative-skills"),))

    assert exc_info.value.code == PackLifecycleIssueCode.PATH_UNSAFE


def test_unhashable_obsolete_owned_tree_is_preserved_as_conflict(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    catalog, router_digest, required_digest, optional_digest = _installed_fixture(home)
    legacy_path = home / "skills" / "legacy" / "optional-skill"
    legacy_digest = _write_skill(legacy_path, "optional-skill")
    old_release = catalog["packs"][0]["releases"][0]
    old_optional = old_release["members"][1]
    old_optional.update({
        "ownership": "pack",
        "source_kind": "pack",
        "source_path": "members/optional-skill",
        "install_path": "legacy/optional-skill",
        "source_tree_sha256": legacy_digest,
    })
    _write_state(
        home,
        router_digest,
        required_digest=required_digest,
        optional_digest=legacy_digest,
    )
    state_path = home / "capability-packs" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    installed = state["installed"][PACK_ID]
    installed["owned"]["legacy/optional-skill"] = {
        "kind": "member",
        "sha256": legacy_digest,
    }
    installed["members"]["optional-skill"].update({
        "ownership": "pack",
        "effective_path": "legacy/optional-skill",
        "source_sha256": legacy_digest,
        "installed_sha256": legacy_digest,
    })
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    target = copy.deepcopy(old_release)
    target["version"] = "2.0.0"
    target["authoring_manifest"] = {
        "path": f"{PACK_ID}/2.0.0/pack.yaml",
        "sha256": "4" * 64,
    }
    target["release_tree_sha256"] = "5" * 64
    target["members"] = [target["members"][0]]
    catalog["packs"][0]["releases"].append(target)
    outside = tmp_path / "sentinel"
    outside.write_text("do not touch", encoding="utf-8")
    try:
        (legacy_path / "unsafe-link").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    result = _plan(
        home,
        catalog,
        operation="update",
        target_version="2.0.0",
    )

    obsolete = next(
        operation
        for operation in result.operations
        if operation.destination_relative_path == "legacy/optional-skill"
    )
    assert obsolete.kind == "preserve"
    assert result.mutation_status == MutationPlanStatus.CONFLICT
    assert PackLifecycleIssueCode.USER_MODIFIED_CONFLICT in {
        issue.code for issue in result.issues
    }
    assert outside.read_text(encoding="utf-8") == "do not touch"


def test_state_schema_version_rejects_boolean_alias_for_one(tmp_path: Path) -> None:
    from fabric_cli import capability_pack_lifecycle as lifecycle

    home = tmp_path / "profile"
    state_root = home / "capability-packs"
    state_root.mkdir(parents=True)
    (state_root / "state.json").write_text(
        json.dumps({
            "schema_version": True,
            "revision": 0,
            "last_transaction_id": None,
            "installed": {},
        }),
        encoding="utf-8",
    )

    with pytest.raises(PackLifecycleValidationError) as exc_info:
        lifecycle._load_pack_state(home)

    assert exc_info.value.code == PackLifecycleIssueCode.STATE_INVALID
