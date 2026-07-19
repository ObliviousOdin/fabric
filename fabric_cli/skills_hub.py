#!/usr/bin/env python3
"""
Skills Hub CLI — Unified interface for the Fabric Skills Hub.

Powers both:
  - `fabric skills <subcommand>` (CLI argparse entry point)
  - `/skills <subcommand>` (slash command in the interactive chat)

All logic lives in shared do_* functions. The CLI entry point and slash command
handler are thin wrappers that parse args and delegate.
"""

import copy
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Lazy imports to avoid circular dependencies and slow startup.
# tools.skills_hub and tools.skills_guard are imported inside functions.
from fabric_constants import display_fabric_home, get_fabric_home
from agent.skill_utils import is_excluded_skill_path

_console = Console()
_MAX_SNAPSHOT_JSON_BYTES = 4 * 1024 * 1024
_MAX_SNAPSHOT_SKILLS = 10_000
_MAX_SNAPSHOT_TAPS = 1_000
_MAX_SNAPSHOT_STRING_BYTES = 8 * 1024
_SNAPSHOT_SCHEMA_VERSION = 2
_SNAPSHOT_ROOT_FIELDS = frozenset(
    {"schema_version", "fabric_version", "exported_at", "skills", "taps"}
)
_SNAPSHOT_SKILL_FIELDS = frozenset(
    {
        "name",
        "source_name",
        "source_revision",
        "authority",
        "digest",
        "category",
    }
)
_SNAPSHOT_TAP_FIELDS = frozenset({"repo", "path"})
_SNAPSHOT_REPO_RE = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})/"
    r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})\Z"
)


def _read_bounded_snapshot_text(path: Path) -> str:
    """Read one regular snapshot file without a stat/read allocation race."""

    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags)
    try:
        inspected = os.fstat(descriptor)
        if not stat.S_ISREG(inspected.st_mode):
            raise ValueError("snapshot input must be a regular file")
        if inspected.st_size > _MAX_SNAPSHOT_JSON_BYTES:
            raise ValueError(f"snapshot exceeds {_MAX_SNAPSHOT_JSON_BYTES} bytes")

        chunks: list[bytes] = []
        received = 0
        while True:
            # Read one sentinel byte beyond the ceiling. This catches a file
            # that grows after fstat without ever allocating an unbounded
            # buffer through Path.read_text().
            remaining = _MAX_SNAPSHOT_JSON_BYTES + 1 - received
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            received += len(chunk)
            if received > _MAX_SNAPSHOT_JSON_BYTES:
                raise ValueError(f"snapshot exceeds {_MAX_SNAPSHOT_JSON_BYTES} bytes")
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8")
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class SkillInstallOutcome:
    """Machine-readable result shared by CLI-adjacent install surfaces."""

    installed: bool
    name: str = ""
    message: str = ""


def _is_official_skill(result: object) -> bool:
    return getattr(result, "source", "") == "official"


def _display_source_id(source: str) -> str:
    return source


def _display_source(r) -> str:
    """Human-facing source label for a result row.

    GitHub-tap skills are stored under source="github"; surface their per-tap
    provider label (NVIDIA / OpenAI / ...) when present so the table reflects
    the real origin instead of the generic "github".
    """
    if _is_official_skill(r):
        return _display_source_id(r.source)
    if r.source == "github":
        provider = (getattr(r, "extra", None) or {}).get("provider")
        if provider:
            return provider
    return r.source


def _display_trust_label(r) -> str:
    if _is_official_skill(r):
        return "official"
    return r.trust_level


def _display_description(r) -> str:
    """Return the source-provided description without rewriting provenance."""

    return str(getattr(r, "description", "") or "")


# ---------------------------------------------------------------------------
# Shared do_* functions
# ---------------------------------------------------------------------------

def _resolve_short_name(name: str, sources, console: Console) -> str:
    """
    Resolve a short skill name (e.g. 'pptx') to a full identifier by searching
    all sources. If exactly one match is found, returns its identifier. If multiple
    matches exist, shows them and asks the user to use the full identifier.
    Returns empty string if nothing found or ambiguous.
    """
    from tools.skills_hub import unified_search

    c = console or _console
    c.print(f"[dim]Resolving '{name}'...[/]")

    results = unified_search(name, sources, source_filter="all", limit=20)

    # Filter to exact name matches (case-insensitive)
    exact = [r for r in results if r.name.lower() == name.lower()]

    if len(exact) == 1:
        c.print(f"[dim]Resolved to: {exact[0].identifier}[/]")
        return exact[0].identifier

    if len(exact) > 1:
        c.print(f"\n[yellow]Multiple skills named '{name}' found:[/]")
        table = Table()
        table.add_column("Source", style="dim")
        table.add_column("Trust", style="dim")
        # overflow="fold" keeps the full slug visible (wraps instead of ellipsis-truncating)
        # so users can copy it for `fabric skills install`.
        table.add_column("Identifier", style="bold cyan", overflow="fold", no_wrap=False)
        for r in exact:
            trust_style = {"builtin": "bright_cyan", "trusted": "green", "community": "yellow"}.get(r.trust_level, "dim")
            trust_label = _display_trust_label(r)
            table.add_row(_display_source(r), f"[{trust_style}]{trust_label}[/]", r.identifier)
        c.print(table)
        c.print("[bold]Use the full identifier to install a specific one.[/]\n")
        return ""

    # No exact match — check if there are partial matches to suggest
    if results:
        c.print(f"[yellow]No exact match for '{name}'. Did you mean one of these?[/]")
        for r in results[:5]:
            c.print(f"  [cyan]{r.name}[/] — {r.identifier}")
        c.print()
        return ""

    c.print(f"[bold red]Error:[/] No skill named '{name}' found in any source.\n")
    return ""


def _format_extra_metadata_lines(extra: Dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if not extra:
        return lines

    if extra.get("repo_url"):
        lines.append(f"[bold]Repo:[/] {extra['repo_url']}")
    if extra.get("detail_url"):
        lines.append(f"[bold]Detail Page:[/] {extra['detail_url']}")
    if extra.get("index_url"):
        lines.append(f"[bold]Index:[/] {extra['index_url']}")
    if extra.get("endpoint"):
        lines.append(f"[bold]Endpoint:[/] {extra['endpoint']}")
    if extra.get("install_command"):
        lines.append(f"[bold]Install Command:[/] {extra['install_command']}")
    if extra.get("installs") is not None:
        lines.append(f"[bold]Installs:[/] {extra['installs']}")
    if extra.get("weekly_installs"):
        lines.append(f"[bold]Weekly Installs:[/] {extra['weekly_installs']}")

    security = extra.get("security_audits")
    if isinstance(security, dict) and security:
        ordered = ", ".join(f"{name}={status}" for name, status in sorted(security.items()))
        lines.append(f"[bold]Security:[/] {ordered}")

    return lines


def _resolve_source_meta_and_bundle(identifier: str, sources):
    """Resolve metadata and bundle for a specific identifier."""
    meta = None
    bundle = None
    matched_source = None

    for src in sources:
        if meta is None:
            try:
                meta = src.inspect(identifier)
                if meta:
                    matched_source = src
            except Exception:
                meta = None
        try:
            bundle = src.fetch(identifier)
        except Exception:
            bundle = None
        if bundle:
            matched_source = src
            if meta is None:
                try:
                    meta = src.inspect(identifier)
                except Exception:
                    meta = None
            break

    return meta, bundle, matched_source


def _derive_category_from_install_path(install_path: str) -> str:
    path = Path(install_path)
    parent = str(path.parent)
    return "" if parent == "." else parent


# ---------------------------------------------------------------------------
# Interactive name/category resolution for URL-installed skills
# ---------------------------------------------------------------------------

_VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_VALID_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_/-]*$")


def _is_valid_installed_skill_name(name: str) -> bool:
    """Accept identifier-shaped names, reject empty / sentinel-y values."""
    if not isinstance(name, str):
        return False
    candidate = name.strip().lower()
    if not candidate or candidate in {"skill", "readme", "index", "unnamed-skill"}:
        return False
    return bool(_VALID_NAME_RE.match(candidate))


def _existing_categories() -> List[str]:
    """Return sorted subdirectory names under ``~/.fabric/skills/`` that look
    like category buckets (contain at least one ``SKILL.md`` somewhere below).

    Used to suggest reusable categories when interactively installing from a
    URL. Hidden dirs (``.hub``, ``.trash``) are skipped.
    """
    from tools.skills_hub import SKILLS_DIR
    out: List[str] = []
    try:
        for entry in SKILLS_DIR.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            # Only count as a category if it contains skills, not if it IS a skill.
            # Heuristic: if ``<entry>/SKILL.md`` exists, it's a skill at the
            # top level (no category); otherwise treat as a category bucket.
            if (entry / "SKILL.md").exists():
                continue
            # Has at least one nested SKILL.md (excluding dependency/cache dirs)?
            try:
                if any(
                    not is_excluded_skill_path(p)
                    for p in entry.rglob("SKILL.md")
                ):
                    out.append(entry.name)
            except OSError:
                continue
    except (FileNotFoundError, OSError):
        return []
    return sorted(set(out))


