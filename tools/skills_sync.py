#!/usr/bin/env python3
"""
Skills Sync -- Manifest-based seeding and updating of bundled skills.

Copies bundled skills from the repo's skills/ directory into ~/.hermes/skills/
and uses a manifest to track which skills have been synced and their origin hash.

Manifest format (v2): each line is "skill_name:origin_hash" where origin_hash
is the MD5 of the bundled skill at the time it was last synced to the user dir.
Old v1 manifests (plain names without hashes) are auto-migrated.

Update logic:
  - NEW skills (not in manifest): copied to user dir, origin hash recorded.
  - EXISTING skills (in manifest, present in user dir):
      * If user copy matches origin hash: user hasn't modified it → safe to
        update from bundled if bundled changed. New origin hash recorded.
      * If user copy differs from origin hash: user customized it → SKIP.
  - DELETED by user (in manifest, absent from user dir): respected, not re-added.
  - REMOVED from bundled (in manifest, gone from repo): cleaned from manifest.

The manifest lives at ~/.hermes/skills/.bundled_manifest.
"""

import hashlib
import logging
import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from fabric_constants import get_bundled_skills_dir, get_fabric_home, get_optional_skills_dir
from agent.skill_utils import is_excluded_skill_path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


FABRIC_HOME = get_fabric_home()
SKILLS_DIR = FABRIC_HOME / "skills"
MANIFEST_FILE = SKILLS_DIR / ".bundled_manifest"

# Marker file written by `fabric profile create --no-skills` (named profiles)
# and by the installer's `--no-skills` flag (the default ~/.fabric profile).
# When present in FABRIC_HOME, sync_skills() is a no-op so neither the
# installer, `fabric update`, nor a direct sync re-injects bundled skills.
# Delete the file to opt back in. Mirrors
# fabric_cli.profiles.NO_BUNDLED_SKILLS_MARKER (kept as a literal here to
# avoid importing the CLI layer into this low-level sync module).
NO_BUNDLED_SKILLS_MARKER = ".no-bundled-skills"


def _get_bundled_dir() -> Path:
    """Locate the immutable distribution-owned bundled skills directory."""
    return get_bundled_skills_dir(Path(__file__).parent.parent / "skills")


def _get_optional_dir() -> Path:
    """Locate the official optional-skills/ directory."""
    return get_optional_skills_dir(Path(__file__).parent.parent / "optional-skills")


def _build_external_skill_index() -> Set[str]:
    """Index every skill available in external_dirs by name and frontmatter name.

    Returns a set of skill names that are already provided by external dirs.
    Used to prevent sync_skills from shadowing externally-delegated skills.
    """
    try:
        from agent.skill_utils import get_external_skills_dirs, _external_dirs_cache_clear
    except ImportError:
        return set()

    # Clear the external dirs cache so a config edit (or a test patch) is seen.
    _external_dirs_cache_clear()

    external_names: Set[str] = set()
    for ext_dir in get_external_skills_dirs():
        for skill_md in ext_dir.rglob("SKILL.md"):
            if is_excluded_skill_path(skill_md):
                continue
            skill_dir = skill_md.parent
            # Index by directory name (how _find_skill resolves skills)
            external_names.add(skill_dir.name)
            # Also index by frontmatter name (alternate identifier)
            frontmatter_name = _read_skill_name(skill_md, "")
            if frontmatter_name:
                external_names.add(frontmatter_name)
    return external_names


def _read_manifest_locked() -> Dict[str, str]:
    """
    Read the manifest as a dict of {skill_name: origin_hash}.

    Handles both v1 (plain names) and v2 (name:hash) formats.
    v1 entries get an empty hash string which triggers migration on next sync.
    """
    from tools.skills_hub import _read_bounded_regular_file

    if not _profile_exists(MANIFEST_FILE):
        return {}
    payload, _state = _read_bounded_regular_file(
        MANIFEST_FILE,
        max_bytes=4 * 1024 * 1024,
        require_unique=True,
    )
    text = payload.decode("utf-8")
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            # v2 format: name:hash
            name, _, hash_val = line.partition(":")
            result[name.strip()] = hash_val.strip()
        else:
            # v1 format: plain name — empty hash triggers migration
            result[line] = ""
    return result


def _read_manifest() -> Dict[str, str]:
    """Read manifest while pinned to the profile generation it belongs to."""

    with _skills_mutation_scope(
        MANIFEST_FILE.parent.parent,
        skills_dir=MANIFEST_FILE.parent,
    ):
        return _read_manifest_locked()


def _read_suppressed_names() -> set:
    """Built-in skills the curator pruned — must NOT be re-seeded on sync.

    Delegates to ``tools.skill_usage`` (single source of truth) and falls back
    to reading ``~/.hermes/skills/.curator_suppressed`` directly if that import
    is unavailable in a packaged/update context.
    """
    from tools.skills_hub import _read_bounded_regular_file

    path = SKILLS_DIR / ".curator_suppressed"
    if not _profile_exists(path):
        return set()
    try:
        payload, _state = _read_bounded_regular_file(
            path,
            max_bytes=4 * 1024 * 1024,
            require_unique=True,
        )
        text = payload.decode("utf-8")
    except (FileNotFoundError, OSError, UnicodeError):
        return set()
    return {
        line
        for raw_line in text.splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    }


def _skills_mutation_home() -> Path:
    """Return the profile generation that owns the active skills tree."""

    return Path(SKILLS_DIR).parent


def _skills_mutation_scope(
    home: Optional[Path] = None,
    *,
    skills_dir: Optional[Path] = None,
):
    """Pin one profile generation for a complete legacy sync mutation."""

    from tools.skills_hub import hub_mutation_scope

    target_home = Path(home or _skills_mutation_home())
    target_skills = Path(skills_dir or SKILLS_DIR)
    if skills_dir is None and Path(os.path.abspath(target_skills.parent)) != Path(
        os.path.abspath(target_home)
    ):
        target_skills = target_home / "skills"
    return hub_mutation_scope(
        target_home,
        skills_dir=target_skills,
    )


def _snapshot_md5(snapshot) -> str:
    """Legacy manifest digest derived from one immutable tree observation."""

    hasher = hashlib.md5()
    for item in snapshot.files:
        hasher.update(item.relative_path.as_posix().encode("utf-8"))
        hasher.update(item.content)
    return hasher.hexdigest()


def _profile_snapshot(path: Path):
    from tools.skills_hub import _capture_hub_tree

    return _capture_hub_tree(path)


