"""Fail-closed governance gates for quarantined skill promotion.

This module is deliberately outside the model-tool schema.  It operates only
on an already-staged, immutable pending batch and never executes a provider,
hook, command, or skill-authored code.  The caller supplies the virtual final
trees produced by :mod:`tools.skill_manager_tool`; each tree is materialized
under a private temporary directory without following redirects before the
contract validator, data-only evaluation runner, and authoritative security
scanner inspect it.

Ordinary foreground approval remains a legacy-compatible path.  These gates
apply only to the closed quarantined-origin set defined by
``tools.skill_provenance``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Sequence

from agent.skill_contract import (
    SkillContractValidation,
    source_freshness_blockers,
    validate_skill_directory,
)
from agent.skill_eval_runner import (
    SkillEvalInputError,
    SkillEvalReport,
    run_skill_evaluation,
)
from agent.skill_evals import validate_eval_manifest
from tools.skills_guard import scan_skill_attested


GOVERNANCE_SCHEMA_VERSION = 1
MAX_OBSERVATIONS_BYTES = 20 * 1024 * 1024
_DIGEST_RE = __import__("re").compile(r"^[0-9a-f]{64}$")


class SkillPromotionGateError(RuntimeError):
    """Stable fail-closed error raised before promotion can claim records."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class GovernedSkillCandidate:
    """One final non-deleted skill bound into review and eval receipts."""

    name: str
    candidate_digest: str
    contract_digest: str
    eval_manifest_digest: str
    eval_suite: str
    security_tree_digest: str
    permission_expansion: tuple[str, ...]


@dataclass(frozen=True)
class GovernedBatch:
    """Immutable governance projection for an exact pending batch."""

    batch_id: str
    batch_digest: str
    record_ids: tuple[str, ...]
    origin: str
    skills: tuple[GovernedSkillCandidate, ...]

    @property
    def digest(self) -> str:
        return canonical_digest(self.projection())

    def projection(self) -> dict[str, Any]:
        return {
            "schema_version": GOVERNANCE_SCHEMA_VERSION,
            "batch_id": self.batch_id,
            "batch_digest": self.batch_digest,
            "record_ids": list(self.record_ids),
            "origin": self.origin,
            "skills": [_candidate_projection(skill) for skill in self.skills],
        }


def canonical_digest(value: Any) -> str:
    """Return stable canonical-JSON SHA-256 for governance state."""

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def governed_origin(records: Sequence[Mapping[str, Any]]) -> str | None:
    """Return the exact quarantined origin, or ``None`` for foreground work.

    Provenance is an authority boundary.  Import/read failure and mixed-origin
    batches fail closed rather than downgrading a potentially quarantined
    write to foreground authority.
    """

    try:
        from tools.skill_provenance import QUARANTINED_SKILL_ORIGINS
    except Exception as exc:  # pragma: no cover - exercised via monkeypatch
        raise SkillPromotionGateError(
            "provenance_unavailable",
            f"Skill draft provenance is unavailable; promotion refused ({exc}).",
        ) from exc

    origins = {record.get("origin") for record in records}
    if not origins or any(not isinstance(origin, str) for origin in origins):
        raise SkillPromotionGateError(
            "provenance_invalid", "Skill draft provenance is missing or invalid."
        )
    if len(origins) != 1:
        raise SkillPromotionGateError(
            "provenance_mixed", "A pending skill batch may not mix write origins."
        )
    origin = next(iter(origins))
    if origin in QUARANTINED_SKILL_ORIGINS:
        return origin
    if origin not in {"foreground", "assistant_tool"}:
        raise SkillPromotionGateError(
            "provenance_unsupported", f"Unsupported skill draft origin {origin!r}."
        )
    return None


