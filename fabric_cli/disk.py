"""``fabric disk`` — inspect and reclaim Fabric's on-disk storage.

Two user-facing operations, both scoped strictly to the Fabric home
directory (``~/.fabric`` / ``%LOCALAPPDATA%\\fabric``):

  * ``fabric disk usage`` (alias ``du``) — report how much space each
    Fabric store is using, largest-first, with a grand total and the free
    space left on the volume.
  * ``fabric disk clean`` — reclaim regenerable caches, rotated log backups,
    diagnostic traces, and scratch directories.  Dry-run by default;
    ``--yes`` actually deletes.

Design stance is deliberately conservative.  ``clean`` only ever touches an
explicit allow-list of regenerable data and refuses, with a hard runtime
guard, to delete anything outside that list — never databases, sessions,
memories, credentials, config, backups, the cron control-plane, installed
skills/plugins, or another profile.  The safety invariants mirror the
``disk-cleanup`` plugin (``plugins/disk-cleanup/disk_cleanup.py``) and the
backup exclusion sets (``fabric_cli/backup.py``).
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from fabric_constants import display_fabric_home, get_fabric_home
from fabric_cli.colors import Colors, color


# ---------------------------------------------------------------------------
# Human-readable sizes (mirrors fabric_cli/checkpoints.py:31 — kept local so
# this module owns its formatting and has no import-time dependency on the
# checkpoints command).
# ---------------------------------------------------------------------------

def _fmt_bytes(n: int | float | None) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(n or 0)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


# ---------------------------------------------------------------------------
# Size measurement
# ---------------------------------------------------------------------------

def _path_size(path: Path) -> tuple[int, int]:
    """Return ``(total_bytes, file_count)`` for *path*.

    Handles a file, a directory tree, or a missing path.  Symlinks are never
    followed (``followlinks=False``) and their own size is not counted, so a
    symlink loop cannot hang the walk and shared targets are not double
    counted.  Errors on individual entries are ignored — a disk report must
    never crash on one unreadable file.
    """
    try:
        if path.is_symlink() or not path.exists():
            return (0, 0)
        if path.is_file():
            return (path.stat().st_size, 1)
    except OSError:
        return (0, 0)

    total = 0
    count = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        dp = Path(dirpath)
        for name in filenames:
            fpath = dp / name
            try:
                if fpath.is_symlink():
                    continue
                total += fpath.stat().st_size
                count += 1
            except OSError:
                continue
    return (total, count)


def _sum_sizes(paths: Iterable[Path]) -> tuple[int, int]:
    total = 0
    count = 0
    for p in paths:
        b, c = _path_size(p)
        total += b
        count += c
    return (total, count)


def _free_disk_bytes(home: Path) -> tuple[int, int] | None:
    """Return ``(total_bytes, free_bytes)`` for the volume holding *home*.

    Walks up to the nearest existing ancestor so a not-yet-created home still
    reports the mountpoint's numbers.  Returns ``None`` on failure — free
    space is a nice-to-have, never a reason to fail the command.
    """
    probe = home
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
        return (usage.total, usage.free)
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Category model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DiskCategory:
    """One line in the usage report and (optionally) a cleanup target.

    ``usage_paths`` / ``usage_globs`` describe what to *measure* for the
    report.  ``clean_dirs`` / ``clean_trees`` / ``clean_globs`` describe the
    (safe) subset ``clean`` may *delete* — empty on report-only categories.

    The two facets differ for a category like ``logs``: usage measures the
    whole ``logs/`` directory, but ``clean`` only removes rotated backups
    (``logs/*.log.*``) and keeps the live logs.
    """

    key: str
    label: str
    usage_paths: tuple[str, ...] = ()
    usage_globs: tuple[str, ...] = ()
    # clean facet
    clean_dirs: tuple[str, ...] = ()    # delete CONTENTS, keep the directory
    clean_trees: tuple[str, ...] = ()   # delete the path entirely (dir or file)
    clean_globs: tuple[str, ...] = ()   # delete matching files (glob rel to home)
    note: str = ""

    @property
    def reclaimable(self) -> bool:
        return bool(self.clean_dirs or self.clean_trees or self.clean_globs)


# The canonical layout.  Report-only categories carry no clean_* fields and so
# are never eligible for deletion.  Reclaimable categories list only the
# regenerable subset.  Order here is irrelevant — usage sorts largest-first.
CATEGORIES: tuple[DiskCategory, ...] = (
    # ----- persistent user data (never cleaned) -----
    DiskCategory(
        "sessions", "Sessions & state DB",
        usage_paths=("sessions", "state.db", "state.db-wal", "state.db-shm", "state"),
        note="Conversation history and the main state database.",
    ),
    DiskCategory(
        "memories", "Memory",
        usage_paths=(
            "memories", "memory_store.db", "mem0_qdrant", "mem0.json",
            ".honcho", "honcho.json", "hindsight", ".hindsight", "byterover",
        ),
        note="Long-term agent memory and memory-provider stores.",
    ),
    DiskCategory(
        "credentials", "Credentials",
        usage_paths=(
            ".env", "auth.json", "auth.lock", "provider-accounts.json",
            "provider-accounts.lock", ".provider-account-repair",
            ".anthropic_oauth.json", "google_token.json", "slack_tokens.json",
            "mcp-tokens", ".op.env",
        ),
        note="API keys and OAuth tokens.",
    ),
    DiskCategory(
        "skills", "Skills",
        usage_paths=("skills", "skill-bundles"),
        note="Installed and curated skills.",
    ),
    DiskCategory(
        "plugins", "Plugins",
        usage_paths=("plugins", "optional-mcps"),
        note="Installed plugins and MCP servers.",
    ),
    DiskCategory(
        "config", "Config & extensions",
        usage_paths=(
            "config.yaml", "active_profile", "hooks", "skins", "scripts",
            "dashboard-themes", "channel_directory.json", "channel_aliases.json",
            "SOUL.md",
        ),
        note="Configuration, hooks, skins, and gateway routing.",
    ),
    DiskCategory(
        "databases", "Databases",
        usage_paths=(
            "projects.db", "kanban.db", "kanban", "verification_evidence.db",
            "response_store.db", "response_store.db-wal", "response_store.db-shm",
        ),
        note="Projects, kanban, and gateway databases.",
    ),
    DiskCategory(
        "cron", "Scheduler",
        usage_paths=("cron", "cronjobs"),
        note="Scheduled jobs and their run history.",
    ),
    DiskCategory(
        "platforms", "Messaging platforms",
        usage_paths=("platforms",),
        clean_trees=("platforms/whatsapp_cloud/media",),
        note="Messaging state; only re-downloadable WhatsApp Cloud media is cleaned.",
    ),
    DiskCategory("pets", "Pets", usage_paths=("pets",), note="Virtual-pet state."),
    DiskCategory("pastes", "Pastes", usage_paths=("pastes",), note="Saved paste payloads."),
    DiskCategory(
        "backups", "Backups & snapshots",
        usage_paths=("backups", "state-snapshots"),
        note="Your own `fabric backup` archives and state snapshots.",
    ),
    DiskCategory(
        "exports", "Session exports",
        usage_paths=("session-exports",),
        note="Session archives you exported on purpose.",
    ),
    DiskCategory(
        "install", "App runtime (node, venv)",
        usage_paths=(
            "node", "node_modules", "bin", "lsp", "mcp-installs",
            "venv", ".venv", "fabric-agent",
        ),
        note="Regeneratable install tooling — reinstalled, not cleaned here.",
    ),
    DiskCategory(
        "tracker", "Cleanup tracker",
        usage_paths=("disk-cleanup",),
        note="Bookkeeping for the auto-cleanup plugin.",
    ),

    # ----- reclaimable (cleaned by default) -----
    DiskCategory(
        "cache", "Caches",
        usage_paths=(
            "cache", "image_cache", "video_cache", "temp_video_files",
            "audio_cache", "browser_screenshots",
        ),
        usage_globs=("*_cache.json",),
        clean_dirs=("cache",),
        clean_trees=(
            "image_cache", "video_cache", "temp_video_files",
            "audio_cache", "browser_screenshots",
        ),
        clean_globs=("*_cache.json",),
        note="Regenerated on demand (images, video, model metadata).",
    ),
    DiskCategory(
        "logs", "Logs",
        usage_paths=("logs", "perf.log"),
        clean_globs=("logs/*.log.*",),
        note="Only rotated log backups are removed; live logs are kept.",
    ),
    DiskCategory(
        "traces", "Diagnostic traces",
        usage_paths=("moa-traces", "spawn-trees"),
        clean_trees=("moa-traces", "spawn-trees"),
        note="Write-only diagnostics.",
    ),
    DiskCategory(
        "sandboxes", "Sandboxes & worktrees",
        usage_paths=("sandboxes", "chrome-debug", ".worktrees"),
        clean_trees=("sandboxes", "chrome-debug", ".worktrees"),
        note="Disposable working directories.",
    ),
    DiskCategory(
        "tmp", "Temp scratch",
        usage_paths=("tmp",),
        clean_dirs=("tmp",),
        note="General scratch space.",
    ),

    # ----- report-only: managed by the dedicated `fabric checkpoints` command -----
    DiskCategory(
        "checkpoints", "Rollback checkpoints",
        usage_paths=("checkpoints",),
        note="Powers /rollback and /undo — prune with `fabric checkpoints prune`.",
    ),
)

RECLAIMABLE_KEYS: tuple[str, ...] = tuple(c.key for c in CATEGORIES if c.reclaimable)


# Top-level names any category measures — used to route unclassified entries
# into the "other" bucket so the grand total always equals the home size.
# Globs are expanded against *home* so a matched top-level file (e.g.
# ``provider_models_cache.json`` from ``*_cache.json``) is claimed by its real
# name and not double-counted into "other".
def _claimed_top_level(home: Path) -> set[str]:
    claimed: set[str] = set()
    for cat in CATEGORIES:
        for rel in cat.usage_paths:
            claimed.add(Path(rel).parts[0])
        for pat in cat.usage_globs:
            for match in home.glob(pat):
                try:
                    claimed.add(match.relative_to(home).parts[0])
                except ValueError:
                    continue
    return claimed


# ---------------------------------------------------------------------------
# Cleanup safety guard — a target is deletable only if it sits under one of the
# allow-prefixes or matches one of the allow-globs derived from CATEGORIES.
# Nothing else under the home may ever be removed, whatever a caller passes.
# ---------------------------------------------------------------------------

def _clean_allow() -> tuple[set[str], set[str]]:
    prefixes: set[str] = set()
    globs: set[str] = set()
    for cat in CATEGORIES:
        for rel in (*cat.clean_dirs, *cat.clean_trees):
            prefixes.add(str(Path(rel)))
        for pat in cat.clean_globs:
            globs.add(pat)
    return prefixes, globs


def _is_clean_safe(target: Path, home: Path) -> bool:
    """True iff *target* is inside an allow-listed reclaimable location."""
    try:
        rel = target.resolve().relative_to(home.resolve())
    except (ValueError, OSError):
        return False
    rel_str = str(rel)
    rel_parts = rel.parts
    prefixes, globs = _clean_allow()
    for prefix in prefixes:
        if rel_str == prefix or prefix in {str(p) for p in rel.parents}:
            return True
    for pat in globs:
        # Match per path segment so a ``*`` in the pattern never crosses ``/``
        # (plain fnmatch would let ``*_cache.json`` match ``sessions/x_cache.json``
        # and ``logs/*.log.*`` match ``logs/sub/live.log``, approving protected
        # nested paths). This keeps the glob anchored to the depth it declares.
        pat_parts = pat.split("/")
        if len(pat_parts) == len(rel_parts) and all(
            fnmatch.fnmatch(rp, pp) for rp, pp in zip(rel_parts, pat_parts)
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

@dataclass
class CategoryUsage:
    category: DiskCategory
    bytes: int = 0
    files: int = 0


def _resolve_usage_targets(cat: DiskCategory, home: Path) -> list[Path]:
    targets: list[Path] = []
    for rel in cat.usage_paths:
        targets.append(home / rel)
    for pat in cat.usage_globs:
        targets.extend(home.glob(pat))
    return targets


def scan_categories(home: Path) -> list[CategoryUsage]:
    """Measure every category plus an ``other`` catch-all under *home*."""
    results: list[CategoryUsage] = []
    for cat in CATEGORIES:
        b, c = _sum_sizes(_resolve_usage_targets(cat, home))
        results.append(CategoryUsage(cat, b, c))

    # Sweep any top-level entry no category claimed into "other" so the grand
    # total equals the real home size.
    claimed = _claimed_top_level(home)
    other = CategoryUsage(DiskCategory("other", "Other", note="Unclassified files."))
    try:
        for entry in home.iterdir():
            if entry.name in claimed:
                continue
            b, c = _path_size(entry)
            other.bytes += b
            other.files += c
    except OSError:
        pass
    results.append(other)
    return results


def _resolve_scan_home(args) -> Path:
    """Honor ``--profile NAME`` by scanning ``profiles/<NAME>/`` if given."""
    home = get_fabric_home()
    profile = getattr(args, "profile", None)
    if profile:
        from fabric_constants import get_default_fabric_root

        return get_default_fabric_root() / "profiles" / profile
    return home


# ---------------------------------------------------------------------------
# usage
# ---------------------------------------------------------------------------

def disk_usage(args) -> int:
    home = _resolve_scan_home(args)
    profile = getattr(args, "profile", None)

    if not home.exists():
        if getattr(args, "json_output", False):
            # Keep --json machine-readable even when there's nothing to report.
            print(json.dumps({
                "home": str(home),
                "total_bytes": 0,
                "total_files": 0,
                "categories": [],
            }, indent=2))
            return 0
        where = f"profile {profile!r}" if profile else display_fabric_home()
        print(f"No Fabric data found for {where} ({home}).")
        return 0

    usages = scan_categories(home)
    total_bytes = sum(u.bytes for u in usages)
    total_files = sum(u.files for u in usages)
    free = _free_disk_bytes(home)

    if getattr(args, "json_output", False):
        payload = {
            "home": str(home),
            "total_bytes": total_bytes,
            "total_files": total_files,
            "categories": [
                {
                    "key": u.category.key,
                    "label": u.category.label,
                    "bytes": u.bytes,
                    "files": u.files,
                    "reclaimable": u.category.reclaimable,
                }
                for u in sorted(usages, key=lambda u: u.bytes, reverse=True)
            ],
        }
        if free is not None:
            payload["volume_total_bytes"], payload["volume_free_bytes"] = free
        print(json.dumps(payload, indent=2))
        return 0

    show_all = getattr(args, "all", False)
    rows = sorted(usages, key=lambda u: u.bytes, reverse=True)
    visible = [u for u in rows if u.bytes > 0 or show_all]

    where = f"profile {profile!r}" if profile else display_fabric_home()
    print(color(f"\nFabric disk usage — {where}", Colors.BOLD))
    print("─" * 52)
    label_w = 26
    for u in visible:
        label = u.category.label
        if u.category.reclaimable:
            label = color(label, Colors.CYAN)
            # pad using the uncolored length so columns stay aligned
            pad = " " * max(0, label_w - len(u.category.label))
        else:
            pad = " " * max(0, label_w - len(label))
        print(f"  {label}{pad}{_fmt_bytes(u.bytes):>10}   {u.files:>7} files")
    if not visible:
        print("  (empty)")
    print("─" * 52)
    total_label = "Total"
    # Right-justify the size before coloring so ANSI codes don't skew alignment.
    total_size = _fmt_bytes(total_bytes).rjust(10)
    print(
        f"  {color(total_label, Colors.BOLD)}{' ' * (label_w - len(total_label))}"
        f"{color(total_size, Colors.BOLD)}   {total_files:>7} files"
    )
    if free is not None:
        vol_total, vol_free = free
        print(
            color(
                f"\n  {_fmt_bytes(vol_free)} free of {_fmt_bytes(vol_total)} on this volume",
                Colors.DIM,
            )
        )
    reclaimable_total = sum(u.bytes for u in usages if u.category.reclaimable)
    if reclaimable_total > 0:
        print(
            color(
                f"  {_fmt_bytes(reclaimable_total)} is reclaimable — run "
                "`fabric disk clean` to preview.",
                Colors.DIM,
            )
        )
    print()
    return 0


# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------

def _select_categories(args) -> list[DiskCategory]:
    only = getattr(args, "only", None)
    skip = set(getattr(args, "skip", None) or [])

    reclaimable = [c for c in CATEGORIES if c.reclaimable]
    if only:
        only_set = set(only)
        return [c for c in reclaimable if c.key in only_set]
    return [c for c in reclaimable if c.key not in skip]


@dataclass
class CleanTarget:
    path: Path
    mode: str          # "contents" | "tree" | "file"
    bytes: int
    files: int


def _plan_category(cat: DiskCategory, home: Path) -> list[CleanTarget]:
    """Resolve a reclaimable category into concrete, existing targets."""
    targets: list[CleanTarget] = []

    for rel in cat.clean_dirs:
        d = home / rel
        if not d.is_dir() or d.is_symlink():
            continue
        try:
            children = list(d.iterdir())
        except OSError:
            children = []
        for child in children:
            if not _is_clean_safe(child, home):
                continue
            b, c = _path_size(child)
            targets.append(CleanTarget(child, "tree", b, c))

    for rel in cat.clean_trees:
        p = home / rel
        if not p.exists() or p.is_symlink():
            continue
        if not _is_clean_safe(p, home):
            continue
        b, c = _path_size(p)
        targets.append(CleanTarget(p, "tree", b, c))

    for pat in cat.clean_globs:
        for p in home.glob(pat):
            if p.is_symlink() or not p.is_file():
                continue
            if not _is_clean_safe(p, home):
                continue
            b, c = _path_size(p)
            targets.append(CleanTarget(p, "file", b, c))

    return targets


def _delete_target(t: CleanTarget) -> None:
    if t.path.is_dir() and not t.path.is_symlink():
        shutil.rmtree(t.path)
    else:
        t.path.unlink()


def disk_clean(args) -> int:
    home = get_fabric_home()
    dry_run = not getattr(args, "yes", False)
    force = getattr(args, "force", False)

    try:
        selected = _select_categories(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not selected:
        print("Nothing selected to clean.", file=sys.stderr)
        return 1

    plans: list[tuple[DiskCategory, list[CleanTarget]]] = []
    for cat in selected:
        targets = _plan_category(cat, home)
        if targets:
            plans.append((cat, targets))

    grand_bytes = sum(t.bytes for _, ts in plans for t in ts)
    grand_files = sum(t.files for _, ts in plans for t in ts)

    header = "Would reclaim" if dry_run else "Reclaiming"
    print(color(f"\nFabric disk clean — {display_fabric_home()}", Colors.BOLD))
    if dry_run:
        print(color("Dry run: nothing will be deleted.", Colors.CYAN))
    print("─" * 52)

    if not plans:
        print("  Nothing to reclaim — already clean.")
        print()
        return 0

    for cat, targets in plans:
        cbytes = sum(t.bytes for t in targets)
        cfiles = sum(t.files for t in targets)
        verb = "Would remove" if dry_run else "Removing"
        print(
            f"  {verb} {color(cat.label, Colors.CYAN)}: "
            f"{cfiles} item(s), {_fmt_bytes(cbytes)}"
        )
        if cat.note:
            print(color(f"      {cat.note}", Colors.DIM))
    print("─" * 52)
    print(f"  {header}: {color(_fmt_bytes(grand_bytes), Colors.BOLD)} across {grand_files} item(s)")

    if dry_run:
        print(
            color(
                "\n  Re-run with --yes to delete. "
                "Add --only/--skip to choose categories.",
                Colors.DIM,
            )
        )
        # Point at the dedicated command for stores this sweep deliberately
        # leaves alone (they have their own retention policy).
        ckpt = next((c for c in CATEGORIES if c.key == "checkpoints"), None)
        if ckpt is not None:
            b, _ = _sum_sizes(_resolve_usage_targets(ckpt, home))
            if b > 0:
                print(
                    color(
                        f"  Tip: Rollback checkpoints hold {_fmt_bytes(b)} — "
                        "prune them with `fabric checkpoints prune`.",
                        Colors.DIM,
                    )
                )
        print()
        return 0

    # --- real deletion path ---
    if not force:
        if not sys.stdin.isatty():
            print(
                "Refusing to delete on a non-interactive terminal without --force.",
                file=sys.stderr,
            )
            return 2
        try:
            answer = input(
                f"\n  Delete {_fmt_bytes(grand_bytes)} of reclaimable data? "
                "Type 'yes' to confirm: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.\n")
            return 1
        if answer != "yes":
            print("  Cancelled.\n")
            return 1

    freed_bytes = 0
    freed_files = 0
    errors: list[str] = []
    for _cat, targets in plans:
        for t in targets:
            # Defense in depth: re-check the guard immediately before delete.
            if not _is_clean_safe(t.path, home):
                errors.append(f"refused (outside allow-list): {t.path}")
                continue
            try:
                _delete_target(t)
                freed_bytes += t.bytes
                freed_files += t.files
            except OSError as exc:
                errors.append(f"{t.path}: {exc}")

    print("─" * 52)
    print(f"  Freed {color(_fmt_bytes(freed_bytes), Colors.GREEN)} across {freed_files} item(s)")
    if errors:
        print(color(f"  {len(errors)} item(s) could not be removed:", Colors.YELLOW))
        for msg in errors[:10]:
            print(color(f"    {msg}", Colors.YELLOW))
    print()
    return 0


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def disk_command(args) -> int:
    sub = getattr(args, "disk_command", None)
    if sub in {"usage", "du"}:
        return disk_usage(args)
    if sub == "clean":
        return disk_clean(args)
    parser = getattr(args, "_disk_parser", None)
    if parser is not None:
        parser.print_help()
        return 0
    print("usage: fabric disk {usage|clean}", file=sys.stderr)
    return 1