def _profile_exists(path: Path) -> bool:
    from tools.skills_hub import _hub_exists, _hub_relative_parts

    if _hub_relative_parts(path) is None:
        # Legacy test/integration hooks can inject FABRIC_HOME independently
        # from SKILLS_DIR. Production paths share one profile root; a renamed
        # bound path still resolves through _hub_relative_parts and cannot
        # fall back to this compatibility probe.
        try:
            path.lstat()
        except (FileNotFoundError, NotADirectoryError):
            return False
        return True
    return _hub_exists(path)


def _profile_copy_snapshot(snapshot, destination: Path) -> None:
    from tools.skills_hub import (
        _hub_exists,
        _hub_lstat,
        _hub_remove_tree,
        _materialize_snapshot_candidate,
        _open_hub_directory,
    )

    parent_fd = _open_hub_directory(destination.parent, create=True)
    os.close(parent_fd)
    try:
        _materialize_snapshot_candidate(snapshot, destination)
    except BaseException:
        if _hub_exists(destination):
            inspected = _hub_lstat(destination)
            _hub_remove_tree(
                destination,
                expected_identity=(inspected.st_dev, inspected.st_ino),
            )
        raise


def _profile_move_directory(
    source: Path,
    destination: Path,
    *,
    expected_snapshot=None,
) -> None:
    from tools.skills_hub import _atomic_move_directory

    snapshot = _profile_snapshot(source)
    if expected_snapshot is not None and (
        snapshot.root_identity != expected_snapshot.root_identity
        or snapshot.tree_sha256 != expected_snapshot.tree_sha256
        or snapshot.content_sha256 != expected_snapshot.content_sha256
    ):
        raise ValueError("profile skill changed after classification")
    _atomic_move_directory(
        source,
        destination,
        expected_identity=snapshot.root_identity,
        expected_native_identity=snapshot.native_root_identity,
    )


def _profile_remove_tree(path: Path) -> None:
    from tools.skills_hub import _hub_remove_tree

    snapshot = _profile_snapshot(path)
    _hub_remove_tree(
        path,
        expected_identity=snapshot.root_identity,
        expected_native_identity=snapshot.native_root_identity,
    )


def _write_manifest_locked(entries: Dict[str, str]):
    """Write the manifest file atomically in v2 format (name:hash).

    Uses a temp file + os.replace() to avoid corruption if the process
    crashes or is interrupted mid-write.
    """
    data = "\n".join(f"{name}:{hash_val}" for name, hash_val in sorted(entries.items())) + "\n"
    from tools.skills_hub import _hub_write_regular_file_atomic

    # Publication is part of the operation's commit contract. Any failure is
    # propagated so callers cannot report a successful sync/reset with stale
    # ownership metadata or leave future syncs permanently wedged.
    _hub_write_regular_file_atomic(MANIFEST_FILE, data.encode("utf-8"))


def _write_manifest(entries: Dict[str, str]):
    """Compatibility entry point that serializes direct manifest writers."""

    with _skills_mutation_scope(
        MANIFEST_FILE.parent.parent,
        skills_dir=MANIFEST_FILE.parent,
    ):
        _write_manifest_locked(entries)


def _read_skill_name_content(content: str, fallback: str) -> str:
    """Parse a skill name from one already-captured frontmatter prefix."""

    in_frontmatter = False
    for line in content[:4000].split("\n"):
        stripped = line.strip()
        if stripped == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter and stripped.startswith("name:"):
            value = stripped.split(":", 1)[1].strip().strip("\"'")
            if value:
                return value
    return fallback


def _read_skill_name(skill_md: Path, fallback: str) -> str:
    """Read the name field from SKILL.md YAML frontmatter, falling back to *fallback*."""
    try:
        content = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return fallback
    return _read_skill_name_content(content, fallback)


def _snapshot_skill_name(snapshot, fallback: str) -> str:
    """Parse SKILL.md from the exact immutable tree used for classification."""

    for item in snapshot.files:
        if item.relative_path.as_posix() == "SKILL.md":
            return _read_skill_name_content(
                item.content.decode("utf-8", errors="replace"),
                fallback,
            )
    return fallback


def _profile_active_skill_snapshots() -> List[Tuple[Path, object, str]]:
    """Discover active skills entirely through the pinned profile capability."""

    from agent.skill_utils import EXCLUDED_SKILL_DIRS, SKILL_SUPPORT_DIRS
    from tools.skills_hub import (
        MAX_HUB_DIRECTORY_ENTRIES,
        _hub_list_directory,
        _hub_lstat,
    )

    if not _profile_exists(SKILLS_DIR):
        return []
    found: List[Tuple[Path, object, str]] = []
    pending = [SKILLS_DIR]
    seen = 0
    while pending:
        directory = pending.pop()
        remaining = MAX_HUB_DIRECTORY_ENTRIES - seen
        if remaining < 1:
            raise ValueError("active skills tree exceeds the discovery entry limit")
        children = _hub_list_directory(directory, max_entries=remaining)
        seen += len(children)
        marker_present = False
        child_directories: List[Path] = []
        for child in children:
            state = _hub_lstat(child)
            if stat.S_ISREG(state.st_mode) and child.name == "SKILL.md":
                marker_present = True
            elif stat.S_ISDIR(state.st_mode):
                child_directories.append(child)
        if marker_present:
            snapshot = _profile_snapshot(directory)
            if any(
                item.relative_path.as_posix() == "SKILL.md"
                for item in snapshot.files
            ):
                found.append(
                    (
                        directory,
                        snapshot,
                        _snapshot_skill_name(snapshot, directory.name),
                    )
                )
        for child in reversed(child_directories):
            if child.name in EXCLUDED_SKILL_DIRS:
                continue
            if marker_present and child.name in SKILL_SUPPORT_DIRS:
                continue
            pending.append(child)
    found.sort(key=lambda item: item[0].as_posix())
    return found


def _discover_bundled_skills(bundled_dir: Path) -> List[Tuple[str, Path]]:
    """
    Find all SKILL.md files in the bundled directory.
    Returns list of (skill_name, skill_directory_path) tuples.
    """
    skills = []
    if not bundled_dir.exists():
        return skills

    for skill_md in bundled_dir.rglob("SKILL.md"):
        if is_excluded_skill_path(skill_md):
            continue
        skill_dir = skill_md.parent
        skill_name = _read_skill_name(skill_md, skill_dir.name)
        skills.append((skill_name, skill_dir))

    return skills


