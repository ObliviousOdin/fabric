"""Behavior contracts for Fabric's pure signed-skill distribution verifier."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent.skill_distribution import (
    DistributionErrorCode,
    OfflineGracePolicy,
    SkillDistributionError,
    TrustedRoot,
    TrustedVersions,
    VerifiedRelease,
    bind_verified_release_to_artifact,
    canonical_json_bytes,
    issue_installed_release_proof,
    load_trusted_root,
    rotate_trusted_root,
    verify_release,
)


NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
FRESH_ROOT_EXPIRY = "2026-08-14T12:00:00Z"
FRESH_METADATA_EXPIRY = "2026-07-21T12:00:00Z"
RECEIPT_KEY = b"r" * 32


def _private(seed: int) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes([seed]) * 32)


PRIVATE_KEYS = {
    name: _private(seed)
    for seed, name in enumerate(
        (
            "old-root-a",
            "old-root-b",
            "new-root-a",
            "new-root-b",
            "timestamp",
            "snapshot",
            "targets",
            "revocations",
            "outsider",
        ),
        start=1,
    )
}


def _key_object(name: str) -> dict[str, str]:
    public = (
        PRIVATE_KEYS[name]
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    return {
        "keytype": "ed25519",
        "scheme": "ed25519",
        "keyval": base64.b64encode(public).decode("ascii"),
    }


def _keyid(name: str) -> str:
    return hashlib.sha256(canonical_json_bytes(_key_object(name))).hexdigest()


def _envelope(signed: dict[str, Any], signers: tuple[str, ...]) -> bytes:
    payload = canonical_json_bytes(signed)
    signatures = [
        {
            "keyid": _keyid(name),
            "sig": base64.b64encode(PRIVATE_KEYS[name].sign(payload)).decode("ascii"),
        }
        for name in signers
    ]
    return canonical_json_bytes({"signed": signed, "signatures": signatures})


def _root_signed(
    *,
    version: int = 1,
    root_names: tuple[str, ...] = ("old-root-a", "old-root-b"),
    root_threshold: int = 2,
    expires: str = FRESH_ROOT_EXPIRY,
) -> dict[str, Any]:
    role_names = {
        "root": root_names,
        "timestamp": ("timestamp",),
        "snapshot": ("snapshot",),
        "targets": ("targets",),
        "revocations": ("revocations",),
    }
    all_names = set().union(*role_names.values())
    return {
        "_type": "root",
        "spec_version": "fabric-distribution-1",
        "version": version,
        "expires": expires,
        "keys": {_keyid(name): _key_object(name) for name in all_names},
        "roles": {
            role: {
                "keyids": [_keyid(name) for name in names],
                "threshold": root_threshold if role == "root" else 1,
            }
            for role, names in role_names.items()
        },
    }


def _root_bytes(
    *,
    version: int = 1,
    root_names: tuple[str, ...] = ("old-root-a", "old-root-b"),
    root_threshold: int = 2,
    signers: tuple[str, ...] | None = None,
    expires: str = FRESH_ROOT_EXPIRY,
) -> bytes:
    signed = _root_signed(
        version=version,
        root_names=root_names,
        root_threshold=root_threshold,
        expires=expires,
    )
    return _envelope(signed, signers if signers is not None else root_names)


def _load_root(raw: bytes, *, now: datetime = NOW, minimum_version: int = 0):
    return load_trusted_root(
        raw,
        now=now,
        trusted_sha256=hashlib.sha256(raw).hexdigest(),
        minimum_version=minimum_version,
    )


def _reference(raw: bytes, version: int) -> dict[str, Any]:
    return {
        "version": version,
        "length": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


@dataclass(frozen=True)
class MetadataFixture:
    root: TrustedRoot
    timestamp: bytes
    snapshot: bytes
    targets: bytes
    revocations: bytes


def _metadata_fixture(
    *,
    metadata_expires: str = FRESH_METADATA_EXPIRY,
    timestamp_expires: str | None = None,
    snapshot_expires: str | None = None,
    targets_expires: str | None = None,
    revocations_expires: str | None = None,
    versions: dict[str, int] | None = None,
    revocation_records: list[dict[str, Any]] | None = None,
    target_version: str = "1.2.3",
    channel: str = "stable",
    publisher: str = "Fabric Release Engineering",
    tree_sha256: str = "a" * 64,
    contract_sha256: str = "b" * 64,
    eval_sha256: str = "c" * 64,
    trusted_root: TrustedRoot | None = None,
    timestamp_signer: str = "timestamp",
    snapshot_signer: str = "snapshot",
    targets_signer: str = "targets",
    revocations_signer: str = "revocations",
) -> MetadataFixture:
    root = trusted_root or _load_root(_root_bytes())
    versions = versions or {
        "timestamp": 11,
        "snapshot": 12,
        "targets": 13,
        "revocations": 14,
    }
    targets_signed = {
        "_type": "targets",
        "spec_version": "fabric-distribution-1",
        "version": versions["targets"],
        "expires": targets_expires or metadata_expires,
        "targets": {
            f"software-development/demo@{target_version}": {
                "name": "software-development/demo",
                "version": target_version,
                "tree_sha256": tree_sha256,
                "contract_sha256": contract_sha256,
                "eval_sha256": eval_sha256,
                "channel": channel,
                "publisher": publisher,
            }
        },
    }
    targets_raw = _envelope(targets_signed, (targets_signer,))

    revocations_signed = {
        "_type": "revocations",
        "spec_version": "fabric-distribution-1",
        "version": versions["revocations"],
        "expires": revocations_expires or metadata_expires,
        "revocations": revocation_records or [],
    }
    revocations_raw = _envelope(revocations_signed, (revocations_signer,))

    snapshot_signed = {
        "_type": "snapshot",
        "spec_version": "fabric-distribution-1",
        "version": versions["snapshot"],
        "expires": snapshot_expires or metadata_expires,
        "meta": {
            "targets": _reference(targets_raw, versions["targets"]),
            "revocations": _reference(revocations_raw, versions["revocations"]),
        },
    }
    snapshot_raw = _envelope(snapshot_signed, (snapshot_signer,))

    timestamp_signed = {
        "_type": "timestamp",
        "spec_version": "fabric-distribution-1",
        "version": versions["timestamp"],
        "expires": timestamp_expires or metadata_expires,
        "snapshot": _reference(snapshot_raw, versions["snapshot"]),
    }
    timestamp_raw = _envelope(timestamp_signed, (timestamp_signer,))
    return MetadataFixture(
        root=root,
        timestamp=timestamp_raw,
        snapshot=snapshot_raw,
        targets=targets_raw,
        revocations=revocations_raw,
    )


def _verify(fixture: MetadataFixture, **overrides: Any):
    arguments = {
        "root": fixture.root,
        "timestamp": fixture.timestamp,
        "snapshot": fixture.snapshot,
        "targets": fixture.targets,
        "revocations": fixture.revocations,
        "name": "software-development/demo",
        "version": "1.2.3",
        "now": NOW,
        "prior_versions": TrustedVersions(),
    }
    arguments.update(overrides)
    return verify_release(**arguments)


def _grace_proof_args(release, *, measured_digest: str | None = None) -> dict[str, Any]:
    proof = issue_installed_release_proof(
        release,
        receipt_key=RECEIPT_KEY,
        installed_tree_sha256=release.tree_sha256,
    )
    return {
        "installed_proof": proof,
        "receipt_key": RECEIPT_KEY,
        "installed_tree_sha256": measured_digest or release.tree_sha256,
    }


def _assert_code(code: DistributionErrorCode, call) -> SkillDistributionError:
    with pytest.raises(SkillDistributionError) as exc_info:
        call()
    assert exc_info.value.code == code.value
    return exc_info.value


def _replace_envelope_signed(
    raw: bytes, mutate, *, signers: tuple[str, ...] | None = None
) -> bytes:
    envelope = json.loads(raw)
    mutate(envelope["signed"])
    if signers is None:
        return canonical_json_bytes(envelope)
    return _envelope(envelope["signed"], signers)


def test_canonical_json_bytes_are_deterministic_and_minimal() -> None:
    assert canonical_json_bytes({"z": [3, 2, 1], "a": "é"}) == (
        '{"a":"é","z":[3,2,1]}'.encode()
    )


def test_canonical_json_has_cross_language_escape_and_unicode_vectors() -> None:
    value = {"😀": "snowman ☃", "a": 'line\n"\\', "é": -7}
    assert canonical_json_bytes(value) == (
        '{"a":"line\\n\\"\\\\","é":-7,"😀":"snowman ☃"}'.encode()
    )
    _assert_code(
        DistributionErrorCode.NON_CANONICAL_JSON,
        lambda: canonical_json_bytes({"e\u0301": "decomposed key"}),
    )


def test_duplicate_keys_are_rejected_before_schema_validation() -> None:
    metadata = b'{"signatures":[],"signatures":[],"signed":{}}'
    _assert_code(
        DistributionErrorCode.DUPLICATE_KEY,
        lambda: _load_root(metadata),
    )


@pytest.mark.parametrize(
    ("metadata", "code"),
    [
        (_root_bytes() + b"\n", DistributionErrorCode.NON_CANONICAL_JSON),
        (
            b'{"signatures":[],"signed":{"value":1.5}}',
            DistributionErrorCode.INVALID_JSON,
        ),
    ],
)
def test_noncanonical_values_fail_closed(
    metadata: bytes, code: DistributionErrorCode
) -> None:
    _assert_code(code, lambda: _load_root(metadata))


def test_valid_chain_returns_exact_release_and_versions() -> None:
    fixture = _metadata_fixture()
    release = _verify(fixture)
    assert release.name == "software-development/demo"
    assert release.version == "1.2.3"
    assert release.tree_sha256 == "a" * 64
    assert release.contract_sha256 == "b" * 64
    assert release.eval_sha256 == "c" * 64
    assert release.channel == "stable"
    assert release.publisher == "Fabric Release Engineering"
    assert (release.root_version, release.timestamp_version) == (1, 11)
    assert (release.snapshot_version, release.targets_version) == (12, 13)
    assert release.revocations_version == 14
    assert release.revocation.revoked is False
    assert release.offline_grace_used is False


def test_verified_release_binds_exact_local_artifact_measurements() -> None:
    release = _verify(_metadata_fixture())
    bind_verified_release_to_artifact(
        release,
        name=release.name,
        tree_sha256=release.tree_sha256,
        contract_sha256=release.contract_sha256,
        eval_sha256=release.eval_sha256,
    )

    for field in ("tree_sha256", "contract_sha256", "eval_sha256"):
        values = {
            "name": release.name,
            "tree_sha256": release.tree_sha256,
            "contract_sha256": release.contract_sha256,
            "eval_sha256": release.eval_sha256,
        }
        values[field] = "f" * 64
        error = _assert_code(
            DistributionErrorCode.ARTIFACT_MISMATCH,
            lambda values=values: bind_verified_release_to_artifact(release, **values),
        )
        assert error.path == field

    _assert_code(
        DistributionErrorCode.ARTIFACT_MISMATCH,
        lambda: bind_verified_release_to_artifact(
            object(),
            name=release.name,
            tree_sha256=release.tree_sha256,
            contract_sha256=release.contract_sha256,
            eval_sha256=release.eval_sha256,
        ),
    )


@pytest.mark.parametrize("field", ["channel", "publisher"])
def test_signed_target_requires_distribution_identity(field: str) -> None:
    fixture = _metadata_fixture()
    altered = _replace_envelope_signed(
        fixture.targets,
        lambda signed: signed["targets"]["software-development/demo@1.2.3"].pop(field),
        signers=("targets",),
    )
    _assert_code(
        DistributionErrorCode.SCHEMA_ERROR,
        lambda: _verify(fixture, targets=altered),
    )


def test_signed_target_alteration_invalidates_signature() -> None:
    fixture = _metadata_fixture()
    altered = _replace_envelope_signed(
        fixture.targets,
        lambda signed: signed["targets"]["software-development/demo@1.2.3"].__setitem__(
            "tree_sha256", "d" * 64
        ),
    )
    _assert_code(
        DistributionErrorCode.INVALID_SIGNATURE,
        lambda: _verify(fixture, targets=altered),
    )


def test_resigned_target_alteration_breaks_snapshot_hash_binding() -> None:
    fixture = _metadata_fixture()
    altered = _replace_envelope_signed(
        fixture.targets,
        lambda signed: signed["targets"]["software-development/demo@1.2.3"].__setitem__(
            "tree_sha256", "d" * 64
        ),
        signers=("targets",),
    )
    _assert_code(
        DistributionErrorCode.METADATA_HASH_MISMATCH,
        lambda: _verify(fixture, targets=altered),
    )


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("version", DistributionErrorCode.METADATA_VERSION_MISMATCH),
        ("length", DistributionErrorCode.METADATA_LENGTH_MISMATCH),
        ("sha256", DistributionErrorCode.METADATA_HASH_MISMATCH),
    ],
)
def test_timestamp_reference_binds_snapshot_version_length_and_digest(
    field: str, code: DistributionErrorCode
) -> None:
    fixture = _metadata_fixture()

    def mutate(signed: dict[str, Any]) -> None:
        if field == "sha256":
            signed["snapshot"][field] = "f" * 64
        else:
            signed["snapshot"][field] += 1

    timestamp = _replace_envelope_signed(
        fixture.timestamp,
        mutate,
        signers=("timestamp",),
    )
    _assert_code(code, lambda: _verify(fixture, timestamp=timestamp))


def test_unknown_signature_key_is_rejected() -> None:
    fixture = _metadata_fixture()
    timestamp = _replace_envelope_signed(
        fixture.timestamp, lambda signed: None, signers=("outsider",)
    )
    _assert_code(
        DistributionErrorCode.UNKNOWN_KEY,
        lambda: _verify(fixture, timestamp=timestamp),
    )


def test_known_key_for_wrong_role_is_rejected() -> None:
    fixture = _metadata_fixture()
    timestamp = _replace_envelope_signed(
        fixture.timestamp, lambda signed: None, signers=("targets",)
    )
    _assert_code(
        DistributionErrorCode.UNAUTHORIZED_KEY,
        lambda: _verify(fixture, timestamp=timestamp),
    )


def test_root_threshold_counts_distinct_authorized_keys() -> None:
    root = _root_bytes(signers=("old-root-a",))
    _assert_code(
        DistributionErrorCode.THRESHOLD_NOT_MET,
        lambda: _load_root(root),
    )


def test_duplicate_signer_cannot_be_counted_twice_toward_threshold() -> None:
    root_value = json.loads(_root_bytes())
    root_value["signatures"][1] = copy_signature = dict(root_value["signatures"][0])
    assert copy_signature["keyid"] == root_value["signatures"][0]["keyid"]
    _assert_code(
        DistributionErrorCode.SCHEMA_ERROR,
        lambda: _load_root(canonical_json_bytes(root_value)),
    )


def test_root_rotation_requires_old_and_new_thresholds() -> None:
    current = _load_root(_root_bytes())
    candidate = _root_bytes(
        version=2,
        root_names=("new-root-a", "new-root-b"),
        signers=("old-root-a", "old-root-b", "new-root-a", "new-root-b"),
    )
    result = rotate_trusted_root(
        current, candidate, now=NOW, prior_versions=TrustedVersions()
    )
    rotated = result.root
    assert rotated.version == 2
    assert rotated.canonical_sha256 == hashlib.sha256(candidate).hexdigest()
    assert result.trusted_versions.root == 2


def test_verified_rotated_root_envelope_reloads_with_its_persisted_digest() -> None:
    """Old-threshold signatures remain valid envelope history after rotation.

    The new root no longer declares the old keys, so restart loading must
    ignore those extra signatures while still requiring the new threshold.
    """

    current = _load_root(_root_bytes())
    candidate = _root_bytes(
        version=2,
        root_names=("new-root-a", "new-root-b"),
        signers=("old-root-a", "old-root-b", "new-root-a", "new-root-b"),
    )
    rotated = rotate_trusted_root(
        current,
        candidate,
        now=NOW,
        prior_versions=TrustedVersions(),
    )

    reloaded = load_trusted_root(
        candidate,
        now=NOW,
        trusted_sha256=rotated.root.canonical_sha256,
        minimum_version=rotated.root.version,
    )
    assert reloaded.version == rotated.root.version == 2
    assert reloaded.canonical_sha256 == rotated.root.canonical_sha256


@pytest.mark.parametrize(
    "signers",
    [
        ("new-root-a", "new-root-b"),
        ("old-root-a", "old-root-b"),
    ],
)
def test_root_rotation_fails_if_either_threshold_is_missing(
    signers: tuple[str, ...],
) -> None:
    current = _load_root(_root_bytes())
    candidate = _root_bytes(
        version=2,
        root_names=("new-root-a", "new-root-b"),
        signers=signers,
    )
    _assert_code(
        DistributionErrorCode.THRESHOLD_NOT_MET,
        lambda: rotate_trusted_root(
            current, candidate, now=NOW, prior_versions=TrustedVersions()
        ),
    )


@pytest.mark.parametrize(
    ("version", "code"),
    [
        (1, DistributionErrorCode.ROOT_ROLLBACK),
        (3, DistributionErrorCode.ROOT_VERSION_GAP),
    ],
)
def test_root_rotation_rejects_rollback_and_version_gaps(
    version: int, code: DistributionErrorCode
) -> None:
    current = _load_root(_root_bytes())
    candidate = _root_bytes(
        version=version,
        root_names=("new-root-a", "new-root-b"),
        signers=("old-root-a", "old-root-b", "new-root-a", "new-root-b"),
    )
    _assert_code(
        code,
        lambda: rotate_trusted_root(
            current, candidate, now=NOW, prior_versions=TrustedVersions()
        ),
    )


def test_root_bootstrap_requires_the_out_of_band_digest_pin() -> None:
    root = _root_bytes()
    _assert_code(
        DistributionErrorCode.ROOT_PIN_MISMATCH,
        lambda: load_trusted_root(root, now=NOW, trusted_sha256="0" * 64),
    )
    _assert_code(
        DistributionErrorCode.SCHEMA_ERROR,
        lambda: load_trusted_root(root, now=NOW),
    )


def test_trust_objects_cannot_be_constructed_by_callers() -> None:
    _assert_code(DistributionErrorCode.SCHEMA_ERROR, lambda: TrustedRoot())
    _assert_code(DistributionErrorCode.SCHEMA_ERROR, lambda: VerifiedRelease())


def test_verification_and_rotation_require_persisted_rollback_state() -> None:
    fixture = _metadata_fixture()
    _assert_code(
        DistributionErrorCode.SCHEMA_ERROR,
        lambda: verify_release(
            root=fixture.root,
            timestamp=fixture.timestamp,
            snapshot=fixture.snapshot,
            targets=fixture.targets,
            revocations=fixture.revocations,
            name="software-development/demo",
            version="1.2.3",
            now=NOW,
        ),
    )
    candidate = _root_bytes(
        version=2,
        root_names=("new-root-a", "new-root-b"),
        signers=("old-root-a", "old-root-b", "new-root-a", "new-root-b"),
    )
    _assert_code(
        DistributionErrorCode.SCHEMA_ERROR,
        lambda: rotate_trusted_root(fixture.root, candidate, now=NOW),
    )


def test_expired_intermediate_root_can_rotate_to_a_fresh_final_root() -> None:
    current = _load_root(_root_bytes())
    expired_intermediate = _root_bytes(
        version=2,
        root_names=("new-root-a", "new-root-b"),
        signers=("old-root-a", "old-root-b", "new-root-a", "new-root-b"),
        expires="2026-07-14T11:59:59Z",
    )
    intermediate_result = rotate_trusted_root(
        current,
        expired_intermediate,
        now=NOW,
        prior_versions=TrustedVersions(),
    )
    final = _root_bytes(
        version=3,
        root_names=("new-root-a", "new-root-b"),
        signers=("new-root-a", "new-root-b"),
    )
    rotated = rotate_trusted_root(
        intermediate_result.root,
        final,
        now=NOW,
        prior_versions=intermediate_result.trusted_versions,
    )
    assert rotated.root.version == 3
    assert rotated.root.expires > NOW


def test_nonroot_key_rotation_resets_fast_forwarded_downstream_state() -> None:
    current = _load_root(_root_bytes())
    prior = _verify(_metadata_fixture()).trusted_versions
    fast_forwarded = replace(
        prior,
        timestamp=2**63 - 1,
        snapshot=2**63 - 1,
        targets=2**63 - 1,
        revocations=2**63 - 1,
    )

    candidate_signed = _root_signed(version=2)
    for name in ("new-root-a", "new-root-b"):
        candidate_signed["keys"][_keyid(name)] = _key_object(name)
    candidate_signed["roles"]["timestamp"] = {
        "keyids": [_keyid("new-root-a")],
        "threshold": 1,
    }
    candidate_signed["roles"]["snapshot"] = {
        "keyids": [_keyid("new-root-b")],
        "threshold": 1,
    }
    candidate = _envelope(candidate_signed, ("old-root-a", "old-root-b"))
    rotation = rotate_trusted_root(
        current, candidate, now=NOW, prior_versions=fast_forwarded
    )

    reconciled = rotation.trusted_versions
    assert reconciled.root == 2
    assert (reconciled.timestamp, reconciled.snapshot) == (0, 0)
    assert (reconciled.targets, reconciled.revocations) == (0, 0)

    # Simulate restart: reload only the pinned root bytes and the atomic state
    # returned by rotation. Transition-only in-memory flags are not required.
    reloaded = _load_root(candidate, minimum_version=2)
    new_fixture = _metadata_fixture(
        trusted_root=reloaded,
        timestamp_signer="new-root-a",
        snapshot_signer="new-root-b",
    )
    release = _verify(new_fixture, prior_versions=reconciled)
    assert release.root_version == 2
    # Rotation invalidations are consumed once the new root state is trusted.
    assert (
        _verify(new_fixture, prior_versions=release.trusted_versions).timestamp_version
        == 11
    )


def test_expired_pinned_root_loads_for_rotation_but_blocks_release() -> None:
    root_raw = _root_bytes(expires="2026-07-14T11:59:59Z")
    root = _load_root(root_raw)
    fixture = replace(_metadata_fixture(), root=root)
    _assert_code(
        DistributionErrorCode.METADATA_EXPIRED,
        lambda: _verify(fixture),
    )


def test_expired_timestamp_is_a_freeze_for_new_install() -> None:
    fixture = _metadata_fixture(timestamp_expires="2026-07-14T11:59:59Z")
    _assert_code(DistributionErrorCode.METADATA_FREEZE, lambda: _verify(fixture))


def test_expired_non_timestamp_metadata_blocks_new_install() -> None:
    fixture = _metadata_fixture(targets_expires="2026-07-14T11:59:59Z")
    _assert_code(DistributionErrorCode.METADATA_EXPIRED, lambda: _verify(fixture))


@pytest.mark.parametrize("role", ["timestamp", "snapshot", "targets", "revocations"])
def test_caller_trusted_versions_block_metadata_rollback(role: str) -> None:
    fixture = _metadata_fixture()
    baseline = _verify(fixture).trusted_versions
    prior = replace(baseline, **{role: getattr(baseline, role) + 1})
    _assert_code(
        DistributionErrorCode.METADATA_ROLLBACK,
        lambda: _verify(fixture, prior_versions=prior),
    )


def test_caller_trusted_root_version_blocks_root_rollback() -> None:
    fixture = _metadata_fixture()
    baseline = _verify(fixture).trusted_versions
    prior = replace(baseline, root=2)
    _assert_code(
        DistributionErrorCode.ROOT_ROLLBACK,
        lambda: _verify(fixture, prior_versions=prior),
    )


def test_same_version_changed_metadata_is_rejected_as_equivocation() -> None:
    first_fixture = _metadata_fixture()
    first = _verify(first_fixture)
    changed_same_versions = _metadata_fixture(publisher="Different Publisher")
    _assert_code(
        DistributionErrorCode.METADATA_EQUIVOCATION,
        lambda: _verify(
            changed_same_versions,
            prior_versions=first.trusted_versions,
        ),
    )


def test_version_only_rollback_state_is_rejected() -> None:
    _assert_code(
        DistributionErrorCode.SCHEMA_ERROR,
        lambda: TrustedVersions(root=1),
    )


@pytest.mark.parametrize(
    "record",
    [
        {
            "kind": "name_version",
            "name": "software-development/demo",
            "version": "1.2.3",
            "reason": "known unsafe release",
        },
        {"kind": "digest", "sha256": "a" * 64, "reason": "compromised tree"},
        {
            "kind": "minimum_safe_version",
            "name": "software-development/demo",
            "version": "1.2.4",
            "reason": "upgrade required",
        },
    ],
)
def test_signed_revocation_rules_block_release(record: dict[str, Any]) -> None:
    fixture = _metadata_fixture(revocation_records=[record])
    error = _assert_code(DistributionErrorCode.TARGET_REVOKED, lambda: _verify(fixture))
    assert error.revocation is not None
    assert error.revocation.revoked is True
    assert error.revocation.matched_by == record["kind"]


def test_minimum_safe_version_at_or_below_release_is_non_revoking() -> None:
    fixture = _metadata_fixture(
        revocation_records=[
            {
                "kind": "minimum_safe_version",
                "name": "software-development/demo",
                "version": "1.2.3",
            }
        ]
    )
    release = _verify(fixture)
    assert release.revocation.revoked is False
    assert release.revocation.minimum_safe_version == "1.2.3"


@pytest.mark.parametrize(
    ("target_version", "minimum_version", "revoked"),
    [
        ("1.0.0-beta.11", "1.0.0-rc.1", True),
        ("1.0.0-rc.1", "1.0.0-beta.11", False),
        ("1.0.0+build.1", "1.0.0+build.2", False),
    ],
)
def test_minimum_safe_version_uses_semver_precedence(
    target_version: str, minimum_version: str, revoked: bool
) -> None:
    fixture = _metadata_fixture(
        target_version=target_version,
        revocation_records=[
            {
                "kind": "minimum_safe_version",
                "name": "software-development/demo",
                "version": minimum_version,
            }
        ],
    )
    if revoked:
        _assert_code(
            DistributionErrorCode.TARGET_REVOKED,
            lambda: _verify(fixture, version=target_version),
        )
    else:
        release = _verify(fixture, version=target_version)
        assert release.revocation.revoked is False


def test_highest_minimum_safe_version_wins_independent_of_record_order() -> None:
    fixture = _metadata_fixture(
        target_version="1.5.0",
        revocation_records=[
            {
                "kind": "minimum_safe_version",
                "name": "software-development/demo",
                "version": "2.0.0",
                "reason": "highest floor",
            },
            {
                "kind": "minimum_safe_version",
                "name": "software-development/demo",
                "version": "1.4.0",
                "reason": "lower floor",
            },
        ],
    )
    error = _assert_code(
        DistributionErrorCode.TARGET_REVOKED,
        lambda: _verify(fixture, version="1.5.0"),
    )
    assert error.revocation is not None
    assert error.revocation.minimum_safe_version == "2.0.0"
    assert error.revocation.reason == "highest floor"


def test_revocations_require_the_dedicated_role_key() -> None:
    fixture = _metadata_fixture()
    revocations = _replace_envelope_signed(
        fixture.revocations, lambda signed: None, signers=("targets",)
    )
    _assert_code(
        DistributionErrorCode.UNAUTHORIZED_KEY,
        lambda: _verify(fixture, revocations=revocations),
    )


def test_offline_grace_allows_only_exact_previously_verified_install() -> None:
    fixture = _metadata_fixture(metadata_expires="2026-07-14T13:00:00Z")
    installed = _verify(fixture)
    release = _verify(
        fixture,
        now=NOW + timedelta(hours=2),
        offline_grace=OfflineGracePolicy(timedelta(hours=3)),
        **_grace_proof_args(installed),
    )
    assert release.offline_grace_used is True
    assert release.stale_roles == ("timestamp", "snapshot", "targets", "revocations")


def test_stale_metadata_blocks_new_install_even_when_offline() -> None:
    fixture = _metadata_fixture(metadata_expires="2026-07-14T13:00:00Z")
    _assert_code(
        DistributionErrorCode.METADATA_FREEZE,
        lambda: _verify(fixture, now=NOW + timedelta(hours=2)),
    )


def test_offline_grace_rejects_mismatched_install_receipt() -> None:
    fixture = _metadata_fixture(metadata_expires="2026-07-14T13:00:00Z")
    installed = _verify(fixture)
    _assert_code(
        DistributionErrorCode.OFFLINE_GRACE_DENIED,
        lambda: _verify(
            fixture,
            now=NOW + timedelta(hours=2),
            offline_grace=OfflineGracePolicy(timedelta(hours=3)),
            **_grace_proof_args(installed, measured_digest="f" * 64),
        ),
    )


def test_offline_grace_is_bounded() -> None:
    fixture = _metadata_fixture(metadata_expires="2026-07-14T13:00:00Z")
    installed = _verify(fixture)
    _assert_code(
        DistributionErrorCode.OFFLINE_GRACE_DENIED,
        lambda: _verify(
            fixture,
            now=NOW + timedelta(hours=5),
            offline_grace=OfflineGracePolicy(timedelta(hours=3)),
            **_grace_proof_args(installed),
        ),
    )


def test_revocation_cannot_be_bypassed_by_offline_grace() -> None:
    clean = _metadata_fixture(metadata_expires="2026-07-14T13:00:00Z")
    installed = _verify(clean)
    revoked = _metadata_fixture(
        metadata_expires="2026-07-14T13:00:00Z",
        revocation_records=[{"kind": "digest", "sha256": "a" * 64}],
    )
    _assert_code(
        DistributionErrorCode.TARGET_REVOKED,
        lambda: _verify(
            revoked,
            now=NOW + timedelta(hours=2),
            offline_grace=OfflineGracePolicy(timedelta(hours=3)),
            **_grace_proof_args(installed),
        ),
    )


def test_offline_proof_is_hmac_authenticated() -> None:
    fixture = _metadata_fixture(metadata_expires="2026-07-14T13:00:00Z")
    installed = _verify(fixture)
    arguments = _grace_proof_args(installed)
    tampered = json.loads(arguments["installed_proof"])
    tampered["payload"]["release"]["publisher"] = "Injected Publisher"
    arguments["installed_proof"] = canonical_json_bytes(tampered)
    _assert_code(
        DistributionErrorCode.INSTALL_PROOF_INVALID,
        lambda: _verify(
            fixture,
            now=NOW + timedelta(hours=2),
            offline_grace=OfflineGracePolicy(timedelta(hours=3)),
            **arguments,
        ),
    )


def test_offline_proof_binds_channel_publisher_and_current_tree_measurement() -> None:
    installed_fixture = _metadata_fixture(
        metadata_expires="2026-07-14T13:00:00Z",
        channel="stable",
        publisher="Publisher A",
    )
    installed = _verify(installed_fixture)
    changed_identity = _metadata_fixture(
        metadata_expires="2026-07-14T13:00:00Z",
        channel="beta",
        publisher="Publisher B",
    )
    _assert_code(
        DistributionErrorCode.OFFLINE_GRACE_DENIED,
        lambda: _verify(
            changed_identity,
            now=NOW + timedelta(hours=2),
            offline_grace=OfflineGracePolicy(timedelta(hours=3)),
            **_grace_proof_args(installed),
        ),
    )


def test_offline_proof_binds_exact_signed_metadata_trust_state() -> None:
    installed_fixture = _metadata_fixture(
        metadata_expires="2026-07-14T13:00:00Z",
    )
    installed = _verify(installed_fixture)
    different_trust_state = _metadata_fixture(
        metadata_expires="2026-07-14T13:00:00Z",
        versions={
            "timestamp": 21,
            "snapshot": 22,
            "targets": 23,
            "revocations": 24,
        },
    )

    _assert_code(
        DistributionErrorCode.OFFLINE_GRACE_DENIED,
        lambda: _verify(
            different_trust_state,
            now=NOW + timedelta(hours=2),
            offline_grace=OfflineGracePolicy(timedelta(hours=3)),
            **_grace_proof_args(installed),
        ),
    )


def test_offline_proof_requires_complete_inputs_and_a_32_byte_key() -> None:
    fixture = _metadata_fixture()
    release = _verify(fixture)
    _assert_code(
        DistributionErrorCode.SCHEMA_ERROR,
        lambda: issue_installed_release_proof(
            release,
            receipt_key=b"short",
            installed_tree_sha256=release.tree_sha256,
        ),
    )
    proof = issue_installed_release_proof(
        release,
        receipt_key=RECEIPT_KEY,
        installed_tree_sha256=release.tree_sha256,
    )
    _assert_code(
        DistributionErrorCode.SCHEMA_ERROR,
        lambda: _verify(fixture, installed_proof=proof),
    )


def test_offline_grace_has_a_hard_safety_cap() -> None:
    _assert_code(
        DistributionErrorCode.SCHEMA_ERROR,
        lambda: OfflineGracePolicy(timedelta(days=31)),
    )


def test_malformed_base64_and_unknown_fields_fail_closed() -> None:
    root_value = json.loads(_root_bytes())
    root_value["signatures"][0]["sig"] = "!not-base64!"
    _assert_code(
        DistributionErrorCode.MALFORMED_BASE64,
        lambda: _load_root(canonical_json_bytes(root_value)),
    )

    root_value = json.loads(_root_bytes())
    root_value["signed"]["surprise"] = True
    _assert_code(
        DistributionErrorCode.SCHEMA_ERROR,
        lambda: _load_root(canonical_json_bytes(root_value)),
    )


def test_metadata_size_bound_is_checked_before_parsing() -> None:
    oversized = b" " * (2 * 1024 * 1024 + 1)
    _assert_code(
        DistributionErrorCode.METADATA_TOO_LARGE,
        lambda: _load_root(oversized),
    )


@pytest.mark.parametrize(
    "malformed",
    [
        b"[" * 2_000 + b"0" + b"]" * 2_000,
        b'{"signatures":[],"signed":{"value":"\\ud800"}}',
    ],
)
def test_pathological_json_is_normalized_to_a_distribution_error(
    malformed: bytes,
) -> None:
    error = _assert_code(
        DistributionErrorCode.INVALID_JSON,
        lambda: _load_root(malformed),
    )
    assert not isinstance(error.__cause__, (RecursionError, UnicodeEncodeError))


def test_unknown_algorithm_and_key_id_mismatch_fail_closed() -> None:
    signed = _root_signed()
    keyid = next(iter(signed["keys"]))
    signed["keys"][keyid]["scheme"] = "ed25519ph"
    _assert_code(
        DistributionErrorCode.UNSUPPORTED_ALGORITHM,
        lambda: _load_root(_envelope(signed, ("old-root-a", "old-root-b"))),
    )

    signed = _root_signed()
    original_keyid = next(iter(signed["keys"]))
    key = signed["keys"].pop(original_keyid)
    signed["keys"]["f" * 64] = key
    for role in signed["roles"].values():
        role["keyids"] = [
            "f" * 64 if item == original_keyid else item for item in role["keyids"]
        ]
    _assert_code(
        DistributionErrorCode.KEY_ID_MISMATCH,
        lambda: _load_root(_envelope(signed, ("old-root-a", "old-root-b"))),
    )


def test_target_lookup_requires_exact_semver() -> None:
    fixture = _metadata_fixture()
    _assert_code(
        DistributionErrorCode.SCHEMA_ERROR,
        lambda: _verify(fixture, version="1.2"),
    )
    _assert_code(
        DistributionErrorCode.TARGET_NOT_FOUND,
        lambda: _verify(fixture, version="1.2.4"),
    )


def test_prior_equal_versions_are_valid_for_cached_offline_verification() -> None:
    fixture = _metadata_fixture()
    first = _verify(fixture)
    release = _verify(fixture, prior_versions=first.trusted_versions)
    assert release.version == "1.2.3"