def virtual_tree_digest(entries: Mapping[str, Any]) -> str:
    """Digest a manager virtual tree using its exact durable tree contract."""

    digest = hashlib.sha256()
    for rel, entry in sorted(entries.items()):
        kind = getattr(entry, "kind", None)
        data = getattr(entry, "data", None)
        mode = getattr(entry, "mode", None)
        if not isinstance(rel, str) or not isinstance(kind, str):
            raise SkillPromotionGateError(
                "candidate_tree_invalid", "Skill candidate tree is malformed."
            )
        if not isinstance(data, bytes) or not isinstance(mode, int):
            raise SkillPromotionGateError(
                "candidate_tree_invalid", "Skill candidate tree is malformed."
            )
        for part in (
            rel.encode("utf-8"),
            kind.encode("ascii"),
            f"{mode:o}".encode("ascii"),
            data,
        ):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()


def analyze_governed_batch(
    *,
    batch_id: str,
    batch_digest: str,
    records: Sequence[Mapping[str, Any]],
    final_skills: Mapping[str, Any | None],
    current_skill_dirs: Mapping[str, Path | None],
    temporary_root: Path,
) -> GovernedBatch | None:
    """Validate and attest an exact final batch without mutating active state.

    Deleted final skills are intentionally absent from contract/eval/scan
    checks.  Thus a deletion-only governed batch remains reviewable, while
    every non-deleted final candidate must independently pass every gate.
    """

    origin = governed_origin(records)
    if origin is None:
        return None
    if not _DIGEST_RE.fullmatch(batch_digest):
        raise SkillPromotionGateError(
            "batch_digest_invalid", "Pending skill batch digest is invalid."
        )

    candidates: list[GovernedSkillCandidate] = []
    with materialized_final_skills(final_skills, temporary_root) as materialized:
        for name in sorted(final_skills):
            virtual = final_skills[name]
            if virtual is None:
                continue
            skill_dir = materialized[name]
            candidate_digest = virtual_tree_digest(getattr(virtual, "entries", {}))
            actual_digest = _capture_materialized_digest(skill_dir)
            if actual_digest != candidate_digest:
                raise SkillPromotionGateError(
                    "candidate_digest_mismatch",
                    f"Materialized candidate digest changed for skill {name!r}.",
                )

            validation = validate_skill_directory(skill_dir, require_contract=True)
            _require_valid_contract(name, validation)
            assert validation.contract is not None
            assert validation.digest is not None
            blockers = source_freshness_blockers(validation)
            if blockers:
                codes = ", ".join(sorted({issue.code for issue in blockers}))
                raise SkillPromotionGateError(
                    "source_expired",
                    f"Skill {name!r} has stale declared sources ({codes}); refresh them before promotion.",
                )

            eval_suite = validation.contract["evals"]["suite"]
            eval_validation = validate_eval_manifest(skill_dir, eval_suite)
            if (
                not eval_validation.ok
                or eval_validation.digest is None
                or eval_validation.manifest is None
            ):
                raise SkillPromotionGateError(
                    "eval_manifest_invalid",
                    f"Skill {name!r} has no valid deterministic evaluation manifest.",
                )

            try:
                scan = scan_skill_attested(
                    skill_dir,
                    source="agent-created",
                    respect_skillignore=False,
                )
            except Exception as exc:
                raise SkillPromotionGateError(
                    "security_scan_failed",
                    f"Authoritative security scan failed for skill {name!r}: {exc}",
                ) from exc
            result = scan.result
            if result.verdict != "safe" or result.findings:
                raise SkillPromotionGateError(
                    "security_scan_blocked",
                    f"Authoritative security scan blocked skill {name!r} ({result.verdict}, {len(result.findings)} finding(s)).",
                )
            # The scanner captures once. Re-read our private materialization
            # afterward using the manager's mode-sensitive digest so even a
            # buggy/mutating scanner cannot attest different bytes.
            if _capture_materialized_digest(skill_dir) != candidate_digest:
                raise SkillPromotionGateError(
                    "security_scan_candidate_changed",
                    f"Skill {name!r} changed during its security scan.",
                )

            before_validation = _validated_current_contract(
                name, current_skill_dirs.get(name)
            )
            expansion = permission_expansion_details(
                before_validation.contract if before_validation else None,
                validation.contract,
            )
            candidates.append(
                GovernedSkillCandidate(
                    name=name,
                    candidate_digest=candidate_digest,
                    contract_digest=validation.digest,
                    eval_manifest_digest=eval_validation.digest,
                    eval_suite=eval_suite,
                    security_tree_digest=result.attested_tree_sha256,
                    permission_expansion=expansion,
                )
            )

    return GovernedBatch(
        batch_id=batch_id,
        batch_digest=batch_digest,
        record_ids=tuple(str(record["id"]) for record in records),
        origin=origin,
        skills=tuple(candidates),
    )