def _compute_relative_dest(skill_dir: Path, bundled_dir: Path) -> Path:
    """
    Compute the destination path in SKILLS_DIR preserving the category structure.
    e.g., bundled/skills/mlops/axolotl -> ~/.hermes/skills/mlops/axolotl
    """
    rel = skill_dir.relative_to(bundled_dir)
    return SKILLS_DIR / rel


def _dir_hash(directory: Path) -> str:
    """Compute a hash of all file contents in a directory for change detection."""
    hasher = hashlib.md5()
    try:
        for fpath in sorted(directory.rglob("*")):
            if fpath.is_file():
                rel = fpath.relative_to(directory)
                hasher.update(str(rel).encode("utf-8"))
                hasher.update(fpath.read_bytes())
    except (OSError, IOError):
        pass
    return hasher.hexdigest()


def _safe_rel_install_path(path: Path, base: Path) -> str:
    """Return a normalized relative POSIX path, rejecting traversal/absolute paths."""
    rel = path.relative_to(base)
    posix = rel.as_posix()
    pure = PurePosixPath(posix)
    parts = [part for part in pure.parts if part not in {"", "."}]
    if pure.is_absolute() or not parts or any(part == ".." for part in parts):
        raise ValueError(f"Unsafe optional skill path: {posix}")
    return "/".join(parts)


def _skill_file_list(skill_dir: Path) -> List[str]:
    """List files inside a skill directory in lock-file format."""
    files: List[str] = []
    for fpath in sorted(skill_dir.rglob("*")):
        if fpath.is_file():
            files.append(fpath.relative_to(skill_dir).as_posix())
    return files


def _content_hash(directory: Path) -> str:
    """Return the same hash style the skills hub lock uses, falling back locally."""
    try:
        from tools.skills_guard import content_hash

        return content_hash(directory)
    except Exception:
        # Hashing is provenance metadata only; keep sync resilient if guard
        # dependencies are unavailable in a packaged/update context.
        return _dir_hash(directory)


def _optional_skill_index() -> Dict[str, Tuple[str, str, Path]]:
    """Return official optional skills keyed by folder name and frontmatter name.

    Values are ``(folder_name, install_path, source_dir)``. Multiple keys may
    point to the same skill so callers can accept either the folder slug used
    by the hub lock or the user-facing frontmatter name.
    """
    optional_dir = _get_optional_dir()
    index: Dict[str, Tuple[str, str, Path]] = {}
    if not optional_dir.exists():
        return index
    for skill_md in sorted(optional_dir.rglob("SKILL.md")):
        if is_excluded_skill_path(skill_md):
            continue
        src = skill_md.parent
        try:
            install_path = _safe_rel_install_path(src, optional_dir)
        except ValueError:
            continue
        folder_name = src.name
        frontmatter_name = _read_skill_name(skill_md, folder_name)
        value = (folder_name, install_path, src)
        index[folder_name] = value
        index[frontmatter_name] = value
    return index


def _move_to_restore_backup(
    path: Path,
    backup_root: Path,
    *,
    expected_snapshot=None,
) -> str:
    """Move an existing skill directory into a restore backup, preserving rel path."""
    rel = path.relative_to(SKILLS_DIR)
    target = backup_root / rel
    if _profile_exists(target):
        suffix = 1
        while _profile_exists(target.with_name(f"{target.name}-{suffix}")):
            suffix += 1
        target = target.with_name(f"{target.name}-{suffix}")
    _profile_move_directory(
        path,
        target,
        expected_snapshot=expected_snapshot,
    )
    return rel.as_posix()


def _restore_official_optional_skill_locked(
    name: str, *, restore: bool = False
) -> dict:
    """Restore one or all official optional skills from repo source.

    ``restore=False`` only performs exact-match provenance backfill. ``restore=True``
    repairs already-mutated/reorganized skills by backing up matching active
    copies and copying the official optional source into its canonical path.
    """
    index = _optional_skill_index()
    if not index:
        return {"ok": False, "message": "No official optional skills directory found.", "restored": [], "backfilled": [], "backed_up": []}

    targets = sorted(set(index.values()), key=lambda item: item[1]) if name in {"all", "*"} else []
    if not targets:
        target = index.get(name)
        if target is None:
            return {"ok": False, "message": f"Official optional skill not found: {name}", "restored": [], "backfilled": [], "backed_up": []}
        targets = [target]

    restored: List[str] = []
    backed_up: List[str] = []
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_root = SKILLS_DIR / ".restore-backups" / f"official-optional-{timestamp}"

    for folder_name, install_path, src in targets:
        dest = SKILLS_DIR / Path(*install_path.split("/"))
        from tools.skill_install import capture_tree_snapshot

        source_snapshot = capture_tree_snapshot(src)
        canonical_snapshot = (
            _profile_snapshot(dest) if _profile_exists(dest) else None
        )
        canonical_ok = (
            canonical_snapshot is not None
            and canonical_snapshot.tree_sha256 == source_snapshot.tree_sha256
            and canonical_snapshot.content_sha256 == source_snapshot.content_sha256
        )

        # Find already-active copies of this official skill by frontmatter name
        # or folder slug, even if curator moved it into another category.
        src_frontmatter = _snapshot_skill_name(source_snapshot, folder_name)
        matches: List[Tuple[Path, object]] = []
        for candidate, candidate_snapshot, candidate_name in (
            _profile_active_skill_snapshots()
        ):
            if candidate == dest:
                continue
            if (
                candidate.name == folder_name
                or candidate_name in {folder_name, src_frontmatter}
            ):
                matches.append((candidate, candidate_snapshot))

        if restore:
            for match, match_snapshot in matches:
                if _profile_exists(match):
                    backed_up.append(
                        _move_to_restore_backup(
                            match,
                            backup_root,
                            expected_snapshot=match_snapshot,
                        )
                    )
            if _profile_exists(dest) and not canonical_ok:
                if canonical_snapshot is None:
                    raise ValueError(
                        "canonical optional skill appeared after classification"
                    )
                backed_up.append(
                    _move_to_restore_backup(
                        dest,
                        backup_root,
                        expected_snapshot=canonical_snapshot,
                    )
                )
            if not _profile_exists(dest):
                _profile_copy_snapshot(source_snapshot, dest)
                restored.append(folder_name)
        elif not canonical_ok:
            continue

    backfilled = _backfill_optional_provenance_locked(quiet=True)
    return {
        "ok": True,
        "message": "Official optional skill repair complete.",
        "restored": restored,
        "backfilled": backfilled,
        "backed_up": backed_up,
        "backup_dir": str(backup_root) if backed_up else "",
    }