def _prompt_for_skill_name(c: Console, url: str, default: str = "") -> Optional[str]:
    """Prompt interactively for a skill name. Returns None on cancel/EOF."""
    c.print()
    c.print(
        f"[yellow]The SKILL.md at {url} doesn't declare a `name:` in its "
        f"frontmatter,[/]\n[yellow]and the URL path doesn't produce a valid "
        f"identifier either.[/]"
    )
    default_hint = f" [{default}]" if default else ""
    c.print(
        f"[bold]Enter a skill name{default_hint}:[/] "
        f"[dim](lowercase letters, digits, hyphens, underscores; starts with a letter)[/]"
    )
    try:
        answer = input("Name: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not answer and default:
        answer = default
    if not _is_valid_installed_skill_name(answer):
        c.print(f"[bold red]Invalid name:[/] {answer!r}. Aborting install.\n")
        return None
    return answer


def _prompt_for_category(c: Console, existing: List[str]) -> str:
    """Prompt interactively for a category. Empty/None input means flat install."""
    c.print()
    if existing:
        c.print(
            "[bold]Pick a category[/] "
            "[dim](reuse an existing bucket, type a new one, or press Enter to install flat)[/]"
        )
        c.print(f"[dim]Existing: {', '.join(existing)}[/]")
    else:
        c.print(
            "[bold]Category[/] [dim](optional — press Enter to install flat at ~/.fabric/skills/<name>/)[/]"
        )
    try:
        answer = input("Category: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    if not answer:
        return ""
    if not _VALID_CATEGORY_RE.match(answer):
        c.print(f"[dim]Invalid category {answer!r} — installing flat.[/]")
        return ""
    return answer


def do_search(query: str, source: str = "all", limit: int = 10,
              console: Optional[Console] = None, as_json: bool = False) -> None:
    """Search registries and display results as a Rich table.

    When ``as_json=True`` writes a JSON array of result records to stdout
    (one object per skill: ``name``, ``identifier``, ``source``,
    ``trust_level``, ``description``) and skips the table render. This is
    the scripting / copy-paste handle: the full identifier is always
    intact, even for browse-sh slugs that the table would otherwise wrap.
    """
    from tools.skills_hub import GitHubAuth, create_source_router, unified_search

    c = console or _console

    auth = GitHubAuth()
    sources = create_source_router(auth)
    if as_json:
        # Avoid Rich status spinner contaminating stdout — JSON consumers
        # expect a clean parseable stream.
        results = unified_search(query, sources, source_filter=source, limit=limit)
        payload = [
            {
                "name": r.name,
                "identifier": r.identifier,
                "source": r.source,
                "trust_level": r.trust_level,
                "description": r.description,
            }
            for r in results
        ]
        print(json.dumps(payload, indent=2))
        return

    c.print(f"\n[bold]Searching for:[/] {query}")
    with c.status("[bold]Searching registries..."):
        results = unified_search(query, sources, source_filter=source, limit=limit)

    if not results:
        c.print("[dim]No skills found matching your query.[/]\n")
        return

    table = Table(title=f"Skills Hub — {len(results)} result(s)")
    table.add_column("Name", style="bold cyan")
    table.add_column("Description", max_width=60)
    table.add_column("Source", style="dim")
    table.add_column("Trust", style="dim")
    # overflow="fold" keeps the full slug visible (wraps instead of
    # ellipsis-truncating). Browse.sh slugs end in a `-XXXXXX` hash that
    # is part of the actual identifier — truncating it makes copy-paste
    # into `fabric skills install` fail.
    table.add_column("Identifier", style="dim", overflow="fold", no_wrap=False)

    for r in results:
        trust_style = {"builtin": "bright_cyan", "trusted": "green", "community": "yellow"}.get(r.trust_level, "dim")
        trust_label = _display_trust_label(r)
        description = _display_description(r)
        table.add_row(
            r.name,
            description[:60] + ("..." if len(description) > 60 else ""),
            _display_source(r),
            f"[{trust_style}]{trust_label}[/]",
            r.identifier,
        )

    c.print(table)
    c.print("[dim]Use: fabric skills inspect <identifier> to preview, "
            "fabric skills install <identifier> to install "
            "(--json for scripting)[/]\n")


def do_browse(page: int = 1, page_size: int = 20, source: str = "all",
              console: Optional[Console] = None) -> None:
    """Browse all available skills across registries, paginated.

    Official skills are always shown first, regardless of source filter.
    """
    from tools.skills_hub import (
        GitHubAuth, create_source_router, parallel_search_sources,
    )

    # Clamp page_size to safe range
    page_size = max(1, min(page_size, 100))

    c = console or _console

    auth = GitHubAuth()
    sources = create_source_router(auth)

    # Collect results from all (or filtered) sources in parallel.
    # Per-source limits are generous — parallelism + 30s timeout cap prevents hangs.
    _TRUST_RANK = {"builtin": 3, "trusted": 2, "community": 1}
    # NOTE: when the centralized index is available, parallel_search_sources
    # skips the external API sources and serves everything from "fabric-index".
    # That source MUST therefore carry a limit large enough to cover the whole
    # catalog, or browse silently caps the hub — it shipped at 50 (surfaced
    # ~136 of 88k skills), then 5000 (surfaced ~5.4k of 90k). The index is
    # disk-cached and browse paginates client-side, so a ceiling above the
    # current catalog size is the right call. The external-source limits below
    # only apply when the index is unavailable (offline / first run before the
    # cache populates).
    _PER_SOURCE_LIMIT = {
        "fabric-index": 1000000,
        "official": 200, "skills-sh": 200, "well-known": 50,
        "github": 200, "clawhub": 500, "claude-marketplace": 100,
        "lobehub": 500, "browse-sh": 500,
    }

    with c.status("[bold]Fetching skills from registries...") as status:
        # Live progress: tick off each source as it resolves so the wait is
        # visible instead of a frozen spinner. parallel_search_sources invokes
        # this callback from the collecting thread as each source completes;
        # the page itself is still rendered once, after the correctly-merged
        # and trust-sorted result set is final (browse's ordering contract is
        # computed over the whole set, so we never render a half-sorted page).
        _done: List[str] = []

        def _on_source_done(sid: str, count: int) -> None:
            _done.append(f"{sid} ({count})")
            status.update(
                "[bold]Fetching skills from registries...[/]  "
                f"[dim]done: {', '.join(_done)}[/]"
            )

        all_results, source_counts, timed_out = parallel_search_sources(
            sources,
            query="",
            per_source_limits=_PER_SOURCE_LIMIT,
            source_filter=source,
            overall_timeout=30,
            on_source_done=_on_source_done,
        )

    if not all_results:
        c.print("[dim]No skills found in the Skills Hub.[/]\n")
        return

    # Provider filter (nvidia/openai/...) narrows GitHub-tap skills by their
    # per-tap ``extra.provider`` label (the runtime index stores them all under
    # source="github"). Real source ids were already filtered upstream.
    from tools.skills_hub import _PROVIDER_FILTER_VALUES, _filter_results_by_provider
    if source.strip().lower() in _PROVIDER_FILTER_VALUES:
        all_results = _filter_results_by_provider(all_results, source)
        if not all_results:
            c.print(f"[dim]No skills found for provider '{source}'.[/]\n")
            return

    # Deduplicate by identifier, preferring higher trust.
    # identifier is always unique per skill; name is not (browse-sh skills from different
    # sites can share the same task name, e.g. "search-listings" on Airbnb and Booking.com).
    seen: dict = {}
    for r in all_results:
        rank = _TRUST_RANK.get(r.trust_level, 0)
        if r.identifier not in seen or rank > _TRUST_RANK.get(seen[r.identifier].trust_level, 0):
            seen[r.identifier] = r
    deduped = list(seen.values())

    # Sort: official first, then by trust level (desc), then alphabetically
    deduped.sort(key=lambda r: (
        -_TRUST_RANK.get(r.trust_level, 0),
        r.source != "official",
        r.name.lower(),
    ))

    # Paginate
    total = len(deduped)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = min(start + page_size, total)
    page_items = deduped[start:end]

    # Count official vs other
    official_count = sum(1 for r in deduped if r.source == "official")

    # Build header
    source_label = f"— {_display_source_id(source)}" if source != "all" else "— all sources"
    loaded_label = f"{total} skills loaded"
    if timed_out:
        loaded_label += f", {len(timed_out)} source(s) still loading"
    c.print(f"\n[bold]Skills Hub — Browse {source_label}[/]"
            f"  [dim]({loaded_label}, page {page}/{total_pages})[/]")
    if official_count > 0 and page == 1:
        c.print(f"[bright_cyan]★ {official_count} official optional skill(s) from Nous Research[/]")
    c.print()

    # Build table
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Name", style="bold cyan", max_width=22)
    table.add_column("Description", max_width=44)
    table.add_column("Source", style="dim", width=12)
    table.add_column("Trust", width=10)
    # The identifier is what you pass to `fabric skills install`. Browse used
    # to omit it entirely, so users couldn't act on what they saw without a
    # second `search`. overflow="fold" keeps long slugs copy-pasteable.
    table.add_column("Identifier", style="dim", overflow="fold", no_wrap=False)

    for i, r in enumerate(page_items, start=start + 1):
        trust_style = {"builtin": "bright_cyan", "trusted": "green",
                       "community": "yellow"}.get(r.trust_level, "dim")
        trust_label = "★ official" if r.source == "official" else r.trust_level

        display_description = _display_description(r)
        desc = display_description[:44]
        if len(display_description) > 44:
            desc += "..."

        table.add_row(
            str(i),
            r.name,
            desc,
            _display_source(r),
            f"[{trust_style}]{trust_label}[/]",
            r.identifier,
        )

    c.print(table)

    # Navigation hints
    nav_parts = []
    if page > 1:
        nav_parts.append(f"[cyan]--page {page - 1}[/] ← prev")
    if page < total_pages:
        nav_parts.append(f"[cyan]--page {page + 1}[/] → next")

    if nav_parts:
        c.print(f"  {' | '.join(nav_parts)}")

    # Source summary
    if source == "all" and source_counts:
        parts = [
            f"{_display_source_id(sid)}: {ct}"
            for sid, ct in sorted(source_counts.items())
        ]
        c.print(f"  [dim]Sources: {', '.join(parts)}[/]")

    if timed_out:
        c.print(f"  [yellow]⚡ Slow sources skipped: {', '.join(_display_source_id(sid) for sid in timed_out)} "
                f"— run again for cached results[/]")

    c.print("[dim]Tip: 'fabric skills inspect <identifier>' to preview, "
            "'fabric skills install <identifier>' to install, "
            "'fabric skills search <query>' to search deeper[/]\n")


def do_install(identifier: str, category: str = "", force: bool = False,
               console: Optional[Console] = None, skip_confirm: bool = False,
               invalidate_cache: bool = True,
               name_override: str = "",
               snapshot_identity: Optional[dict] = None,
               checked_update: Optional[dict] = None) -> SkillInstallOutcome:
    """Fetch, quarantine, scan, confirm, and install a skill.

    ``name_override`` lets non-interactive callers (slash commands, gateway,
    scripts) supply a skill name when the upstream SKILL.md lacks a valid
    ``name:`` frontmatter field. On interactive TTY surfaces, a missing name
    triggers a prompt instead; ``skip_confirm=True`` means "non-interactive"
    (so pair it with ``name_override`` when installing from a URL that has
    no frontmatter). The structured outcome prevents non-interactive callers
    from mistaking a handled refusal or fetch failure for a successful install.
    """
    from tools.skills_hub import (
        GitHubAuth, create_source_router, ensure_hub_dirs,
        quarantine_bundle, install_from_quarantine, HubLockFile,
        _resolve_lock_install_path, scan_skill_with_authority,
        source_authority_for_adapter, HubSourceAuthority,
        HubSourceKind,
        bundle_source_revision, fetch_snapshot_bundle,
        bundle_content_hash, bundle_snapshot_identity,
    )
    from tools.skills_guard import scan_skill, should_allow_install, format_scan_report

    c = console or _console
    ensure_hub_dirs()

    if snapshot_identity is not None and checked_update is not None:
        return SkillInstallOutcome(
            installed=False,
            message="Snapshot install and checked update cannot be combined.",
        )

    # Resolve which source adapter handles this identifier. Checked updates
    # carry the exact in-memory candidate and never consult the router again.
    sources = []
    if checked_update is None:
        auth = GitHubAuth()
        sources = create_source_router(auth)

    expected_authority = None
    checked_installed_entry = None
    bundle = None
    meta = None
    matched_source = None
    if checked_update is not None:
        try:
            expected_authority = HubSourceAuthority.from_dict(
                checked_update["authority"]
            )
            bundle = copy.deepcopy(checked_update["bundle"])
            checked_installed_entry = copy.deepcopy(
                checked_update["installed_entry"]
            )
            expected_hash = checked_update["latest_hash"]
            expected_snapshot_identity = checked_update["snapshot_identity"]
            expected_name = checked_update["source_name"]
            expected_revision = checked_update["source_revision"]
            if not isinstance(checked_installed_entry, dict):
                raise ValueError("installed entry is invalid")
            expected_authority.validate_bundle(bundle)
            if (
                bundle_content_hash(bundle) != expected_hash
                or bundle_snapshot_identity(bundle) != expected_snapshot_identity
                or bundle.name != expected_name
                or bundle_source_revision(bundle) != expected_revision
            ):
                raise ValueError("checked bundle identity changed")
            identifier = expected_authority.remote_identifier
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            return SkillInstallOutcome(
                installed=False,
                message=f"Checked update candidate is invalid: {exc}",
            )
    if snapshot_identity is not None:
        try:
            expected_authority = HubSourceAuthority.from_dict(
                snapshot_identity["authority"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            return SkillInstallOutcome(
                installed=False,
                message=f"Snapshot authority is invalid: {exc}",
            )
        sources = [
            source
            for source in sources
            if source.source_id() == expected_authority.adapter.value
        ]
        if len(sources) != 1:
            return SkillInstallOutcome(
                installed=False,
                message=(
                    "Snapshot adapter is unavailable; refusing to resolve through "
                    "another source."
                ),
            )
        identifier = expected_authority.remote_identifier

    # If identifier looks like a short name (no slashes), resolve it via search
    if snapshot_identity is None and checked_update is None and "/" not in identifier:
        identifier = _resolve_short_name(identifier, sources, c)
        if not identifier:
            return SkillInstallOutcome(
                installed=False,
                message="Skill name could not be resolved to a unique source.",
            )

    c.print(f"\n[bold]Fetching:[/] {identifier}")

    if checked_update is not None:
        pass
    elif expected_authority is None:
        meta, bundle, matched_source = _resolve_source_meta_and_bundle(
            identifier,
            sources,
        )
    else:
        meta = None
        matched_source = sources[0]
        try:
            bundle = fetch_snapshot_bundle(
                matched_source,
                expected_authority,
                snapshot_identity["source_revision"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            return SkillInstallOutcome(
                installed=False,
                message=f"Snapshot source identity is invalid: {exc}",
            )

    if not bundle:
        # Check if any source hit GitHub API rate limit
        rate_limited = any(
            getattr(src, "is_rate_limited", False)
            or getattr(getattr(src, "github", None), "is_rate_limited", False)
            for src in sources
        )
        c.print(f"[bold red]Error:[/] Could not fetch '{identifier}' from any source.")
        if rate_limited:
            c.print(
                "[yellow]Hint:[/] GitHub API rate limit exhausted "
                "(unauthenticated: 60 requests/hour).\n"
                "Set [bold]GITHUB_TOKEN[/] in your .env or install the "
                "[bold]gh[/] CLI and run [bold]gh auth login[/] "
                "to raise the limit to 5,000/hr.\n"
            )
        else:
            c.print()
        return SkillInstallOutcome(
            installed=False,
            message=f"Could not fetch '{identifier}' from any source.",
        )

    if checked_update is not None:
        assert expected_authority is not None
        source_authority = expected_authority
    else:
        if matched_source is None:
            return SkillInstallOutcome(
                installed=False,
                message="The fetched skill has no authenticated source adapter.",
            )
        try:
            source_authority = source_authority_for_adapter(matched_source, bundle)
        except ValueError as exc:
            c.print(f"[bold red]Installation blocked:[/] {exc}\n")
            return SkillInstallOutcome(
                installed=False,
                name=str(getattr(bundle, "name", "") or ""),
                message=f"Installation blocked: {exc}",
            )
    if snapshot_identity is not None:
        expected_name = snapshot_identity.get("source_name")
        expected_revision = snapshot_identity.get("source_revision")
        if (
            source_authority != expected_authority
            or bundle.name != expected_name
            or bundle_source_revision(bundle) != expected_revision
        ):
            message = "Snapshot source identity no longer matches the fetched bundle"
            c.print(f"[bold red]Installation blocked:[/] {message}\n")
            return SkillInstallOutcome(
                installed=False,
                name=str(bundle.name or ""),
                message=message,
            )

    # URL-sourced skills may arrive with an empty name when SKILL.md has no
    # ``name:`` in frontmatter AND the URL path doesn't yield a valid
    # identifier. Resolve by (1) --name override, (2) interactive prompt on
    # a TTY, (3) refuse with an actionable error on non-interactive surfaces.
    bundle_meta = getattr(bundle, "metadata", {}) or {}
    if bundle.source == "url" and (not bundle.name or bundle_meta.get("awaiting_name")):
        if name_override and _is_valid_installed_skill_name(name_override):
            bundle.name = name_override.strip()
            bundle_meta["awaiting_name"] = False
        elif name_override:
            c.print(
                f"[bold red]Invalid --name:[/] {name_override!r}. "
                "Must be a lowercase identifier (letters, digits, hyphens, "
                "underscores; starts with a letter).\n"
            )
            return SkillInstallOutcome(
                installed=False,
                name=str(bundle.name or ""),
                message=f"Invalid skill name override: {name_override!r}.",
            )
        elif skip_confirm:
            # Non-interactive surface (slash command / TUI / gateway). Can't
            # prompt — emit an actionable error.
            url = bundle_meta.get("url") or identifier
            c.print(
                f"[bold red]Cannot install from URL:[/] {url}\n"
                "[yellow]The SKILL.md has no `name:` in its frontmatter, "
                "and the URL path doesn't produce a valid identifier.[/]\n\n"
                "Retry with an explicit name:\n"
                f"  [bold]/skills install {url} --name <your-name>[/]\n"
                f"  [bold]fabric skills install {url} --name <your-name>[/]\n\n"
                "[dim]Or ask the SKILL.md's author to add a `name:` field to "
                "its YAML frontmatter.[/]\n"
            )
            return SkillInstallOutcome(
                installed=False,
                message="The skill has no valid name; retry with --name <your-name>.",
            )
        else:
            # Interactive TTY — prompt.
            url = bundle_meta.get("url") or identifier
            chosen = _prompt_for_skill_name(c, url)
            if not chosen:
                c.print("[dim]Installation cancelled.[/]\n")
                return SkillInstallOutcome(
                    installed=False,
                    message="Installation cancelled.",
                )
            bundle.name = chosen
            bundle_meta["awaiting_name"] = False
        # Keep SkillMeta in sync so downstream "already installed" checks,
        # audit logs, and display all see the final name.
        if meta is not None:
            meta.name = bundle.name
            meta.path = bundle.name

    # URL-sourced skills: offer to pick a category interactively when the
    # caller didn't specify one (TTY only — non-interactive installs fall
    # through to flat install, matching all other sources).
    if bundle.source == "url" and not category and not skip_confirm:
        category = _prompt_for_category(c, _existing_categories())

    # Auto-detect the full parent path for official skills. Optional skills
    # can be nested (e.g. "official/mlops/training/trl-fine-tuning"), so keep
    # every identifier segment between "official" and the final skill slug.
    is_official_optional = (
        source_authority.adapter is HubSourceKind.OFFICIAL_OPTIONAL
    )
    if is_official_optional and not category:
        id_parts = bundle.identifier.split("/")
        if len(id_parts) >= 3:
            category = "/".join(id_parts[1:-1])

    # Check if already installed
    lock = HubLockFile()
    existing = lock.get_installed(bundle.name)
    expected_commit_entry = None
    if checked_installed_entry is not None:
        expected_entry = dict(checked_installed_entry)
        expected_entry.pop("name", None)
        if existing != expected_entry:
            message = "Installed Hub state changed after the update check"
            c.print(f"[bold red]Installation blocked:[/] {message}\n")
            return SkillInstallOutcome(
                installed=False,
                name=bundle.name,
                message=message,
            )
        expected_commit_entry = expected_entry
    install_rel_path = f"{category}/{bundle.name}" if category else bundle.name
    try:
        preflight_destination = _resolve_lock_install_path(
            install_rel_path,
            bundle.name,
        )
    except ValueError as exc:
        c.print(f"[bold red]Installation blocked:[/] {exc}\n")
        return SkillInstallOutcome(
            installed=False,
            name=bundle.name,
            message=f"Installation blocked: {exc}",
        )
    if existing is None and (
        preflight_destination.exists() or preflight_destination.is_symlink()
    ):
        message = "Refusing to replace an untracked or locally owned skill directory"
        c.print(f"[bold red]Installation blocked:[/] {message}\n")
        return SkillInstallOutcome(
            installed=False,
            name=bundle.name,
            message=message,
        )
    if existing:
        c.print(f"[yellow]Warning:[/] '{bundle.name}' is already installed at {existing['install_path']}")
        if not force:
            c.print("Use --force to reinstall.\n")
            return SkillInstallOutcome(
                installed=False,
                name=bundle.name,
                message=f"Skill '{bundle.name}' is already installed; use --force to reinstall.",
            )

    extra_metadata = dict(getattr(meta, "extra", {}) or {})
    extra_metadata.update(getattr(bundle, "metadata", {}) or {})

    # Quarantine the bundle
    try:
        q_path = quarantine_bundle(bundle)
    except ValueError as exc:
        c.print(f"[bold red]Installation blocked:[/] {exc}\n")
        from tools.skills_hub import append_audit_log
        append_audit_log(
            "BLOCKED",
            bundle.name,
            source_authority.adapter.value,
            source_authority.trust_level,
            "invalid_path",
            str(exc),
        )
        return SkillInstallOutcome(
            installed=False,
            name=bundle.name,
            message=f"Installation blocked: {exc}",
        )
    c.print(f"[dim]Quarantined to {q_path.relative_to(q_path.parent.parent.parent)}[/]")

    # Scan
    c.print("[bold]Running security scan...[/]")
    result = scan_skill_with_authority(q_path, source_authority)
    if snapshot_identity is not None and (
        result.attested_tree_sha256 != snapshot_identity.get("digest")
    ):
        message = "Snapshot digest no longer matches the fetched source tree"
        c.print(f"[bold red]Installation blocked:[/] {message}\n")
        return SkillInstallOutcome(
            installed=False,
            name=bundle.name,
            message=message,
        )
    c.print(format_scan_report(result))

    # Check install policy
    allowed, reason = should_allow_install(result, force=force)
    if not allowed:
        c.print(f"\n[bold red]Installation blocked:[/] {reason}")
        # Clean up quarantine
        shutil.rmtree(q_path, ignore_errors=True)
        from tools.skills_hub import append_audit_log
        append_audit_log(
            "BLOCKED",
            bundle.name,
            source_authority.adapter.value,
            source_authority.trust_level,
            result.verdict,
            f"{len(result.findings)}_findings",
        )
        return SkillInstallOutcome(
            installed=False,
            name=bundle.name,
            message=f"Installation blocked: {reason}",
        )

    if extra_metadata:
        metadata_lines = _format_extra_metadata_lines(extra_metadata)
        if metadata_lines:
            c.print(Panel("\n".join(metadata_lines), title="Upstream Metadata", border_style="blue"))

    # Confirm with user — show appropriate warning based on source
    # skip_confirm bypasses the prompt (needed in TUI mode where input() hangs)
    if not force and not skip_confirm:
        c.print()
        if is_official_optional:
            provenance = "[bold bright_cyan]This is an official optional skill maintained by Nous Research.[/]"
            panel_title = "Official Skill"
            c.print(Panel(
                f"{provenance}\n\n"
                "It ships with fabric-agent but is not activated by default.\n"
                "Installing will copy it to your skills directory where the agent can use it.\n\n"
                f"Files will be at: [cyan]{display_fabric_home()}/skills/{category + '/' if category else ''}{bundle.name}/[/]",
                title=panel_title,
                border_style="bright_cyan",
            ))
        else:
            c.print(Panel(
                "[bold yellow]You are installing a third-party skill at your own risk.[/]\n\n"
                "External skills can contain instructions that influence agent behavior,\n"
                "shell commands, and scripts. Even after automated scanning, you should\n"
                "review the installed files before use.\n\n"
                f"Files will be at: [cyan]{display_fabric_home()}/skills/{category + '/' if category else ''}{bundle.name}/[/]",
                title="Disclaimer",
                border_style="yellow",
            ))
        c.print(f"[bold]Install '{bundle.name}'?[/]")
        try:
            answer = input("Confirm [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in {"y", "yes"}:
            c.print("[dim]Installation cancelled.[/]\n")
            shutil.rmtree(q_path, ignore_errors=True)
            return SkillInstallOutcome(
                installed=False,
                name=bundle.name,
                message="Installation cancelled.",
            )

    # Install
    try:
        commit_kwargs = {
            "source_authority": source_authority,
            "force": force,
        }
        if expected_commit_entry is not None:
            commit_kwargs["expected_installed_entry"] = expected_commit_entry
        hub_outcome = install_from_quarantine(
            q_path,
            bundle.name,
            category,
            bundle,
            result,
            **commit_kwargs,
        )
    except ValueError as exc:
        c.print(f"[bold red]Installation blocked:[/] {exc}\n")
        from tools.skills_hub import append_audit_log
        append_audit_log("BLOCKED", bundle.name, bundle.source,
                         bundle.trust_level, "invalid_path", str(exc))
        return SkillInstallOutcome(
            installed=False,
            name=bundle.name,
            message=f"Installation blocked: {exc}",
        )
    if not hub_outcome.committed or hub_outcome.install_path is None:
        c.print(
            f"[bold red]Installation not committed:[/] {hub_outcome.message}\n"
        )
        return SkillInstallOutcome(
            installed=False,
            name=bundle.name,
            message=hub_outcome.message,
        )
    install_dir = hub_outcome.install_path
    from tools.skills_hub import SKILLS_DIR

    c.print(f"[bold green]Installed:[/] {install_dir.relative_to(SKILLS_DIR)}")
    installed_files = sorted(
        entry.relative_to(install_dir).as_posix()
        for entry in install_dir.rglob("*")
        if entry.is_file()
    )
    c.print(f"[dim]Files: {', '.join(installed_files)}[/]\n")
    if hub_outcome.cleanup_pending:
        c.print(
            "[dim]Recovery artifacts retained: "
            f"{', '.join(hub_outcome.cleanup_pending)}[/]\n"
        )

    # Blueprint detection: if the installed skill declares a
    # metadata.fabric.blueprint block,
    # it is a runnable automation. Register it as a Suggested Cron Job rather
    # than auto-scheduling — installing never
    # silently creates a recurring job; the user accepts it via /suggestions.
    # This is the single surface every automation proposal flows through.
    try:
        from tools.blueprints import BlueprintError, blueprint_spec_for_installed, register_blueprint_suggestion

        try:
            spec = blueprint_spec_for_installed(bundle.name)
        except BlueprintError as _rec_err:
            c.print(f"[yellow]Blueprint block present but invalid:[/] {_rec_err}\n")
            spec = None
        if spec is not None:
            registered = register_blueprint_suggestion(spec)
            if registered is not None:
                c.print(
                    f"[bold cyan]Blueprint:[/] '{bundle.name}' is an automation "
                    f"(schedule [bold]{spec.schedule}[/])."
                )
                c.print(
                    "[dim]Added to your suggestions — run[/] [bold]/suggestions[/] "
                    "[dim]to schedule or dismiss it.[/]\n"
                )
            else:
                # Dropped: already offered/dismissed (latched) or the pending
                # list is at its cap. Say so instead of silently doing nothing —
                # the user can still schedule it by hand.
                c.print(
                    f"[bold cyan]Blueprint:[/] '{bundle.name}' is an automation "
                    f"(schedule [bold]{spec.schedule}[/]), but it wasn't added to "
                    "your suggestions (already offered/dismissed, or the pending "
                    "list is full — run [bold]/suggestions[/] to review)."
                )
                c.print(
                    "[dim]You can still schedule it any time by asking the agent "
                    "or via[/] [bold]fabric cron add[/][dim].[/]\n"
                )
    except Exception:  # pragma: no cover - blueprint detection is best-effort
        pass

    if invalidate_cache:
        # Invalidate the skills prompt cache so the new skill appears immediately
        try:
            from agent.prompt_builder import clear_skills_system_prompt_cache
            clear_skills_system_prompt_cache(clear_snapshot=True)
        except Exception:
            pass
    else:
        c.print("[dim]Skill will be available in your next session.[/]")
        c.print("[dim]Use /reset to start a new session now, or --now to activate immediately (invalidates prompt cache).[/]\n")

    return SkillInstallOutcome(
        installed=True,
        name=bundle.name,
        message="Installed successfully.",
    )


def do_inspect(identifier: str, console: Optional[Console] = None) -> None:
    """Preview a skill's SKILL.md content without installing."""
    from tools.skills_hub import GitHubAuth, create_source_router

    c = console or _console
    auth = GitHubAuth()
    sources = create_source_router(auth)

    if "/" not in identifier:
        identifier = _resolve_short_name(identifier, sources, c)
        if not identifier:
            return

    meta, bundle, _matched_source = _resolve_source_meta_and_bundle(identifier, sources)

    if not meta:
        c.print(f"[bold red]Error:[/] Could not find '{identifier}' in any source.\n")
        return

    c.print()
    trust_style = {"builtin": "bright_cyan", "trusted": "green", "community": "yellow"}.get(meta.trust_level, "dim")

    info_lines = [
        f"[bold]Name:[/] {meta.name}",
        f"[bold]Description:[/] {_display_description(meta)}",
        f"[bold]Source:[/] {_display_source(meta)}",
        f"[bold]Trust:[/] [{trust_style}]{_display_trust_label(meta)}[/]",
        f"[bold]Identifier:[/] {meta.identifier}",
    ]
    if meta.tags:
        info_lines.append(f"[bold]Tags:[/] {', '.join(meta.tags)}")
    info_lines.extend(_format_extra_metadata_lines(meta.extra))

    c.print(Panel("\n".join(info_lines), title=f"Skill: {meta.name}"))

    if bundle and "SKILL.md" in bundle.files:
        content = bundle.files["SKILL.md"]
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        # Show first 50 lines as preview
        lines = content.split("\n")
        preview = "\n".join(lines[:50])
        if len(lines) > 50:
            preview += f"\n\n... ({len(lines) - 50} more lines)"
        c.print(Panel(preview, title="SKILL.md Preview", subtitle="fabric skills install <id> to install"))

    c.print()


def browse_skills(page: int = 1, page_size: int = 20, source: str = "all") -> dict:
    """Paginated hub browse for programmatic callers (e.g. TUI gateway).

    Returns ``{"items": [...], "page": int, "total_pages": int, "total": int}``.
    """
    from tools.skills_hub import (
        GitHubAuth, create_source_router, parallel_search_sources,
    )

    page_size = max(1, min(page_size, 100))
    _TRUST_RANK = {"builtin": 3, "trusted": 2, "community": 1}
    # "fabric-index" must carry a high limit: when the index is available the
    # router skips external API sources and serves everything from it, so a
    # low cap here silently truncates the whole hub (see do_browse note).
    _PER_SOURCE_LIMIT = {"fabric-index": 5000, "official": 100, "skills-sh": 100,
                         "well-known": 25, "github": 100, "clawhub": 50,
                         "claude-marketplace": 50, "lobehub": 50, "browse-sh": 500}
    auth = GitHubAuth()
    sources = create_source_router(auth)
    # Delegate to the shared parallel walker so this inherits the index-aware
    # source-skip logic — querying fabric-index AND the external APIs at once
    # would double-count every skill.
    all_results, _counts, _timed_out = parallel_search_sources(
        sources, query="", per_source_limits=_PER_SOURCE_LIMIT,
        source_filter=source, overall_timeout=30,
    )
    if not all_results:
        return {"items": [], "page": 1, "total_pages": 1, "total": 0}
    seen: dict = {}
    for r in all_results:
        rank = _TRUST_RANK.get(r.trust_level, 0)
        if r.identifier not in seen or rank > _TRUST_RANK.get(seen[r.identifier].trust_level, 0):
            seen[r.identifier] = r
    deduped = list(seen.values())
    deduped.sort(key=lambda r: (-_TRUST_RANK.get(r.trust_level, 0), r.source != "official", r.name.lower()))
    total = len(deduped)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    page_items = deduped[start : min(start + page_size, total)]
    return {
        "items": [
            {
                "name": r.name,
                "description": _display_description(r),
                # Keep the source identifier as upstream provenance metadata;
                # only the rendered CLI label is presentation-neutralized.
                "source": r.source,
                "trust": _display_trust_label(r),
                "identifier": r.identifier,
            }
            for r in page_items
        ],
        "page": page,
        "total_pages": total_pages,
        "total": total,
    }


def inspect_skill(identifier: str) -> Optional[dict]:
    """Skill metadata (+ SKILL.md preview) for programmatic callers."""
    from tools.skills_hub import GitHubAuth, create_source_router

    class _Q:
        def print(self, *a, **k):
            pass

    c = _Q()
    auth = GitHubAuth()
    sources = create_source_router(auth)
    ident = identifier
    if "/" not in ident:
        ident = _resolve_short_name(ident, sources, c)
        if not ident:
            return None
    meta, bundle, _ = _resolve_source_meta_and_bundle(ident, sources)
    if not meta:
        return None
    out: dict = {
        "name": meta.name,
        "description": _display_description(meta),
        "source": meta.source,
        "identifier": meta.identifier,
        "tags": list(meta.tags) if meta.tags else [],
    }
    if bundle and "SKILL.md" in bundle.files:
        content = bundle.files["SKILL.md"]
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        lines = content.split("\n")
        preview = "\n".join(lines[:50])
        if len(lines) > 50:
            preview += f"\n\n... ({len(lines) - 50} more lines)"
        out["skill_md_preview"] = preview
    return out


def do_list(source_filter: str = "all",
            enabled_only: bool = False,
            console: Optional[Console] = None) -> None:
    """List installed skills, distinguishing hub, builtin, and local skills.

    Args:
        source_filter: ``all`` | ``hub`` | ``builtin`` | ``local``.
        enabled_only: If True, hide disabled skills from the output.

    Enabled/disabled state is resolved against the currently active profile's
    config — ``fabric -p <profile> skills list`` reads that profile's
    ``skills.disabled`` list because ``-p`` swaps ``FABRIC_HOME`` at process
    start.  No explicit profile flag needed here.
    """
    from tools.skills_hub import (
        HubInstallError,
        HubLockFile,
        HubSourceKind,
        _authority_for_installed_entry,
        ensure_hub_dirs,
    )
    from tools.skills_sync import _read_manifest
    from tools.skills_tool import _find_all_skills
    from agent.skill_utils import get_disabled_skill_names

    c = console or _console
    ensure_hub_dirs()
    lock = HubLockFile()
    hub_installed = {e["name"]: e for e in lock.list_installed()}
    builtin_names = set(_read_manifest())

    # Pull ALL skills (including disabled ones) so we can annotate status.
    all_skills = _find_all_skills(skip_disabled=True)
    disabled_names = get_disabled_skill_names()

    title = "Installed Skills"
    if enabled_only:
        title += " (enabled only)"

    table = Table(title=title)
    table.add_column("Name", style="bold cyan")
    table.add_column("Category", style="dim")
    table.add_column("Source", style="dim")
    table.add_column("Trust", style="dim")
    table.add_column("Status", style="dim")

    hub_count = 0
    builtin_count = 0
    local_count = 0
    enabled_count = 0
    disabled_count = 0

    for skill in sorted(all_skills, key=lambda s: (s.get("category") or "", s["name"])):
        name = skill["name"]
        category = skill.get("category", "")
        hub_entry = hub_installed.get(name)
        is_official = False

        if hub_entry:
            source_type = "hub"
            try:
                authority = _authority_for_installed_entry(hub_entry)
            except HubInstallError:
                authority = None
            is_official = (
                authority is not None
                and authority.adapter is HubSourceKind.OFFICIAL_OPTIONAL
                and authority.trust_level == "builtin"
            )
            if is_official:
                source_display = "official"
                trust = "builtin"
            elif authority is None or hub_entry.get("source") == "official":
                # A raw/legacy source string cannot grant the official label.
                source_display = "unverified"
                trust = "community"
            else:
                source_display = authority.bundle_source
                trust = authority.trust_level
        elif name in builtin_names:
            source_type = "builtin"
            source_display = "builtin"
            trust = "builtin"
        else:
            source_type = "local"
            source_display = "local"
            trust = "local"

        if source_filter != "all" and source_filter != source_type:
            continue

        is_enabled = name not in disabled_names
        if enabled_only and not is_enabled:
            continue

        if source_type == "hub":
            hub_count += 1
        elif source_type == "builtin":
            builtin_count += 1
        else:
            local_count += 1

        if is_enabled:
            enabled_count += 1
            status_cell = "[bold green]enabled[/]"
        else:
            disabled_count += 1
            status_cell = "[dim red]disabled[/]"

        trust_style = {"builtin": "bright_cyan", "trusted": "green", "community": "yellow", "local": "dim"}.get(trust, "dim")
        trust_label = "official" if source_type == "hub" and is_official else trust
        table.add_row(name, category, source_display, f"[{trust_style}]{trust_label}[/]", status_cell)

    c.print(table)
    summary = f"[dim]{hub_count} hub-installed, {builtin_count} builtin, {local_count} local"
    if enabled_only:
        summary += f" — {enabled_count} enabled shown"
    else:
        summary += f" — {enabled_count} enabled, {disabled_count} disabled"
    summary += "[/]\n"
    c.print(summary)


def do_check(name: Optional[str] = None, console: Optional[Console] = None) -> None:
    """Check hub-installed skills for upstream updates."""
    from tools.skills_hub import check_for_skill_updates

    c = console or _console
    results = check_for_skill_updates(name=name)
    if not results:
        c.print("[dim]No hub-installed skills to check.[/]\n")
        return

    table = Table(title="Skill Updates")
    table.add_column("Name", style="bold cyan")
    table.add_column("Source", style="dim")
    table.add_column("Status", style="dim")

    for entry in results:
        table.add_row(entry.get("name", ""), entry.get("source", ""), entry.get("status", ""))

    c.print(table)
    update_count = sum(1 for entry in results if entry.get("status") == "update_available")
    c.print(f"[dim]{update_count} update(s) available across {len(results)} checked skill(s)[/]\n")


def do_update(name: Optional[str] = None, console: Optional[Console] = None) -> None:
    """Update hub-installed skills with upstream changes."""
    from tools.skills_hub import check_for_skill_updates

    c = console or _console
    updates = [entry for entry in check_for_skill_updates(name=name) if entry.get("status") == "update_available"]
    if not updates:
        c.print("[dim]No updates available.[/]\n")
        return

    updated = 0
    refused = 0
    for entry in updates:
        candidate = entry.get("checked_candidate")
        if not isinstance(candidate, dict):
            refused += 1
            c.print(
                f"[bold red]Update not applied:[/] {entry['name']} — "
                "the checked candidate is unavailable"
            )
            continue
        installed = (
            candidate.get("installed_entry")
            if isinstance(candidate, dict) else None
        )
        category = _derive_category_from_install_path(installed.get("install_path", "")) if installed else ""
        c.print(f"[bold]Updating:[/] {entry['name']}")
        outcome = do_install(
            entry["identifier"],
            category=category,
            force=True,
            console=c,
            checked_update=candidate,
        )
        if outcome.installed:
            updated += 1
        else:
            refused += 1
            c.print(
                f"[bold red]Update not applied:[/] {entry['name']} — "
                f"{outcome.message}"
            )

    style = "bold green" if refused == 0 else "bold yellow"
    c.print(
        f"[{style}]Update result: {updated} applied, {refused} refused/failed.[/]\n"
    )


def do_gc(console: Optional[Console] = None) -> dict[str, int]:
    """Recover and prune one bounded batch of terminal Hub transactions."""

    from tools.skills_hub import gc_hub_transaction_artifacts

    c = console or _console
    result = gc_hub_transaction_artifacts()
    c.print(
        "[bold green]Skills Hub cleanup complete:[/] "
        f"{result['transactions_removed']} transaction record(s), "
        f"{result['removed']} payload artifact(s) removed; "
        f"{result['retained']} payload artifact(s) and "
        f"{result.get('transactions_retained', 0)} transaction record(s) "
        "retained for inspection."
    )
    if result.get("truncated"):
        c.print(
            "[dim]More transaction records remain; run `fabric skills gc` again.[/]"
        )
    c.print()
    return result


def do_audit(name: Optional[str] = None, console: Optional[Console] = None,
             deep: bool = False) -> None:
    """Re-run security scan on installed hub skills.

    When ``deep=True``, also runs an opt-in AST-level diagnostic on Python
    files (review aid only — not a security gate; skills_guard.py verdicts
    are unchanged).
    """
    from tools.skills_hub import HubLockFile, SKILLS_DIR
    from tools.skills_guard import scan_skill, format_scan_report

    c = console or _console
    lock = HubLockFile()
    installed = lock.list_installed()

    if not installed:
        c.print("[dim]No hub-installed skills to audit.[/]\n")
        return

    targets = installed
    if name:
        targets = [e for e in installed if e["name"] == name]
        if not targets:
            c.print(f"[bold red]Error:[/] '{name}' is not a hub-installed skill.\n")
            return

    c.print(f"\n[bold]Auditing {len(targets)} skill(s)...[/]\n")

    if deep:
        from tools.skills_ast_audit import ast_scan_path, format_ast_report

    for entry in targets:
        skill_path = SKILLS_DIR / entry["install_path"]
        if not skill_path.exists():
            c.print(f"[yellow]Warning:[/] {entry['name']} — path missing: {entry['install_path']}")
            continue

        result = scan_skill(skill_path, source=entry.get("identifier", entry["source"]))
        c.print(format_scan_report(result))

        if deep:
            c.print(format_ast_report(ast_scan_path(skill_path), skill_name=entry["name"]))

        c.print()


def do_uninstall(name: str, console: Optional[Console] = None,
                 skip_confirm: bool = False,
                 invalidate_cache: bool = True) -> None:
    """Remove a hub-installed skill with confirmation."""
    from tools.skills_hub import uninstall_skill

    c = console or _console

    # skip_confirm bypasses the prompt (needed in TUI mode where input() hangs)
    if not skip_confirm:
        c.print(f"\n[bold]Uninstall '{name}'?[/]")
        try:
            answer = input("Confirm [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in {"y", "yes"}:
            c.print("[dim]Cancelled.[/]\n")
            return

    outcome = uninstall_skill(name)
    if outcome.committed:
        c.print(f"[bold green]{outcome.message}[/]\n")
        if outcome.cleanup_pending:
            c.print(
                "[dim]Recovery artifacts retained: "
                f"{', '.join(outcome.cleanup_pending)}[/]\n"
            )
        if invalidate_cache:
            try:
                from agent.prompt_builder import clear_skills_system_prompt_cache
                clear_skills_system_prompt_cache(clear_snapshot=True)
            except Exception:
                pass
        else:
            c.print("[dim]Change will take effect in your next session.[/]")
            c.print("[dim]Use /reset to start a new session now, or --now to apply immediately (invalidates prompt cache).[/]\n")
    else:
        c.print(f"[bold red]{outcome.message}[/]\n")


def do_reset(name: str, restore: bool = False,
             console: Optional[Console] = None,
             skip_confirm: bool = False,
             invalidate_cache: bool = True) -> None:
    """Reset a bundled skill's manifest tracking (+ optionally restore from bundled)."""
    from tools.skills_sync import reset_bundled_skill

    c = console or _console

    if not skip_confirm and restore:
        c.print(f"\n[bold]Restore '{name}' from bundled source?[/]")
        c.print("[dim]This will DELETE your current copy and re-copy the bundled version.[/]")
        try:
            answer = input("Confirm [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in {"y", "yes"}:
            c.print("[dim]Cancelled.[/]\n")
            return

    result = reset_bundled_skill(name, restore=restore)

    if not result["ok"]:
        c.print(f"[bold red]Error:[/] {result['message']}\n")
        return

    c.print(f"[bold green]{result['message']}[/]")
    synced = result.get("synced") or {}
    if synced.get("copied"):
        c.print(f"[dim]Copied: {', '.join(synced['copied'])}[/]")
    if synced.get("updated"):
        c.print(f"[dim]Updated: {', '.join(synced['updated'])}[/]")
    c.print()

    if invalidate_cache:
        try:
            from agent.prompt_builder import clear_skills_system_prompt_cache
            clear_skills_system_prompt_cache(clear_snapshot=True)
        except Exception:
            pass
    else:
        c.print("[dim]Change will take effect in your next session.[/]")
        c.print("[dim]Use /reset to start a new session now, or --now to apply immediately (invalidates prompt cache).[/]\n")


def do_list_modified(console: Optional[Console] = None,
                     as_json: bool = False) -> None:
    """List bundled skills the user has edited (which `fabric update` keeps)."""
    from tools.skills_sync import list_user_modified_bundled_skills

    c = console or _console
    modified = list_user_modified_bundled_skills()

    if as_json:
        import json

        c.print(json.dumps([m["name"] for m in modified]))
        return

    if not modified:
        c.print("[dim]No user-modified bundled skills — everything tracks upstream.[/]\n")
        return

    c.print(f"\n[bold]{len(modified)} user-modified bundled skill(s)[/] "
            "[dim](kept as-is by `fabric update`):[/]")
    for entry in modified:
        c.print(f"  [yellow]~[/] {entry['name']}")
    c.print()
    c.print("[dim]See changes:   fabric skills diff <name>[/]")
    c.print("[dim]Resume updates: fabric skills reset <name>          (keep your copy, re-baseline)[/]")
    c.print("[dim]Revert to stock: fabric skills reset <name> --restore[/]\n")


def do_diff(name: str, console: Optional[Console] = None) -> None:
    """Show how the user's copy of a bundled skill differs from the stock version."""
    from tools.skills_sync import diff_bundled_skill

    c = console or _console
    result = diff_bundled_skill(name)

    if not result["ok"]:
        c.print(f"[bold red]Error:[/] {result['message']}\n")
        return

    if not result["modified"]:
        c.print(f"[green]{result['message']}[/]\n")
        return

    c.print(f"\n[bold]{result['message']}[/]\n")
    for entry in result["diffs"]:
        status = entry["status"]
        if status == "modified":
            # Render the unified diff with light coloring.
            for line in entry["diff"].splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    c.print(f"[green]{line}[/]")
                elif line.startswith("-") and not line.startswith("---"):
                    c.print(f"[red]{line}[/]")
                elif line.startswith("@@"):
                    c.print(f"[cyan]{line}[/]")
                else:
                    c.print(line, highlight=False)
        elif status == "added":
            c.print(f"[green]+ only in your copy:[/] {entry['path']}")
        elif status == "removed":
            c.print(f"[red]- only in stock:[/] {entry['path']}")
        else:  # binary
            c.print(f"[yellow]~ {entry['path']}:[/] binary file differs")
    c.print()
    c.print(f"[dim]Revert with: fabric skills reset {name} --restore[/]\n")


def do_opt_out(remove: bool = False,
               console: Optional[Console] = None,
               skip_confirm: bool = False,
               invalidate_cache: bool = True) -> None:
    """Opt the active profile out of bundled-skill seeding.

    Always writes the .no-bundled-skills marker (stop future seeding). With
    ``remove``, also deletes already-present bundled skills that are pristine
    (manifest-tracked AND unmodified); user-edited and non-bundled skills are
    never touched.
    """
    from tools.skills_sync import (
        set_bundled_skills_opt_out,
        remove_pristine_bundled_skills,
    )

    c = console or _console

    # Write the marker first (the always-safe part).
    res = set_bundled_skills_opt_out(True)
    if not res["ok"]:
        c.print(f"[bold red]Error:[/] {res['message']}\n")
        return
    c.print(f"[bold green]{res['message']}[/]")
    c.print(f"[dim]Marker: {res['marker']}[/]")

    if not remove:
        c.print("[dim]Existing skills on disk were left in place. "
                "Re-run with --remove to also delete unmodified bundled skills.[/]\n")
        return

    # Destructive step: preview, confirm, then delete.
    preview = remove_pristine_bundled_skills(dry_run=True)
    candidates = preview["removed"]
    kept = preview["skipped"]
    if not candidates:
        c.print("[dim]No pristine bundled skills to remove "
                "(nothing tracked, or all are user-modified/local).[/]\n")
        return

    c.print(f"\n[bold]Will remove {len(candidates)} unmodified bundled skill(s):[/]")
    c.print(f"[dim]{', '.join(candidates)}[/]")
    if kept:
        c.print(f"[dim]Keeping {len(kept)} (user-modified or non-bundled).[/]")

    if not skip_confirm:
        c.print("[dim]This deletes the on-disk copies. User-edited and "
                "hub/local skills are NOT touched.[/]")
        try:
            answer = input("Confirm [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in {"y", "yes"}:
            c.print("[dim]Marker kept; no skills deleted.[/]\n")
            return

    result = remove_pristine_bundled_skills(dry_run=False)
    c.print(f"[bold green]{result['message']}[/]")
    if result["removed"]:
        c.print(f"[dim]Removed: {', '.join(result['removed'])}[/]")
    c.print()

    if invalidate_cache:
        try:
            from agent.prompt_builder import clear_skills_system_prompt_cache
            clear_skills_system_prompt_cache(clear_snapshot=True)
        except Exception:
            pass


def do_opt_in(sync: bool = False,
              console: Optional[Console] = None,
              invalidate_cache: bool = True) -> None:
    """Remove the opt-out marker so bundled-skill seeding resumes.

    With ``sync``, immediately re-seed bundled skills instead of waiting for
    the next ``fabric update``.
    """
    from tools.skills_sync import set_bundled_skills_opt_out, sync_skills

    c = console or _console

    res = set_bundled_skills_opt_out(False)
    if not res["ok"]:
        c.print(f"[bold red]Error:[/] {res['message']}\n")
        return
    c.print(f"[bold green]{res['message']}[/]")

    if sync:
        synced = sync_skills(quiet=True)
        copied = len(synced.get("copied", []))
        c.print(f"[dim]Re-seeded {copied} bundled skill(s).[/]")
        if invalidate_cache:
            try:
                from agent.prompt_builder import clear_skills_system_prompt_cache
                clear_skills_system_prompt_cache(clear_snapshot=True)
            except Exception:
                pass
    c.print()


def do_repair_official(name: str, restore: bool = False,
                       console: Optional[Console] = None,
                       skip_confirm: bool = False,
                       invalidate_cache: bool = True) -> None:
    """Backfill or restore official optional skills from repo source."""
    from tools.skills_sync import restore_official_optional_skill

    c = console or _console
    if restore and not skip_confirm:
        c.print(f"\n[bold]Restore official optional skill '{name}' from repo source?[/]")
        c.print("[dim]Existing matching active copies will be moved to a restore backup before copying the official source.[/]")
        try:
            answer = input("Confirm [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in {"y", "yes"}:
            c.print("[dim]Cancelled.[/]\n")
            return

    result = restore_official_optional_skill(name, restore=restore)
    if not result.get("ok"):
        c.print(f"[bold red]Error:[/] {result.get('message', 'Repair failed')}\n")
        return

    c.print(f"[bold green]{result['message']}[/]")
    if result.get("restored"):
        c.print(f"[dim]Restored: {', '.join(result['restored'])}[/]")
    if result.get("backfilled"):
        c.print(f"[dim]Backfilled provenance: {', '.join(result['backfilled'])}[/]")
    if result.get("backed_up"):
        c.print(f"[dim]Backed up: {', '.join(result['backed_up'])}[/]")
        c.print(f"[dim]Backup dir: {result.get('backup_dir')}[/]")
    c.print()

    if invalidate_cache:
        try:
            from agent.prompt_builder import clear_skills_system_prompt_cache
            clear_skills_system_prompt_cache(clear_snapshot=True)
        except Exception:
            pass


def do_tap(action: str, repo: str = "", console: Optional[Console] = None) -> None:
    """Manage taps (custom GitHub repo sources)."""
    from tools.skills_hub import TapsManager

    c = console or _console
    mgr = TapsManager()

    if action == "list":
        taps = mgr.list_taps()
        if not taps:
            c.print("[dim]No custom taps configured. Using default sources only.[/]\n")
            return
        table = Table(title="Configured Taps")
        table.add_column("Repo", style="bold cyan")
        table.add_column("Path", style="dim")
        for t in taps:
            label = t.get("repo") or t.get("name") or t.get("path", "unknown")
            table.add_row(label, t.get("path", "skills/"))
        c.print(table)
        c.print()

    elif action == "add":
        if not repo:
            c.print("[bold red]Error:[/] Repo required. Usage: fabric skills tap add owner/repo\n")
            return
        outcome = mgr.add(repo)
        if outcome.committed and outcome.changed:
            c.print(f"[bold green]Added tap:[/] {repo}\n")
        elif outcome.status == "recovery_pending":
            c.print(f"[bold red]{outcome.message}[/]\n")
        else:
            c.print(f"[yellow]Tap already exists:[/] {repo}\n")

    elif action == "remove":
        if not repo:
            c.print("[bold red]Error:[/] Repo required. Usage: fabric skills tap remove owner/repo\n")
            return
        outcome = mgr.remove(repo)
        if outcome.committed and outcome.changed:
            c.print(f"[bold green]Removed tap:[/] {repo}\n")
        elif outcome.status == "recovery_pending":
            c.print(f"[bold red]{outcome.message}[/]\n")
        else:
            c.print(f"[bold red]Error:[/] Tap not found: {repo}\n")

    else:
        c.print(f"[bold red]Unknown tap action:[/] {action}. Use: list, add, remove\n")


def do_publish(skill_path: str, target: str = "github", repo: str = "",
               console: Optional[Console] = None) -> None:
    """Publish a local skill to a registry (GitHub PR or ClawHub submission)."""
    from tools.skills_hub import GitHubAuth, SKILLS_DIR
    from tools.skills_guard import scan_skill, format_scan_report

    c = console or _console
    path = Path(skill_path)

    # Resolve relative to skills dir if not absolute
    if not path.is_absolute():
        path = SKILLS_DIR / path
    if not path.exists() or not (path / "SKILL.md").exists():
        c.print(f"[bold red]Error:[/] No SKILL.md found at {path}\n")
        return

    # Validate the skill
    import yaml
    skill_md = (path / "SKILL.md").read_text(encoding="utf-8")
    fm = {}
    if skill_md.startswith("---"):
        import re
        match = re.search(r'\n---\s*\n', skill_md[3:])
        if match:
            try:
                fm = yaml.safe_load(skill_md[3:match.start() + 3]) or {}
            except yaml.YAMLError:
                pass

    name = fm.get("name", path.name)
    description = fm.get("description", "")
    if not description:
        c.print("[bold red]Error:[/] SKILL.md must have a 'description' in frontmatter.\n")
        return

    # Self-scan before publishing
    c.print(f"[bold]Scanning '{name}' before publish...[/]")
    result = scan_skill(path, source="self")
    c.print(format_scan_report(result))
    if result.verdict == "dangerous":
        c.print("[bold red]Cannot publish a skill with DANGEROUS verdict.[/]\n")
        return

    if target == "github":
        if not repo:
            c.print("[bold red]Error:[/] --repo required for GitHub publish.\n"
                    "Usage: fabric skills publish <path> --to github --repo owner/repo\n")
            return

        auth = GitHubAuth()
        if not auth.is_authenticated():
            c.print("[bold red]Error:[/] GitHub authentication required.\n"
                    f"Set GITHUB_TOKEN in {display_fabric_home()}/.env or run 'gh auth login'.\n")
            return

        c.print(f"[bold]Publishing '{name}' to {repo}...[/]")
        success, msg = _github_publish(path, name, repo, auth)
        if success:
            c.print(f"[bold green]{msg}[/]\n")
        else:
            c.print(f"[bold red]Error:[/] {msg}\n")

    elif target == "clawhub":
        c.print("[yellow]ClawHub publishing is not yet supported. "
                "Submit manually at https://clawhub.ai/submit[/]\n")
    else:
        c.print(f"[bold red]Unknown target:[/] {target}. Use 'github' or 'clawhub'.\n")


def _github_publish(skill_path: Path, skill_name: str, target_repo: str,
                    auth) -> tuple:
    """Create a PR to a GitHub repo with the skill. Returns (success, message)."""
    import httpx

    headers = auth.get_headers()

    # 1. Fork the repo
    try:
        resp = httpx.post(
            f"https://api.github.com/repos/{target_repo}/forks",
            headers=headers, timeout=30,
        )
        if resp.status_code in {200, 202}:
            fork = resp.json()
            fork_repo = fork["full_name"]
        elif resp.status_code == 403:
            return False, "GitHub token lacks permission to fork repos"
        else:
            return False, f"Failed to fork {target_repo}: {resp.status_code}"
    except httpx.HTTPError as e:
        return False, f"Network error forking repo: {e}"

    # 2. Get default branch
    try:
        resp = httpx.get(
            f"https://api.github.com/repos/{target_repo}",
            headers=headers, timeout=15,
        )
        default_branch = resp.json().get("default_branch", "main")
    except Exception:
        default_branch = "main"

    # 3. Get the base tree SHA
    try:
        resp = httpx.get(
            f"https://api.github.com/repos/{fork_repo}/git/refs/heads/{default_branch}",
            headers=headers, timeout=15,
        )
        base_sha = resp.json()["object"]["sha"]
    except Exception as e:
        return False, f"Failed to get base branch: {e}"

    # 4. Create a new branch
    branch_name = f"add-skill-{skill_name}"
    try:
        httpx.post(
            f"https://api.github.com/repos/{fork_repo}/git/refs",
            headers=headers, timeout=15,
            json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        )
    except Exception as e:
        return False, f"Failed to create branch: {e}"

    # 5. Upload skill files
    for f in skill_path.rglob("*"):
        if not f.is_file():
            continue
        rel = str(f.relative_to(skill_path))
        upload_path = f"skills/{skill_name}/{rel}"
        try:
            import base64
            content_b64 = base64.b64encode(f.read_bytes()).decode()
            httpx.put(
                f"https://api.github.com/repos/{fork_repo}/contents/{upload_path}",
                headers=headers, timeout=15,
                json={
                    "message": f"Add {skill_name} skill: {rel}",
                    "content": content_b64,
                    "branch": branch_name,
                },
            )
        except Exception as e:
            return False, f"Failed to upload {rel}: {e}"

    # 6. Create PR
    try:
        resp = httpx.post(
            f"https://api.github.com/repos/{target_repo}/pulls",
            headers=headers,
            timeout=15,
            json={
                "title": f"Add skill: {skill_name}",
                "body": f"Submitting the `{skill_name}` skill via Fabric Skills Hub.\n\n"
                        f"This skill was scanned by the Fabric Skills Guard before submission.",
                "head": f"{fork_repo.split('/')[0]}:{branch_name}",
                "base": default_branch,
            },
        )
        if resp.status_code == 201:
            pr_url = resp.json().get("html_url", "")
            return True, f"PR created: {pr_url}"
        else:
            return False, f"Failed to create PR: {resp.status_code} {resp.text[:200]}"
    except httpx.HTTPError as e:
        return False, f"Network error creating PR: {e}"


def _validated_snapshot_document(snapshot: object) -> dict:
    from tools.skills_hub import HubSourceAuthority
    from tools.skill_install import (
        normalize_relative_path,
        validate_skill_name,
    )

    def checked_string(
        value: object,
        *,
        field: str,
        allow_empty: bool = False,
    ) -> str:
        if not isinstance(value, str) or (not allow_empty and not value):
            qualifier = "a string" if allow_empty else "a non-empty string"
            raise ValueError(f"{field} must be {qualifier}")
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError(f"{field} must be valid UTF-8") from exc
        if len(encoded) > _MAX_SNAPSHOT_STRING_BYTES:
            raise ValueError(f"{field} exceeds {_MAX_SNAPSHOT_STRING_BYTES} bytes")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError(f"{field} contains a control character")
        return value

    if not isinstance(snapshot, dict):
        raise ValueError("snapshot root must be an object")
    unknown_root_fields = set(snapshot) - _SNAPSHOT_ROOT_FIELDS
    if unknown_root_fields:
        raise ValueError(
            f"snapshot contains unknown field: {min(unknown_root_fields)!r}"
        )
    if not {"schema_version", "skills", "taps"}.issubset(snapshot):
        raise ValueError("snapshot requires schema_version, skills, and taps")
    if snapshot["schema_version"] != _SNAPSHOT_SCHEMA_VERSION:
        raise ValueError(
            f"snapshot schema must be exactly {_SNAPSHOT_SCHEMA_VERSION}"
        )
    for field in ("fabric_version", "exported_at"):
        if field in snapshot:
            checked_string(snapshot[field], field=f"snapshot field {field!r}")
    skills = snapshot["skills"]
    taps = snapshot["taps"]
    if not isinstance(skills, list) or not isinstance(taps, list):
        raise ValueError("snapshot skills and taps must be arrays")
    if len(skills) > _MAX_SNAPSHOT_SKILLS:
        raise ValueError(f"snapshot contains more than {_MAX_SNAPSHOT_SKILLS} skills")
    if len(taps) > _MAX_SNAPSHOT_TAPS:
        raise ValueError(f"snapshot contains more than {_MAX_SNAPSHOT_TAPS} taps")

    validated_skills: list[dict[str, object]] = []
    seen_skills: set[str] = set()
    for index, entry in enumerate(skills):
        if not isinstance(entry, dict) or set(entry) != _SNAPSHOT_SKILL_FIELDS:
            raise ValueError(f"snapshot skill {index} must be an object")
        name = checked_string(entry["name"], field=f"snapshot skill {index} name")
        try:
            safe_name = validate_skill_name(name)
        except ValueError as exc:
            raise ValueError(f"snapshot skill {index} has an invalid name") from exc
        if safe_name != name:
            raise ValueError(f"snapshot skill {index} name is not canonical")
        if safe_name in seen_skills:
            raise ValueError(f"snapshot contains duplicate skill: {safe_name}")
        seen_skills.add(safe_name)
        source_name = checked_string(
            entry["source_name"], field=f"snapshot skill {index} source name"
        )
        source_revision = checked_string(
            entry["source_revision"],
            field=f"snapshot skill {index} source revision",
        )
        digest = checked_string(
            entry["digest"], field=f"snapshot skill {index} digest"
        )
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError(f"snapshot skill {index} digest is invalid")
        try:
            authority = HubSourceAuthority.from_dict(entry["authority"])
        except ValueError as exc:
            raise ValueError(
                f"snapshot skill {index} authority is invalid"
            ) from exc
        if authority.adapter.value == "unverified":
            raise ValueError(
                f"snapshot skill {index} has no replayable adapter authority"
            )
        category = checked_string(
            entry["category"],
            field=f"snapshot skill {index} category",
            allow_empty=True,
        )
        if category:
            try:
                safe_category = normalize_relative_path(
                    category,
                    field="snapshot category",
                )
            except ValueError as exc:
                raise ValueError(
                    f"snapshot skill {index} has an invalid category"
                ) from exc
            if safe_category != category:
                raise ValueError(f"snapshot skill {index} category is not canonical")
        validated_skills.append({
            "name": safe_name,
            "source_name": source_name,
            "source_revision": source_revision,
            "authority": authority.as_dict(),
            "digest": digest,
            "category": category,
        })

    validated_taps: list[dict[str, str]] = []
    seen_taps: set[tuple[str, str]] = set()
    for index, tap in enumerate(taps):
        if not isinstance(tap, dict) or set(tap) != _SNAPSHOT_TAP_FIELDS:
            raise ValueError(f"snapshot tap {index} must be an object")
        repo = checked_string(tap["repo"], field=f"snapshot tap {index} repo")
        if _SNAPSHOT_REPO_RE.fullmatch(repo) is None:
            raise ValueError(f"snapshot tap {index} repo must be owner/repository")
        path = checked_string(tap["path"], field=f"snapshot tap {index} path")
        try:
            safe_path = normalize_relative_path(path, field="snapshot tap path")
        except ValueError as exc:
            raise ValueError(f"snapshot tap {index} has an invalid path") from exc
        # Existing snapshots conventionally include one trailing slash.
        if path not in {safe_path, f"{safe_path}/"}:
            raise ValueError(f"snapshot tap {index} path is not canonical")
        canonical_tap = (repo, safe_path)
        if canonical_tap in seen_taps:
            raise ValueError(f"snapshot contains duplicate tap: {repo}/{safe_path}")
        seen_taps.add(canonical_tap)
        validated_taps.append({"repo": repo, "path": f"{safe_path}/"})

    result = {
        field: snapshot[field]
        for field in ("schema_version", "fabric_version", "exported_at")
        if field in snapshot
    }
    result["skills"] = validated_skills
    result["taps"] = validated_taps
    return result


def do_snapshot_export(output_path: str, console: Optional[Console] = None) -> None:
    """Export current hub skill configuration to a portable JSON file."""
    from fabric_cli import __version__
    from tools.skills_hub import (
        HubLockFile,
        TapsManager,
        _authority_for_installed_entry,
        _recover_hub_transactions_locked,
        _skills_dir,
        hub_mutation_scope,
    )

    c = console or _console
    lock = HubLockFile()
    taps = TapsManager()

    try:
        mutation_scope = hub_mutation_scope(_skills_dir().parent)
        with mutation_scope:
            _recover_hub_transactions_locked(lock=lock)
            lock_data = lock.load(strict=True)
            tap_list = taps.load(strict=True)
            installed = [
                {"name": name, **entry}
                for name, entry in lock_data["installed"].items()
                if isinstance(entry, dict)
            ]
            if len(installed) != len(lock_data["installed"]):
                raise ValueError("Hub lock file contains an invalid install entry")
            exported_skills = []
            for entry in installed:
                authority = _authority_for_installed_entry(entry)
                digest = entry.get("attested_tree_sha256")
                if not isinstance(digest, str) or re.fullmatch(
                    r"[0-9a-f]{64}", digest
                ) is None:
                    raise ValueError(
                        f"Hub install {entry['name']!r} has no exact tree digest"
                    )
                metadata = entry.get("metadata", {})
                if not isinstance(metadata, dict):
                    raise ValueError(
                        f"Hub install {entry['name']!r} has invalid metadata"
                    )
                source_name = metadata.get("source_name", entry["name"])
                source_revision = metadata.get(
                    "source_revision", authority.remote_identifier
                )
                if not isinstance(source_name, str) or not source_name:
                    raise ValueError("Hub source name is invalid")
                if not isinstance(source_revision, str) or not source_revision:
                    raise ValueError("Hub source revision is invalid")
                exported_skills.append(
                    {
                        "name": entry["name"],
                        "source_name": source_name,
                        "source_revision": source_revision,
                        "authority": authority.as_dict(),
                        "digest": digest,
                        "category": (
                            str(Path(entry.get("install_path", "")).parent)
                            if "/" in entry.get("install_path", "")
                            else ""
                        ),
                    }
                )
        snapshot = {
            "schema_version": _SNAPSHOT_SCHEMA_VERSION,
            "fabric_version": __version__,
            "exported_at": __import__("datetime")
            .datetime.now(__import__("datetime").timezone.utc)
            .isoformat(),
            "skills": exported_skills,
            "taps": tap_list,
        }
        snapshot = _validated_snapshot_document(snapshot)

        if output_path == "-":
            payload = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
        else:
            out = Path(output_path)
            publisher = HubLockFile(path=out)
            try:
                publisher.save(snapshot)
            except BaseException:
                try:
                    observed = json.loads(out.read_text(encoding="utf-8"))
                    publisher.ensure_parent_durable()
                except BaseException:
                    raise
                if observed != snapshot:
                    raise
    except (OSError, RuntimeError, ValueError) as exc:
        c.print(f"[bold red]Snapshot export failed:[/] {exc}\n")
        return

    if output_path == "-":
        import sys

        sys.stdout.write(payload)
    else:
        c.print(f"[bold green]Snapshot exported:[/] {out}")
        c.print(f"[dim]{len(installed)} skill(s), {len(tap_list)} tap(s)[/]\n")


def do_snapshot_import(
    input_path: str, force: bool = False, console: Optional[Console] = None
) -> None:
    """Re-install skills from a snapshot file."""
    from tools.skills_hub import HubMetadataMutationOutcome, TapsManager

    c = console or _console
    inp = Path(input_path)
    if not inp.exists():
        c.print(f"[bold red]Error:[/] File not found: {inp}\n")
        return

    try:
        snapshot = _validated_snapshot_document(
            json.loads(_read_bounded_snapshot_text(inp))
        )
    except (
        json.JSONDecodeError,
        OSError,
        RecursionError,
        UnicodeDecodeError,
        ValueError,
    ) as exc:
        c.print(f"[bold red]Error:[/] Invalid snapshot in {inp}: {exc}\n")
        return

    # Restore taps first
    taps = snapshot.get("taps", [])
    if taps:
        mgr = TapsManager()
        restored_taps = 0
        refused_taps = 0
        for tap in taps:
            try:
                outcome = mgr.add(tap["repo"], tap["path"])
                if not isinstance(outcome, HubMetadataMutationOutcome):
                    raise TypeError("tap manager returned an invalid outcome")
            except Exception as exc:
                refused_taps += 1
                c.print(f"[yellow]Tap not restored: {tap['repo']} — {exc}[/]")
                continue
            if outcome.committed and outcome.changed:
                restored_taps += 1
            else:
                refused_taps += 1
                c.print(
                    f"[yellow]Tap not restored: {tap['repo']} — {outcome.message}[/]"
                )
        c.print(
            f"[dim]Tap restore result: {restored_taps} added, "
            f"{refused_taps} refused/unchanged[/]"
        )

    # Install skills
    skills = snapshot.get("skills", [])
    if not skills:
        c.print("[dim]No skills in snapshot to install.[/]\n")
        return

    c.print(f"[bold]Importing {len(skills)} skill(s) from snapshot...[/]\n")
    installed_count = 0
    refused_count = 0
    for entry in skills:
        authority = entry["authority"]
        identifier = authority["remote_identifier"]
        category = entry.get("category", "")

        c.print(f"[bold]--- {entry.get('name', identifier)} ---[/]")
        outcome = do_install(
            identifier,
            category=category,
            force=force,
            console=c,
            snapshot_identity=entry,
        )
        if outcome.installed:
            installed_count += 1
        else:
            refused_count += 1
            c.print(
                f"[bold red]Snapshot entry not installed:[/] "
                f"{entry.get('name', identifier)} — {outcome.message}"
            )

    style = "bold green" if refused_count == 0 else "bold yellow"
    c.print(
        f"[{style}]Snapshot import result: {installed_count} installed, "
        f"{refused_count} refused/failed.[/]\n"
    )


# ---------------------------------------------------------------------------
# CLI argparse entry point
# ---------------------------------------------------------------------------

def skills_command(args) -> None:
    """Router for `fabric skills <subcommand>` — called from fabric_cli/main.py."""
    action = getattr(args, "skills_action", None)

    if action == "browse":
        do_browse(page=args.page, page_size=args.size, source=args.source)
    elif action == "search":
        do_search(args.query, source=args.source, limit=args.limit,
                  as_json=getattr(args, "json", False))
    elif action == "install":
        do_install(args.identifier, category=args.category, force=args.force,
                   skip_confirm=getattr(args, "yes", False),
                   name_override=getattr(args, "name", "") or "")
    elif action == "inspect":
        do_inspect(args.identifier)
    elif action == "list":
        do_list(
            source_filter=args.source,
            enabled_only=getattr(args, "enabled_only", False),
        )
    elif action == "validate":
        from fabric_cli.skill_contracts import do_validate

        do_validate(
            target=getattr(args, "target", None),
            require_contract=getattr(args, "require_contract", False),
            as_json=getattr(args, "json", False),
        )
    elif action == "evaluate":
        from tools.skill_manager_tool import evaluate_skill_pending_batch

        result = evaluate_skill_pending_batch(
            args.pending_id, Path(args.observations)
        )
        if getattr(args, "json", False):
            _console.print(
                json.dumps(result, sort_keys=True, separators=(",", ":")),
                markup=False,
            )
        elif result.get("success"):
            names = ", ".join(result.get("skills", [])) or "deletion-only batch"
            _console.print(
                "Evaluation passed and was durably attested for "
                f"{names}.\nBatch: {result.get('batch_id')}\n"
                "Review the full pending diff, then explicitly approve that exact batch.",
                markup=False,
            )
        else:
            _console.print(
                f"Evaluation failed: {result.get('error', 'unknown error')}",
                markup=False,
            )
            raise SystemExit(1)
    elif action == "rollback":
        from tools.skill_manager_tool import rollback_committed_skill_transaction

        result = rollback_committed_skill_transaction(
            args.transaction_id, activate_now=bool(getattr(args, "now", False))
        )
        if getattr(args, "json", False):
            _console.print(
                json.dumps(result, sort_keys=True, separators=(",", ":")),
                markup=False,
            )
        elif result.get("success"):
            _console.print(
                "Rolled back skill promotion transaction "
                f"{args.transaction_id}. "
                + (
                    "Skill routing was refreshed immediately."
                    if getattr(args, "now", False)
                    else "The restored routing will activate in the next session; use --now to refresh immediately."
                ),
                markup=False,
            )
        else:
            _console.print(
                f"Rollback refused: {result.get('error', 'unknown error')}",
                markup=False,
            )
            raise SystemExit(1)
    elif action == "check":
        do_check(name=getattr(args, "name", None))
    elif action == "update":
        do_update(name=getattr(args, "name", None))
    elif action == "audit":
        do_audit(name=getattr(args, "name", None),
                 deep=getattr(args, "deep", False))
    elif action == "gc":
        do_gc()
    elif action == "uninstall":
        do_uninstall(args.name)
    elif action == "reset":
        do_reset(args.name, restore=getattr(args, "restore", False),
                 skip_confirm=getattr(args, "yes", False))
    elif action == "list-modified":
        do_list_modified(as_json=getattr(args, "json", False))
    elif action == "diff":
        do_diff(args.name)
    elif action == "opt-out":
        do_opt_out(remove=getattr(args, "remove", False),
                   skip_confirm=getattr(args, "yes", False))
    elif action == "opt-in":
        do_opt_in(sync=getattr(args, "sync", False))
    elif action == "repair-official":
        do_repair_official(args.name, restore=getattr(args, "restore", False),
                           skip_confirm=getattr(args, "yes", False))
    elif action == "publish":
        do_publish(
            args.skill_path,
            target=getattr(args, "to", "github"),
            repo=getattr(args, "repo", ""),
        )
    elif action == "snapshot":
        snap_action = getattr(args, "snapshot_action", None)
        if snap_action == "export":
            do_snapshot_export(args.output)
        elif snap_action == "import":
            do_snapshot_import(args.input, force=getattr(args, "force", False))
        else:
            _console.print("Usage: fabric skills snapshot [export|import]\n", markup=False)
    elif action == "tap":
        tap_action = getattr(args, "tap_action", None)
        repo = getattr(args, "repo", "") or getattr(args, "name", "")
        if not tap_action:
            _console.print("Usage: fabric skills tap [list|add|remove]\n", markup=False)
            return
        do_tap(tap_action, repo=repo)
    else:
        _console.print(
            "Usage: fabric skills [browse|search|install|inspect|list|validate|evaluate|rollback|list-modified|diff|check|update|audit|gc|uninstall|reset|opt-out|opt-in|publish|snapshot|tap]\n",
            markup=False,
        )
        _console.print("Run 'fabric skills <command> --help' for details.\n")


# ---------------------------------------------------------------------------
# Slash command entry point (/skills in chat)
# ---------------------------------------------------------------------------

def handle_skills_slash(cmd: str, console: Optional[Console] = None) -> None:
    """
    Parse and dispatch `/skills <subcommand> [args]` from the chat interface.

    Examples:
        /skills search kubernetes
        /skills install openai/skills/skill-creator
        /skills install openai/skills/skill-creator --force
        /skills install https://example.com/path/SKILL.md
        /skills inspect openai/skills/skill-creator
        /skills list
        /skills list --source hub
        /skills check
        /skills update
        /skills audit
        /skills audit my-skill
        /skills audit --deep
        /skills audit my-skill --deep
        /skills gc
        /skills uninstall my-skill
        /skills tap list
        /skills tap add owner/repo
        /skills tap remove owner/repo
    """
    c = console or _console
    parts = cmd.strip().split()

    # Strip the leading "/skills" if present
    if parts and parts[0].lower() == "/skills":
        parts = parts[1:]

    if not parts:
        _print_skills_help(c)
        return

    action = parts[0].lower()
    args = parts[1:]

    if action == "browse":
        page = 1
        page_size = 20
        source = "all"
        i = 0
        while i < len(args):
            if args[i] == "--page" and i + 1 < len(args):
                try:
                    page = int(args[i + 1])
                except ValueError:
                    pass
                i += 2
            elif args[i] == "--size" and i + 1 < len(args):
                try:
                    page_size = int(args[i + 1])
                except ValueError:
                    pass
                i += 2
            elif args[i] == "--source" and i + 1 < len(args):
                source = args[i + 1]
                i += 2
            else:
                i += 1
        do_browse(page=page, page_size=page_size, source=source, console=c)

    elif action == "search":
        if not args:
            c.print("[bold red]Usage:[/] /skills search <query> [--source skills-sh|github|official|nvidia|openai|anthropic|huggingface] [--limit N] [--json]\n")
            return
        source = "all"
        limit = 25
        as_json = False
        query_parts = []
        i = 0
        while i < len(args):
            if args[i] == "--source" and i + 1 < len(args):
                source = args[i + 1]
                i += 2
            elif args[i] == "--limit" and i + 1 < len(args):
                try:
                    limit = int(args[i + 1])
                except ValueError:
                    pass
                i += 2
            elif args[i] == "--json":
                as_json = True
                i += 1
            else:
                query_parts.append(args[i])
                i += 1
        do_search(" ".join(query_parts), source=source, limit=limit,
                  console=c, as_json=as_json)

    elif action == "install":
        if not args:
            c.print("[bold red]Usage:[/] /skills install <identifier-or-url> [--name <name>] [--category <cat>] [--force] [--now]\n")
            return
        identifier = args[0]
        category = ""
        name_override = ""
        # Slash commands run inside prompt_toolkit where input() hangs.
        # Always skip confirmation — the user typing the command is implicit consent.
        skip_confirm = True
        force = "--force" in args
        # --now invalidates prompt cache immediately (costs more money).
        # Default: defer to next session to preserve cache.
        invalidate_cache = "--now" in args
        for i, a in enumerate(args):
            if a == "--category" and i + 1 < len(args):
                category = args[i + 1]
            elif a == "--name" and i + 1 < len(args):
                name_override = args[i + 1]
        do_install(identifier, category=category, force=force,
                   skip_confirm=skip_confirm, invalidate_cache=invalidate_cache,
                   name_override=name_override, console=c)

    elif action == "inspect":
        if not args:
            c.print("[bold red]Usage:[/] /skills inspect <identifier>\n")
            return
        do_inspect(args[0], console=c)

    elif action == "list":
        source_filter = "all"
        enabled_only = "--enabled-only" in args or "--enabled" in args
        if "--source" in args:
            idx = args.index("--source")
            if idx + 1 < len(args):
                source_filter = args[idx + 1]
        do_list(source_filter=source_filter, enabled_only=enabled_only, console=c)

    elif action == "check":
        name = args[0] if args else None
        do_check(name=name, console=c)

    elif action == "update":
        name = args[0] if args else None
        do_update(name=name, console=c)

    elif action == "audit":
        name = args[0] if args and not args[0].startswith("--") else None
        deep = "--deep" in args
        do_audit(name=name, console=c, deep=deep)

    elif action == "gc":
        do_gc(console=c)

    elif action == "uninstall":
        if not args:
            c.print("[bold red]Usage:[/] /skills uninstall <name> [--now]\n")
            return
        # Slash commands run inside prompt_toolkit where input() hangs.
        skip_confirm = True
        invalidate_cache = "--now" in args
        do_uninstall(args[0], console=c, skip_confirm=skip_confirm,
                     invalidate_cache=invalidate_cache)

    elif action == "reset":
        if not args:
            c.print("[bold red]Usage:[/] /skills reset <name> [--restore] [--now]\n")
            c.print("[dim]Clears the bundled-skills manifest entry so future updates stop marking it as user-modified.[/]")
            c.print("[dim]Pass --restore to also replace the current copy with the bundled version.[/]\n")
            return
        name = args[0]
        restore = "--restore" in args
        invalidate_cache = "--now" in args
        # Slash commands can't prompt — --restore in slash mode is implicit consent.
        do_reset(name, restore=restore, console=c, skip_confirm=True,
                 invalidate_cache=invalidate_cache)

    elif action in {"list-modified", "modified"}:
        do_list_modified(console=c, as_json="--json" in args)

    elif action == "diff":
        if not args:
            c.print("[bold red]Usage:[/] /skills diff <name>\n")
            return
        do_diff(args[0], console=c)

    elif action == "publish":
        if not args:
            c.print("[bold red]Usage:[/] /skills publish <skill-path> [--to github] [--repo owner/repo]\n")
            return
        skill_path = args[0]
        target = "github"
        repo = ""
        for i, a in enumerate(args):
            if a == "--to" and i + 1 < len(args):
                target = args[i + 1]
            if a == "--repo" and i + 1 < len(args):
                repo = args[i + 1]
        do_publish(skill_path, target=target, repo=repo, console=c)

    elif action == "snapshot":
        if not args:
            c.print("[bold red]Usage:[/] /skills snapshot export <file> | /skills snapshot import <file>\n")
            return
        snap_action = args[0]
        if snap_action == "export" and len(args) > 1:
            do_snapshot_export(args[1], console=c)
        elif snap_action == "import" and len(args) > 1:
            force = "--force" in args
            do_snapshot_import(args[1], force=force, console=c)
        else:
            c.print("[bold red]Usage:[/] /skills snapshot export <file> | /skills snapshot import <file>\n")

    elif action == "tap":
        if not args:
            do_tap("list", console=c)
            return
        tap_action = args[0]
        repo = args[1] if len(args) > 1 else ""
        do_tap(tap_action, repo=repo, console=c)

    elif action in {"help", "--help", "-h"}:
        _print_skills_help(c)

    else:
        c.print(f"[bold red]Unknown action:[/] {action}")
        _print_skills_help(c)


def _print_skills_help(console: Console) -> None:
    """Print help for the /skills slash command."""
    console.print(Panel(
        "[bold]Skills Hub Commands:[/]\n\n"
        "  [cyan]browse[/] [--source official]   Browse all available skills (paginated)\n"
        "  [cyan]search[/] <query>              Search registries for skills\n"
        "  [cyan]install[/] <identifier>        Install a skill (with security scan)\n"
        "  [cyan]inspect[/] <identifier>        Preview a skill without installing\n"
        "  [cyan]list[/] [--source hub|builtin|local] [--enabled-only]\n"
        "       List installed skills; --enabled-only filters to the active profile's live set\n"
        "  [cyan]check[/] [name]                Check hub skills for upstream updates\n"
        "  [cyan]update[/] [name]               Update hub skills with upstream changes\n"
        "  [cyan]audit[/] [name]                Re-scan hub skills for security\n"
        "  [cyan]gc[/]                          Recover/prune completed Hub transactions\n"
        "  [cyan]uninstall[/] <name>            Remove a hub-installed skill\n"
        "  [cyan]list-modified[/]               List bundled skills you've edited (kept by update)\n"
        "  [cyan]diff[/] <name>                 Diff your copy of a bundled skill vs the stock version\n"
        "  [cyan]reset[/] <name> [--restore]    Reset bundled-skill tracking (fix 'user-modified' flag)\n"
        "  [cyan]publish[/] <path> --repo <r>   Publish a skill to GitHub via PR\n"
        "  [cyan]snapshot[/] export|import      Export/import skill configurations\n"
        "  [cyan]tap[/] list|add|remove         Manage skill sources\n",
        title="/skills",
    ))