def evaluate_governed_batch(
    batch: GovernedBatch,
    *,
    final_skills: Mapping[str, Any | None],
    temporary_root: Path,
    observations_path: Path,
) -> dict[str, Any]:
    """Run closed observations for every final skill and return an attestation.

    The observation file is never retained.  Single-skill batches accept the
    runner's native case-id mapping. Multi-skill batches require the closed
    envelope ``{"skills": {"name": <case observations>, ...}}``.
    """

    observations = load_observations_file(observations_path)
    skill_names = [candidate.name for candidate in batch.skills]
    if not skill_names:
        if observations not in ({}, {"skills": {}}):
            raise SkillPromotionGateError(
                "eval_observations_unexpected",
                "A deletion-only batch accepts only an empty observations object.",
            )
        per_skill: Mapping[str, Any] = {}
    elif len(skill_names) == 1 and "skills" not in observations:
        per_skill = {skill_names[0]: observations}
    else:
        if set(observations) != {"skills"} or type(observations.get("skills")) is not dict:
            raise SkillPromotionGateError(
                "eval_observations_envelope",
                "Multi-skill observations must use exactly {\"skills\": {<name>: <observations>}}.",
            )
        per_skill = observations["skills"]
    if set(per_skill) != set(skill_names):
        raise SkillPromotionGateError(
            "eval_observations_skill_set",
            "Observation skill names must exactly match the final governed skill set.",
        )

    reports: dict[str, dict[str, Any]] = {}
    with materialized_final_skills(final_skills, temporary_root) as materialized:
        for candidate in batch.skills:
            skill_dir = materialized[candidate.name]
            if _capture_materialized_digest(skill_dir) != candidate.candidate_digest:
                raise SkillPromotionGateError(
                    "candidate_digest_mismatch",
                    f"Candidate digest changed before evaluating skill {candidate.name!r}.",
                )
            try:
                report = run_skill_evaluation(
                    skill_dir,
                    candidate.eval_suite,
                    per_skill[candidate.name],
                )
            except SkillEvalInputError as exc:
                codes = ", ".join(issue.code for issue in exc.issues[:8])
                raise SkillPromotionGateError(
                    "eval_observations_invalid",
                    f"Evaluation observations are invalid for skill {candidate.name!r}: {codes}",
                ) from exc
            if report.manifest_digest != candidate.eval_manifest_digest:
                raise SkillPromotionGateError(
                    "eval_manifest_digest_mismatch",
                    f"Evaluation manifest changed for skill {candidate.name!r}.",
                )
            if not report.passed:
                reasons = ", ".join(report.failure_reasons) or "threshold"
                raise SkillPromotionGateError(
                    "eval_failed",
                    f"Deterministic evaluation failed for skill {candidate.name!r}: {reasons}.",
                )
            reports[candidate.name] = report_projection(report)

    return {
        "schema_version": GOVERNANCE_SCHEMA_VERSION,
        "batch_id": batch.batch_id,
        "batch_digest": batch.batch_digest,
        "governance_digest": batch.digest,
        "record_ids": list(batch.record_ids),
        "origin": batch.origin,
        "skills": [_candidate_projection(skill) for skill in batch.skills],
        "reports": reports,
    }