def restore_official_optional_skill(name: str, *, restore: bool = False) -> dict:
    """Serialize optional-skill restore with Hub and pack skill writers."""

    with _skills_mutation_scope():
        return _restore_official_optional_skill_locked(name, restore=restore)


def _backfill_optional_provenance_locked(quiet: bool = False) -> List[str]:
    """Mark already-present official optional skills as hub-installed.

    This covers the migration case where a skill used to be bundled (or was
    manually copied into the active skills tree) and later lives under
    optional-skills/. If the active copy is byte-identical to the official
    optional source, adopt it through the ordinary journaled Hub install
    transaction. Modified/local skills are left alone.

    Adoption deliberately rebuilds the same bytes from an immutable snapshot.
    Merely publishing elevated provenance and revoking it after a post-check
    has an unsafe failure window if the revocation write itself fails. The Hub
    transaction instead keeps the old untracked tree as its rollback backup
    and makes the captured candidate plus exact lock post-image one recoverable
    commit.
    """
    optional_dir = _get_optional_dir()
    if not optional_dir.exists():
        return []

    import uuid

    from tools.skill_install import capture_tree_snapshot
    from tools.skills_hub import (
        HubInstallError,
        HubLockFile,
        HubSourceAuthority,
        HubSourceKind,
        SkillBundle,
        _materialize_snapshot_candidate,
        _quarantine_dir,
        ensure_hub_dirs,
        install_from_quarantine,
        scan_skill_with_authority,
    )

    lock = HubLockFile(path=SKILLS_DIR / ".hub" / "lock.json")
    try:
        data = lock.load(strict=True)
    except (ValueError, OSError) as exc:
        logger.warning(
            "Skipping optional provenance backfill because %s is unreadable: %s",
            lock.path,
            exc,
        )
        return []
    installed = data["installed"]
    existing_names = set(installed)
    existing_paths = {
        entry.get("install_path")
        for entry in installed.values()
        if isinstance(entry, dict)
    }

    backfilled: List[str] = []
    for skill_md in sorted(optional_dir.rglob("SKILL.md")):
        if is_excluded_skill_path(skill_md):
            continue
        src = skill_md.parent
        try:
            install_path = _safe_rel_install_path(src, optional_dir)
        except ValueError as e:
            logger.debug("Skipping optional skill with unsafe path %s: %s", src, e)
            continue
        dest = SKILLS_DIR / Path(*install_path.split("/"))
        if not _profile_exists(dest):
            continue
        try:
            source_snapshot = capture_tree_snapshot(src)
            active_snapshot = _profile_snapshot(dest)
        except (OSError, ValueError) as exc:
            logger.debug("Skipping unstable optional skill %s: %s", src, exc)
            continue
        if (
            active_snapshot.tree_sha256 != source_snapshot.tree_sha256
            or active_snapshot.content_sha256 != source_snapshot.content_sha256
        ):
            continue

        lock_name = src.name
        if lock_name in existing_names or install_path in existing_paths:
            continue

        authority = HubSourceAuthority(
            adapter=HubSourceKind.OFFICIAL_OPTIONAL,
            remote_identifier=f"official/{install_path}",
            bundle_source="official",
            trust_level="builtin",
        )
        bundle = SkillBundle(
            name=lock_name,
            files={
                item.relative_path.as_posix(): item.content
                for item in source_snapshot.files
            },
            source="official",
            identifier=authority.remote_identifier,
            trust_level="builtin",
            metadata={
                "backfilled_from": "optional-skills",
                "source_revision": authority.remote_identifier,
            },
        )
        ensure_hub_dirs()
        quarantine = _quarantine_dir() / f"{lock_name}-{uuid.uuid4().hex}"
        try:
            # Preserve the already-active file modes while binding all policy
            # and provenance fields to the byte-identical official snapshot.
            _materialize_snapshot_candidate(active_snapshot, quarantine)
            scan_result = scan_skill_with_authority(quarantine, authority)
        except (HubInstallError, OSError, ValueError) as exc:
            logger.warning(
                "Could not stage official optional provenance for %s: %s",
                lock_name,
                exc,
            )
            continue
        outcome = install_from_quarantine(
            quarantine,
            lock_name,
            install_path.rpartition("/")[0],
            bundle,
            scan_result,
            source_authority=authority,
            force=True,
            adopt_identical_untracked=True,
        )
        if outcome.status == "recovery_pending":
            raise HubInstallError(outcome.message)
        if not outcome.committed:
            logger.warning(
                "Official optional provenance adoption rolled back for %s: %s",
                lock_name,
                outcome.message,
            )
            continue

        existing_names.add(lock_name)
        existing_paths.add(install_path)
        backfilled.append(lock_name)
        if not quiet:
            print(f"  = {lock_name} (official optional provenance backfilled)")
    return backfilled


def _backfill_optional_provenance(quiet: bool = False) -> List[str]:
    """Serialize direct migration callers with every other skill writer."""

    with _skills_mutation_scope():
        return _backfill_optional_provenance_locked(quiet=quiet)


