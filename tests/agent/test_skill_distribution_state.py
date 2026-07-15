"""Durability and isolation contracts for signed-skill trust state."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import timedelta

import pytest

from agent.skill_distribution import (
    DistributionErrorCode,
    OfflineGracePolicy,
    SkillDistributionError,
)
from agent.skill_distribution_state import (
    SkillDistributionStateError,
    SkillDistributionStateStore,
)
from tests.agent.test_skill_distribution import (
    NOW,
    _metadata_fixture,
    _root_bytes,
    _verify as _verify_pure,
)


def _bootstrap(store: SkillDistributionStateStore):
    raw = _root_bytes()
    return store.bootstrap(
        raw,
        trusted_sha256=hashlib.sha256(raw).hexdigest(),
        now=NOW,
    )


def _verify(store: SkillDistributionStateStore, fixture, **overrides):
    arguments = {
        "timestamp": fixture.timestamp,
        "snapshot": fixture.snapshot,
        "targets": fixture.targets,
        "revocations": fixture.revocations,
        "name": "software-development/demo",
        "version": "1.2.3",
        "now": NOW,
    }
    arguments.update(overrides)
    return store.verify_and_advance(**arguments)


def test_bootstrap_persists_root_and_rollback_state_atomically(tmp_path) -> None:
    store = SkillDistributionStateStore(tmp_path / "trust")
    initialized = _bootstrap(store)
    reloaded = store.load(now=NOW)

    assert initialized.root.version == reloaded.root.version == 1
    assert initialized.root_envelope == reloaded.root_envelope
    assert reloaded.trusted_versions.root == 1
    assert (
        reloaded.trusted_versions.root_sha256
        == hashlib.sha256(initialized.root_envelope).hexdigest()
    )
    assert store.state_path.stat().st_mode & 0o777 == 0o600
    assert store.directory.stat().st_mode & 0o777 == 0o700


def test_bootstrap_requires_out_of_band_pin_and_refuses_reinitialization(
    tmp_path,
) -> None:
    store = SkillDistributionStateStore(tmp_path / "trust")
    root = _root_bytes()
    with pytest.raises(SkillDistributionError) as mismatch:
        store.bootstrap(root, trusted_sha256="0" * 64, now=NOW)
    assert mismatch.value.code == DistributionErrorCode.ROOT_PIN_MISMATCH.value

    _bootstrap(store)
    with pytest.raises(SkillDistributionStateError, match="already initialized"):
        _bootstrap(store)


def test_verification_advances_exact_version_and_digest_state(tmp_path) -> None:
    store = SkillDistributionStateStore(tmp_path / "trust")
    _bootstrap(store)
    fixture = _metadata_fixture()
    release = _verify(store, fixture)
    reloaded = store.load(now=NOW)

    assert reloaded.trusted_versions == release.trusted_versions
    assert reloaded.trusted_versions.targets == 13
    assert (
        reloaded.trusted_versions.targets_sha256
        == hashlib.sha256(fixture.targets).hexdigest()
    )
    assert release.publisher == "Fabric Release Engineering"
    assert release.channel == "stable"


def test_unadvanced_store_cannot_issue_proof_for_global_verified_release(
    tmp_path,
) -> None:
    store = SkillDistributionStateStore(tmp_path / "trust")
    _bootstrap(store)
    release = _verify_pure(_metadata_fixture())

    with pytest.raises(SkillDistributionStateError, match="current.*trust state"):
        store.issue_installed_proof(
            release,
            installed_tree_sha256=release.tree_sha256,
            now=NOW,
        )
    assert not store.key_path.exists()


def test_stale_store_state_cannot_re_sign_an_older_verified_release(tmp_path) -> None:
    store = SkillDistributionStateStore(tmp_path / "trust")
    _bootstrap(store)
    old_release = _verify(store, _metadata_fixture())
    advanced_fixture = _metadata_fixture(
        versions={
            "timestamp": 21,
            "snapshot": 22,
            "targets": 23,
            "revocations": 24,
        }
    )
    _verify(store, advanced_fixture)

    with pytest.raises(SkillDistributionStateError, match="current.*trust state"):
        store.issue_installed_proof(
            old_release,
            installed_tree_sha256=old_release.tree_sha256,
            now=NOW,
        )
    assert not store.key_path.exists()


def test_cross_root_store_cannot_re_sign_a_verified_release(tmp_path) -> None:
    first = SkillDistributionStateStore(tmp_path / "first")
    _bootstrap(first)
    first_release = _verify(first, _metadata_fixture())

    second = SkillDistributionStateStore(tmp_path / "second")
    second_root_bytes = _root_bytes(
        root_names=("new-root-a", "new-root-b"),
    )
    second.bootstrap(
        second_root_bytes,
        trusted_sha256=hashlib.sha256(second_root_bytes).hexdigest(),
        now=NOW,
    )
    second_root = second.load(now=NOW).root
    _verify(second, _metadata_fixture(trusted_root=second_root))

    with pytest.raises(SkillDistributionStateError, match="current.*trust state"):
        second.issue_installed_proof(
            first_release,
            installed_tree_sha256=first_release.tree_sha256,
            now=NOW,
        )
    assert not second.key_path.exists()


def test_same_version_equivocation_is_rejected_after_restart(tmp_path) -> None:
    store = SkillDistributionStateStore(tmp_path / "trust")
    _bootstrap(store)
    _verify(store, _metadata_fixture())

    restarted = SkillDistributionStateStore(tmp_path / "trust")
    changed = _metadata_fixture(publisher="Different Publisher")
    with pytest.raises(SkillDistributionError) as equivocation:
        _verify(restarted, changed)
    assert equivocation.value.code == DistributionErrorCode.METADATA_EQUIVOCATION.value


def test_root_rotation_persists_root_and_state_as_one_restart_unit(tmp_path) -> None:
    store = SkillDistributionStateStore(tmp_path / "trust")
    _bootstrap(store)
    candidate = _root_bytes(
        version=2,
        root_names=("new-root-a", "new-root-b"),
        signers=("old-root-a", "old-root-b", "new-root-a", "new-root-b"),
    )
    rotated = store.rotate(candidate, now=NOW)

    restarted = SkillDistributionStateStore(tmp_path / "trust").load(now=NOW)
    assert rotated.root.version == restarted.root.version == 2
    assert restarted.root_envelope == candidate
    assert restarted.trusted_versions.root == 2
    assert (
        restarted.trusted_versions.root_sha256 == hashlib.sha256(candidate).hexdigest()
    )


def test_failed_rotation_preserves_prior_state_bytes(tmp_path) -> None:
    store = SkillDistributionStateStore(tmp_path / "trust")
    _bootstrap(store)
    before = store.state_path.read_bytes()
    invalid = _root_bytes(version=3)

    with pytest.raises(SkillDistributionError):
        store.rotate(invalid, now=NOW)
    assert store.state_path.read_bytes() == before
    assert store.load(now=NOW).root.version == 1


def test_offline_proof_key_is_separate_private_and_exact_tree_bound(tmp_path) -> None:
    store = SkillDistributionStateStore(tmp_path / "trust")
    _bootstrap(store)
    fixture = _metadata_fixture(metadata_expires="2026-07-14T13:00:00Z")
    installed = _verify(store, fixture)
    proof = store.issue_installed_proof(
        installed,
        installed_tree_sha256=installed.tree_sha256,
        now=NOW,
    )

    state_text = store.state_path.read_text(encoding="utf-8")
    assert store.key_path.read_bytes() not in store.state_path.read_bytes()
    assert "receipt" not in state_text
    assert store.key_path.stat().st_mode & 0o777 == 0o600

    release = _verify(
        store,
        fixture,
        now=NOW + timedelta(hours=2),
        installed_proof=proof,
        installed_tree_sha256=installed.tree_sha256,
        offline_grace=OfflineGracePolicy(timedelta(hours=3)),
    )
    assert release.offline_grace_used is True

    with pytest.raises(SkillDistributionError) as mismatch:
        _verify(
            store,
            fixture,
            now=NOW + timedelta(hours=2),
            installed_proof=proof,
            installed_tree_sha256="f" * 64,
            offline_grace=OfflineGracePolicy(timedelta(hours=3)),
        )
    assert mismatch.value.code == DistributionErrorCode.OFFLINE_GRACE_DENIED.value


def test_proof_inputs_must_be_complete_and_existing_key_is_required(tmp_path) -> None:
    store = SkillDistributionStateStore(tmp_path / "trust")
    _bootstrap(store)
    fixture = _metadata_fixture()
    with pytest.raises(SkillDistributionStateError, match="supplied together"):
        _verify(store, fixture, installed_proof=b"{}")
    with pytest.raises(SkillDistributionStateError, match="key is unavailable"):
        _verify(
            store,
            fixture,
            installed_proof=b"{}",
            installed_tree_sha256="a" * 64,
        )


def test_corrupt_noncanonical_and_unknown_state_fail_closed(tmp_path) -> None:
    store = SkillDistributionStateStore(tmp_path / "trust")
    _bootstrap(store)
    parsed = json.loads(store.state_path.read_bytes())
    parsed["unknown"] = True
    store.state_path.write_text(json.dumps(parsed), encoding="utf-8")

    with pytest.raises(SkillDistributionStateError):
        store.load(now=NOW)


def test_symlinked_state_or_key_is_rejected(tmp_path) -> None:
    state_store = SkillDistributionStateStore(tmp_path / "state-trust")
    state_store.directory.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("{}", encoding="utf-8")
    state_store.state_path.symlink_to(outside)
    with pytest.raises(SkillDistributionStateError):
        _bootstrap(state_store)

    key_store = SkillDistributionStateStore(tmp_path / "key-trust")
    _bootstrap(key_store)
    key_store.key_path.symlink_to(outside)
    release = _verify(key_store, _metadata_fixture())
    with pytest.raises(SkillDistributionStateError):
        key_store.issue_installed_proof(
            release,
            installed_tree_sha256=release.tree_sha256,
            now=NOW,
        )


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_overly_broad_state_or_receipt_key_permissions_fail_closed(tmp_path) -> None:
    state_store = SkillDistributionStateStore(tmp_path / "state-mode")
    _bootstrap(state_store)
    state_store.state_path.chmod(0o644)
    with pytest.raises(SkillDistributionStateError, match="unsafe"):
        state_store.load(now=NOW)

    key_store = SkillDistributionStateStore(tmp_path / "key-mode")
    _bootstrap(key_store)
    release = _verify(key_store, _metadata_fixture())
    key_store.issue_installed_proof(
        release,
        installed_tree_sha256=release.tree_sha256,
        now=NOW,
    )
    key_store.key_path.chmod(0o644)
    with pytest.raises(SkillDistributionStateError, match="unsafe"):
        key_store.issue_installed_proof(
            release,
            installed_tree_sha256=release.tree_sha256,
            now=NOW,
        )


def test_profile_paths_are_isolated(tmp_path) -> None:
    first = SkillDistributionStateStore(tmp_path / "one" / "trust")
    second = SkillDistributionStateStore(tmp_path / "two" / "trust")
    _bootstrap(first)
    _bootstrap(second)
    _verify(first, _metadata_fixture())

    assert first.load(now=NOW).trusted_versions.targets == 13
    assert second.load(now=NOW).trusted_versions.targets == 0
    assert os.path.commonpath([first.state_path, second.state_path]) == str(tmp_path)