def report_projection(report: SkillEvalReport) -> dict[str, Any]:
    """Serialize a report without any observed output or event payloads."""

    return asdict(report)


def _candidate_projection(candidate: GovernedSkillCandidate) -> dict[str, Any]:
    value = asdict(candidate)
    value["permission_expansion"] = list(candidate.permission_expansion)
    return value


def load_observations_file(path: Path) -> dict[str, Any]:
    """Read one bounded, regular, non-symlink JSON observations file."""

    path = Path(path)
    try:
        before = path.lstat()
    except OSError as exc:
        raise SkillPromotionGateError(
            "eval_observations_read_failed", f"Could not inspect observations: {exc}"
        ) from exc
    if not stat.S_ISREG(before.st_mode) or path.is_symlink():
        raise SkillPromotionGateError(
            "eval_observations_unsafe", "Observations must be a regular non-symlink file."
        )
    if before.st_size > MAX_OBSERVATIONS_BYTES:
        raise SkillPromotionGateError(
            "eval_observations_too_large",
            f"Observations exceed {MAX_OBSERVATIONS_BYTES} bytes.",
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                or opened.st_size > MAX_OBSERVATIONS_BYTES
            ):
                raise SkillPromotionGateError(
                    "eval_observations_changed", "Observations changed while opening."
                )
            with os.fdopen(fd, "rb") as handle:
                fd = -1
                raw = handle.read(MAX_OBSERVATIONS_BYTES + 1)
        finally:
            if fd >= 0:
                os.close(fd)
    except SkillPromotionGateError:
        raise
    except OSError as exc:
        raise SkillPromotionGateError(
            "eval_observations_read_failed", f"Could not read observations JSON: {exc}"
        ) from exc
    if len(raw) > MAX_OBSERVATIONS_BYTES:
        raise SkillPromotionGateError(
            "eval_observations_too_large",
            f"Observations exceed {MAX_OBSERVATIONS_BYTES} bytes.",
        )
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_unique_json_object)
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise SkillPromotionGateError(
            "eval_observations_invalid_json", f"Could not parse observations JSON: {exc}"
        ) from exc
    if type(value) is not dict:
        raise SkillPromotionGateError(
            "eval_observations_type", "Observations JSON root must be an object."
        )
    return value


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key {key!r}")
        value[key] = item
    return value


def permission_expansion_details(
    before_contract: Mapping[str, Any] | None,
    after_contract: Mapping[str, Any],
) -> tuple[str, ...]:
    """Enumerate added authority scopes for exact human review.

    Prohibition declarations never count as requested authority. Added
    toolsets, file access bits, network methods, secrets, approval-scoped
    actions, and reversible actions do. Inputs are already strict validated;
    malformed prior state is conservatively treated as no verified authority.
    """

    before = _permissions(before_contract)
    after = _permissions(after_contract)
    expanded: set[str] = set()

    for field in ("toolsets_required", "secrets"):
        previous = _string_set(before.get(field))
        current = _string_set(after.get(field))
        for value in current - previous:
            expanded.add(f"permissions.{field}:+{value}")

    access_bits = {"read": 1, "write": 2, "read_write": 3}
    before_files = {
        item["scope"]: access_bits[item["access"]]
        for item in before.get("files", [])
        if isinstance(item, Mapping)
        and item.get("scope") in {"workspace", "skill", "temp"}
        and item.get("access") in access_bits
    }
    for item in after.get("files", []):
        scope = item["scope"]
        bits = access_bits[item["access"]]
        added = bits & ~before_files.get(scope, 0)
        if added & 1:
            expanded.add(f"permissions.files:{scope}:+read")
        if added & 2:
            expanded.add(f"permissions.files:{scope}:+write")

    before_network = {
        item["host"]: _string_set(item.get("methods"))
        for item in before.get("network", [])
        if isinstance(item, Mapping) and isinstance(item.get("host"), str)
    }
    for item in after.get("network", []):
        host = item["host"]
        for method in _string_set(item.get("methods")) - before_network.get(host, set()):
            expanded.add(f"permissions.network:{host}:+{method}")

    before_actions = before.get("actions") if isinstance(before.get("actions"), Mapping) else {}
    after_actions = after.get("actions") if isinstance(after.get("actions"), Mapping) else {}
    for field in ("approval_required", "reversible"):
        previous = _string_set(before_actions.get(field))
        current = _string_set(after_actions.get(field))
        for action in current - previous:
            expanded.add(f"permissions.actions.{field}:+{action}")
    return tuple(sorted(expanded))


