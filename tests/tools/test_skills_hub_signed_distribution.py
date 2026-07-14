"""Signed-release binding at the existing transactional Hub boundary."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.skill_contract import validate_skill_directory
from agent.skill_distribution_policy import DistributionPolicy, ENFORCE_ALL
from agent.skill_distribution_state import SkillDistributionStateStore
from agent.skill_evals import validate_eval_manifest
from tests.agent.test_skill_distribution import (
    NOW,
    _metadata_fixture,
    _root_bytes,
    _verify,
)
from tools.skills_guard import scan_skill
from tools.skills_hub import (
    HubInstallError,
    HubLockFile,
    SkillBundle,
    install_from_quarantine,
    quarantine_bundle,
)


@contextmanager
def _hub_paths(tmp_path: Path):
    import tools.skills_hub as hub

    skills = tmp_path / "skills"
    root = skills / ".hub"
    values = {
        "SKILLS_DIR": skills,
        "HUB_DIR": root,
        "LOCK_FILE": root / "lock.json",
        "QUARANTINE_DIR": root / "quarantine",
        "AUDIT_LOG": root / "audit.log",
        "TAPS_FILE": root / "taps.json",
        "INDEX_CACHE_DIR": root / "index-cache",
    }
    with ExitStack() as stack:
        for name, value in values.items():
            stack.enter_context(patch.object(hub, name, value))
        yield skills


def _governed_bundle() -> SkillBundle:
    source = Path("skills/software-development/fabric-agent-skill-authoring")
    return SkillBundle(
        name="fabric-agent-skill-authoring",
        source="github",
        identifier="fabric/skills/fabric-agent-skill-authoring",
        trust_level="community",
        files={
            "SKILL.md": (source / "SKILL.md").read_text(encoding="utf-8"),
            "skill.contract.yaml": (source / "skill.contract.yaml").read_text(
                encoding="utf-8"
            ),
            "evals/cases.yaml": (source / "evals/cases.yaml").read_text(
                encoding="utf-8"
            ),
        },
    )


def _release_for_quarantine(quarantine: Path):
    scan = scan_skill(quarantine, source="github")
    contract = validate_skill_directory(quarantine, require_contract=True)
    assert contract.ok and contract.digest and contract.contract
    evals = validate_eval_manifest(
        quarantine,
        contract.contract["evals"]["suite"],
    )
    assert evals.ok and evals.digest
    fixture = _metadata_fixture(
        tree_sha256=scan.attested_tree_sha256,
        contract_sha256=contract.digest,
        eval_sha256=evals.digest,
    )
    return scan, fixture


def _advance_release(store: SkillDistributionStateStore, fixture):
    return store.verify_and_advance(
        timestamp=fixture.timestamp,
        snapshot=fixture.snapshot,
        targets=fixture.targets,
        revocations=fixture.revocations,
        name="software-development/demo",
        version="1.2.3",
        now=NOW,
    )


def _proof_store(path: Path) -> SkillDistributionStateStore:
    import hashlib

    store = SkillDistributionStateStore(path)
    root = _root_bytes()
    store.bootstrap(
        root,
        trusted_sha256=hashlib.sha256(root).hexdigest(),
        now=NOW,
    )
    return store


def test_verified_release_is_bound_and_recorded_in_atomic_lock_state(tmp_path) -> None:
    with _hub_paths(tmp_path) as skills:
        bundle = _governed_bundle()
        quarantine = quarantine_bundle(bundle)
        store = _proof_store(tmp_path / "trust")
        scan, fixture = _release_for_quarantine(quarantine)
        release = _advance_release(store, fixture)

        outcome = install_from_quarantine(
            quarantine,
            bundle.name,
            "software-development",
            bundle,
            scan,
            verified_release=release,
            distribution_name=release.name,
            distribution_store=store,
        )

        assert outcome.committed is True
        assert outcome.install_path == skills / "software-development" / bundle.name
        locked = HubLockFile().get_installed(bundle.name)
        signed = locked["metadata"]["signed_release"]
        assert signed["name"] == release.name
        assert signed["version"] == release.version
        assert signed["tree_sha256"] == release.tree_sha256
        assert signed["publisher"] == release.publisher
        assert signed["offline_grace_used"] is False
        assert signed["installed_proof"].startswith('{"hmac_sha256"')
        assert store.key_path.read_bytes() not in HubLockFile().path.read_bytes()


def test_verified_release_requires_the_exact_advanced_trust_store(tmp_path) -> None:
    with _hub_paths(tmp_path) as skills:
        bundle = _governed_bundle()
        quarantine = quarantine_bundle(bundle)
        scan, fixture = _release_for_quarantine(quarantine)
        release = _verify(fixture)
        unadvanced_store = _proof_store(tmp_path / "unadvanced-trust")

        with pytest.raises(
            HubInstallError,
            match="authenticated installed-release proof",
        ):
            install_from_quarantine(
                quarantine,
                bundle.name,
                "software-development",
                bundle,
                scan,
                verified_release=release,
                distribution_name=release.name,
                distribution_store=unadvanced_store,
            )
        assert not (skills / "software-development" / bundle.name).exists()
        assert not unadvanced_store.key_path.exists()


def test_verified_release_digest_mismatch_blocks_before_install_transaction(
    tmp_path,
) -> None:
    with _hub_paths(tmp_path) as skills:
        bundle = _governed_bundle()
        quarantine = quarantine_bundle(bundle)
        scan, _fixture = _release_for_quarantine(quarantine)
        wrong_release = _verify(_metadata_fixture())
        store = _proof_store(tmp_path / "trust")

        with pytest.raises(HubInstallError, match="artifact_mismatch"):
            install_from_quarantine(
                quarantine,
                bundle.name,
                "software-development",
                bundle,
                scan,
                verified_release=wrong_release,
                distribution_name=wrong_release.name,
                distribution_store=store,
            )
        assert not (skills / "software-development" / bundle.name).exists()


def test_verified_release_requires_contract_eval_and_explicit_distribution_name(
    tmp_path,
) -> None:
    with _hub_paths(tmp_path):
        bundle = _governed_bundle()
        quarantine = quarantine_bundle(bundle)
        scan, fixture = _release_for_quarantine(quarantine)
        release = _verify(fixture)
        store = _proof_store(tmp_path / "trust")
        with pytest.raises(HubInstallError, match="canonical distribution name"):
            install_from_quarantine(
                quarantine,
                bundle.name,
                "",
                bundle,
                scan,
                verified_release=release,
                distribution_store=store,
            )

    with _hub_paths(tmp_path / "missing"):
        bundle = SkillBundle(
            name="unsigned-shape",
            source="github",
            identifier="fabric/unsigned-shape",
            trust_level="community",
            files={"SKILL.md": "---\nname: unsigned-shape\ndescription: demo\n---\n"},
        )
        quarantine = quarantine_bundle(bundle)
        scan = scan_skill(quarantine, source="github")
        release = _verify(_metadata_fixture())
        store = _proof_store(tmp_path / "missing-trust")
        with pytest.raises(HubInstallError, match="no valid contract"):
            install_from_quarantine(
                quarantine,
                bundle.name,
                "",
                bundle,
                scan,
                verified_release=release,
                distribution_name=release.name,
                distribution_store=store,
            )


def test_enforce_all_blocks_unsigned_hub_install_while_observe_remains_compatible(
    tmp_path,
) -> None:
    with _hub_paths(tmp_path) as skills:
        bundle = SkillBundle(
            name="plain-skill",
            source="github",
            identifier="fabric/plain-skill",
            trust_level="community",
            files={"SKILL.md": "# Plain\n"},
        )
        quarantine = quarantine_bundle(bundle)
        scan = scan_skill(quarantine, source="github")
        with patch(
            "agent.skill_distribution_policy.load_distribution_policy",
            return_value=DistributionPolicy(ENFORCE_ALL),
        ):
            with pytest.raises(HubInstallError, match="unsigned Hub install"):
                install_from_quarantine(
                    quarantine,
                    bundle.name,
                    "",
                    bundle,
                    scan,
                )
        assert not (skills / bundle.name).exists()

        # Default observe mode preserves legacy/community installs.
        outcome = install_from_quarantine(
            quarantine,
            bundle.name,
            "",
            bundle,
            scan,
        )
        assert outcome.committed is True
