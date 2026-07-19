#!/usr/bin/env python3
"""
Skill Manager Tool -- Agent-Managed Skill Creation & Editing

Allows the agent to create, update, and delete skills, turning successful
approaches into reusable procedural knowledge. New skills are created in
~/.fabric/skills/. Existing skills (bundled, hub-installed, or user-created)
can be modified or deleted wherever they live.

Skills are the agent's procedural memory: they capture *how to do a specific
type of task* based on proven experience. General memory (MEMORY.md, USER.md) is
broad and declarative. Skills are narrow and actionable.

Actions:
  create     -- Create a new skill (SKILL.md + directory structure)
  edit       -- Replace the SKILL.md content of a user skill (full rewrite)
  patch      -- Targeted find-and-replace within SKILL.md or any supporting file
  delete     -- Remove a user skill entirely
  write_file -- Add/overwrite a supporting file (reference, template, script, asset)
  remove_file-- Remove a supporting file from a user skill

Directory layout for user skills:
    ~/.fabric/skills/
    ├── my-skill/
    │   ├── SKILL.md
    │   ├── references/
    │   ├── templates/
    │   ├── scripts/
    │   └── assets/
    └── category-name/
        └── another-skill/
            └── SKILL.md
"""

import json
import hashlib
import logging
import math
import os
import re
import shutil
import stat
import tempfile
import time
import contextvars as _ctxvars
import uuid
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fabric_constants import get_fabric_home, get_skills_dir, display_fabric_home
from utils import atomic_replace, is_truthy_value
from fabric_cli.config import cfg_get

logger = logging.getLogger(__name__)


def _serialized_skill_writer(function):
    """Coordinate every editor entry point with Hub/sync/curator writers."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        from tools.skill_mutation import skill_mutation_lock

        with skill_mutation_lock(_skills_dir().parent):
            return function(*args, **kwargs)

    return wrapped

_background_review_read_paths: "_ctxvars.ContextVar[frozenset[str]]" = _ctxvars.ContextVar(
    "background_review_read_paths", default=frozenset()
)

# Approval replay may restore the original autonomous provenance so ownership
# guards and recoverable archive semantics remain intact. The human approval
# itself is the read/review boundary, so only the model-turn read-before-write
# check is bypassed during that exact replay.
_approved_skill_replay: "_ctxvars.ContextVar[bool]" = _ctxvars.ContextVar(
    "approved_skill_replay", default=False
)


def mark_background_review_skill_read(path: Path) -> None:
    """Record that the active autonomous fork has read a skill file.

    The autonomous review fork is allowed to evolve skills, but it must not
    patch or rewrite content it has only inferred from the transcript.  The
    skill_view tool calls this after returning file content to the model; write
    paths below require the corresponding target path to be present when the
    current origin is background review or curator.
    """
    try:
        from tools.skill_provenance import is_autonomous_skill_writer
        if not is_autonomous_skill_writer():
            return
    except Exception:
        return

    try:
        resolved = str(path.resolve())
    except Exception:
        resolved = str(path)
    current = set(_background_review_read_paths.get())
    current.add(resolved)
    _background_review_read_paths.set(frozenset(current))


def _background_review_has_read(path: Path) -> bool:
    try:
        resolved = str(path.resolve())
    except Exception:
        resolved = str(path)
    return resolved in _background_review_read_paths.get()


def _reset_background_review_read_marks() -> None:
    """Test helper: clear read-before-write marks for the current context."""
    _background_review_read_paths.set(frozenset())

# Import security scanner — external hub installs always get scanned;
# agent-created skills only get scanned when skills.guard_agent_created is on.
try:
    from tools.skills_guard import scan_skill, should_allow_install, format_scan_report
    _GUARD_AVAILABLE = True
except ImportError:
    _GUARD_AVAILABLE = False


def _guard_agent_created_enabled() -> bool:
    """Read skills.guard_agent_created from config (default False).

    Off by default because the agent can already execute the same code
    paths via terminal() with no gate, so the scan adds friction without
    meaningful security.  Users who want belt-and-suspenders can turn it
    on via `fabric config set skills.guard_agent_created true`.
    """
    try:
        from fabric_cli.config import load_config
        cfg = load_config()
        return is_truthy_value(
            cfg_get(cfg, "skills", "guard_agent_created"),
            default=False,
        )
    except Exception:
        return False


def _security_scan_skill(skill_dir: Path) -> Optional[str]:
    """Scan a skill directory after write. Returns error string if blocked, else None.

    No-op when skills.guard_agent_created is disabled (the default).
    """
    if not _GUARD_AVAILABLE:
        return None
    if not _guard_agent_created_enabled():
        return None
    try:
        result = scan_skill(skill_dir, source="agent-created")
        allowed, reason = should_allow_install(result)
        if allowed is False:
            report = format_scan_report(result)
            return f"Security scan blocked this skill ({reason}):\n{report}"
        if allowed is None:
            # "ask" verdict — for agent-created skills this means dangerous
            # findings were detected.  Surface as an error so the agent can
            # retry with the flagged content removed.
            report = format_scan_report(result)
            logger.warning("Agent-created skill blocked (dangerous findings): %s", reason)
            return f"Security scan blocked this skill ({reason}):\n{report}"
    except Exception as e:
        logger.warning("Security scan failed for %s: %s", skill_dir, e, exc_info=True)
    return None

import yaml


def _skills_dir() -> Path:
    """Return the active profile's skills directory at call time."""
    return get_skills_dir()

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024


def _containing_skills_root(skill_path: Path) -> Path:
    """Return the skills root directory (local or external_dirs entry) that
    contains ``skill_path``.  Falls back to the local ``SKILLS_DIR`` if no
    match is found (defensive — callers should have located the skill via
    ``_find_skill`` first).
    """
    from agent.skill_utils import get_all_skills_dirs

    try:
        resolved = skill_path.resolve()
    except OSError:
        resolved = skill_path

    roots = [_skills_dir(), *get_all_skills_dirs()]
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return root
        except (ValueError, OSError):
            continue
    return _skills_dir()


def _is_path_redirect(path: Path) -> bool:
    """True when ``path`` is a symlink or (on Windows) a directory junction.

    Either form lets a poisoned skills tree redirect a subsequent
    ``shutil.rmtree`` to content outside the skills root. ``is_junction``
    only exists on Python 3.12+ Windows; gate with ``hasattr``.
    """
    try:
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
    except OSError:
        return False


def _validate_delete_target(skill_dir: Path) -> Optional[str]:
    """Last-line guard before ``shutil.rmtree(skill_dir)`` in ``_delete_skill``.

    ``_find_skill`` already restricts ``skill_dir`` to a real ``SKILL.md``
    parent discovered by walking the skills roots, so the agent cannot inject
    an arbitrary path the way Kilo Code's HTTP endpoint could (their issue
    #11227: a built-in-skill sentinel resolved to the server cwd and a
    recursive delete wiped the user's entire working directory). This is the
    matching defense-in-depth for our agent-facing ``skill_manage`` delete
    path: even if discovery or a poisoned tree hands us a bad directory, never
    recursively delete

      1. a path that is not strictly *inside* one of the known skills roots,
      2. a skills root itself (would wipe every installed skill), or
      3. a directory reached via a symlink / junction (``rmtree`` would follow
         it into content outside the skills tree).

    Returns an error string to refuse on, or ``None`` when the delete is safe.
    """
    from agent.skill_utils import get_all_skills_dirs

    # (3) Reject symlink/junction redirects on the skill directory itself.
    if _is_path_redirect(skill_dir):
        return (
            f"Refusing to delete '{skill_dir}': the skill directory is a "
            f"symlink/junction. Remove the link target manually if intended."
        )

    try:
        resolved = skill_dir.resolve()
    except OSError as exc:
        return f"Refusing to delete '{skill_dir}': could not resolve path ({exc})."

    roots = []
    for root in get_all_skills_dirs():
        try:
            roots.append(root.resolve())
        except OSError:
            continue

    for root in roots:
        # (2) Never rmtree a skills root itself.
        if resolved == root:
            return (
                f"Refusing to delete '{skill_dir}': resolves to the skills root "
                f"itself, which would remove every installed skill."
            )
        # (1) Must be strictly inside a known root.
        try:
            rel = resolved.relative_to(root)
        except ValueError:
            continue
        if rel.parts:  # at least one component below the root
            return None

    return (
        f"Refusing to delete '{skill_dir}': path does not resolve inside any "
        f"known skills root."
    )


def _pinned_guard(name: str) -> Optional[str]:
    """Return a refusal message if *name* is pinned, else None.

    Pin protects a skill from **deletion** — both the curator's auto-archive
    passes and the agent's ``skill_manage(action="delete")`` tool call. The
    agent can still patch/edit pinned skills; pin only guards against
    irrecoverable loss, not against content evolution.

    Best-effort: if the sidecar is unreadable we let the delete through
    rather than block on a broken telemetry file.
    """
    try:
        from tools import skill_usage
        rec = skill_usage.get_record(name)
        if rec.get("pinned"):
            return (
                f"Skill '{name}' is pinned and cannot be deleted by "
                f"skill_manage. Ask the user to run "
                f"`fabric curator unpin {name}` if they want to delete it. "
                f"Patches and edits are allowed on pinned skills; only "
                f"deletion is blocked."
            )
    except Exception:
        logger.debug("pinned-guard lookup failed for %s", name, exc_info=True)
    return None


def _background_review_write_guard(
    name: str,
    skill_dir: Path,
    action: str,
) -> Optional[Dict[str, Any]]:
    """Refuse autonomous curator writes to externally owned skills.

    Foreground agents may still perform user-directed edits to external,
    bundled, or hub-installed skills. The background review fork is different:
    it is autonomous lifecycle maintenance, so its write surface is restricted
    to local curator-owned sediment.
    """
    try:
        from tools.skill_provenance import is_autonomous_skill_writer
        if not is_autonomous_skill_writer():
            return None
    except Exception:
        return None

    # Pin must be respected by autonomous maintenance. The curator already
    # skips pinned skills from every auto-transition; the background review
    # fork is the same kind of autonomous, no-user-present actor, so it must
    # not write to a pinned skill either (issue #25839). This is stricter than
    # the foreground ``_pinned_guard`` (which only blocks deletion) precisely
    # because there is no user in the loop to consent to an edit here.
    try:
        from tools import skill_usage
        if skill_usage.get_record(name).get("pinned"):
            return {
                "success": False,
                "error": (
                    f"Refusing background curator {action} for pinned skill "
                    f"'{name}': pinned skills are off-limits to autonomous "
                    "maintenance. Ask the user to run "
                    f"`fabric curator unpin {name}` if they want it changed."
                ),
            }
    except Exception:
        logger.debug("pinned skill guard lookup failed for %s", name, exc_info=True)

    try:
        from agent.skill_utils import is_external_skill_path
        if is_external_skill_path(skill_dir):
            return {
                "success": False,
                "error": (
                    f"Refusing background curator {action} for skill '{name}': "
                    "the skill lives in skills.external_dirs, which are "
                    "externally owned and read-only to autonomous curation."
                ),
            }
    except Exception:
        logger.debug("external skill guard lookup failed for %s", name, exc_info=True)

    try:
        from tools import skill_usage
        if skill_usage.is_protected_builtin(name):
            return {
                "success": False,
                "error": (
                    f"Refusing background curator {action} for protected "
                    f"built-in skill '{name}'."
                ),
            }
        if skill_usage.is_hub_installed(name):
            return {
                "success": False,
                "error": (
                    f"Refusing background curator {action} for hub-installed "
                    f"skill '{name}'."
                ),
            }
        if skill_usage.is_bundled(name):
            return {
                "success": False,
                "error": (
                    f"Refusing background curator {action} for bundled "
                    f"skill '{name}'."
                ),
            }
    except Exception:
        logger.debug("owned skill guard lookup failed for %s", name, exc_info=True)
    return None


def _background_review_read_before_write_guard(
    name: str,
    target: Path,
    action: str,
    file_label: str,
) -> Optional[Dict[str, Any]]:
    """Require review forks to load the exact target before mutating it."""
    if _approved_skill_replay.get():
        return None
    try:
        from tools.skill_provenance import is_autonomous_skill_writer
        if not is_autonomous_skill_writer():
            return None
    except Exception:
        return None

    if _background_review_has_read(target):
        return None

    return {
        "success": False,
        "error": (
            f"Refusing background curator {action} for skill '{name}': "
            f"the current {file_label} content has not been loaded in this "
            "review turn. Call skill_view(name) for SKILL.md, or "
            "skill_view(name, file_path=...) for a supporting file, then "
            "retry the write using the content just returned."
        ),
        "_read_before_write_required": True,
    }