def _sync_skills_locked(quiet: bool = False) -> dict:
    """
    Sync bundled skills into ~/.hermes/skills/ using the manifest.

    Returns:
        dict with keys: copied (list), updated (list), skipped (int),
                        user_modified (list), cleaned (list), total_bundled (int)
    """
    # Opt-out: a profile (named or the default ~/.hermes) that wrote the
    # .no-bundled-skills marker gets zero bundled-skill seeding. Returning the
    # empty-result shape with skipped_opt_out lets callers report "opted out"
    # instead of "synced 0 / failed". This is the default-profile counterpart
    # to seed_profile_skills()'s marker check for named profiles.
    if _profile_exists(FABRIC_HOME / NO_BUNDLED_SKILLS_MARKER):
        if not quiet:
            print("  (skipped — profile opted out of bundled skills via .no-bundled-skills)")
        return {
            "copied": [], "updated": [], "skipped": 0,
            "user_modified": [], "cleaned": [], "total_bundled": 0,
            "optional_provenance_backfilled": [], "skipped_opt_out": True,
        }

    bundled_dir = _get_bundled_dir()
    if not bundled_dir.exists():
        return {
            "copied": [], "updated": [], "skipped": 0,
            "user_modified": [], "cleaned": [], "suppressed": [], "total_bundled": 0,
            "optional_provenance_backfilled": [],
        }

    from tools.skill_install import capture_tree_snapshot
    from tools.skills_hub import _open_hub_directory

    skills_fd = _open_hub_directory(SKILLS_DIR, create=True)
    os.close(skills_fd)
    manifest = _read_manifest_locked()
    bundled_skills = _discover_bundled_skills(bundled_dir)
    bundled_names = {name for name, _ in bundled_skills}
    suppressed = _read_suppressed_names()
    # Index of skills already provided by external_dirs (skip writing them)
    external_index = _build_external_skill_index()
    shadowed_by_external: List[str] = []

    copied = []
    updated = []
    user_modified = []
    suppressed_skipped: List[str] = []
    skipped = 0

    for skill_name, skill_src in bundled_skills:
        # Curator-pruned built-ins: do not re-seed. The suppression list
        # (~/.hermes/skills/.curator_suppressed) is written when the curator
        # archives a bundled skill with curator.prune_builtins enabled. Without
        # this skip, every `fabric update` would resurrect a skill the user
        # deliberately pruned. Restoring the skill clears its suppression entry.
        if skill_name in suppressed:
            suppressed_skipped.append(skill_name)
            continue

        dest = _compute_relative_dest(skill_src, bundled_dir)
        try:
            bundled_snapshot = capture_tree_snapshot(skill_src)
        except (OSError, ValueError) as exc:
            logger.warning("Could not capture bundled skill %s: %s", skill_name, exc)
            skipped += 1
            continue
        bundled_hash = _snapshot_md5(bundled_snapshot)

        # Recover an orphaned backup before classifying. If a previous
        # update was interrupted between moving dest aside and copying the
        # new version in, the user's only copy sits in ``dest.bak`` while
        # dest is gone — without this, the "in manifest but not on disk"
        # branch below misreads the skill as user-deleted and it silently
        # vanishes from discovery.
        _orphan = dest.with_suffix(".bak")
        if _profile_exists(_orphan) and not _profile_exists(dest):
            try:
                _profile_move_directory(_orphan, dest)
                logger.info("Recovered orphaned skill backup: %s", _orphan)
            except (OSError, IOError):
                logger.warning(
                    "Could not recover orphaned skill backup %s", _orphan,
                    exc_info=True,
                )

        if skill_name in external_index:
            # An external_dirs source already provides this skill. Writing it
            # into the profile-local tree would create a name collision the
            # loader refuses to resolve (#28126). Defer to the external copy
            # for ALL manifest states (new, previously-synced, user-deleted).
            shadowed_by_external.append(skill_name)
            skipped += 1
            if not quiet:
                print(
                    f"  ⇢ {skill_name} (deferred to external_dirs, "
                    "not written to local tree)"
                )
            # Self-healing: a prior sync (before external_dirs was configured,
            # or an older buggy sync) may have left a local shadow that now
            # collides. We own that shadow only when it is byte-identical to
            # the bundled source — a user's own customized skill by the same
            # name differs, so never delete or re-baseline it. Drop the stale
            # manifest entry so the skill isn't later misread as user-deleted.
            if (
                _profile_exists(dest)
                and _snapshot_md5(_profile_snapshot(dest)) == bundled_hash
            ):
                _profile_remove_tree(dest)
                if not quiet:
                    print(f"  ✓ removed stale shadow of {skill_name}")
                manifest.pop(skill_name, None)
            continue

        if skill_name not in manifest:
            # ── New skill — never offered before ──
            try:
                if _profile_exists(dest):
                    # User already has a skill with the same name — don't overwrite.
                    # Only baseline in the manifest when the on-disk copy is
                    # byte-identical to bundled (e.g. a reset that re-syncs, or
                    # a coincidentally identical install); that case is harmless
                    # to track. If the copy differs (custom skill, hub-installed,
                    # or user-edited) skip the manifest write: recording
                    # bundled_hash there would poison update detection by making
                    # user_hash != origin_hash read as "user-modified" on every
                    # subsequent sync, permanently blocking bundled updates.
                    skipped += 1
                    if _snapshot_md5(_profile_snapshot(dest)) == bundled_hash:
                        manifest[skill_name] = bundled_hash
                    elif not quiet:
                        print(
                            f"  ⚠ {skill_name}: bundled version shipped but you "
                            f"already have a local skill by this name — yours "
                            f"was kept. Run `Fabric skills reset {skill_name}` "
                            f"to replace it with the bundled version."
                        )
                else:
                    _profile_copy_snapshot(bundled_snapshot, dest)
                    copied.append(skill_name)
                    manifest[skill_name] = bundled_hash
                    if not quiet:
                        print(f"  + {skill_name}")
            except (OSError, IOError) as e:
                if not quiet:
                    print(f"  ! Failed to copy {skill_name}: {e}")
                # Do NOT add to manifest — next sync should retry

        elif _profile_exists(dest):
            # ── Existing skill — in manifest AND on disk ──
            origin_hash = manifest.get(skill_name, "")
            user_hash = _snapshot_md5(_profile_snapshot(dest))

            if not origin_hash:
                # v1 migration: no origin hash recorded. Set baseline from
                # user's current copy so future syncs can detect modifications.
                manifest[skill_name] = user_hash
                if user_hash == bundled_hash:
                    skipped += 1  # already in sync
                else:
                    # Can't tell if user modified or bundled changed — be safe
                    skipped += 1
                continue

            if _is_tracked_user_modification(origin_hash, user_hash):
                # User modified this skill — don't overwrite their changes
                user_modified.append(skill_name)
                if not quiet:
                    print(f"  ~ {skill_name} (user-modified, skipping)")
                continue

            # User copy matches origin — check if bundled has a newer version
            if bundled_hash != origin_hash:
                try:
                    # Move old copy to a backup so we can restore on failure
                    backup = dest.with_suffix(".bak")
                    # A stale backup left by an earlier failure would make
                    # shutil.move() nest dest *inside* it (or fail outright)
                    # and would poison the restore path below. The current
                    # dest is the authoritative copy — clear the leftover.
                    if _profile_exists(backup):
                        _profile_remove_tree(backup)
                    _profile_move_directory(dest, backup)
                    try:
                        _profile_copy_snapshot(bundled_snapshot, dest)
                        manifest[skill_name] = bundled_hash
                        updated.append(skill_name)
                        if not quiet:
                            print(f"  ↑ {skill_name} (updated)")
                        # Remove backup after successful copy
                        try:
                            _profile_remove_tree(backup)
                        except (OSError, IOError):
                            logger.debug("Could not remove backup %s", backup, exc_info=True)
                    except (OSError, IOError):
                        # Restore from backup. A partially-written dest must
                        # not shadow the user's copy or block the restore —
                        # clear it first, then move the backup home.
                        if _profile_exists(backup):
                            if _profile_exists(dest):
                                try:
                                    _profile_remove_tree(dest)
                                except (OSError, IOError):
                                    logger.warning(
                                        "Could not clear partial copy %s during restore",
                                        dest, exc_info=True,
                                    )
                            if not _profile_exists(dest):
                                _profile_move_directory(backup, dest)
                        raise
                except (OSError, IOError) as e:
                    if not quiet:
                        print(f"  ! Failed to update {skill_name}: {e}")
            else:
                skipped += 1  # bundled unchanged, user unchanged

        else:
            # ── In manifest but not on disk — user deleted it ──
            skipped += 1

    # Clean stale manifest entries (skills removed from bundled dir)
    cleaned = sorted(set(manifest.keys()) - bundled_names)
    for name in cleaned:
        del manifest[name]

    # Also copy DESCRIPTION.md files for categories (if not already present)
    for desc_md in bundled_dir.rglob("DESCRIPTION.md"):
        rel = desc_md.relative_to(bundled_dir)
        dest_desc = SKILLS_DIR / rel
        if not _profile_exists(dest_desc):
            try:
                from tools.skills_hub import _hub_write_regular_file_atomic

                _hub_write_regular_file_atomic(dest_desc, desc_md.read_bytes())
            except (OSError, IOError) as e:
                logger.debug("Could not copy %s: %s", desc_md, e)

    _write_manifest_locked(manifest)
    optional_provenance_backfilled = _backfill_optional_provenance_locked(quiet=quiet)

    return {
        "copied": copied,
        "updated": updated,
        "skipped": skipped,
        "user_modified": user_modified,
        "cleaned": cleaned,
        "suppressed": suppressed_skipped,
        "total_bundled": len(bundled_skills),
        "optional_provenance_backfilled": optional_provenance_backfilled,
        "shadowed_by_external": shadowed_by_external,
    }