def _permissions(contract: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(contract, Mapping):
        return {}
    value = contract.get("permissions")
    return value if isinstance(value, Mapping) else {}


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str)}


def _require_valid_contract(
    name: str, validation: SkillContractValidation
) -> None:
    if validation.ok and validation.status == "verified" and validation.digest:
        identity = validation.contract.get("identity") if validation.contract else None
        if isinstance(identity, Mapping) and identity.get("name") == name:
            return
    codes = ", ".join(issue.code for issue in validation.errors[:8])
    suffix = f" ({codes})" if codes else ""
    raise SkillPromotionGateError(
        "contract_invalid",
        f"Skill {name!r} requires a strict valid skill.contract.yaml{suffix}.",
    )


def _validated_current_contract(
    name: str, skill_dir: Path | None
) -> SkillContractValidation | None:
    if skill_dir is None:
        return None
    try:
        validation = validate_skill_directory(Path(skill_dir), require_contract=True)
    except Exception:
        return None
    if not validation.ok or validation.status != "verified" or not validation.contract:
        return None
    identity = validation.contract.get("identity")
    if not isinstance(identity, Mapping) or identity.get("name") != name:
        return None
    return validation


@contextmanager
def materialized_final_skills(
    final_skills: Mapping[str, Any | None], temporary_root: Path
) -> Iterator[dict[str, Path]]:
    """Materialize regular final trees beneath a private non-redirected root."""

    root = _safe_private_root(Path(temporary_root))
    work = Path(tempfile.mkdtemp(prefix="promotion-", dir=root))
    os.chmod(work, 0o700)
    materialized: dict[str, Path] = {}
    try:
        for index, name in enumerate(sorted(final_skills)):
            virtual = final_skills[name]
            if virtual is None:
                continue
            skill_dir = work / f"{index:04d}-{name}"
            os.mkdir(skill_dir, 0o700)
            _materialize_entries(skill_dir, getattr(virtual, "entries", {}))
            materialized[name] = skill_dir
        yield materialized
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _safe_private_root(root: Path) -> Path:
    parent = root.parent
    if not parent.exists() or parent.is_symlink() or not parent.is_dir():
        raise SkillPromotionGateError(
            "governance_store_unsafe", "Pending governance parent is unsafe."
        )
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise SkillPromotionGateError(
            "governance_store_unsafe", "Pending governance store is unsafe."
        )
    root.mkdir(mode=0o700, parents=False, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    if root.resolve(strict=True).parent != parent.resolve(strict=True):
        raise SkillPromotionGateError(
            "governance_store_redirected", "Pending governance store is redirected."
        )
    return root


def _canonical_relative_path(rel: str) -> PurePosixPath:
    if (
        not rel
        or "\\" in rel
        or rel.startswith("/")
        or any(part in {"", ".", ".."} for part in rel.split("/"))
    ):
        raise SkillPromotionGateError(
            "candidate_path_unsafe", f"Unsafe path in skill candidate: {rel!r}."
        )
    return PurePosixPath(rel)


def _materialize_entries(root: Path, entries: Mapping[str, Any]) -> None:
    if not isinstance(entries, Mapping) or "" not in entries:
        raise SkillPromotionGateError(
            "candidate_tree_invalid", "Skill candidate tree has no root entry."
        )
    root_entry = entries[""]
    if getattr(root_entry, "kind", None) != "directory":
        raise SkillPromotionGateError(
            "candidate_tree_invalid", "Skill candidate root is not a directory."
        )
    os.chmod(root, stat.S_IMODE(getattr(root_entry, "mode", 0)) or 0o700)
    items = sorted(
        ((rel, entry) for rel, entry in entries.items() if rel),
        key=lambda item: (len(PurePosixPath(item[0]).parts), item[0]),
    )
    for rel, entry in items:
        pure = _canonical_relative_path(rel)
        path = root.joinpath(*pure.parts)
        kind = getattr(entry, "kind", None)
        mode = getattr(entry, "mode", 0)
        if kind == "directory":
            try:
                os.mkdir(path, 0o700)
            except FileExistsError:
                if path.is_symlink() or not path.is_dir():
                    raise SkillPromotionGateError(
                        "candidate_path_collision", f"Unsafe candidate directory {rel!r}."
                    )
            os.chmod(path, stat.S_IMODE(mode) or 0o700)
            continue
        if kind != "file":
            # A governed candidate may not retain symlinks, junctions, FIFOs,
            # or devices. Legacy foreground skills remain unaffected.
            raise SkillPromotionGateError(
                "candidate_redirect",
                f"Governed skill candidate contains unsupported redirected entry {rel!r}.",
            )
        if not path.parent.is_dir() or path.parent.is_symlink():
            raise SkillPromotionGateError(
                "candidate_parent_unsafe", f"Unsafe parent for candidate file {rel!r}."
            )
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        fd = os.open(path, flags, 0o600)
        try:
            data = getattr(entry, "data", None)
            if not isinstance(data, bytes):
                raise SkillPromotionGateError(
                    "candidate_tree_invalid", f"Candidate file {rel!r} has invalid data."
                )
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(path, stat.S_IMODE(mode) or 0o600)
        finally:
            if fd >= 0:
                os.close(fd)


def _capture_materialized_digest(root: Path) -> str:
    """Capture the private tree without following any redirect."""

    entries: dict[str, _CapturedEntry] = {}
    root_info = root.lstat()
    if not stat.S_ISDIR(root_info.st_mode) or root.is_symlink():
        raise SkillPromotionGateError(
            "candidate_root_unsafe", "Materialized skill root is unsafe."
        )
    entries[""] = _CapturedEntry("directory", b"", stat.S_IMODE(root_info.st_mode))
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in list(directories):
            child = current_path / name
            info = child.lstat()
            rel = child.relative_to(root).as_posix()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise SkillPromotionGateError(
                    "candidate_redirect", f"Materialized candidate contains redirect {rel!r}."
                )
            entries[rel] = _CapturedEntry("directory", b"", stat.S_IMODE(info.st_mode))
        for name in files:
            child = current_path / name
            info = child.lstat()
            rel = child.relative_to(root).as_posix()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise SkillPromotionGateError(
                    "candidate_redirect", f"Materialized candidate contains redirect {rel!r}."
                )
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(child, flags)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise SkillPromotionGateError(
                        "candidate_changed", f"Candidate file changed while opening {rel!r}."
                    )
                with os.fdopen(fd, "rb") as handle:
                    fd = -1
                    data = handle.read()
            finally:
                if fd >= 0:
                    os.close(fd)
            entries[rel] = _CapturedEntry("file", data, stat.S_IMODE(info.st_mode))
    return virtual_tree_digest(entries)


@dataclass(frozen=True)
class _CapturedEntry:
    kind: str
    data: bytes
    mode: int


__all__ = [
    "GOVERNANCE_SCHEMA_VERSION",
    "GovernedBatch",
    "GovernedSkillCandidate",
    "MAX_OBSERVATIONS_BYTES",
    "SkillPromotionGateError",
    "analyze_governed_batch",
    "canonical_digest",
    "evaluate_governed_batch",
    "governed_origin",
    "load_observations_file",
    "permission_expansion_details",
    "virtual_tree_digest",
]