def _background_review_preflight(
    action: str,
    name: str,
    file_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if action not in {"edit", "patch", "delete", "write_file", "remove_file"}:
        return None
    existing = _find_skill(name)
    if not existing:
        return None
    guard = _background_review_write_guard(name, existing["path"], action)
    if guard:
        return guard

    # Preserve the autonomous read-before-write contract even though governed
    # writes now stage before the action handler runs. New support files have
    # no prior bytes to read; existing targets do.
    if action in {"edit", "patch", "write_file", "remove_file"}:
        skill_dir = existing["path"]
        if action == "edit" or not file_path:
            target = skill_dir / "SKILL.md"
            label = "SKILL.md"
        else:
            err = _validate_file_path(file_path)
            if err:
                return {"success": False, "error": err}
            target, err = _resolve_skill_target(skill_dir, file_path)
            if err:
                return {"success": False, "error": err}
            assert target is not None
            label = file_path
        if target.exists():
            return _background_review_read_before_write_guard(
                name, target, action, label
            )
    return None


def _curator_consolidation_delete_guard(
    name: str, absorbed_into: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Fail closed on unverified deletes during the curator consolidation pass.

    The curator's forked review agent (``is_autonomous_skill_writer()``) runs the
    LLM umbrella-building pass. Its only legitimate ``skill_manage(delete)`` is
    a *verified consolidation*: the skill's content was absorbed into an
    umbrella, declared via ``absorbed_into=<umbrella>`` where the umbrella
    exists on disk (validated separately in ``_delete_skill``).

    A delete with no forwarding target — ``absorbed_into`` omitted (``None``)
    or empty (``""``) — is the fail-open behavior reported in #29912: the
    consolidation pass archived whole clusters of active skills with zero
    verified consolidations (``consolidated_this_run == 0``), leaving active
    automations pointing at names that no longer resolve. The deterministic
    inactivity prune is the only legitimate prune path, and it archives via
    ``skill_usage.archive_skill()`` directly without ever calling
    ``skill_manage`` — so a bare prune reaching here can only be the LLM pass
    pruning without consolidation evidence. Refuse it; keep the skill active.

    Returns an error dict to abort the delete, or ``None`` when the delete is
    allowed to proceed (not the curator pass, or a declared consolidation).
    """
    try:
        from tools.skill_provenance import is_autonomous_skill_writer
        if not is_autonomous_skill_writer():
            return None
    except Exception:
        return None

    declared = isinstance(absorbed_into, str) and absorbed_into.strip()
    if declared:
        return None

    return {
        "success": False,
        "error": (
            f"Refusing background curator delete of skill '{name}': the "
            "consolidation pass may only archive a skill it has absorbed into "
            "an umbrella. Pass absorbed_into=<umbrella> (the umbrella must "
            "already exist) to record a verified consolidation. Pruning a "
            "skill with no forwarding target is not permitted here — the "
            "deterministic inactivity prune handles staleness archival "
            "separately. Keeping '{name}' active.".format(name=name)
        ),
        "_fail_closed": True,
    }


MAX_SKILL_CONTENT_CHARS = 100_000   # ~36k tokens at 2.75 chars/token
MAX_SKILL_FILE_BYTES = 1_048_576    # 1 MiB per supporting file

# Characters allowed in skill names (filesystem-safe, URL-friendly)
VALID_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._-]*$')

# Subdirectories allowed for write_file/remove_file. ``evals`` is governance
# data, never executable configuration. The only additional root-level file
# accepted by this API is the closed ``skill.contract.yaml`` contract below.
ALLOWED_SUBDIRS = {"references", "templates", "scripts", "assets", "evals"}


# =============================================================================
# Validation helpers
# =============================================================================

def _validate_name(name: str) -> Optional[str]:
    """Validate a skill name. Returns error message or None if valid."""
    if not name:
        return "Skill name is required."
    if len(name) > MAX_NAME_LENGTH:
        return f"Skill name exceeds {MAX_NAME_LENGTH} characters."
    if not VALID_NAME_RE.match(name):
        return (
            f"Invalid skill name '{name}'. Use lowercase letters, numbers, "
            f"hyphens, dots, and underscores. Must start with a letter or digit."
        )
    return None


def _validate_category(category: Optional[str]) -> Optional[str]:
    """Validate an optional category name used as a single directory segment."""
    if category is None:
        return None
    if not isinstance(category, str):
        return "Category must be a string."

    category = category.strip()
    if not category:
        return None
    if "/" in category or "\\" in category:
        return (
            f"Invalid category '{category}'. Use lowercase letters, numbers, "
            "hyphens, dots, and underscores. Categories must be a single directory name."
        )
    if len(category) > MAX_NAME_LENGTH:
        return f"Category exceeds {MAX_NAME_LENGTH} characters."
    if not VALID_NAME_RE.match(category):
        return (
            f"Invalid category '{category}'. Use lowercase letters, numbers, "
            "hyphens, dots, and underscores. Categories must be a single directory name."
        )
    return None


def _validate_frontmatter(content: str) -> Optional[str]:
    """
    Validate that SKILL.md content has proper frontmatter with required fields.
    Returns error message or None if valid.
    """
    if not content.strip():
        return "Content cannot be empty."

    if not content.startswith("---"):
        return "SKILL.md must start with YAML frontmatter (---). See existing skills for format."

    end_match = re.search(r'\n---\s*\n', content[3:])
    if not end_match:
        return "SKILL.md frontmatter is not closed. Ensure you have a closing '---' line."

    yaml_content = content[3:end_match.start() + 3]

    try:
        parsed = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        return f"YAML frontmatter parse error: {e}"

    if not isinstance(parsed, dict):
        return "Frontmatter must be a YAML mapping (key: value pairs)."

    if "name" not in parsed:
        return "Frontmatter must include 'name' field."
    if "description" not in parsed:
        return "Frontmatter must include 'description' field."
    if len(str(parsed["description"])) > MAX_DESCRIPTION_LENGTH:
        return f"Description exceeds {MAX_DESCRIPTION_LENGTH} characters."

    body = content[end_match.end() + 3:].strip()
    if not body:
        return "SKILL.md must have content after the frontmatter (instructions, procedures, etc.)."

    return None


def _validate_content_size(content: str, label: str = "SKILL.md") -> Optional[str]:
    """Check that content doesn't exceed the character limit for agent writes.

    Returns an error message or None if within bounds.
    """
    if len(content) > MAX_SKILL_CONTENT_CHARS:
        return (
            f"{label} content is {len(content):,} characters "
            f"(limit: {MAX_SKILL_CONTENT_CHARS:,}). "
            f"Consider splitting into a smaller SKILL.md with supporting files "
            f"in references/ or templates/."
        )
    return None


def _resolve_skill_dir(name: str, category: str = None) -> Path:
    """Build the directory path for a new skill, optionally under a category."""
    if category:
        return _skills_dir() / category / name
    return _skills_dir() / name


def _validate_new_skill_destination(destination: Path) -> Optional[str]:
    """Refuse creation through redirected category/skill path components."""
    root = _skills_dir()
    try:
        resolved_root = root.resolve(strict=False)
        resolved_destination = destination.resolve(strict=False)
        relative = destination.relative_to(root)
        resolved_destination.relative_to(resolved_root)
    except (OSError, ValueError):
        return "Skill destination escapes the active skills directory."
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if _is_path_redirect(current):
                return (
                    "Skill destination contains a symlink/junction and cannot "
                    f"be written safely: {current}"
                )
    return None


def _find_skill(name: str) -> Optional[Dict[str, Any]]:
    """
    Find a skill by name across all skill directories.

    Searches the local skills dir (~/.fabric/skills/) first, then any
    external dirs configured via skills.external_dirs.  Returns
    {"path": Path} or None.
    """
    from agent.skill_utils import get_all_skills_dirs, is_excluded_skill_path
    for skills_dir in get_all_skills_dirs():
        if not skills_dir.exists():
            continue
        for skill_md in skills_dir.rglob("SKILL.md"):
            if is_excluded_skill_path(skill_md):
                continue
            if skill_md.parent.name == name:
                return {"path": skill_md.parent}
    return None


def _find_skill_in_other_profiles(name: str) -> List[Tuple[str, Path]]:
    """Look for ``name`` under SKILL.md across OTHER Fabric profiles.

    Returns a list of ``(profile_name, skill_dir)`` pairs. Used to make
    the "Skill X not found" error explain when the user is editing the
    wrong profile. Empty list when no other profile has the skill (or
    when profile discovery fails — fail-quiet, the caller falls back to
    the plain "not found" error).
    """
    matches: List[Tuple[str, Path]] = []
    try:
        from fabric_constants import get_default_fabric_root
        from agent.skill_utils import is_excluded_skill_path
    except Exception:
        return matches

    try:
        root = get_default_fabric_root()
    except Exception:
        return matches

    # Collect (profile_name, skills_dir) for every profile EXCEPT the
    # one whose skills dir we already searched in _find_skill().
    _active = _skills_dir()
    active_dir = _active.resolve() if _active.exists() else _active
    candidates: List[Tuple[str, Path]] = []

    # Default profile (~/.fabric/skills) — only consider when active is non-default.
    default_skills = root / "skills"
    try:
        if default_skills.resolve() != active_dir:
            candidates.append(("default", default_skills))
    except (OSError, RuntimeError):
        pass

    # All named profiles (~/.fabric/profiles/*/skills)
    profiles_root = root / "profiles"
    if profiles_root.is_dir():
        try:
            for entry in profiles_root.iterdir():
                if not entry.is_dir():
                    continue
                pskills = entry / "skills"
                try:
                    if pskills.resolve() == active_dir:
                        continue
                except (OSError, RuntimeError):
                    continue
                candidates.append((entry.name, pskills))
        except OSError:
            pass

    for profile_name, skills_dir in candidates:
        if not skills_dir.is_dir():
            continue
        try:
            for skill_md in skills_dir.rglob("SKILL.md"):
                if is_excluded_skill_path(skill_md):
                    continue
                if skill_md.parent.name == name:
                    matches.append((profile_name, skill_md.parent))
                    break  # one match per profile is enough
        except OSError:
            continue
    return matches


def _skill_not_found_error(name: str, suffix: str = "") -> str:
    """Build a "skill not found" error that names other profiles holding
    the same skill, so the agent can recognize a profile-scoping mistake.

    ``suffix`` is appended after the cross-profile hint if present
    (e.g. ``" Create it first with action='create'."``).
    """
    from agent.file_safety import _resolve_active_profile_name
    active = _resolve_active_profile_name()
    base = f"Skill '{name}' not found in active profile '{active}'."

    others = _find_skill_in_other_profiles(name)
    if others:
        if len(others) == 1:
            other_profile, other_path = others[0]
            base += (
                f" A skill by that name exists in profile "
                f"'{other_profile}' ({other_path}). To edit a skill in "
                f"another profile, switch profiles (`fabric -p "
                f"{other_profile}`) or operate via explicit file tools "
                f"with ``cross_profile=True``."
            )
        else:
            names = ", ".join(f"'{p}'" for p, _ in others)
            base += (
                f" Skills by that name exist in other profiles: {names}. "
                f"Switch profiles (`fabric -p <name>`) to edit there, or "
                f"operate via explicit file tools with ``cross_profile=True``."
            )
    else:
        base += " Use skills_list() to see available skills."

    if suffix:
        base += suffix
    return base


def _validate_file_path(file_path: str) -> Optional[str]:
    """
    Validate a file path for write_file/remove_file.
    Must be under an allowed subdirectory and not escape the skill dir.
    """
    from tools.path_security import has_traversal_component

    if not file_path:
        return "file_path is required."

    normalized = Path(file_path)

    # Prevent path traversal (checked before any allow-listing so the SKILL.md
    # exception below can never be reached by a traversal-laden path).
    if has_traversal_component(file_path):
        return "Path traversal ('..') is not allowed."

    # SKILL.md and the governed contract live at the skill root. Accept their
    # natural root spelling (and the historical name-prefixed SKILL.md form).
    # The traversal guard above still applies, so neither can escape.
    if normalized.parts and normalized.name == "SKILL.md":
        if len(normalized.parts) == 1 or len(normalized.parts) == 2:
            return None
    if normalized.parts == ("skill.contract.yaml",):
        return None

    # Must be under an allowed subdirectory
    if not normalized.parts or normalized.parts[0] not in ALLOWED_SUBDIRS:
        allowed = ", ".join(sorted(ALLOWED_SUBDIRS))
        return f"File must be under one of: {allowed}. Got: '{file_path}'"

    # Must have a filename (not just a directory)
    if len(normalized.parts) < 2:
        return f"Provide a file path, not just a directory. Example: '{normalized.parts[0]}/myfile.md'"

    return None


def _resolve_skill_target(skill_dir: Path, file_path: str) -> Tuple[Optional[Path], Optional[str]]:
    """Resolve a supporting-file path and ensure it stays within the skill directory."""
    from tools.path_security import validate_within_dir

    target = skill_dir / file_path
    error = validate_within_dir(target, skill_dir)
    if error:
        return None, error
    return target, None


def _atomic_write_text(file_path: Path, content: str, encoding: str = "utf-8") -> None:
    """
    Atomically write text content to a file.
    
    Uses a temporary file in the same directory and os.replace() to ensure
    the target file is never left in a partially-written state if the process
    crashes or is interrupted.
    
    Args:
        file_path: Target file path
        content: Content to write
        encoding: Text encoding (default: utf-8)
    """
    missing_parents: List[Path] = []
    parent = file_path.parent
    while not parent.exists():
        missing_parents.append(parent)
        if parent == parent.parent:
            break
        parent = parent.parent
    file_path.parent.mkdir(parents=True, exist_ok=True)
    for created in reversed(missing_parents):
        os.chmod(created, 0o755)

    target_mode = 0o600
    try:
        existing_info = file_path.lstat()
        if stat.S_ISREG(existing_info.st_mode) and not file_path.is_symlink():
            target_mode = stat.S_IMODE(existing_info.st_mode)
    except FileNotFoundError:
        pass
    fd, temp_path = tempfile.mkstemp(
        dir=str(file_path.parent),
        prefix=f".{file_path.name}.tmp.",
        suffix="",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            os.fchmod(f.fileno(), target_mode)
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        atomic_replace(temp_path, file_path)
        if os.name != "nt":
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            parent_fd = os.open(file_path.parent, flags)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except OSError:
            logger.error("Failed to remove temporary file %s during atomic write", temp_path, exc_info=True)
        raise


# =============================================================================
# Core actions
# =============================================================================

@_serialized_skill_writer
def _create_skill(name: str, content: str, category: str = None) -> Dict[str, Any]:
    """Create a new user skill with SKILL.md content."""
    # Validate name
    err = _validate_name(name)
    if err:
        return {"success": False, "error": err}

    err = _validate_category(category)
    if err:
        return {"success": False, "error": err}

    # Validate content
    err = _validate_frontmatter(content)
    if err:
        return {"success": False, "error": err}

    err = _validate_content_size(content)
    if err:
        return {"success": False, "error": err}

    # Check for name collisions across all directories
    existing = _find_skill(name)
    if existing:
        return {
            "success": False,
            "error": f"A skill named '{name}' already exists at {existing['path']}."
        }

    # Create the skill directory
    skill_dir = _resolve_skill_dir(name, category)
    destination_error = _validate_new_skill_destination(skill_dir)
    if destination_error:
        return {"success": False, "error": destination_error}
    missing_dirs: List[Path] = []
    candidate = skill_dir
    while candidate != _skills_dir() and not candidate.exists():
        missing_dirs.append(candidate)
        candidate = candidate.parent
    skill_dir.mkdir(parents=True, exist_ok=True)
    for created in reversed(missing_dirs):
        os.chmod(created, 0o755)

    # Write SKILL.md atomically
    skill_md = skill_dir / "SKILL.md"
    _atomic_write_text(skill_md, content)

    # Security scan — roll back on block
    scan_error = _security_scan_skill(skill_dir)
    if scan_error:
        shutil.rmtree(skill_dir, ignore_errors=True)
        return {"success": False, "error": scan_error}

    # Extract description from frontmatter for verbose notifications
    _desc = ""
    try:
        _fm_end = re.search(r'\n---\s*\n', content[3:])
        if _fm_end:
            _parsed = yaml.safe_load(content[3:_fm_end.start() + 3])
            _desc = str(_parsed.get("description", ""))[:120]
    except Exception:
        pass

    result = {
        "success": True,
        "message": f"Skill '{name}' created.",
        "path": str(skill_dir.relative_to(_skills_dir())),
        "skill_md": str(skill_md),
        "_change": {"description": _desc},
    }
    if category:
        result["category"] = category
    result["hint"] = (
        "To add reference files, templates, or scripts, use "
        "skill_manage(action='write_file', name='{}', file_path='references/example.md', file_content='...')".format(name)
    )
    return result


@_serialized_skill_writer
def _edit_skill(name: str, content: str) -> Dict[str, Any]:
    """Replace the SKILL.md of any existing skill (full rewrite)."""
    err = _validate_frontmatter(content)
    if err:
        return {"success": False, "error": err}

    err = _validate_content_size(content)
    if err:
        return {"success": False, "error": err}

    existing = _find_skill(name)
    if not existing:
        return {"success": False, "error": _skill_not_found_error(name)}
    guard = _background_review_write_guard(name, existing["path"], "edit")
    if guard:
        return guard

    skill_md = existing["path"] / "SKILL.md"
    read_guard = _background_review_read_before_write_guard(
        name, skill_md, "edit", "SKILL.md"
    )
    if read_guard:
        return read_guard

    # Back up original content for rollback
    original_content = skill_md.read_text(encoding="utf-8") if skill_md.exists() else None
    _atomic_write_text(skill_md, content)

    # Security scan — roll back on block
    scan_error = _security_scan_skill(existing["path"])
    if scan_error:
        if original_content is not None:
            _atomic_write_text(skill_md, original_content)
        return {"success": False, "error": scan_error}

    # Extract description from new content for verbose notifications
    _desc = ""
    try:
        _fm_end = re.search(r'\n---\s*\n', content[3:])
        if _fm_end:
            _parsed = yaml.safe_load(content[3:_fm_end.start() + 3])
            _desc = str(_parsed.get("description", ""))[:120]
    except Exception:
        pass

    return {
        "success": True,
        "message": f"Skill '{name}' updated (full rewrite).",
        "path": str(existing["path"]),
        "_change": {"description": _desc},
    }


@_serialized_skill_writer
def _patch_skill(
    name: str,
    old_string: str,
    new_string: str,
    file_path: str = None,
    replace_all: bool = False,
) -> Dict[str, Any]:
    """Targeted find-and-replace within a skill file.

    Defaults to SKILL.md. Use file_path to patch a supporting file instead.
    Requires a unique match unless replace_all is True.
    """
    if not old_string:
        return {"success": False, "error": "old_string is required for 'patch'."}
    if new_string is None:
        return {"success": False, "error": "new_string is required for 'patch'. Use an empty string to delete matched text."}

    existing = _find_skill(name)
    if not existing:
        return {"success": False, "error": _skill_not_found_error(name)}

    skill_dir = existing["path"]
    guard = _background_review_write_guard(name, skill_dir, "patch")
    if guard:
        return guard

    if file_path:
        # Patching a supporting file
        err = _validate_file_path(file_path)
        if err:
            return {"success": False, "error": err}
        target, err = _resolve_skill_target(skill_dir, file_path)
        if err:
            return {"success": False, "error": err}
        assert target is not None
    else:
        # Patching SKILL.md
        target = skill_dir / "SKILL.md"

    if not target.exists():
        return {"success": False, "error": f"File not found: {target.relative_to(skill_dir)}"}

    read_guard = _background_review_read_before_write_guard(
        name,
        target,
        "patch",
        "SKILL.md" if not file_path else file_path,
    )
    if read_guard:
        return read_guard

    content = target.read_text(encoding="utf-8")

    # One pure transform powers execution, pending validation, and preview so
    # the bytes a user reviews are exactly the bytes replay will write.
    new_content, match_count, match_error = _compute_patch_content(
        content, old_string, new_string, replace_all
    )
    if match_error or new_content is None:
        # Show a short preview of the file so the model can self-correct
        preview = content[:500] + ("..." if len(content) > 500 else "")
        return {
            "success": False,
            "error": match_error or "Patch did not produce content.",
            "file_preview": preview,
        }

    # Check size limit on the result
    target_label = "SKILL.md" if not file_path else file_path
    err = _validate_content_size(new_content, label=target_label)
    if err:
        return {"success": False, "error": err}

    # If patching SKILL.md, validate frontmatter is still intact
    if not file_path:
        err = _validate_frontmatter(new_content)
        if err:
            return {
                "success": False,
                "error": f"Patch would break SKILL.md structure: {err}",
            }

    original_content = content  # for rollback
    _atomic_write_text(target, new_content)

    # Security scan — roll back on block
    scan_error = _security_scan_skill(skill_dir)
    if scan_error:
        _atomic_write_text(target, original_content)
        return {"success": False, "error": scan_error}

    result = {
        "success": True,
        "message": f"Patched {'SKILL.md' if not file_path else file_path} in skill '{name}' ({match_count} replacement{'s' if match_count > 1 else ''}).",
    }
    # Include change previews for verbose notifications
    result["_change"] = {
        "old": old_string[:200] + ("…" if len(old_string) > 200 else ""),
        "new": new_string[:200] + ("…" if len(new_string) > 200 else ""),
    }
    return result


@_serialized_skill_writer
def _delete_skill(name: str, absorbed_into: Optional[str] = None) -> Dict[str, Any]:
    """Delete a skill.

    ``absorbed_into`` declares intent:
      - ``None`` / missing  → caller didn't declare (legacy / non-curator path);
        accepted for backward compat but logs a warning because the curator
        classification pipeline can't tell consolidation from pruning without it.
      - ``""`` (empty)      → explicit "truly pruned, no forwarding target".
      - ``"<skill-name>"``  → content was absorbed into that umbrella; the
        target must exist on disk. Validated here so the model can't claim an
        umbrella that doesn't exist.
    """
    existing = _find_skill(name)
    if not existing:
        return {"success": False, "error": _skill_not_found_error(name)}
    guard = _background_review_write_guard(name, existing["path"], "delete")
    if guard:
        return guard

    # Fail closed on unverified deletes during the curator consolidation pass.
    # A bare prune (no absorbed_into) from the LLM umbrella pass is the
    # fail-open behavior reported in #29912 — refuse it; keep the skill active.
    fail_closed = _curator_consolidation_delete_guard(name, absorbed_into)
    if fail_closed:
        return fail_closed

    pinned_err = _pinned_guard(name)
    if pinned_err:
        return {"success": False, "error": pinned_err}

    # Validate absorbed_into target when declared non-empty
    absorbed_target = (
        absorbed_into.strip()
        if absorbed_into is not None and isinstance(absorbed_into, str)
        else ""
    )
    is_consolidation = bool(absorbed_target)
    if is_consolidation:
        target_name = absorbed_target
        if target_name == name:
            return {
                "success": False,
                "error": f"absorbed_into='{target_name}' cannot equal the skill being deleted.",
            }
        target = _find_skill(target_name)
        if not target:
            return {
                "success": False,
                "error": (
                    f"absorbed_into='{target_name}' does not exist. "
                    f"Create or patch the umbrella skill first, then retry the delete."
                ),
            }

    skill_dir = existing["path"]
    skills_root = _containing_skills_root(skill_dir)

    # Defense-in-depth before the recursive delete (port of Kilo Code #11240).
    unsafe = _validate_delete_target(skill_dir)
    if unsafe:
        return {"success": False, "error": unsafe}

    # During the curator consolidation pass, a verified consolidation must be
    # RECOVERABLE: archival into ~/.fabric/skills/.archive/ is documented as
    # the maximum destructive action the curator may take, and
    # `fabric curator restore` promises the skill can be brought back. Route
    # through the recoverable archive primitive instead of permanent rmtree so
    # a misjudged consolidation can be undone (#29912). Foreground,
    # user-directed deletes keep their existing hard-delete semantics.
    try:
        from tools.skill_provenance import is_autonomous_skill_writer
        curator_pass = is_autonomous_skill_writer()
    except Exception:
        curator_pass = False

    if curator_pass:
        try:
            from tools.skill_usage import archive_skill
            ok, archive_msg = archive_skill(name)
        except Exception as e:
            return {"success": False, "error": f"failed to archive '{name}': {e}"}
        if not ok:
            return {"success": False, "error": archive_msg}
        message = f"Skill '{name}' archived ({archive_msg})."
        if is_consolidation:
            message += f" Content absorbed into '{absorbed_target}'."
        return {"success": True, "message": message, "_archived": True}

    shutil.rmtree(skill_dir)

    # Clean up empty category directories (don't remove the skills root itself)
    parent = skill_dir.parent
    if parent != skills_root and parent.exists() and not any(parent.iterdir()):
        parent.rmdir()

    message = f"Skill '{name}' deleted."
    if is_consolidation:
        message += f" Content absorbed into '{absorbed_target}'."

    return {
        "success": True,
        "message": message,
    }


@_serialized_skill_writer
def _write_file(name: str, file_path: str, file_content: str) -> Dict[str, Any]:
    """Add or overwrite a supporting file within any skill directory."""
    err = _validate_file_path(file_path)
    if err:
        return {"success": False, "error": err}

    if not file_content and file_content != "":
        return {"success": False, "error": "file_content is required."}

    # Check size limits
    content_bytes = len(file_content.encode("utf-8"))
    if content_bytes > MAX_SKILL_FILE_BYTES:
        return {
            "success": False,
            "error": (
                f"File content is {content_bytes:,} bytes "
                f"(limit: {MAX_SKILL_FILE_BYTES:,} bytes / 1 MiB). "
                f"Consider splitting into smaller files."
            ),
        }
    err = _validate_content_size(file_content, label=file_path)
    if err:
        return {"success": False, "error": err}

    existing = _find_skill(name)
    if not existing:
        return {"success": False, "error": _skill_not_found_error(name, " Create it first with action='create'.")}
    guard = _background_review_write_guard(name, existing["path"], "write_file")
    if guard:
        return guard

    target, err = _resolve_skill_target(existing["path"], file_path)
    if err:
        return {"success": False, "error": err}
    assert target is not None
    if target.exists():
        read_guard = _background_review_read_before_write_guard(
            name, target, "write_file", file_path
        )
        if read_guard:
            return read_guard
    target.parent.mkdir(parents=True, exist_ok=True)
    # Back up for rollback
    original_content = target.read_text(encoding="utf-8") if target.exists() else None
    _atomic_write_text(target, file_content)

    # Security scan — roll back on block
    scan_error = _security_scan_skill(existing["path"])
    if scan_error:
        if original_content is not None:
            _atomic_write_text(target, original_content)
        else:
            target.unlink(missing_ok=True)
        return {"success": False, "error": scan_error}

    return {
        "success": True,
        "message": f"File '{file_path}' written to skill '{name}'.",
        "path": str(target),
    }


@_serialized_skill_writer
def _remove_file(name: str, file_path: str) -> Dict[str, Any]:
    """Remove a supporting file from any skill directory."""
    err = _validate_file_path(file_path)
    if err:
        return {"success": False, "error": err}

    existing = _find_skill(name)
    if not existing:
        return {"success": False, "error": _skill_not_found_error(name)}

    skill_dir = existing["path"]
    guard = _background_review_write_guard(name, skill_dir, "remove_file")
    if guard:
        return guard

    target, err = _resolve_skill_target(skill_dir, file_path)
    if err:
        return {"success": False, "error": err}
    assert target is not None
    if not target.exists():
        # List what's actually there for the model to see
        available = []
        for subdir in ALLOWED_SUBDIRS:
            d = skill_dir / subdir
            if d.exists():
                for f in d.rglob("*"):
                    if f.is_file():
                        available.append(str(f.relative_to(skill_dir)))
        return {
            "success": False,
            "error": f"File '{file_path}' not found in skill '{name}'.",
            "available_files": available if available else None,
        }

    read_guard = _background_review_read_before_write_guard(
        name, target, "remove_file", file_path
    )
    if read_guard:
        return read_guard

    target.unlink()

    # Clean up empty subdirectories
    parent = target.parent
    if parent != skill_dir and parent.exists() and not any(parent.iterdir()):
        parent.rmdir()

    return {
        "success": True,
        "message": f"File '{file_path}' removed from skill '{name}'.",
    }


# =============================================================================
# Governed draft planning, optimistic concurrency, and previews
# =============================================================================

_PENDING_ACTIONS = {
    "create",
    "edit",
    "patch",
    "delete",
    "write_file",
    "remove_file",
}
_PENDING_PAYLOAD_KEYS = {
    "action",
    "name",
    "content",
    "category",
    "file_path",
    "file_content",
    "old_string",
    "new_string",
    "replace_all",
    "absorbed_into",
}
_PENDING_RECORD_ID_RE = re.compile(r"^(?:[0-9a-f]{8}|[0-9a-f]{32})$")
_PENDING_BATCH_ID_RE = re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f]{64})$")


@dataclass
class _VirtualEntry:
    kind: str
    data: bytes
    mode: int


@dataclass
class _VirtualSkill:
    name: str
    path: Path
    entries: Dict[str, _VirtualEntry]


def _capture_virtual_skill(name: str, path: Path) -> _VirtualSkill:
    """Read a skill tree without following redirects.

    The complete tree (rather than only the target file) is fingerprinted so
    promotion cannot silently overwrite a concurrent edit to a sibling
    reference, script, or asset.
    """
    if _is_path_redirect(path):
        raise ValueError(f"Skill '{name}' is a symlink/junction and cannot be promoted safely.")
    entries: Dict[str, _VirtualEntry] = {}
    try:
        root_info = path.lstat()
    except OSError as exc:
        raise ValueError(f"Could not inspect skill '{name}': {exc}") from exc
    if not stat.S_ISDIR(root_info.st_mode):
        raise ValueError(f"Skill '{name}' is not stored in a regular directory.")
    entries[""] = _VirtualEntry("directory", b"", stat.S_IMODE(root_info.st_mode))

    for current, directory_names, file_names in os.walk(path, followlinks=False):
        current_path = Path(current)
        for child_name in list(directory_names):
            child = current_path / child_name
            rel = child.relative_to(path).as_posix()
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode):
                entries[rel] = _VirtualEntry(
                    "symlink",
                    os.fsencode(os.readlink(child)),
                    stat.S_IMODE(info.st_mode),
                )
                directory_names.remove(child_name)
            elif stat.S_ISDIR(info.st_mode):
                entries[rel] = _VirtualEntry(
                    "directory", b"", stat.S_IMODE(info.st_mode)
                )
            else:
                raise ValueError(f"Unsupported entry type in skill '{name}': {rel}")
        for child_name in file_names:
            child = current_path / child_name
            rel = child.relative_to(path).as_posix()
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode):
                entries[rel] = _VirtualEntry(
                    "symlink",
                    os.fsencode(os.readlink(child)),
                    stat.S_IMODE(info.st_mode),
                )
            elif stat.S_ISREG(info.st_mode):
                entries[rel] = _VirtualEntry(
                    "file", child.read_bytes(), stat.S_IMODE(info.st_mode)
                )
            else:
                raise ValueError(f"Unsupported entry type in skill '{name}': {rel}")
    return _VirtualSkill(name=name, path=path.resolve(), entries=entries)


def _virtual_tree_digest(skill: _VirtualSkill) -> str:
    digest = hashlib.sha256()
    for rel, entry in sorted(skill.entries.items()):
        for part in (
            rel.encode("utf-8"),
            entry.kind.encode("ascii"),
            f"{entry.mode:o}".encode("ascii"),
            entry.data,
        ):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()


def _virtual_precondition(skill: Optional[_VirtualSkill], *, name: str, path: Path) -> Dict[str, Any]:
    if skill is None:
        return {
            "schema_version": 1,
            "kind": "skill_absent",
            "name": name,
            "path": str(path.resolve(strict=False)),
        }
    return {
        "schema_version": 1,
        "kind": "skill_tree",
        "name": name,
        "path": str(skill.path),
        "sha256": _virtual_tree_digest(skill),
    }


def _virtual_skill(
    state: Dict[str, Optional[_VirtualSkill]], name: str
) -> Optional[_VirtualSkill]:
    if name in state:
        return state[name]
    found = _find_skill(name)
    if found is None:
        state[name] = None
    else:
        state[name] = _capture_virtual_skill(name, found["path"])
    return state[name]


def _virtual_target_rel(skill: _VirtualSkill, file_path: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not file_path:
        return "SKILL.md", None
    err = _validate_file_path(file_path)
    if err:
        return None, err
    target, err = _resolve_skill_target(skill.path, file_path)
    if err:
        return None, err
    assert target is not None
    try:
        return target.relative_to(skill.path).as_posix(), None
    except ValueError:
        return None, "Skill file path escapes the skill directory."


def _ensure_virtual_parent_dirs(skill: _VirtualSkill, rel: str) -> Optional[str]:
    parts = Path(rel).parts[:-1]
    current: List[str] = []
    for part in parts:
        current.append(part)
        key = Path(*current).as_posix()
        existing = skill.entries.get(key)
        if existing is not None and existing.kind != "directory":
            return f"Cannot write '{rel}': '{key}' is not a directory."
        if existing is None:
            skill.entries[key] = _VirtualEntry("directory", b"", 0o755)
    return None


def _compute_patch_content(
    content: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
) -> Tuple[Optional[str], int, Optional[str]]:
    """Pure patch transform shared by execution, draft validation, and preview."""
    from tools.fuzzy_match import fuzzy_find_and_replace

    new_content, match_count, _strategy, match_error = fuzzy_find_and_replace(
        content, old_string, new_string, replace_all
    )
    if match_error:
        err_msg = match_error
        try:
            from tools.fuzzy_match import format_no_match_hint

            err_msg += format_no_match_hint(
                match_error, match_count, old_string, content
            )
        except Exception:
            pass
        return None, match_count, err_msg
    return new_content, match_count, None


def _pending_origin_validation_error(origin: str) -> Optional[str]:
    try:
        from tools.skill_provenance import QUARANTINED_SKILL_ORIGINS

        supported = {"foreground", "assistant_tool"}.union(
            QUARANTINED_SKILL_ORIGINS
        )
    except Exception as exc:
        return (
            "Skill draft provenance validation is unavailable; refusing the "
            f"write safely ({exc})."
        )
    if origin not in supported:
        return f"Unsupported draft origin: {origin!r}."
    return None


def _validate_pending_origin_guard(
    *,
    origin: str,
    action: str,
    name: str,
    skill: Optional[_VirtualSkill],
    absorbed_into: object,
) -> Optional[str]:
    origin_error = _pending_origin_validation_error(origin)
    if origin_error:
        return origin_error
    from tools.skill_provenance import BACKGROUND_REVIEW

    if origin != BACKGROUND_REVIEW or skill is None:
        return None

    from tools.skill_provenance import (
        reset_current_write_origin,
        set_current_write_origin,
    )

    token = set_current_write_origin(origin)
    try:
        guard = _background_review_write_guard(name, skill.path, action)
        if guard:
            return str(guard.get("error") or "Background skill mutation refused.")
        if action == "delete":
            guard = _curator_consolidation_delete_guard(
                name,
                absorbed_into if isinstance(absorbed_into, str) else None,
            )
            if guard:
                return str(guard.get("error") or "Background skill deletion refused.")
    finally:
        reset_current_write_origin(token)
    return None


def _plan_pending_payload(
    state: Dict[str, Optional[_VirtualSkill]],
    payload: Dict[str, Any],
    *,
    origin: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Validate one payload and apply it to an in-memory skill-tree model."""
    if not isinstance(payload, dict):
        return None, "Draft payload must be a mapping."
    unknown = sorted(set(payload) - _PENDING_PAYLOAD_KEYS)
    if unknown:
        return None, f"Draft payload has unsupported field(s): {', '.join(unknown)}."
    action = payload.get("action")
    name = payload.get("name")
    if not isinstance(action, str) or action not in _PENDING_ACTIONS:
        return None, f"Unknown skill action {action!r}."
    if not isinstance(name, str):
        return None, "Skill name must be a string."
    err = _validate_name(name)
    if err:
        return None, err
    if "replace_all" in payload and not isinstance(payload["replace_all"], bool):
        return None, "replace_all must be a boolean."

    skill = _virtual_skill(state, name)
    guard_error = _validate_pending_origin_guard(
        origin=origin,
        action=action,
        name=name,
        skill=skill,
        absorbed_into=payload.get("absorbed_into"),
    )
    if guard_error:
        return None, guard_error
    if action == "create":
        content = payload.get("content")
        category = payload.get("category")
        if not isinstance(content, str) or not content:
            return None, "content is required for 'create'."
        err = _validate_category(category)
        if err:
            return None, err
        err = _validate_frontmatter(content) or _validate_content_size(content)
        if err:
            return None, err
        destination = _resolve_skill_dir(name, category)
        destination_error = _validate_new_skill_destination(destination)
        if destination_error:
            return None, destination_error
        precondition = _virtual_precondition(None, name=name, path=destination)
        if skill is not None:
            return None, f"A skill named '{name}' already exists at {skill.path}."
        if destination.exists():
            return None, f"Skill destination already exists: {destination}."
        state[name] = _VirtualSkill(
            name=name,
            path=destination.resolve(strict=False),
            entries={
                "": _VirtualEntry("directory", b"", 0o755),
                "SKILL.md": _VirtualEntry("file", content.encode("utf-8"), 0o600),
            },
        )
        return {
            "action": action,
            "name": name,
            "skill_path": str(destination.resolve(strict=False)),
            "precondition": precondition,
            "target": "SKILL.md",
            "before": None,
            "after": content.encode("utf-8"),
        }, None

    if skill is None:
        return None, _skill_not_found_error(name)

    precondition = _virtual_precondition(skill, name=name, path=skill.path)

    if action == "edit":
        content = payload.get("content")
        if not isinstance(content, str) or not content:
            return None, "content is required for 'edit'."
        err = _validate_frontmatter(content) or _validate_content_size(content)
        if err:
            return None, err
        current = skill.entries.get("SKILL.md")
        if current is None or current.kind != "file":
            return None, "Existing skill has no regular SKILL.md file."
        before = current.data
        after = content.encode("utf-8")
        skill.entries["SKILL.md"] = _VirtualEntry("file", after, current.mode)
        return {
            "action": action,
            "name": name,
            "skill_path": str(skill.path),
            "precondition": precondition,
            "target": "SKILL.md",
            "before": before,
            "after": after,
        }, None

    if action in {"patch", "write_file", "remove_file"}:
        raw_path = payload.get("file_path")
        if action in {"write_file", "remove_file"} and not isinstance(raw_path, str):
            return None, f"file_path is required for '{action}'."
        if raw_path is not None and not isinstance(raw_path, str):
            return None, "file_path must be a string."
        rel, err = _virtual_target_rel(skill, raw_path)
        if err:
            return None, err
        assert rel is not None
        current = skill.entries.get(rel)

        if action == "patch":
            old_string = payload.get("old_string")
            new_string = payload.get("new_string")
            if not isinstance(old_string, str) or not old_string:
                return None, "old_string is required for 'patch'."
            if not isinstance(new_string, str):
                return None, "new_string is required for 'patch'."
            if current is None or current.kind != "file":
                return None, f"File not found or not regular: {rel}"
            try:
                current_text = current.data.decode("utf-8")
            except UnicodeDecodeError:
                return None, f"File is not valid UTF-8 and cannot be patched: {rel}"
            new_content, match_count, patch_error = _compute_patch_content(
                current_text,
                old_string,
                new_string,
                payload.get("replace_all", False),
            )
            if patch_error or new_content is None:
                return None, patch_error or "Patch did not produce content."
            err = _validate_content_size(new_content, label=rel)
            if rel == "SKILL.md":
                err = err or _validate_frontmatter(new_content)
            if err:
                return None, err
            before = current.data
            after = new_content.encode("utf-8")
            skill.entries[rel] = _VirtualEntry("file", after, current.mode)
            return {
                "action": action,
                "name": name,
                "skill_path": str(skill.path),
                "precondition": precondition,
                "target": rel,
                "before": before,
                "after": after,
                "match_count": match_count,
            }, None

        if action == "write_file":
            file_content = payload.get("file_content")
            if not isinstance(file_content, str):
                return None, "file_content is required for 'write_file'."
            encoded = file_content.encode("utf-8")
            if len(encoded) > MAX_SKILL_FILE_BYTES:
                return None, (
                    f"File content is {len(encoded):,} bytes "
                    f"(limit: {MAX_SKILL_FILE_BYTES:,} bytes / 1 MiB)."
                )
            err = _validate_content_size(file_content, label=rel)
            if err:
                return None, err
            if rel == "SKILL.md":
                err = _validate_frontmatter(file_content)
                if err:
                    return None, err
            if current is not None and current.kind != "file":
                return None, f"Target is not a regular file: {rel}"
            err = _ensure_virtual_parent_dirs(skill, rel)
            if err:
                return None, err
            before = current.data if current is not None else None
            skill.entries[rel] = _VirtualEntry(
                "file", encoded, current.mode if current is not None else 0o600
            )
            return {
                "action": action,
                "name": name,
                "skill_path": str(skill.path),
                "precondition": precondition,
                "target": rel,
                "before": before,
                "after": encoded,
            }, None

        if rel == "SKILL.md":
            return None, "Use action='delete' to remove a skill; SKILL.md cannot be removed as a supporting file."
        if current is None or current.kind != "file":
            return None, f"File '{rel}' not found or not regular in skill '{name}'."
        before = current.data
        del skill.entries[rel]
        parent = Path(rel).parent.as_posix()
        if parent != "." and not any(
            key != parent and key.startswith(f"{parent}/") for key in skill.entries
        ):
            skill.entries.pop(parent, None)
        return {
            "action": action,
            "name": name,
            "skill_path": str(skill.path),
            "precondition": precondition,
            "target": rel,
            "before": before,
            "after": None,
        }, None

    assert action == "delete"
    absorbed_into = payload.get("absorbed_into")
    if absorbed_into is not None and not isinstance(absorbed_into, str):
        return None, "absorbed_into must be a string when provided."
    absorbed_target = absorbed_into.strip() if isinstance(absorbed_into, str) else ""
    if absorbed_target:
        if absorbed_target == name:
            return None, f"absorbed_into='{name}' cannot equal the skill being deleted."
        if _virtual_skill(state, absorbed_target) is None:
            return None, f"absorbed_into='{absorbed_target}' does not exist."
    pinned_error = _pinned_guard(name)
    if pinned_error:
        return None, pinned_error
    unsafe = _validate_delete_target(skill.path)
    if unsafe:
        return None, unsafe
    before_tree = {
        key: _VirtualEntry(value.kind, value.data, value.mode)
        for key, value in skill.entries.items()
    }
    state[name] = None
    return {
        "action": action,
        "name": name,
        "skill_path": str(skill.path),
        "precondition": precondition,
        "target": None,
        "before": None,
        "after": None,
        "before_tree": before_tree,
    }, None


def _ordered_pending_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    batch_started: Dict[str, float] = {}
    for record in records:
        batch_id = str(record.get("batch_id") or record.get("id") or "")
        raw_created_at = record.get("created_at", 0)
        created_at = (
            float(raw_created_at)
            if isinstance(raw_created_at, (int, float))
            and not isinstance(raw_created_at, bool)
            and math.isfinite(float(raw_created_at))
            else float("inf")
        )
        batch_started[batch_id] = min(batch_started.get(batch_id, created_at), created_at)
    return sorted(
        records,
        key=lambda record: (
            batch_started[str(record.get("batch_id") or record.get("id") or "")],
            str(record.get("batch_id") or record.get("id") or ""),
            (
                record.get("ordinal", 0)
                if isinstance(record.get("ordinal", 0), int)
                and not isinstance(record.get("ordinal", 0), bool)
                else 2**63
            ),
            str(record.get("id", "")),
        ),
    )


def _prepare_skill_pending_records(
    records: List[Dict[str, Any]],
    *,
    require_preconditions: bool,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    batch_ordinals: Dict[str, List[int]] = {}
    for record in records:
        if not isinstance(record, dict) or record.get("subsystem") != "skills":
            return [], "Invalid skill draft record."
        record_id = record.get("id")
        batch_id = record.get("batch_id")
        ordinal = record.get("ordinal")
        created_at = record.get("created_at")
        payload = record.get("payload")
        if not isinstance(record_id, str) or not _PENDING_RECORD_ID_RE.fullmatch(record_id):
            return [], "Invalid skill draft id."
        if record.get("lifecycle") != "draft":
            return [], f"Skill draft {record_id} is not in the draft lifecycle."
        if not isinstance(batch_id, str) or not _PENDING_BATCH_ID_RE.fullmatch(batch_id):
            return [], f"Skill draft {record_id} has an invalid batch id."
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
            return [], f"Skill draft {record_id} has an invalid batch ordinal."
        if (
            isinstance(created_at, bool)
            or not isinstance(created_at, (int, float))
            or not math.isfinite(float(created_at))
        ):
            return [], f"Skill draft {record_id} has an invalid creation time."
        if not isinstance(payload, dict) or record.get("action") != payload.get("action"):
            return [], f"Skill draft {record_id} has inconsistent action metadata."
        batch_ordinals.setdefault(batch_id, []).append(ordinal)
    for batch_id, ordinals in batch_ordinals.items():
        if sorted(ordinals) != list(range(len(ordinals))):
            return [], f"Skill draft batch {batch_id[:8]} has missing or duplicate actions."

    state: Dict[str, Optional[_VirtualSkill]] = {}
    plans: List[Dict[str, Any]] = []
    for record in _ordered_pending_records(records):
        if not isinstance(record, dict) or record.get("subsystem") != "skills":
            return [], "Invalid skill draft record."
        payload = record.get("payload")
        origin = record.get("origin", "foreground")
        if not isinstance(origin, str):
            return [], "Invalid skill draft origin."
        stored = record.get("precondition")
        if isinstance(payload, dict) and isinstance(stored, dict):
            pending_name = payload.get("name")
            if isinstance(pending_name, str):
                current = _virtual_skill(state, pending_name)
                if stored.get("kind") == "skill_absent":
                    destination = _resolve_skill_dir(
                        pending_name, payload.get("category")
                    )
                    if current is not None or destination.exists():
                        return [], (
                            f"Draft conflict for skill '{pending_name}': active "
                            "content changed after this draft was staged. The "
                            "draft was retained; review the new active version "
                            "and restage or reject it."
                        )
                elif stored.get("kind") == "skill_tree":
                    current_state = _virtual_precondition(
                        current,
                        name=pending_name,
                        path=current.path if current is not None else _skills_dir() / pending_name,
                    )
                    if current is None or current_state != stored:
                        return [], (
                            f"Draft conflict for skill '{pending_name}': active "
                            "content changed after this draft was staged. The "
                            "draft was retained; review the new active version "
                            "and restage or reject it."
                        )
        plan, error = _plan_pending_payload(state, payload, origin=origin)
        if error or plan is None:
            return [], error or "Could not prepare skill draft."
        if stored is None and require_preconditions:
            return [], (
                f"Draft {record.get('id', '<unknown>')} predates optimistic "
                "concurrency protection; reject it and stage a fresh draft."
            )
        if stored is not None and stored != plan["precondition"]:
            return [], (
                f"Draft conflict for skill '{plan['name']}': active content "
                "changed after this draft was staged. The draft was retained; "
                "review the new active version and restage or reject it."
            )
        post_skill = state.get(plan["name"])
        post_path = (
            post_skill.path
            if post_skill is not None
            else Path(plan["skill_path"])
        )
        plan["postcondition"] = _virtual_precondition(
            post_skill,
            name=plan["name"],
            path=post_path,
        )
        plan["record"] = record
        plans.append(plan)
    return plans, None


def _governance_virtual_state(
    records: List[Dict[str, Any]],
) -> Tuple[Dict[str, Optional[_VirtualSkill]], Dict[str, Optional[Path]]]:
    """Return exact final touched trees plus their pre-batch active locations.

    This is called only after ``_prepare_skill_pending_records`` has validated
    the same immutable records under the shared writer lock. Replaying the
    pure planner here gives the promotion gate complete final trees without
    widening the durable plan/journal schema with raw candidate bytes.
    """

    touched = {
        str(record.get("payload", {}).get("name"))
        for record in records
        if isinstance(record.get("payload"), dict)
        and isinstance(record["payload"].get("name"), str)
    }
    current_dirs: Dict[str, Optional[Path]] = {}
    for name in touched:
        found = _find_skill(name)
        current_dirs[name] = Path(found["path"]) if found is not None else None

    state: Dict[str, Optional[_VirtualSkill]] = {}
    for record in _ordered_pending_records(records):
        plan, error = _plan_pending_payload(
            state,
            record.get("payload"),
            origin=str(record.get("origin", "foreground")),
        )
        if error or plan is None:
            raise RuntimeError(error or "Could not reconstruct governed skill candidate.")
    return ({name: state.get(name) for name in sorted(touched)}, current_dirs)


def _plan_new_skill_pending_payload(
    payload: Dict[str, Any],
    *,
    origin: str,
    prior_records: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    state: Dict[str, Optional[_VirtualSkill]] = {}
    for record in _ordered_pending_records(prior_records):
        plan, error = _plan_pending_payload(
            state,
            record.get("payload"),
            origin=str(record.get("origin", "foreground")),
        )
        if error or plan is None:
            return None, error or "Could not validate the existing draft batch."
        if record.get("precondition") != plan["precondition"]:
            return None, (
                "The existing draft batch conflicts with the active skill tree; "
                "reject or promote it before adding another action."
            )
    return _plan_pending_payload(state, payload, origin=origin)


# =============================================================================
# Main entry point
# =============================================================================

# ContextVar bypass: set while replaying an already-approved staged skill write
# so skill_manage() does not re-gate (and re-stage) it.
import contextvars as _ctxvars
_skill_gate_bypass: "_ctxvars.ContextVar[bool]" = _ctxvars.ContextVar(
    "skill_gate_bypass", default=False
)
_skill_batch_replay: "_ctxvars.ContextVar[bool]" = _ctxvars.ContextVar(
    "skill_batch_replay", default=False
)


def _apply_skill_write_gate(
    action,
    name,
    *,
    pending_batch_key: Optional[str] = None,
    **payload_kwargs,
):
    """Evaluate the skill write gate. Returns a JSON tool-result string when the
    write should NOT proceed (blocked or staged), or None to perform the real
    write. Bypassed during approved-pending replay.
    """
    if action not in {"create", "edit", "patch", "delete", "write_file", "remove_file"}:
        return None
    if _skill_gate_bypass.get():
        return None

    # The scheduled curator has a separate snapshot/rollback lifecycle.  It
    # shares autonomous ownership guards with background review, but routing
    # its multi-action consolidation through per-action pending drafts would
    # split one atomic plan into a mixture of staged and live mutations.
    try:
        from tools.skill_provenance import is_curator

        if is_curator():
            return None
    except Exception:
        pass

    try:
        from tools import write_approval as wa
    except Exception:
        return tool_error(
            "Skill write governance is unavailable; refusing the write safely.",
            success=False,
        )

    origin = wa.current_origin(fail_closed=True)
    origin_error = _pending_origin_validation_error(origin)
    if origin_error:
        return tool_error(origin_error, success=False)
    decision = wa.evaluate_gate(wa.SKILLS)
    if decision.allow:
        return None
    if decision.blocked:
        return tool_error(decision.message, success=False)

    # stage — record the full skill_manage kwargs so approval can replay it.
    payload = {"action": action, "name": name}
    payload.update({k: v for k, v in payload_kwargs.items() if v is not None})
    gist = wa.skill_gist(
        action, name,
        content=payload_kwargs.get("content") or "",
        file_path=payload_kwargs.get("file_path") or "",
        old_string=payload_kwargs.get("old_string") or "",
        new_string=payload_kwargs.get("new_string") or "",
    )
    from tools.skill_mutation import skill_mutation_lock

    # Batch selection, validation, fingerprinting, and persistence share the
    # active-tree writer lock. This prevents two concurrent tool calls in one
    # turn from assigning the same ordinal against different base states.
    with skill_mutation_lock(_skills_dir().parent):
        all_pending = wa.list_pending(wa.SKILLS)
        if pending_batch_key:
            batch_material = "\0".join(
                (str(get_fabric_home().resolve()), origin, pending_batch_key)
            )
            batch_id = hashlib.sha256(batch_material.encode("utf-8")).hexdigest()
        else:
            # Direct/library callers do not carry the runtime task id. Preserve
            # the useful create→support-file workflow, but never group two
            # unrelated edits merely because they target the same skill.
            batches: Dict[str, List[Dict[str, Any]]] = {}
            for candidate in all_pending:
                candidate_batch = candidate.get("batch_id")
                if isinstance(candidate_batch, str):
                    batches.setdefault(candidate_batch, []).append(candidate)
            matching: List[Dict[str, Any]] = []
            if action != "create":
                for candidate_batch in batches.values():
                    ordered_batch = _ordered_pending_records(candidate_batch)
                    first_payload = ordered_batch[0].get("payload", {}) if ordered_batch else {}
                    if (
                        ordered_batch
                        and ordered_batch[0].get("origin") == origin
                        and isinstance(first_payload, dict)
                        and first_payload.get("action") == "create"
                        and first_payload.get("name") == name
                    ):
                        matching.extend(ordered_batch)
            batch_id = (
                str(max(matching, key=lambda r: r.get("created_at", 0))["batch_id"])
                if matching
                else uuid.uuid4().hex
            )
        prior = [
            record for record in all_pending if record.get("batch_id") == batch_id
        ]
        plan, validation_error = _plan_new_skill_pending_payload(
            payload,
            origin=origin,
            prior_records=prior,
        )
        if validation_error or plan is None:
            return tool_error(
                "Skill draft was not staged: "
                + (validation_error or "validation failed."),
                success=False,
            )
        record = wa.stage_write(
            wa.SKILLS,
            payload,
            summary=gist,
            origin=origin,
            batch_id=batch_id,
            ordinal=len(prior),
            precondition=plan["precondition"],
        )
    if record.get("_persisted") is not True:
        return tool_error(
            "Could not persist the quarantined skill draft. The active skill "
            "library was not changed; check profile storage permissions and "
            "retry.",
            success=False,
        )
    return json.dumps(
        {"success": True, "staged": True, "pending_id": record["id"],
         "gist": gist, "message": decision.message},
        ensure_ascii=False,
    )


_PROMOTION_SCHEMA_VERSION = 1
_PROMOTION_TX_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_PROMOTION_MAX_TRANSACTIONS = 32
_PROMOTION_MAX_BYTES = 512 * 1024 * 1024
_PROMOTION_MAX_DECISIONS = 128
_PROMOTION_TERMINAL_PHASES = {
    "finalized",
    "rolled_back",
    "rolled_back_after_commit",
}


def _skill_pending_dir() -> Path:
    return get_fabric_home() / "pending" / "skills"


def _skill_transaction_root() -> Path:
    return _skill_pending_dir() / ".transactions"


def _skill_review_root() -> Path:
    return _skill_pending_dir() / ".reviews"


def _skill_governance_root() -> Path:
    return _skill_pending_dir() / ".governance"


def _skill_evaluation_root() -> Path:
    return _skill_governance_root() / "evaluations"


def _skill_decision_root() -> Path:
    return _skill_pending_dir() / ".decisions"


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_nearest_directory(path: Path) -> None:
    current = path
    while current != current.parent and not current.exists():
        current = current.parent
    if current.exists() and current.is_dir() and not current.is_symlink():
        _fsync_dir(current)


def _ensure_private_dir(path: Path) -> None:
    missing: List[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        if current == current.parent:
            break
        current = current.parent
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"Unsafe promotion state directory: {path}")
    for created in reversed(missing):
        try:
            os.chmod(created, 0o700)
        except OSError:
            pass
        if created.parent.exists():
            _fsync_dir(created.parent)


def _atomic_json(path: Path, value: Dict[str, Any]) -> None:
    _ensure_private_dir(path.parent)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _load_json_file(path: Path) -> Dict[str, Any]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or path.is_symlink():
        raise RuntimeError(f"Unsafe promotion state file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise RuntimeError(f"Promotion state changed while opening: {path}")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            value = json.load(handle)
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(value, dict):
        raise RuntimeError(f"Invalid promotion state file: {path}")
    return value


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _record_digest(record: Dict[str, Any]) -> str:
    return _canonical_digest(record)


def _plan_projection(plan: Dict[str, Any]) -> Dict[str, Any]:
    projection: Dict[str, Any] = {
        "action": plan["action"],
        "name": plan["name"],
        "skill_path": plan["skill_path"],
        "target": plan.get("target"),
        "precondition": plan["precondition"],
        "postcondition": plan["postcondition"],
        "before_sha256": (
            hashlib.sha256(plan["before"]).hexdigest()
            if isinstance(plan.get("before"), bytes)
            else None
        ),
        "after_sha256": (
            hashlib.sha256(plan["after"]).hexdigest()
            if isinstance(plan.get("after"), bytes)
            else None
        ),
    }
    if "before_tree" in plan:
        virtual = _VirtualSkill(
            name=plan["name"],
            path=Path(plan["skill_path"]),
            entries=plan["before_tree"],
        )
        projection["deleted_tree_sha256"] = _virtual_tree_digest(virtual)
    return projection


def _batch_digest(
    batch_id: str,
    records: List[Dict[str, Any]],
    plans: List[Dict[str, Any]],
) -> str:
    return _canonical_digest(
        {
            "schema_version": _PROMOTION_SCHEMA_VERSION,
            "batch_id": batch_id,
            "records": records,
            "plans": [_plan_projection(plan) for plan in plans],
        }
    )


def _analyze_skill_batch_governance(
    batch_id: str,
    records: List[Dict[str, Any]],
    batch_digest: str,
):
    """Return the exact governed projection, or ``None`` for foreground work."""

    from agent.skill_promotion_gates import analyze_governed_batch

    final_skills, current_dirs = _governance_virtual_state(records)
    return analyze_governed_batch(
        batch_id=batch_id,
        batch_digest=batch_digest,
        records=records,
        final_skills=final_skills,
        current_skill_dirs=current_dirs,
        temporary_root=_skill_governance_root(),
    )


def _review_path(batch_id: str) -> Path:
    if not _PENDING_BATCH_ID_RE.fullmatch(batch_id):
        raise ValueError("Invalid skill draft batch id.")
    root = _skill_review_root()
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise RuntimeError(f"Unsafe skill review directory: {root}")
    return root / f"{batch_id}.json"


def _evaluation_path(batch_id: str) -> Path:
    if not _PENDING_BATCH_ID_RE.fullmatch(batch_id):
        raise ValueError("Invalid skill draft batch id.")
    root = _skill_evaluation_root()
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise RuntimeError(f"Unsafe skill evaluation directory: {root}")
    return root / f"{batch_id}.json"


def _invalidate_skill_batch_evaluation(batch_id: str) -> None:
    """Invalidate an exact passing eval attestation after candidate changes."""

    path = _evaluation_path(batch_id)
    if path.is_symlink():
        raise RuntimeError(f"Unsafe skill evaluation attestation: {path}")
    if path.exists():
        path.unlink()
        _fsync_dir(path.parent)


def _skill_evaluation_attestation_matches(
    evaluation: Dict[str, Any],
    governance,
    batch_digest: str,
    record_ids: List[str],
) -> bool:
    """Verify a persisted passing report against the exact governed bytes."""

    from agent.skill_promotion_gates import canonical_digest

    projection = governance.projection()
    reports = evaluation.get("reports")
    if not isinstance(reports, dict) or set(reports) != {
        candidate.name for candidate in governance.skills
    }:
        return False
    for candidate in governance.skills:
        report = reports.get(candidate.name)
        if (
            not isinstance(report, dict)
            or report.get("passed") is not True
            or report.get("lift_passed") is not True
            or report.get("manifest_digest") != candidate.eval_manifest_digest
            or report.get("failure_reasons") != []
        ):
            return False
    attestation_digest = evaluation.get("attestation_digest")
    digest_projection = {
        key: value
        for key, value in evaluation.items()
        if key != "attestation_digest"
    }
    return (
        evaluation.get("schema_version") == 1
        and evaluation.get("batch_id") == governance.batch_id
        and evaluation.get("batch_digest") == batch_digest
        and evaluation.get("governance_digest") == governance.digest
        and evaluation.get("record_ids") == record_ids
        and evaluation.get("origin") == governance.origin
        and evaluation.get("skills") == projection["skills"]
        and isinstance(attestation_digest, str)
        and canonical_digest(digest_projection) == attestation_digest
    )


def _invalidate_skill_batch_review(batch_id: str) -> None:
    """Invalidate review and eval attestations after membership changes."""
    path = _review_path(batch_id)
    if path.is_symlink():
        raise RuntimeError(f"Unsafe skill review attestation: {path}")
    if path.exists():
        path.unlink()
        _fsync_dir(path.parent)
    _invalidate_skill_batch_evaluation(batch_id)


def _write_journal(tx_dir: Path, journal: Dict[str, Any], phase: str) -> None:
    updated = dict(journal)
    updated["phase"] = phase
    updated["updated_at"] = time.time()
    if phase in _PROMOTION_TERMINAL_PHASES:
        updated["terminal_at"] = updated["updated_at"]
    _atomic_json(tx_dir / "journal.json", updated)
    journal.clear()
    journal.update(updated)


def _load_journal(tx_dir: Path) -> Dict[str, Any]:
    journal = _load_json_file(tx_dir / "journal.json")
    if (
        journal.get("schema_version") != _PROMOTION_SCHEMA_VERSION
        or journal.get("transaction_id") != tx_dir.name
    ):
        raise RuntimeError(f"Invalid skill promotion journal: {tx_dir}")
    return journal


def _remove_snapshot_target(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _fsync_tree(path: Path) -> None:
    if path.is_symlink():
        _fsync_dir(path.parent)
        return
    if path.is_file():
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        _fsync_dir(path.parent)
        return
    if not path.exists():
        return
    for current, directory_names, file_names in os.walk(path, followlinks=False):
        current_path = Path(current)
        for file_name in file_names:
            child = current_path / file_name
            if child.is_symlink():
                continue
            fd = os.open(child, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        for directory_name in directory_names:
            child = current_path / directory_name
            if not child.is_symlink():
                _fsync_dir(child)
        _fsync_dir(current_path)


def _snapshot_skill_batch(
    plans: List[Dict[str, Any]], snapshot_root: Path
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Capture durable prior bytes without snapshotting category siblings."""
    _ensure_private_dir(snapshot_root)
    candidates = {Path(plan["skill_path"]).resolve(strict=False) for plan in plans}
    skills_root = _skills_dir().resolve(strict=False)
    candidates.update(
        {
            skills_root / ".usage.json",
            skills_root / ".usage.json.lock",
            skills_root / ".curator_suppressed",
        }
    )
    if any(
        plan["action"] == "delete"
        and plan["record"].get("origin") == "background_review"
        for plan in plans
    ):
        candidates.add(skills_root / ".archive")

    snapshots: List[Dict[str, Any]] = []
    for index, path in enumerate(sorted(candidates, key=str)):
        backup = snapshot_root / f"item-{index}"
        kind = "missing"
        mode: Optional[int] = None
        if path.exists() or path.is_symlink():
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                kind = "symlink"
                backup.symlink_to(os.readlink(path), target_is_directory=path.is_dir())
            elif stat.S_ISDIR(info.st_mode):
                kind = "directory"
                shutil.copytree(path, backup, symlinks=True, copy_function=shutil.copy2)
            elif stat.S_ISREG(info.st_mode):
                kind = "file"
                shutil.copy2(path, backup, follow_symlinks=False)
            else:
                raise RuntimeError(f"Unsupported promotion snapshot target: {path}")
            _fsync_tree(backup)
        snapshots.append(
            {
                "path": str(path),
                "backup": backup.name,
                "kind": kind,
                "mode": mode,
            }
        )

    parents: List[Dict[str, Any]] = []
    seen_parents: set[str] = set()
    for plan in plans:
        skill_path = Path(plan["skill_path"]).resolve(strict=False)
        containing_root = _containing_skills_root(skill_path).resolve(strict=False)
        parent = skill_path.parent
        if parent == containing_root or str(parent) in seen_parents:
            continue
        seen_parents.add(str(parent))
        existed = parent.exists() and not parent.is_symlink()
        mode = stat.S_IMODE(parent.lstat().st_mode) if existed else None
        parents.append({"path": str(parent), "existed": existed, "mode": mode})
    _fsync_dir(snapshot_root)
    return snapshots, parents


def _is_allowed_promotion_target(path: Path) -> bool:
    from agent.skill_utils import get_all_skills_dirs

    try:
        # Resolve parents to catch redirected category components, but do not
        # follow the final component: a snapshot may legitimately need to
        # remove/restore that component *as a symlink*.
        resolved = path.parent.resolve(strict=False) / path.name
    except OSError:
        return False
    for root in [_skills_dir(), *get_all_skills_dirs()]:
        try:
            resolved.relative_to(root.resolve(strict=False))
            return resolved != root.resolve(strict=False)
        except (OSError, ValueError):
            continue
    return False


def _restore_skill_batch(
    tx_dir: Path,
    snapshots: List[Dict[str, Any]],
    parent_metadata: List[Dict[str, Any]],
) -> Optional[str]:
    errors: List[str] = []
    snapshot_root = tx_dir / "snapshot"
    try:
        for item in snapshots:
            path = Path(str(item.get("path", "")))
            backup_name = str(item.get("backup", ""))
            backup = snapshot_root / backup_name
            kind = item.get("kind")
            if not _is_allowed_promotion_target(path):
                raise RuntimeError(
                    "snapshot target is outside a configured skills root"
                )
            if not re.fullmatch(r"item-[0-9]+", backup_name):
                raise RuntimeError("invalid snapshot backup name")
            if kind == "directory" and (backup.is_symlink() or not backup.is_dir()):
                raise RuntimeError("directory snapshot backup is invalid")
            if kind == "symlink" and not backup.is_symlink():
                raise RuntimeError("symlink snapshot backup is invalid")
            if kind == "file" and (backup.is_symlink() or not backup.is_file()):
                raise RuntimeError("file snapshot backup is invalid")
            if kind not in {"missing", "directory", "symlink", "file"}:
                raise RuntimeError("unknown snapshot kind")
        for item in parent_metadata:
            if not _is_allowed_promotion_target(
                Path(str(item.get("path", "")))
            ):
                raise RuntimeError(
                    "parent metadata target is outside a skills root"
                )
    except Exception as exc:
        return f"snapshot validation failed: {exc}"

    for item in snapshots:
        path = Path(str(item.get("path", "")))
        backup_name = str(item.get("backup", ""))
        backup = snapshot_root / backup_name
        try:
            _remove_snapshot_target(path)
            if item.get("kind") == "missing":
                _fsync_nearest_directory(path.parent)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if item.get("kind") == "directory":
                if backup.is_symlink() or not backup.is_dir():
                    raise RuntimeError("directory snapshot backup is invalid")
                shutil.copytree(backup, path, symlinks=True, copy_function=shutil.copy2)
            elif item.get("kind") == "symlink":
                if not backup.is_symlink():
                    raise RuntimeError("symlink snapshot backup is invalid")
                path.symlink_to(os.readlink(backup), target_is_directory=backup.is_dir())
            elif item.get("kind") == "file":
                if backup.is_symlink() or not backup.is_file():
                    raise RuntimeError("file snapshot backup is invalid")
                shutil.copy2(backup, path, follow_symlinks=False)
            else:
                raise RuntimeError("unknown snapshot kind")
            if isinstance(item.get("mode"), int) and not path.is_symlink():
                os.chmod(path, int(item["mode"]))
            _fsync_tree(path)
        except Exception as exc:  # pragma: no cover - catastrophic storage failure
            errors.append(f"{path}: {exc}")
    for item in parent_metadata:
        parent = Path(str(item.get("path", "")))
        try:
            if not _is_allowed_promotion_target(parent):
                raise RuntimeError("parent metadata target is outside a skills root")
            if item.get("existed"):
                parent.mkdir(parents=True, exist_ok=True)
                if isinstance(item.get("mode"), int):
                    os.chmod(parent, int(item["mode"]))
                _fsync_dir(parent)
            elif parent.exists() and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                _fsync_dir(parent.parent)
        except Exception as exc:
            errors.append(f"{parent}: {exc}")
    return "; ".join(errors) if errors else None


def _directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for current, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += (Path(current) / name).lstat().st_size
            except OSError:
                pass
    return total


def _terminal_transactions() -> List[Tuple[Path, Dict[str, Any], int]]:
    root = _skill_transaction_root()
    if not root.exists():
        return []
    entries: List[Tuple[Path, Dict[str, Any], int]] = []
    for tx_dir in root.iterdir():
        if not tx_dir.is_dir() or tx_dir.is_symlink() or not _PROMOTION_TX_ID_RE.fullmatch(tx_dir.name):
            continue
        journal = _load_journal(tx_dir)
        if journal.get("phase") in _PROMOTION_TERMINAL_PHASES:
            entries.append((tx_dir, journal, _directory_size(tx_dir)))
    return entries


def _remove_transaction_directory(tx_dir: Path) -> Optional[str]:
    tombstone = tx_dir.parent / f".prune-{tx_dir.name}-{uuid.uuid4().hex}"
    os.replace(tx_dir, tombstone)
    _fsync_dir(tx_dir.parent)
    try:
        shutil.rmtree(tombstone)
        _fsync_dir(tx_dir.parent)
    except Exception as exc:
        return str(exc)
    return None


def _prune_skill_transactions(*, reserve_bytes: int = 0, reserve_count: int = 0) -> Optional[str]:
    entries = _terminal_transactions()
    latest_by_skill: Dict[str, Tuple[float, Path]] = {}
    for tx_dir, journal, _size in entries:
        if journal.get("phase") != "finalized":
            continue
        stamp = float(journal.get("terminal_at") or journal.get("updated_at") or 0)
        for name in journal.get("touched_skills", []):
            if not isinstance(name, str):
                continue
            previous = latest_by_skill.get(name)
            if previous is None or stamp > previous[0]:
                latest_by_skill[name] = (stamp, tx_dir)
    protected = {item[1] for item in latest_by_skill.values()}
    total_count = len(entries) + reserve_count
    total_bytes = sum(item[2] for item in entries) + reserve_bytes
    removable = sorted(
        (item for item in entries if item[0] not in protected),
        key=lambda item: float(item[1].get("terminal_at") or item[1].get("updated_at") or 0),
    )
    for tx_dir, _journal, size in removable:
        if total_count <= _PROMOTION_MAX_TRANSACTIONS and total_bytes <= _PROMOTION_MAX_BYTES:
            break
        cleanup_error = _remove_transaction_directory(tx_dir)
        if cleanup_error:
            return f"Could not prune an expired skill rollback receipt: {cleanup_error}"
        total_count -= 1
        total_bytes -= size
    if total_count > _PROMOTION_MAX_TRANSACTIONS or total_bytes > _PROMOTION_MAX_BYTES:
        return (
            "Skill rollback retention is full. Promotion was not started because "
            "the latest rollback pointer for an active skill would have to be deleted."
        )
    return None


def _prune_skill_decisions() -> None:
    root = _skill_decision_root()
    if not root.exists():
        return
    receipts = [
        path
        for path in root.glob("*.json")
        if path.is_file() and not path.is_symlink()
    ]
    receipts.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for path in receipts[_PROMOTION_MAX_DECISIONS:]:
        path.unlink(missing_ok=True)
    if len(receipts) > _PROMOTION_MAX_DECISIONS:
        _fsync_dir(root)


def _finish_rejecting_receipt(path: Path, receipt: Dict[str, Any]) -> int:
    """Durably finish one rejecting receipt after a full-record preflight."""
    from tools import write_approval as wa

    group_id = receipt.get("group_id")
    if isinstance(group_id, str) and _PENDING_BATCH_ID_RE.fullmatch(group_id):
        _invalidate_skill_batch_review(group_id)

    record_ids = receipt.get("record_ids")
    digests = receipt.get("record_digests")
    if not isinstance(record_ids, list) or not isinstance(digests, dict):
        raise RuntimeError("Invalid rejecting skill receipt metadata.")

    present: List[str] = []
    for pending_id in record_ids:
        if not isinstance(pending_id, str) or not wa.is_valid_pending_id(pending_id):
            raise RuntimeError(f"Invalid rejected skill draft id {pending_id!r}.")
        expected = digests.get(pending_id)
        if not isinstance(expected, str):
            raise RuntimeError(f"Missing rejected skill digest for {pending_id}.")
        record = wa._get_pending_unlocked(wa.SKILLS, pending_id)
        if record is None:
            continue
        if _record_digest(record) != expected:
            raise RuntimeError(
                f"Rejected skill draft {pending_id} changed before recovery."
            )
        present.append(pending_id)

    for pending_id in present:
        wa._discard_pending_unlocked(wa.SKILLS, pending_id)
    remaining = [
        pending_id
        for pending_id in present
        if wa._get_pending_unlocked(wa.SKILLS, pending_id) is not None
    ]
    if remaining:
        raise RuntimeError(
            "Could not delete rejected skill draft(s): " + ", ".join(remaining)
        )
    # `_discard_pending_unlocked` deliberately has a best-effort public API
    # and can report False after unlink when only its fsync failed. A strict
    # final directory fsync keeps the terminal receipt from outrunning those
    # deletions.
    _fsync_dir(_skill_pending_dir())

    updated = dict(receipt)
    updated["state"] = "rejected"
    updated["completed_at"] = time.time()
    _atomic_json(path, updated)
    receipt.clear()
    receipt.update(updated)
    return len(present)


def _claim_records(tx_dir: Path, record_metadata: List[Dict[str, Any]]) -> None:
    from tools import write_approval as wa

    claims = tx_dir / "claims"
    _ensure_private_dir(claims)
    pending = _skill_pending_dir()
    for item in record_metadata:
        pending_id = str(item["id"])
        source = pending / f"{pending_id}.json"
        destination = claims / f"{pending_id}.json"
        record = wa._get_pending_unlocked(wa.SKILLS, pending_id)
        if record is None or _record_digest(record) != item["sha256"]:
            raise RuntimeError(
                f"Skill draft {pending_id} changed before it could be claimed."
            )
        os.replace(source, destination)
        _fsync_dir(source.parent)
        _fsync_dir(destination.parent)


def _restore_claims(tx_dir: Path, journal: Dict[str, Any]) -> Optional[str]:
    from tools import write_approval as wa

    claims = tx_dir / "claims"
    pending = _skill_pending_dir()
    _ensure_private_dir(pending)
    validated: Dict[str, Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]] = {}
    for item in journal.get("records", []):
        pending_id = str(item.get("id", ""))
        if not wa.is_valid_pending_id(pending_id):
            return f"invalid claimed id {pending_id!r}"
        claim = claims / f"{pending_id}.json"
        destination = pending / f"{pending_id}.json"
        claimed = (
            wa._read_pending_record(claim, subsystem=wa.SKILLS, pending_id=pending_id)
            if claim.exists() and not claim.is_symlink()
            else None
        )
        existing = wa._get_pending_unlocked(wa.SKILLS, pending_id)
        expected = item.get("sha256")
        if not isinstance(expected, str):
            return f"missing claim digest {pending_id}"
        if claimed is not None and _record_digest(claimed) != expected:
            return f"claimed draft {pending_id} changed after transaction preparation"
        if existing is not None and _record_digest(existing) != expected:
            return f"pending draft {pending_id} collides with the transaction claim"
        if claimed is None and existing is None:
            return f"missing claim {pending_id}"
        if claimed is not None and existing is not None and claimed != existing:
            return f"pending id collision while restoring claim {pending_id}"
        validated[pending_id] = (claimed, existing)

    errors: List[str] = []
    for pending_id, (claimed, existing) in validated.items():
        claim = claims / f"{pending_id}.json"
        destination = pending / f"{pending_id}.json"
        if existing is not None or claimed is None:
            continue
        try:
            temporary = pending / f".{pending_id}.{uuid.uuid4().hex}.restore"
            shutil.copy2(claim, temporary, follow_symlinks=False)
            fd = os.open(temporary, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(temporary, destination)
            _fsync_dir(pending)
        except Exception as exc:
            errors.append(f"{pending_id}: {exc}")
    return "; ".join(errors) if errors else None


def _actual_postcondition(plan: Dict[str, Any]) -> Dict[str, Any]:
    path = Path(plan["skill_path"])
    if not _is_allowed_promotion_target(path):
        raise RuntimeError("skill postcondition path is outside a skills root")
    if not path.exists() and not path.is_symlink():
        return _virtual_precondition(None, name=plan["name"], path=path)
    actual = _capture_virtual_skill(plan["name"], path)
    return _virtual_precondition(actual, name=plan["name"], path=path)


def _owned_path_condition(path: Path) -> Dict[str, Any]:
    """Fingerprint a transaction-owned path without following redirects."""
    if not _is_allowed_promotion_target(path):
        raise RuntimeError("transaction-owned path is outside a skills root")
    if not path.exists() and not path.is_symlink():
        return {"path": str(path), "kind": "missing"}
    info = path.lstat()
    mode = stat.S_IMODE(info.st_mode)
    if stat.S_ISLNK(info.st_mode):
        target = os.fsencode(os.readlink(path))
        return {
            "path": str(path),
            "kind": "symlink",
            "mode": mode,
            "sha256": hashlib.sha256(target).hexdigest(),
        }
    if stat.S_ISREG(info.st_mode):
        return {
            "path": str(path),
            "kind": "file",
            "mode": mode,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    if stat.S_ISDIR(info.st_mode):
        tree = _capture_virtual_skill(f"transaction path {path.name}", path)
        return {
            "path": str(path),
            "kind": "directory",
            "mode": mode,
            "sha256": _virtual_tree_digest(tree),
        }
    raise RuntimeError(f"Unsupported transaction-owned path: {path}")


def _capture_owned_postconditions(
    snapshots: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    conditions: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in snapshots:
        raw_path = item.get("path")
        if not isinstance(raw_path, str) or raw_path in seen:
            raise RuntimeError("Invalid transaction-owned snapshot metadata.")
        seen.add(raw_path)
        conditions.append(_owned_path_condition(Path(raw_path)))
    return conditions


def _verify_owned_postconditions(journal: Dict[str, Any]) -> Optional[str]:
    expected = journal.get("owned_postconditions")
    if not isinstance(expected, list) or not expected:
        return "committed journal has no transaction-owned postconditions"
    for item in expected:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            return "committed journal has invalid transaction-owned metadata"
        try:
            actual = _owned_path_condition(Path(item["path"]))
        except Exception as exc:
            return f"could not verify transaction-owned state: {exc}"
        if actual != item:
            return f"transaction-owned path {item['path']} no longer matches its journal"
    return None


def _verify_skill_batch_post_state(plans: List[Dict[str, Any]]) -> Optional[str]:
    final_by_name: Dict[str, Dict[str, Any]] = {}
    for plan in plans:
        final_by_name[plan["name"]] = plan
    for name, plan in final_by_name.items():
        try:
            actual = _actual_postcondition(plan)
        except Exception as exc:
            return f"Could not verify promoted skill '{name}': {exc}"
        if actual != plan["postcondition"]:
            return (
                f"Promoted skill '{name}' did not match the reviewed post-state "
                "(bytes, modes, links, or tree membership changed)."
            )
    return None


def _verify_committed_journal_state(journal: Dict[str, Any]) -> Optional[str]:
    final = journal.get("final_postconditions")
    if not isinstance(final, dict) or not final:
        return "committed journal has no final postconditions"
    for name, item in final.items():
        if not isinstance(name, str) or not isinstance(item, dict):
            return "committed journal has invalid postcondition metadata"
        plan = {
            "name": name,
            "skill_path": item.get("skill_path"),
            "postcondition": item.get("postcondition"),
        }
        try:
            actual = _actual_postcondition(plan)
        except Exception as exc:
            return f"could not verify committed skill '{name}': {exc}"
        if actual != item.get("postcondition"):
            return f"committed skill '{name}' no longer matches its journal"
    return _verify_owned_postconditions(journal)


def _durably_publish_skill_batch_post_state(plans: List[Dict[str, Any]]) -> None:
    """Fsync every changed tree/sidecar before publishing ``committed``."""
    paths = {Path(plan["skill_path"]) for plan in plans}
    skills_root = _skills_dir().resolve(strict=False)
    paths.update(
        {
            skills_root / ".usage.json",
            skills_root / ".usage.json.lock",
            skills_root / ".curator_suppressed",
        }
    )
    if any(
        plan["action"] == "delete"
        and plan["record"].get("origin") == "background_review"
        for plan in plans
    ):
        paths.add(skills_root / ".archive")
    for path in sorted(paths, key=str):
        if path.exists() or path.is_symlink():
            _fsync_tree(path)
        _fsync_nearest_directory(path.parent)
    _fsync_nearest_directory(skills_root)


def _promotion_fault(_phase: str) -> None:
    """Fault-injection hook used by crash-recovery tests."""


def _invalidate_transaction_reviews(journal: Dict[str, Any]) -> None:
    for batch_id in journal.get("batch_ids", []):
        if isinstance(batch_id, str):
            _invalidate_skill_batch_review(batch_id)


def _clear_skill_prompt_cache() -> None:
    from agent.prompt_builder import clear_skills_system_prompt_cache

    clear_skills_system_prompt_cache(clear_snapshot=True)


def _defer_skill_prompt_cache_invalidation() -> None:
    from agent.prompt_builder import defer_skills_system_prompt_cache_invalidation

    defer_skills_system_prompt_cache_invalidation()


def _verify_skill_batch_pre_state(plans: List[Dict[str, Any]]) -> Optional[str]:
    """Recheck the exact active trees immediately before approved replay.

    The shared mutation lock coordinates Fabric writers, but it cannot stop a
    person or another process from editing a skill directly.  Promotion can do
    substantial governance and snapshot work after its initial optimistic
    concurrency check, so the active tree must be fingerprinted again before
    any reviewed action is replayed.  Only the first plan for each skill
    describes the pre-batch state; later plans describe virtual intermediate
    states within the same atomic batch.
    """

    first_by_name: Dict[str, Dict[str, Any]] = {}
    for plan in plans:
        first_by_name.setdefault(plan["name"], plan)
    for name, plan in first_by_name.items():
        try:
            actual = _actual_postcondition(plan)
        except Exception as exc:
            return f"Could not revalidate active skill '{name}': {exc}"
        if actual != plan.get("precondition"):
            return (
                f"Draft conflict for skill '{name}': active content changed "
                "immediately before promotion. The out-of-band edit was "
                "preserved and the draft remains pending; review the active "
                "version, then restage or reject the draft."
            )
    return None


def _finalize_committed_transaction(tx_dir: Path, journal: Dict[str, Any]) -> None:
    _invalidate_transaction_reviews(journal)
    _write_journal(tx_dir, journal, "finalized")


def _recover_skill_pending_transactions_locked() -> None:
    pending_root = _skill_pending_dir()
    for component in (pending_root.parent, pending_root):
        if component.exists() and (
            component.is_symlink() or not component.is_dir()
        ):
            raise RuntimeError(f"Unsafe skill pending directory: {component}")
    root = _skill_transaction_root()
    if root.exists() and root.is_symlink():
        raise RuntimeError(f"Unsafe skill transaction directory: {root}")
    if root.exists():
        for orphan in root.iterdir():
            if re.fullmatch(
                r"(?:\.[0-9a-f]{32}\.preparing|\.prune-[0-9a-f]{32}-[0-9a-f]{32})",
                orphan.name,
            ):
                if orphan.is_symlink():
                    raise RuntimeError(f"Unsafe orphan promotion directory: {orphan}")
                if orphan.is_dir():
                    shutil.rmtree(orphan)
                    _fsync_dir(root)
        for tx_dir in sorted(root.iterdir(), key=lambda item: item.name):
            if not tx_dir.is_dir() or tx_dir.is_symlink() or not _PROMOTION_TX_ID_RE.fullmatch(tx_dir.name):
                continue
            journal = _load_journal(tx_dir)
            phase = journal.get("phase")
            if phase in _PROMOTION_TERMINAL_PHASES:
                continue
            if phase == "committed":
                verification_error = _verify_committed_journal_state(journal)
                if verification_error:
                    raise RuntimeError(
                        "Committed skill promotion cannot be finalized safely: "
                        + verification_error
                    )
                _finalize_committed_transaction(tx_dir, journal)
                continue
            if phase in {"preparing", "prepared", "claimed"}:
                claim_error = _restore_claims(tx_dir, journal)
                if claim_error:
                    raise RuntimeError(f"Skill claim recovery failed: {claim_error}")
                _write_journal(tx_dir, journal, "rolled_back")
                continue
            if phase in {"mutating", "rolling_back", "rolling_back_after_commit"}:
                restore_error = _restore_skill_batch(
                    tx_dir,
                    list(journal.get("snapshots", [])),
                    list(journal.get("parent_metadata", [])),
                )
                claim_error = _restore_claims(tx_dir, journal)
                if restore_error or claim_error:
                    raise RuntimeError(
                        "Skill promotion recovery failed: "
                        + "; ".join(item for item in (restore_error, claim_error) if item)
                    )
                if phase == "rolling_back_after_commit":
                    _invalidate_transaction_reviews(journal)
                    if journal.get("invalidate_prompt_cache") is True:
                        _clear_skill_prompt_cache()
                    else:
                        _defer_skill_prompt_cache_invalidation()
                terminal = (
                    "rolled_back_after_commit"
                    if phase == "rolling_back_after_commit"
                    else "rolled_back"
                )
                _write_journal(tx_dir, journal, terminal)
                continue
            raise RuntimeError(
                f"Unknown skill promotion phase {phase!r} in {tx_dir.name}."
            )

    decisions = _skill_decision_root()
    if decisions.exists() and decisions.is_symlink():
        raise RuntimeError(f"Unsafe skill decision directory: {decisions}")
    if decisions.exists():
        for path in decisions.glob("*.json"):
            receipt = _load_json_file(path)
            if receipt.get("state") == "rejecting":
                _finish_rejecting_receipt(path, receipt)
        _prune_skill_decisions()


def recover_skill_pending_transactions(*, _lock_held: bool = False) -> None:
    """Idempotently finish committed promotions or roll incomplete ones back."""
    if _lock_held:
        _recover_skill_pending_transactions_locked()
        return
    from tools.skill_mutation import skill_mutation_lock

    with skill_mutation_lock(_skills_dir().parent):
        _recover_skill_pending_transactions_locked()


def _commit_skill_batch_side_effects(
    plans: List[Dict[str, Any]],
    results: List[Dict[str, Any]],
    *,
    activate_now: bool = False,
) -> None:
    # A long-lived conversation's system prompt is byte-stable by contract.
    # Default promotion therefore publishes durable bytes without rebuilding
    # the process-wide skill index; a new process/session observes them.  The
    # caller may explicitly request immediate activation with ``activate_now``.
    if activate_now:
        _clear_skill_prompt_cache()
    else:
        _defer_skill_prompt_cache_invalidation()
    try:
        from tools.skill_usage import bump_patch, forget, mark_agent_created

        for plan, result in zip(plans, results):
            action = plan["action"]
            name = plan["name"]
            origin = plan["record"].get("origin")
            if action == "create" and origin == "background_review":
                mark_agent_created(name)
            elif action in {"patch", "edit", "write_file", "remove_file"}:
                bump_patch(name)
            elif action == "delete" and not result.get("_archived"):
                forget(name)
    except Exception:
        logger.debug("skill batch telemetry update failed", exc_info=True)


def apply_skill_pending_batch(
    records: List[Dict[str, Any]], *, activate_now: bool = False
) -> Dict[str, Any]:
    """Promote fully reviewed batches through a crash-safe durable journal."""
    if not records:
        return {"success": False, "error": "No skill drafts selected."}
    requested_ids = [
        str(record.get("id"))
        for record in records
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    ]
    if not requested_ids:
        return {"success": False, "error": "No valid skill draft ids selected."}
    from tools.skill_mutation import skill_mutation_lock
    from tools import write_approval as wa

    with skill_mutation_lock(_skills_dir().parent):
        _recover_skill_pending_transactions_locked()
        pending = wa._list_pending_unlocked(wa.SKILLS)
        by_id = {str(record.get("id")): record for record in pending}
        selected = [by_id[pending_id] for pending_id in requested_ids if pending_id in by_id]
        missing = [pending_id for pending_id in requested_ids if pending_id not in by_id]
        if missing and not selected:
            receipt = find_skill_pending_receipt(missing[0], _lock_held=True)
            if receipt and receipt.get("decision") == "promoted":
                return {
                    "success": True,
                    "applied": 0,
                    "already_promoted": True,
                    "transaction_id": receipt.get("transaction_id"),
                    "message": "This reviewed skill batch was already promoted.",
                }
            return {"success": False, "error": f"No pending skill draft with id '{missing[0]}'."}
        if missing:
            return {
                "success": False,
                "error": "The selected draft set changed before approval; review it again.",
            }

        batch_ids = {str(record.get("batch_id")) for record in selected}
        exact_records = [
            record for record in pending if str(record.get("batch_id")) in batch_ids
        ]
        plans, error = _prepare_skill_pending_records(
            exact_records,
            require_preconditions=True,
        )
        if error:
            return {"success": False, "error": error}

        records_by_batch: Dict[str, List[Dict[str, Any]]] = {}
        plans_by_batch: Dict[str, List[Dict[str, Any]]] = {}
        for record, plan in zip(_ordered_pending_records(exact_records), plans):
            batch_id = str(record["batch_id"])
            records_by_batch.setdefault(batch_id, []).append(record)
            plans_by_batch.setdefault(batch_id, []).append(plan)
        batch_digests: Dict[str, str] = {}
        governed_batches: Dict[str, Dict[str, Any]] = {}
        for batch_id in sorted(records_by_batch):
            digest = _batch_digest(
                batch_id,
                records_by_batch[batch_id],
                plans_by_batch[batch_id],
            )
            batch_digests[batch_id] = digest
            try:
                governance = _analyze_skill_batch_governance(
                    batch_id,
                    records_by_batch[batch_id],
                    digest,
                )
            except Exception as exc:
                return {
                    "success": False,
                    "error": (
                        f"Governed promotion checks failed for batch {batch_id[:8]}: {exc}"
                    ),
                }
            governance_projection = (
                governance.projection() if governance is not None else None
            )
            governance_digest = governance.digest if governance is not None else None
            if governance is not None:
                governed_batches[batch_id] = governance_projection
            try:
                review_path = _review_path(batch_id)
                attestation = _load_json_file(review_path)
            except Exception:
                return {
                    "success": False,
                    "error": (
                        f"Skill draft batch {batch_id[:8]} has not been durably reviewed. "
                        "Run /skills diff <id>, inspect every action, then approve it."
                    ),
                }
            expected_ids = [str(record["id"]) for record in records_by_batch[batch_id]]
            if (
                attestation.get("batch_id") != batch_id
                or attestation.get("digest") != digest
                or attestation.get("record_ids") != expected_ids
                or attestation.get("governance_digest") != governance_digest
                or attestation.get("governance") != governance_projection
            ):
                return {
                    "success": False,
                    "error": (
                        f"Skill draft batch {batch_id[:8]} changed after review. "
                        "No actions were promoted; run /skills diff <id> again."
                    ),
                }
            if governance is not None and governance.skills:
                try:
                    evaluation = _load_json_file(_evaluation_path(batch_id))
                except Exception:
                    return {
                        "success": False,
                        "error": (
                            f"Skill draft batch {batch_id[:8]} has no passing "
                            "deterministic evaluation attestation. Run `fabric "
                            f"skills evaluate {expected_ids[0]} --observations <path>`."
                        ),
                    }
                if not _skill_evaluation_attestation_matches(
                    evaluation, governance, digest, expected_ids
                ):
                    return {
                        "success": False,
                        "error": (
                            f"Skill draft batch {batch_id[:8]} evaluation is stale "
                            "or does not match the reviewed candidate. Run the "
                            "evaluation again, then review the diff again."
                        ),
                    }

        ordered_records = _ordered_pending_records(exact_records)
        transaction_id = uuid.uuid4().hex
        tx_root = _skill_transaction_root()
        _ensure_private_dir(tx_root)
        tx_dir = tx_root / transaction_id
        preparing_dir = tx_root / f".{transaction_id}.preparing"
        os.mkdir(preparing_dir, 0o700)
        record_metadata = [
            {
                "id": str(record["id"]),
                "batch_id": str(record["batch_id"]),
                "sha256": _record_digest(record),
            }
            for record in ordered_records
        ]
        final_postconditions: Dict[str, Dict[str, Any]] = {}
        for plan in plans:
            final_postconditions[plan["name"]] = {
                "skill_path": plan["skill_path"],
                "postcondition": plan["postcondition"],
            }
        journal: Dict[str, Any] = {
            "schema_version": _PROMOTION_SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "created_at": time.time(),
            "phase": "preparing",
            "batch_ids": sorted(batch_ids),
            "batch_digests": batch_digests,
            "governed_batches": governed_batches,
            "records": record_metadata,
            "touched_skills": sorted({plan["name"] for plan in plans}),
            "final_postconditions": final_postconditions,
            "snapshots": [],
            "parent_metadata": [],
            "owned_postconditions": [],
            "invalidate_prompt_cache": bool(activate_now),
        }
        try:
            _write_journal(preparing_dir, journal, "preparing")
            os.replace(preparing_dir, tx_dir)
            _fsync_dir(tx_root)
        except Exception as exc:
            shutil.rmtree(preparing_dir, ignore_errors=True)
            return {
                "success": False,
                "error": f"Could not create durable skill promotion journal: {exc}",
            }
        mutation_started = False
        try:
            snapshots, parent_metadata = _snapshot_skill_batch(
                plans, tx_dir / "snapshot"
            )
            journal["snapshots"] = snapshots
            journal["parent_metadata"] = parent_metadata
            _promotion_fault("snapshotted")
            precondition_error = _verify_skill_batch_pre_state(plans)
            if precondition_error:
                raise RuntimeError(precondition_error)
            claim_bytes = sum(
                (_skill_pending_dir() / f"{item['id']}.json").lstat().st_size
                for item in record_metadata
            )
            retention_error = _prune_skill_transactions(
                reserve_bytes=_directory_size(tx_dir) + claim_bytes,
                reserve_count=1,
            )
            if retention_error:
                _write_journal(tx_dir, journal, "rolled_back")
                cleanup_error = _remove_transaction_directory(tx_dir)
                if cleanup_error:
                    logger.warning(
                        "Rolled-back skill transaction cleanup awaits restart: %s",
                        cleanup_error,
                    )
                return {"success": False, "error": retention_error}
            _write_journal(tx_dir, journal, "prepared")
            _promotion_fault("prepared")
            precondition_error = _verify_skill_batch_pre_state(plans)
            if precondition_error:
                raise RuntimeError(precondition_error)
            _claim_records(tx_dir, record_metadata)
            _write_journal(tx_dir, journal, "claimed")
            _promotion_fault("claimed")
            _promotion_fault("pre_mutation")
            # Keep the durable phase at ``claimed`` through the final
            # fault-injection/yield point.  If an out-of-band writer changes a
            # tree there, recovery restores only the pending claims and never
            # overwrites that writer from our snapshot.
            _promotion_fault("mutating")
            precondition_error = _verify_skill_batch_pre_state(plans)
            if precondition_error:
                raise RuntimeError(precondition_error)
            _write_journal(tx_dir, journal, "mutating")
            # Journal publication performs filesystem I/O and is therefore
            # itself a yield point to non-cooperating editors.  Fingerprint the
            # active trees once more after it returns.  Until replay begins,
            # an error must restore claims only—not the older tree snapshot—so
            # an out-of-band edit is never erased by our rollback.
            precondition_error = _verify_skill_batch_pre_state(plans)
            if precondition_error:
                raise RuntimeError(precondition_error)

            replay_token = _skill_batch_replay.set(True)
            results: List[Dict[str, Any]] = []
            try:
                for plan in plans:
                    record = plan["record"]
                    replay_state = {"mutation_started": False}
                    try:
                        raw = apply_skill_pending(
                            record["payload"],
                            origin=record.get("origin"),
                            _expected_plan=plan,
                            _replay_state=replay_state,
                        )
                    finally:
                        mutation_started = mutation_started or bool(
                            replay_state["mutation_started"]
                        )
                    try:
                        result = json.loads(raw)
                    except (TypeError, json.JSONDecodeError):
                        result = {"success": False, "error": "invalid replay result"}
                    if not isinstance(result, dict) or not result.get("success"):
                        raise RuntimeError(
                            str(
                            result.get("error")
                            if isinstance(result, dict)
                            else "invalid replay result"
                            )
                        )
                    results.append(result)
            finally:
                _skill_batch_replay.reset(replay_token)
            verification_error = _verify_skill_batch_post_state(plans)
            if verification_error:
                raise RuntimeError(verification_error)
            _promotion_fault("replayed")
            if activate_now:
                _commit_skill_batch_side_effects(
                    plans, results, activate_now=True
                )
            else:
                _commit_skill_batch_side_effects(plans, results)
            journal["owned_postconditions"] = _capture_owned_postconditions(
                snapshots
            )
            _durably_publish_skill_batch_post_state(plans)
            _promotion_fault("side_effects")
            journal["applied"] = len(results)
            _write_journal(tx_dir, journal, "committed")
            _promotion_fault("committed")
            _finalize_committed_transaction(tx_dir, journal)
            _promotion_fault("finalized")
            _prune_skill_transactions()
            return {
                "success": True,
                "applied": len(results),
                "results": results,
                "transaction_id": transaction_id,
                "activation": "immediate" if activate_now else "next_session",
            }
        except Exception as exc:
            phase = str(journal.get("phase"))
            if phase in {"committed", "finalized"}:
                # The reviewed bytes and side effects are already durable.
                # Cleanup is idempotent and restart recovery will finish it;
                # never reintroduce the claimed drafts or report a rollback.
                if phase == "committed":
                    try:
                        _finalize_committed_transaction(tx_dir, journal)
                    except Exception:
                        logger.warning(
                            "Committed skill promotion %s awaits restart cleanup",
                            transaction_id,
                            exc_info=True,
                        )
                return {
                    "success": True,
                    "applied": len(results),
                    "results": results,
                    "transaction_id": transaction_id,
                    "cleanup_pending": journal.get("phase") != "finalized",
                }
            try:
                if phase in {"mutating", "rolling_back"} and mutation_started:
                    _write_journal(tx_dir, journal, "rolling_back")
                    restore_error = _restore_skill_batch(
                        tx_dir, snapshots, parent_metadata
                    )
                else:
                    restore_error = None
                claim_error = _restore_claims(tx_dir, journal)
                if restore_error or claim_error:
                    raise RuntimeError(
                        "; ".join(
                            item for item in (restore_error, claim_error) if item
                        )
                    )
                _write_journal(tx_dir, journal, "rolled_back")
            except Exception as rollback_exc:
                return {
                    "success": False,
                    "applied": 0,
                    "error": (
                        f"Promotion failed: {exc}. ROLLBACK ERROR: {rollback_exc}. "
                        f"Recovery journal: {tx_dir / 'journal.json'}"
                    ),
                }
            return {
                "success": False,
                "applied": 0,
                "error": f"Promotion failed and was rolled back: {exc}",
                "transaction_id": transaction_id,
            }


def _unified_pending_diff(
    *, target: str, before: Optional[bytes], after: Optional[bytes]
) -> str:
    import difflib

    before = before or b""
    after = after or b""
    try:
        before_text = before.decode("utf-8")
        after_text = after.decode("utf-8")
    except UnicodeDecodeError:
        return (
            f"binary {target}: {len(before)} bytes sha256={hashlib.sha256(before).hexdigest()} "
            f"-> {len(after)} bytes sha256={hashlib.sha256(after).hexdigest()}"
        )
    return "".join(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile=f"a/{target}",
            tofile=f"b/{target}",
        )
    ) or "(no textual change)"


def preview_skill_pending_record(
    record: Dict[str, Any], related_records: List[Dict[str, Any]]
) -> str:
    """Review and durably attest the entire immutable batch containing *record*."""
    del related_records  # The durable store is authoritative under the writer lock.
    from tools.skill_mutation import skill_mutation_lock
    from tools import write_approval as wa

    with skill_mutation_lock(_skills_dir().parent):
        _recover_skill_pending_transactions_locked()
        current = wa._get_pending_unlocked(wa.SKILLS, str(record.get("id", "")))
        if current is None:
            return "(preview unavailable: draft is no longer pending)"
        batch_id = str(current.get("batch_id", ""))
        records = _ordered_pending_records(
            [
                candidate
                for candidate in wa._list_pending_unlocked(wa.SKILLS)
                if candidate.get("batch_id") == batch_id
            ]
        )
        plans, error = _prepare_skill_pending_records(
            records,
            require_preconditions=True,
        )
        if error or not plans:
            return f"(preview unavailable: {error or 'invalid draft'})"
        digest = _batch_digest(batch_id, records, plans)
        try:
            governance = _analyze_skill_batch_governance(
                batch_id, records, digest
            )
        except Exception as exc:
            # The full byte diff remains useful for repairing a governed
            # draft, but no durable review token is issued while any mandatory
            # contract/source/scan gate is unavailable or failing.
            governance = None
            governance_error = str(exc)
        else:
            governance_error = None
        attestation = {
            "schema_version": _PROMOTION_SCHEMA_VERSION,
            "batch_id": batch_id,
            "digest": digest,
            "record_ids": [str(candidate["id"]) for candidate in records],
            "governance_digest": governance.digest if governance is not None else None,
            "governance": governance.projection() if governance is not None else None,
            "reviewed_at": time.time(),
        }
        if governance_error is None:
            try:
                _atomic_json(_review_path(batch_id), attestation)
            except Exception as exc:
                return f"(preview unavailable: could not persist review attestation: {exc})"

    sections = [
        f"Batch {batch_id} — {len(plans)} action(s), applied in the order below.",
        "Approving any id in this batch promotes every reviewed action atomically.",
    ]
    for index, plan in enumerate(plans, start=1):
        sections.append(
            f"\n## Action {index}/{len(plans)} — {plan['action']} {plan['name']}"
        )
        sections.append(_render_pending_plan(plan))
    if governance_error is not None:
        sections.extend(
            [
                "\n## Governed promotion blocked",
                governance_error,
                "No review token was issued. Repair the draft, then inspect it again.",
            ]
        )
    else:
        if governance is not None:
            sections.append("\n## Governed promotion evidence")
            if not governance.skills:
                sections.append("Deletion-only batch: no final skill requires evaluation.")
            for candidate in governance.skills:
                sections.append(
                    f"- {candidate.name}: candidate sha256:{candidate.candidate_digest}; "
                    f"contract sha256:{candidate.contract_digest}; "
                    f"eval manifest sha256:{candidate.eval_manifest_digest}"
                )
                if candidate.permission_expansion:
                    sections.append("  Permission expansion (approval acknowledges all):")
                    sections.extend(
                        f"  - {item}" for item in candidate.permission_expansion
                    )
                else:
                    sections.append("  Permission expansion: none")
            if governance.skills:
                try:
                    evaluation = _load_json_file(_evaluation_path(batch_id))
                except Exception:
                    sections.append(
                        "Evaluation: missing. Run `fabric skills evaluate "
                        f"{records[0]['id']} --observations <path>` before approval."
                    )
                else:
                    if _skill_evaluation_attestation_matches(
                        evaluation,
                        governance,
                        digest,
                        [str(candidate["id"]) for candidate in records],
                    ):
                        sections.append("Evaluation: passing attestation is current.")
                    else:
                        sections.append("Evaluation: stale; run it again before approval.")
        sections.append(f"\nReview token: sha256:{digest}")
    return "\n".join(sections)


def evaluate_skill_pending_batch(
    pending_id: str,
    observations_path: Path,
) -> Dict[str, Any]:
    """Persist a passing data-only eval attestation for one exact draft batch."""

    from tools import write_approval as wa
    from tools.skill_mutation import skill_mutation_lock

    if not wa.is_valid_pending_id(pending_id):
        return {"success": False, "error": "Invalid pending skill draft id."}

    with skill_mutation_lock(_skills_dir().parent):
        _recover_skill_pending_transactions_locked()
        selected = wa._get_pending_unlocked(wa.SKILLS, pending_id)
        if selected is None:
            return {
                "success": False,
                "error": f"No pending skill draft with id '{pending_id}'.",
            }
        batch_id = selected.get("batch_id")
        if not isinstance(batch_id, str) or not _PENDING_BATCH_ID_RE.fullmatch(batch_id):
            return {"success": False, "error": "Pending skill batch id is invalid."}
        records = _ordered_pending_records(
            [
                record
                for record in wa._list_pending_unlocked(wa.SKILLS)
                if record.get("batch_id") == batch_id
            ]
        )
        plans, error = _prepare_skill_pending_records(
            records, require_preconditions=True
        )
        if error or not plans:
            return {"success": False, "error": error or "Invalid pending skill batch."}
        digest = _batch_digest(batch_id, records, plans)
        try:
            governance = _analyze_skill_batch_governance(batch_id, records, digest)
        except Exception as exc:
            return {
                "success": False,
                "error": f"Governed promotion checks failed: {exc}",
            }
        if governance is None:
            return {
                "success": False,
                "error": "Deterministic promotion evaluation applies only to quarantined governed drafts.",
            }

        # A new evaluation attempt replaces authority rather than layering on
        # top of an older pass. A malformed or failing observation file thus
        # cannot leave an earlier attestation silently active.
        try:
            _invalidate_skill_batch_evaluation(batch_id)
        except Exception as exc:
            return {
                "success": False,
                "error": f"Could not invalidate the prior evaluation: {exc}",
            }
        final_skills, _current_dirs = _governance_virtual_state(records)
        try:
            from agent.skill_promotion_gates import evaluate_governed_batch

            attestation = evaluate_governed_batch(
                governance,
                final_skills=final_skills,
                temporary_root=_skill_governance_root(),
                observations_path=Path(observations_path),
            )
            attestation["evaluated_at"] = time.time()
            from agent.skill_promotion_gates import canonical_digest

            attestation["attestation_digest"] = canonical_digest(attestation)
            _atomic_json(_evaluation_path(batch_id), attestation)
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        return {
            "success": True,
            "batch_id": batch_id,
            "batch_digest": digest,
            "governance_digest": governance.digest,
            "record_ids": list(governance.record_ids),
            "skills": [candidate.name for candidate in governance.skills],
            "reports": attestation["reports"],
        }


def _render_pending_plan(plan: Dict[str, Any]) -> str:
    """Render every byte/deletion represented by one reviewed plan."""
    if plan["action"] == "create":
        return (plan.get("after") or b"").decode("utf-8", errors="replace")
    if plan["action"] == "delete":
        tree: Dict[str, _VirtualEntry] = plan["before_tree"]
        lines = [
            f"delete tree: {plan['skill_path']}",
            f"tree sha256: {plan['precondition']['sha256']}",
        ]
        for rel, entry in sorted(tree.items()):
            if not rel:
                continue
            if entry.kind == "file":
                lines.append(
                    _unified_pending_diff(target=rel, before=entry.data, after=None)
                )
            elif entry.kind == "symlink":
                lines.append(f"delete symlink {rel} -> {os.fsdecode(entry.data)}")
            else:
                lines.append(f"delete directory {rel}/")
        return "\n".join(lines)
    if plan["action"] == "remove_file":
        before = plan.get("before") or b""
        return "\n".join(
            [
                f"delete file: {plan.get('target')}",
                f"file sha256: {hashlib.sha256(before).hexdigest()}",
                _unified_pending_diff(
                    target=str(plan.get("target") or "supporting file"),
                    before=before,
                    after=None,
                ),
            ]
        )
    return _unified_pending_diff(
        target=str(plan.get("target") or "SKILL.md"),
        before=plan.get("before"),
        after=plan.get("after"),
    )


def find_skill_pending_receipt(
    pending_id: str, *, _lock_held: bool = False
) -> Optional[Dict[str, Any]]:
    """Return a bounded durable terminal decision receipt for one draft id."""
    from tools import write_approval as wa

    if not wa.is_valid_pending_id(pending_id):
        return None

    def _find() -> Optional[Dict[str, Any]]:
        _recover_skill_pending_transactions_locked()
        for tx_dir, journal, _size in _terminal_transactions():
            if journal.get("phase") != "finalized":
                continue
            if any(item.get("id") == pending_id for item in journal.get("records", [])):
                return {
                    "decision": "promoted",
                    "transaction_id": tx_dir.name,
                    "record_ids": [item.get("id") for item in journal.get("records", [])],
                    "completed_at": journal.get("terminal_at"),
                }
        decisions = _skill_decision_root()
        if decisions.exists():
            for path in decisions.glob("*.json"):
                receipt = _load_json_file(path)
                if (
                    receipt.get("state") == "rejected"
                    and pending_id in receipt.get("record_ids", [])
                ):
                    return {
                        "decision": "rejected",
                        "record_ids": list(receipt.get("record_ids", [])),
                        "completed_at": receipt.get("completed_at"),
                    }
        return None

    if _lock_held:
        return _find()
    from tools.skill_mutation import skill_mutation_lock

    with skill_mutation_lock(_skills_dir().parent):
        return _find()


def reject_skill_pending(
    pending_id: Optional[str] = None, *, reject_all: bool = False
) -> Dict[str, Any]:
    """Reject exact whole batches under the shared lock with durable receipts."""
    from tools import write_approval as wa
    from tools.skill_mutation import skill_mutation_lock

    with skill_mutation_lock(_skills_dir().parent):
        _recover_skill_pending_transactions_locked()
        records = wa._list_pending_unlocked(wa.SKILLS)
        if not reject_all:
            if pending_id is None or not wa.is_valid_pending_id(pending_id):
                return {"success": False, "error": "Invalid pending skill draft id."}
            selected = next(
                (record for record in records if record.get("id") == pending_id),
                None,
            )
            if selected is None:
                receipt = find_skill_pending_receipt(pending_id, _lock_held=True)
                if receipt and receipt.get("decision") == "rejected":
                    return {
                        "success": True,
                        "rejected": 0,
                        "already_rejected": True,
                    }
                if receipt and receipt.get("decision") == "promoted":
                    return {
                        "success": False,
                        "error": "That skill draft was already promoted and cannot be rejected.",
                    }
                return {"success": False, "error": f"No pending skill draft with id '{pending_id}'."}
            selected_batches = {str(selected.get("batch_id") or selected["id"])}
        else:
            selected_batches = {
                str(record.get("batch_id") or record["id"]) for record in records
            }
        if not selected_batches:
            return {"success": True, "rejected": 0}

        rejected = 0
        for group_id in sorted(selected_batches):
            group = [
                record
                for record in records
                if str(record.get("batch_id") or record["id"]) == group_id
            ]
            if not group:
                continue
            receipt_id = hashlib.sha256(f"reject\0{group_id}".encode("utf-8")).hexdigest()
            receipt_path = _skill_decision_root() / f"{receipt_id}.json"
            receipt = {
                "schema_version": _PROMOTION_SCHEMA_VERSION,
                "decision": "rejected",
                "state": "rejecting",
                "group_id": group_id,
                "record_ids": [str(record["id"]) for record in group],
                "record_digests": {
                    str(record["id"]): _record_digest(record) for record in group
                },
                "created_at": time.time(),
            }
            _atomic_json(receipt_path, receipt)
            try:
                rejected += _finish_rejecting_receipt(receipt_path, receipt)
            except Exception as exc:
                return {
                    "success": False,
                    "rejected": rejected,
                    "error": (
                        "Skill draft rejection is incomplete; its durable receipt "
                        f"will retry during recovery: {exc}"
                    ),
                }
        _prune_skill_decisions()
        return {"success": True, "rejected": rejected}


def rollback_committed_skill_transaction(
    transaction_id: str, *, activate_now: bool = False
) -> Dict[str, Any]:
    """Internal tested rollback primitive for the latest committed skill bytes."""
    if not _PROMOTION_TX_ID_RE.fullmatch(transaction_id):
        return {"success": False, "error": "Invalid skill transaction id."}
    from tools.skill_mutation import skill_mutation_lock

    with skill_mutation_lock(_skills_dir().parent):
        _recover_skill_pending_transactions_locked()
        tx_dir = _skill_transaction_root() / transaction_id
        if not tx_dir.is_dir() or tx_dir.is_symlink():
            return {"success": False, "error": "Skill transaction not found."}
        journal = _load_journal(tx_dir)
        if journal.get("phase") != "finalized":
            return {
                "success": False,
                "error": f"Skill transaction is not rollback-eligible ({journal.get('phase')}).",
            }
        stamp = float(journal.get("terminal_at") or 0)
        touched = set(journal.get("touched_skills", []))
        for other_dir, other, _size in _terminal_transactions():
            if other_dir == tx_dir or other.get("phase") != "finalized":
                continue
            other_stamp = float(other.get("terminal_at") or 0)
            if other_stamp > stamp and touched.intersection(other.get("touched_skills", [])):
                return {
                    "success": False,
                    "error": "A newer promotion touches this skill; refusing stale rollback.",
                }
        for name, item in journal.get("final_postconditions", {}).items():
            plan = {
                "name": name,
                "skill_path": item.get("skill_path"),
                "postcondition": item.get("postcondition"),
            }
            try:
                actual = _actual_postcondition(plan)
            except Exception as exc:
                return {"success": False, "error": f"Could not verify current bytes: {exc}"}
            if actual != item.get("postcondition"):
                return {
                    "success": False,
                    "error": "Active skill bytes changed after promotion; refusing stale rollback.",
                }
        owned_error = _verify_owned_postconditions(journal)
        if owned_error:
            return {
                "success": False,
                "error": (
                    "Transaction-owned sidecar/archive state changed after "
                    f"promotion; refusing stale rollback: {owned_error}"
                ),
            }
        journal["invalidate_prompt_cache"] = bool(activate_now)
        _write_journal(tx_dir, journal, "rolling_back_after_commit")
        restore_error = _restore_skill_batch(
            tx_dir,
            list(journal.get("snapshots", [])),
            list(journal.get("parent_metadata", [])),
        )
        claim_error = _restore_claims(tx_dir, journal)
        if restore_error or claim_error:
            return {
                "success": False,
                "error": "Rollback could not be completed; restart recovery will retry: "
                + "; ".join(item for item in (restore_error, claim_error) if item),
            }
        try:
            _invalidate_transaction_reviews(journal)
            if activate_now:
                _clear_skill_prompt_cache()
            else:
                _defer_skill_prompt_cache_invalidation()
        except Exception as exc:
            return {
                "success": False,
                "error": (
                    "Rollback restored durable bytes but could not publish the "
                    f"restored state; recovery will retry: {exc}"
                ),
            }
        _write_journal(tx_dir, journal, "rolled_back_after_commit")
        return {
            "success": True,
            "restored": len(journal.get("touched_skills", [])),
            "activation": "immediate" if activate_now else "next_session",
        }


def apply_skill_pending(
    payload: Dict[str, Any],
    *,
    origin: Optional[str] = None,
    _expected_plan: Optional[Dict[str, Any]] = None,
    _replay_state: Optional[Dict[str, bool]] = None,
) -> str:
    """Replay a staged skill write, bypassing the gate. Returns the tool result
    JSON string. Called by the /skills approve handler.
    """
    replay_origin = origin or "foreground"
    origin_error = _pending_origin_validation_error(replay_origin)
    if origin_error:
        return tool_error(origin_error, success=False)
    gate_token = _skill_gate_bypass.set(True)
    replay_token = _approved_skill_replay.set(True)
    origin_token = None
    try:
        if origin:
            from tools.skill_provenance import set_current_write_origin

            origin_token = set_current_write_origin(origin)
        if _expected_plan is not None:
            expected_record = _expected_plan.get("record")
            if (
                not isinstance(expected_record, dict)
                or expected_record.get("payload") != payload
            ):
                return tool_error(
                    "Approved replay plan does not match the quarantined payload.",
                    success=False,
                )
            precondition_error = _verify_skill_batch_pre_state([_expected_plan])
            if precondition_error:
                return tool_error(precondition_error, success=False)
        if _replay_state is not None:
            _replay_state["mutation_started"] = True
        return skill_manage(
            action=payload.get("action", ""),
            name=payload.get("name", ""),
            content=payload.get("content"),
            category=payload.get("category"),
            file_path=payload.get("file_path"),
            file_content=payload.get("file_content"),
            old_string=payload.get("old_string"),
            new_string=payload.get("new_string"),
            replace_all=payload.get("replace_all", False),
            absorbed_into=payload.get("absorbed_into"),
        )
    finally:
        if origin_token is not None:
            from tools.skill_provenance import reset_current_write_origin

            reset_current_write_origin(origin_token)
        _approved_skill_replay.reset(replay_token)
        _skill_gate_bypass.reset(gate_token)


def skill_manage(
    action: str,
    name: str,
    content: str = None,
    category: str = None,
    file_path: str = None,
    file_content: str = None,
    old_string: str = None,
    new_string: str = None,
    replace_all: bool = False,
    absorbed_into: str = None,
    _pending_batch_key: str = None,
) -> str:
    """
    Manage user-created skills. Dispatches to the appropriate action handler.

    Returns JSON string with results.
    """
    preflight = _background_review_preflight(action, name, file_path)
    if preflight is not None:
        return json.dumps(preflight, ensure_ascii=False)

    # Approval gate: when on, stages the write for review (skills are too large
    # to review inline, so they always stage regardless of origin); when off
    # (default) passes straight through. The gate is bypassed when this call is
    # itself replaying an already-approved staged write (_skill_apply_pending).
    gate_result = _apply_skill_write_gate(
        action, name, content=content, category=category,
        file_path=file_path, file_content=file_content,
        old_string=old_string, new_string=new_string,
        replace_all=replace_all, absorbed_into=absorbed_into,
        pending_batch_key=_pending_batch_key,
    )
    if gate_result is not None:
        return gate_result

    if action == "create":
        if not content:
            return tool_error("content is required for 'create'. Provide the full SKILL.md text (frontmatter + body).", success=False)
        result = _create_skill(name, content, category)

    elif action == "edit":
        if not content:
            return tool_error("content is required for 'edit'. Provide the full updated SKILL.md text.", success=False)
        result = _edit_skill(name, content)

    elif action == "patch":
        if not old_string:
            return tool_error("old_string is required for 'patch'. Provide the text to find.", success=False)
        if new_string is None:
            return tool_error("new_string is required for 'patch'. Use empty string to delete matched text.", success=False)
        result = _patch_skill(name, old_string, new_string, file_path, replace_all)

    elif action == "delete":
        result = _delete_skill(name, absorbed_into=absorbed_into)

    elif action == "write_file":
        if not file_path:
            return tool_error("file_path is required for 'write_file'. Example: 'references/api-guide.md'", success=False)
        if file_content is None:
            return tool_error("file_content is required for 'write_file'.", success=False)
        result = _write_file(name, file_path, file_content)

    elif action == "remove_file":
        if not file_path:
            return tool_error("file_path is required for 'remove_file'.", success=False)
        result = _remove_file(name, file_path)

    else:
        result = {"success": False, "error": f"Unknown action '{action}'. Use: create, edit, patch, delete, write_file, remove_file"}

    if result.get("success") and not _skill_batch_replay.get():
        try:
            from agent.prompt_builder import clear_skills_system_prompt_cache
            clear_skills_system_prompt_cache(clear_snapshot=True)
        except Exception:
            pass
        # Curator telemetry: bump patch_count on edit/patch/write_file (the actions
        # that mutate an existing skill's guidance), drop the record on delete.
        # Only mark a skill as agent-created when an autonomous Fabric writer
        # creates it — foreground `skill_manage(create)` calls are user-directed,
        # and those skills belong to the user. Best-effort; telemetry failures
        # never break the tool.
        try:
            from tools.skill_usage import bump_patch, forget, mark_agent_created
            from tools.skill_provenance import is_autonomous_skill_writer
            if action == "create":
                if is_autonomous_skill_writer():
                    mark_agent_created(name)
            elif action in {"patch", "edit", "write_file", "remove_file"}:
                bump_patch(name)
            elif action == "delete":
                # A recoverable curator archive (routed through archive_skill)
                # keeps its usage record as STATE_ARCHIVED so `fabric curator
                # status`/`restore` still see it. Only a hard delete forgets.
                if not result.get("_archived"):
                    forget(name)
        except Exception:
            pass

    return json.dumps(result, ensure_ascii=False)


# =============================================================================
# OpenAI Function-Calling Schema
# =============================================================================

SKILL_MANAGE_SCHEMA = {
    "name": "skill_manage",
    "description": (
        "Manage skills (create, update, delete). Skills are your procedural "
        "memory — reusable approaches for recurring task types. "
        f"New skills go to {display_fabric_home()}/skills/; existing skills can be modified wherever they live.\n\n"
        "Actions: create (full SKILL.md + optional category), "
        "patch (old_string/new_string — preferred for fixes), "
        "edit (full SKILL.md rewrite — major overhauls only), "
        "delete, write_file, remove_file.\n\n"
        "On delete, pass `absorbed_into=<umbrella>` when you're merging this "
        "skill's content into another one, or `absorbed_into=\"\"` when you're "
        "pruning it with no forwarding target. This lets the curator tell "
        "consolidation from pruning without guessing, so downstream consumers "
        "(cron jobs that reference the old skill name, etc.) get updated "
        "correctly. The target you name in `absorbed_into` must already "
        "exist — create/patch the umbrella first, then delete.\n\n"
        "Create when: complex task succeeded (5+ calls), errors overcome, "
        "user-corrected approach worked, non-trivial workflow discovered, "
        "or user asks you to remember a procedure.\n"
        "Update when: instructions stale/wrong, OS-specific failures, "
        "missing steps or pitfalls found during use. "
        "If you used a skill and hit issues not covered by it, patch it immediately.\n\n"
        "After difficult/iterative tasks, offer to save as a skill. "
        "Skip for simple one-offs. Confirm with user before creating/deleting.\n\n"
        "Good skills: trigger conditions, numbered steps with exact commands, "
        "pitfalls section, verification steps. Use skill_view() to see format examples.\n\n"
        "Pinned skills are protected from deletion only — skill_manage(action='delete') "
        "will refuse with a message pointing the user to `fabric curator unpin <name>`. "
        "Patches and edits go through on pinned skills so you can still improve them as "
        "pitfalls come up; pin only guards against irrecoverable loss."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "patch", "edit", "delete", "write_file", "remove_file"],
                "description": "The action to perform."
            },
            "name": {
                "type": "string",
                "description": (
                    "Skill name (lowercase, hyphens/underscores, max 64 chars). "
                    "Must match an existing skill for patch/edit/delete/write_file/remove_file."
                )
            },
            "content": {
                "type": "string",
                "description": (
                    "Full SKILL.md content (YAML frontmatter + markdown body). "
                    "Required for 'create' and 'edit'. For 'edit', read the skill "
                    "first with skill_view() and provide the complete updated text."
                )
            },
            "old_string": {
                "type": "string",
                "description": (
                    "Text to find in the file (required for 'patch'). Must be unique "
                    "unless replace_all=true. Include enough surrounding context to "
                    "ensure uniqueness."
                )
            },
            "new_string": {
                "type": "string",
                "description": (
                    "Replacement text (required for 'patch'). Can be empty string "
                    "to delete the matched text."
                )
            },
            "replace_all": {
                "type": "boolean",
                "description": "For 'patch': replace all occurrences instead of requiring a unique match (default: false)."
            },
            "category": {
                "type": "string",
                "description": (
                    "Optional category/domain for organizing the skill (e.g., 'devops', "
                    "'data-science', 'mlops'). Creates a subdirectory grouping. "
                    "Only used with 'create'."
                )
            },
            "file_path": {
                "type": "string",
                "description": (
                    "Path to a supporting file within the skill directory. "
                    "For 'write_file'/'remove_file': required, must be under references/, "
                    "templates/, scripts/, or assets/. "
                    "For 'patch': optional, defaults to SKILL.md if omitted."
                )
            },
            "file_content": {
                "type": "string",
                "description": "Content for the file. Required for 'write_file'."
            },
            "absorbed_into": {
                "type": "string",
                "description": (
                    "For 'delete' only — declares intent so the curator can "
                    "tell consolidation from pruning without guessing. "
                    "Pass the umbrella skill name when this skill's content "
                    "was merged into another (the target must already exist). "
                    "Pass an empty string when the skill is truly stale and "
                    "being pruned with no forwarding target. Omitting the arg "
                    "on delete is supported for backward compatibility but "
                    "downstream tooling (e.g. cron-job skill reference "
                    "rewriting) will have to guess at intent."
                )
            },
        },
        "required": ["action", "name"],
    },
}


# --- Registry ---
from tools.registry import registry, tool_error

registry.register(
    name="skill_manage",
    toolset="skills",
    schema=SKILL_MANAGE_SCHEMA,
    handler=lambda args, **kw: skill_manage(
        action=args.get("action", ""),
        name=args.get("name", ""),
        content=args.get("content"),
        category=args.get("category"),
        file_path=args.get("file_path"),
        file_content=args.get("file_content"),
        old_string=args.get("old_string"),
        new_string=args.get("new_string"),
        replace_all=args.get("replace_all", False),
        absorbed_into=args.get("absorbed_into"),
        _pending_batch_key=(
            f"{kw.get('session_id', '')}:{kw.get('task_id', '')}"
            if kw.get("task_id")
            else None
        )),
    emoji="📝",
)