def sync_skills(quiet: bool = False) -> dict:
    """Serialize the complete read/classify/tree/manifest operation."""

    with _skills_mutation_scope():
        return _sync_skills_locked(quiet=quiet)


def _rmtree_writable(path: Path) -> None:
    """Remove a directory tree, making read-only entries writable first.

    Handles immutable package sources (Nix store, deb/rpm installs) that
    preserve read-only permissions on copied files *and* directories
    (``r-xr-xr-x``).  Removing a child requires write permission on its
    parent directory, so the retry handler makes the failing path **and its
    parent** writable before re-attempting.  See #34860, #34972.
    """
    # Defense in depth (#48200): refuse to rmtree anything outside
    # ``FABRIC_HOME/skills/`` to prevent the catastrophic wipe of
    # ``~/.hermes/`` (``.env``, ``MEMORY.md``, ``kanban.db``, custom
    # skills, scripts, …) that an earlier incident observed. Five call
    # sites in this file invoke this helper; if any one of them ever
    # computes a destination outside the skills root — through a bad
    # path join, a missing ``FABRIC_HOME`` default, a malicious
    # bundled-manifest entry, or a mid-flight exception that leaves a
    # stale path in scope — this guard turns the resulting
    # ``shutil.rmtree(~/.hermes)`` into a loud, recoverable ``ValueError``
    # instead of silently destroying the user's install.
    target = Path(path).resolve()
    skills_root = SKILLS_DIR.resolve()
    # Every legitimate caller passes a skill directory or its ``.bak``
    # sibling — always a strict child of the skills root. The skills root
    # itself must never be removed: a ``dest`` that collapses to
    # ``SKILLS_DIR`` (e.g. a relative path resolving to ``.``) would wipe
    # every installed skill, and its ``.bak`` sibling lands one level up in
    # ``FABRIC_HOME``. Require a strict-child relationship so both escape
    # into the skills root and out of it are refused.
    if skills_root not in target.parents:
        raise ValueError(
            f"refusing to rmtree {target!r}: not strictly under {skills_root!r} "
            f"(scope guard — see #48200)"
        )
    import stat

    def _on_error(func, fpath, exc_info):
        # Unlinking a child requires the parent dir to be writable, so chmod
        # the parent as well as the failing path, then retry.
        for target in (os.path.dirname(fpath), fpath):
            try:
                os.chmod(target, stat.S_IRWXU)
            except OSError:
                pass
        func(fpath)

    shutil.rmtree(path, onerror=_on_error)


def _reset_bundled_skill_locked(name: str, restore: bool = False) -> dict:
    """
    Reset a bundled skill's manifest tracking so future syncs work normally.

    When a user edits a bundled skill, subsequent syncs mark it as
    ``user_modified`` and skip it forever — even if the user later copies
    the bundled version back into place, because the manifest still holds
    the *old* origin hash. This function breaks that loop.

    Args:
        name: The skill name (matches the manifest key / skill frontmatter name).
        restore: If True, also delete the user's copy in SKILLS_DIR and let
                 the next sync re-copy the current bundled version. If False
                 (default), only clear the manifest entry — the user's
                 current copy is preserved but future updates work again.

    Returns:
        dict with keys:
          - ok: bool, whether the reset succeeded
          - action: one of "manifest_cleared", "restored", "not_in_manifest",
                    "bundled_missing"
          - message: human-readable description
          - synced: dict from sync_skills() if a sync was triggered, else None
    """
    manifest = _read_manifest()
    bundled_dir = _get_bundled_dir()
    bundled_skills = _discover_bundled_skills(bundled_dir)
    bundled_by_name = dict(bundled_skills)

    in_manifest = name in manifest
    is_bundled = name in bundled_by_name

    if not in_manifest and not is_bundled:
        return {
            "ok": False,
            "action": "not_in_manifest",
            "message": (
                f"'{name}' is not a tracked bundled skill. Nothing to reset. "
                f"(Hub-installed skills use `Fabric skills uninstall`.)"
            ),
            "synced": None,
        }

    # Step 1 (optional): delete the user's copy so next sync re-copies bundled.
    # Must happen BEFORE manifest deletion so that a failed rmtree does not
    # leave the skill in a manifest-less limbo state (see #34972).
    deleted_user_copy = False
    if restore:
        if not is_bundled:
            return {
                "ok": False,
                "action": "bundled_missing",
                "message": (
                    f"'{name}' has no bundled source — manifest entry preserved "
                    f"but cannot restore from bundled (skill was removed upstream)."
                ),
                "synced": None,
            }
        dest = _compute_relative_dest(bundled_by_name[name], bundled_dir)
        if _profile_exists(dest):
            try:
                _profile_remove_tree(dest)
                deleted_user_copy = True
            except (OSError, IOError) as e:
                return {
                    "ok": False,
                    "action": "not_reset",
                    "message": (
                        f"Could not delete user copy at {dest}: {e}. "
                        f"Manifest entry preserved — nothing was changed."
                    ),
                    "synced": None,
                }

    # Step 2: drop the manifest entry so next sync treats it as new
    if in_manifest:
        del manifest[name]
        _write_manifest_locked(manifest)

    # Step 3: run sync to re-baseline (or re-copy if we deleted)
    synced = _sync_skills_locked(quiet=True)

    if restore and deleted_user_copy:
        action = "restored"
        message = f"Restored '{name}' from bundled source."
    elif restore:
        # Nothing on disk to delete, but we re-synced — acts like a fresh install
        action = "restored"
        message = f"Restored '{name}' (no prior user copy, re-copied from bundled)."
    else:
        action = "manifest_cleared"
        message = (
            f"Cleared manifest entry for '{name}'. Future `fabric update` runs "
            f"will re-baseline against your current copy and accept upstream changes."
        )

    return {"ok": True, "action": action, "message": message, "synced": synced}


def reset_bundled_skill(name: str, restore: bool = False) -> dict:
    """Serialize reset and its nested re-sync as one mutation."""

    with _skills_mutation_scope():
        return _reset_bundled_skill_locked(name, restore=restore)


def _is_tracked_user_modification(origin_hash: str, user_hash: str) -> bool:
    """Whether an on-disk skill counts as a user modification ``fabric update`` keeps.

    Shared by the sync loop (which decides what to skip) and
    ``list_user_modified_bundled_skills`` (which surfaces the names) so the two
    can never drift. A skill is a tracked modification only when it has a
    recorded origin hash (an un-baselined / v1 entry with an empty hash is not)
    and its current content hash differs from that origin.
    """
    return bool(origin_hash) and user_hash != origin_hash


def list_user_modified_bundled_skills() -> List[dict]:
    """Return the bundled skills that ``fabric update`` keeps because the user
    edited them locally.

    A skill counts as user-modified when its on-disk copy no longer matches the
    origin hash recorded in the manifest the last time it was synced — the exact
    same test the sync loop uses to decide what to skip. This is the discovery
    half of that behavior, so a user can find the names the ``~ N user-modified
    (kept)`` notice only counts.

    Returns a list (sorted by name) of dicts:
        ``{"name": str, "dest": Path, "bundled_src": Path}``
    where ``dest`` is the user's copy and ``bundled_src`` is the current stock
    copy (so callers can diff or restore).
    """
    manifest = _read_manifest()
    if not manifest:
        return []
    bundled_dir = _get_bundled_dir()
    modified: List[dict] = []
    for skill_name, skill_dir in _discover_bundled_skills(bundled_dir):
        origin_hash = manifest.get(skill_name, "")
        # No entry, or a v1 entry not yet baselined (empty hash): not a tracked
        # modification — the next sync handles it.
        if not origin_hash:
            continue
        dest = _compute_relative_dest(skill_dir, bundled_dir)
        if not dest.exists():
            continue
        if _is_tracked_user_modification(origin_hash, _dir_hash(dest)):
            modified.append(
                {"name": skill_name, "dest": dest, "bundled_src": skill_dir}
            )
    modified.sort(key=lambda e: e["name"])
    return modified


def _read_for_diff(path: Path) -> Tuple[Optional[bytes], Optional[str]]:
    """Read a file once for diffing.

    Returns ``(raw_bytes, text)`` where ``text`` is ``None`` if the file is
    binary; ``(None, None)`` if it could not be read. Returning the raw bytes
    lets the caller compare binary files without re-reading them.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None, None
    if b"\x00" in data:
        return data, None
    try:
        return data, data.decode("utf-8")
    except UnicodeDecodeError:
        return data, None


def diff_bundled_skill(name: str) -> dict:
    """Diff a user's copy of a bundled skill against the current stock version.

    Lets a user see exactly what diverged before deciding whether to keep their
    edits or ``Fabric skills reset`` back to upstream.

    Returns a dict:
        ``ok`` (bool), ``name`` (str), ``found`` (bool — bundled source exists),
        ``modified`` (bool), ``message`` (str),
        ``diffs``: list of ``{"path": str, "status": str, "diff": str}`` where
        status is one of ``modified`` / ``added`` (only in user copy) /
        ``removed`` (only in bundled) / ``binary``.
    """
    import difflib

    bundled_dir = _get_bundled_dir()
    bundled_by_name = dict(_discover_bundled_skills(bundled_dir))
    bundled_src = bundled_by_name.get(name)
    if bundled_src is None:
        return {
            "ok": False,
            "name": name,
            "found": False,
            "modified": False,
            "diffs": [],
            "message": (
                f"'{name}' is not a tracked bundled skill (no stock version to "
                f"diff against). Hub-installed skills use `Fabric skills inspect`."
            ),
        }
    dest = _compute_relative_dest(bundled_src, bundled_dir)
    if not dest.exists():
        return {
            "ok": False,
            "name": name,
            "found": True,
            "modified": False,
            "diffs": [],
            "message": f"No local copy of '{name}' found at {dest}.",
        }

    user_files = set(_skill_file_list(dest))
    stock_files = set(_skill_file_list(bundled_src))

    diffs: List[dict] = []
    for rel in sorted(user_files | stock_files):
        in_user = rel in user_files
        in_stock = rel in stock_files
        user_bytes, user_text = (
            _read_for_diff(dest / rel) if in_user else (None, None)
        )
        stock_bytes, stock_text = (
            _read_for_diff(bundled_src / rel) if in_stock else (None, None)
        )

        if in_user and in_stock:
            if user_text is None or stock_text is None:
                # At least one side is binary — report only if bytes differ
                # (reuse the bytes already read above, no second read).
                if user_bytes != stock_bytes:
                    diffs.append(
                        {"path": rel, "status": "binary", "diff": "<binary file differs>"}
                    )
                continue
            if user_text == stock_text:
                continue
            text = "".join(
                difflib.unified_diff(
                    stock_text.splitlines(keepends=True),
                    user_text.splitlines(keepends=True),
                    fromfile=f"stock/{rel}",
                    tofile=f"yours/{rel}",
                )
            )
            diffs.append({"path": rel, "status": "modified", "diff": text})
        elif in_user:
            diffs.append(
                {"path": rel, "status": "added", "diff": f"+ only in your copy: {rel}"}
            )
        else:
            diffs.append(
                {"path": rel, "status": "removed", "diff": f"- only in stock: {rel}"}
            )

    modified = bool(diffs)
    return {
        "ok": True,
        "name": name,
        "found": True,
        "modified": modified,
        "diffs": diffs,
        "message": (
            f"'{name}' matches the stock version."
            if not modified
            else f"'{name}' differs from the stock version in {len(diffs)} file(s)."
        ),
    }


def _set_bundled_skills_opt_out_locked(enabled: bool) -> dict:
    """Toggle the .no-bundled-skills opt-out marker for the active profile.

    When ``enabled`` is True, writes FABRIC_HOME/.no-bundled-skills so the
    installer, ``fabric update``, and any direct sync stop seeding bundled
    skills. When False, removes the marker so seeding resumes on the next
    sync. This is the on-disk-state half of ``Fabric skills opt-out`` /
    ``opt-in``; removal of already-present skills is a separate, explicit
    step (see ``remove_pristine_bundled_skills``).

    Returns:
        dict with keys: ok (bool), changed (bool), marker (str path),
                        message (str).
    """
    marker = FABRIC_HOME / NO_BUNDLED_SKILLS_MARKER
    existed = _profile_exists(marker)
    try:
        if enabled:
            from tools.skills_hub import _hub_write_regular_file_atomic

            _hub_write_regular_file_atomic(
                marker,
                (
                    "This profile opted out of bundled-skill seeding "
                    "(`Fabric skills opt-out`).\n"
                    "Delete this file to re-enable sync on the next `fabric update`.\n"
                ).encode("utf-8"),
            )
            changed = not existed
            message = (
                "Opted out of bundled skills. Future install / update / sync "
                "runs will not seed bundled skills into this profile."
                if changed
                else "Already opted out — marker was already present."
            )
        else:
            if existed:
                from tools.skills_hub import _hub_unlink_regular_file

                _hub_unlink_regular_file(marker)
            changed = existed
            message = (
                "Opted back in. The next `fabric update` (or `Fabric skills "
                "opt-in --sync`) will re-seed bundled skills."
                if changed
                else "Not opted out — no marker to remove."
            )
    except OSError as e:
        return {
            "ok": False, "changed": False, "marker": str(marker),
            "message": f"Could not update opt-out marker at {marker}: {e}",
        }
    return {"ok": True, "changed": changed, "marker": str(marker), "message": message}


def set_bundled_skills_opt_out(enabled: bool) -> dict:
    """Serialize the profile opt marker with skill-tree writers."""

    with _skills_mutation_scope(Path(FABRIC_HOME)):
        return _set_bundled_skills_opt_out_locked(enabled)


def is_bundled_skills_opt_out() -> bool:
    """Return True if the active profile carries the opt-out marker."""
    return (FABRIC_HOME / NO_BUNDLED_SKILLS_MARKER).exists()


def _remove_pristine_bundled_skills_locked(dry_run: bool = False) -> dict:
    """Delete bundled skills that are present, manifest-tracked, AND unmodified.

    Safety is the whole point of this function. A skill on disk is removed
    ONLY when all of these hold:
      - it is recorded in the sync manifest (so it is genuinely a bundled
        skill, not a hub-installed or hand-written one), AND
      - it still exists in the bundled source (so we can hash-compare), AND
      - its on-disk copy is byte-identical to the manifest origin hash
        (so the user has not edited it).

    Anything user-modified, hub-installed, or locally authored is left
    untouched and reported under ``skipped``. The manifest entry for each
    removed skill is dropped so a later opt-in re-seed treats it as new.

    Args:
        dry_run: When True, compute what would be removed without deleting.

    Returns:
        dict with keys: ok (bool), removed (list[str]),
                        skipped (list[dict]) where each dict is
                        {name, reason}, dry_run (bool), message (str).
    """
    manifest = _read_manifest()
    bundled_dir = _get_bundled_dir()
    bundled_by_name = dict(_discover_bundled_skills(bundled_dir))

    removed: List[str] = []
    skipped: List[dict] = []

    for name, origin_hash in sorted(manifest.items()):
        src = bundled_by_name.get(name)
        if src is None:
            # Tracked but no longer bundled upstream — leave it; not ours to judge.
            skipped.append({"name": name, "reason": "no bundled source (removed upstream)"})
            continue
        dest = _compute_relative_dest(src, bundled_dir)
        if not _profile_exists(dest):
            # Already gone from disk; just forget the stale manifest entry.
            if not dry_run and name in manifest:
                del manifest[name]
            continue
        on_disk = _snapshot_md5(_profile_snapshot(dest))
        if on_disk != origin_hash:
            skipped.append({"name": name, "reason": "user-modified (kept)"})
            continue
        # Pristine bundled copy — safe to remove.
        if dry_run:
            removed.append(name)
            continue
        try:
            _profile_remove_tree(dest)
        except (OSError, IOError) as e:
            skipped.append({"name": name, "reason": f"delete failed: {e}"})
            continue
        if name in manifest:
            del manifest[name]
        removed.append(name)

    if not dry_run and removed:
        _write_manifest_locked(manifest)

    verb = "Would remove" if dry_run else "Removed"
    message = f"{verb} {len(removed)} pristine bundled skill(s); kept {len(skipped)}."
    return {
        "ok": True, "removed": removed, "skipped": skipped,
        "dry_run": dry_run, "message": message,
    }


def remove_pristine_bundled_skills(dry_run: bool = False) -> dict:
    """Serialize pristine-tree removal and manifest publication."""

    with _skills_mutation_scope():
        return _remove_pristine_bundled_skills_locked(dry_run=dry_run)


if __name__ == "__main__":
    print(f"Syncing bundled skills into {SKILLS_DIR} ...")
    result = sync_skills(quiet=False)
    parts = [
        f"{len(result['copied'])} new",
        f"{len(result['updated'])} updated",
        f"{result['skipped']} unchanged",
    ]
    if result["user_modified"]:
        names = result["user_modified"]
        MAX_SHOW = 5
        shown = ", ".join(names[:MAX_SHOW])
        if len(names) > MAX_SHOW:
            shown += f", +{len(names) - MAX_SHOW} more"
        parts.append(f"{len(names)} user-modified (kept): {shown}")
    if result["cleaned"]:
        parts.append(f"{len(result['cleaned'])} cleaned from manifest")
    if result.get("optional_provenance_backfilled"):
        parts.append(f"{len(result['optional_provenance_backfilled'])} official optional backfilled")
    print(f"\nDone: {', '.join(parts)}. {result['total_bundled']} total bundled.")
