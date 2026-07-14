#!/usr/bin/env python3
"""CI audit for skill contracts and the cached skill-index footprint.

This is intentionally a thin wrapper around the runtime's pure validators. It
does not import the tool registry, build an agent, or mutate skill state. The
contract check keeps malformed governed skills out of releases while the
prompt-footprint budget makes catalog growth an explicit architecture choice
instead of an unnoticed per-turn tax.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from agent.skill_contract import (
    discover_skill_directories,
    source_freshness_blockers,
    validate_skill_directory,
)
from agent.skill_utils import (
    extract_skill_description,
    iter_skill_index_files,
    parse_frontmatter,
)


DEFAULT_ROOTS = ("skills", "optional-skills")
DEFAULT_MAX_BUNDLED_INDEX_BYTES = 16 * 1024
_INLINE_DETAIL_LIMIT = 32
_TAXONOMY_MAX_CHARS = 4096


@dataclass(frozen=True)
class AuditIssue:
    code: str
    message: str
    path: str


def _relative(path: Path, repository_root: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(
            repository_root.resolve(strict=False)
        ).as_posix()
    except ValueError:
        return str(path.resolve(strict=False))


def _rendered_index_bytes(skills_root: Path) -> int:
    """Measure the variable skill-catalog block rendered into every prompt.

    This mirrors the relevant hybrid formatting in
    ``build_skills_system_prompt``: small catalogs include metadata rows;
    larger catalogs switch to a bounded top-level taxonomy and route names on
    demand. The fixed instructional preamble is not a catalog-growth cost and
    is deliberately excluded.
    """

    skills_by_category: dict[str, list[tuple[str, str]]] = {}
    category_descriptions: dict[str, str] = {}

    for skill_md in iter_skill_index_files(skills_root, "SKILL.md"):
        try:
            frontmatter, _body = parse_frontmatter(
                skill_md.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValueError):
            continue
        try:
            relative = skill_md.relative_to(skills_root)
        except ValueError:
            continue
        category = "/".join(relative.parts[:-2]) or "general"
        name = frontmatter.get("name")
        canonical_name = (
            name.strip()
            if isinstance(name, str) and name.strip()
            else skill_md.parent.name
        )
        skills_by_category.setdefault(category, []).append(
            (canonical_name, extract_skill_description(frontmatter))
        )

    for description_md in iter_skill_index_files(skills_root, "DESCRIPTION.md"):
        try:
            frontmatter, _body = parse_frontmatter(
                description_md.read_text(encoding="utf-8")
            )
            description = frontmatter.get("description")
            if not isinstance(description, str) or not description.strip():
                continue
            relative = description_md.relative_to(skills_root)
        except (OSError, UnicodeError, ValueError):
            continue
        category = "/".join(relative.parts[:-1]) or "general"
        category_descriptions[category] = description.strip().strip("'\"")

    lines: list[str] = []
    total = sum(
        len({name for name, _description in entries})
        for entries in skills_by_category.values()
    )
    if total > _INLINE_DETAIL_LIMIT:
        counts: dict[str, int] = {}
        for category, entries in skills_by_category.items():
            top_level = category.split("/", 1)[0] or "general"
            counts[top_level] = counts.get(top_level, 0) + len(
                {name for name, _description in entries}
            )
        used_chars = 0
        for category in sorted(counts):
            line = f"  - {category}: {counts[category]} skills"
            if used_chars + len(line) + 1 > _TAXONOMY_MAX_CHARS:
                lines.append("  - additional categories: search on demand")
                break
            lines.append(line)
            used_chars += len(line) + 1
    else:
        for category in sorted(skills_by_category):
            description = category_descriptions.get(category, "")
            lines.append(f"  {category}:" + (f" {description}" if description else ""))
            seen: set[str] = set()
            for name, description in sorted(
                skills_by_category[category], key=lambda item: item[0]
            ):
                if name in seen:
                    continue
                seen.add(name)
                lines.append(
                    f"    - {name}: {description}"
                    if description
                    else f"    - {name}"
                )
    return len(("\n".join(lines) + ("\n" if lines else "")).encode("utf-8"))


def audit_repository(
    repository_root: Path,
    *,
    roots: Iterable[str] = DEFAULT_ROOTS,
    require_contract: bool = False,
    max_bundled_index_bytes: int = DEFAULT_MAX_BUNDLED_INDEX_BYTES,
) -> dict[str, object]:
    """Return a deterministic governance report for repository skill trees."""

    repository_root = Path(repository_root)
    issues: list[AuditIssue] = []
    counts = {"invalid": 0, "legacy": 0, "verified": 0}
    root_records: list[dict[str, object]] = []

    for root_name in roots:
        skill_root = repository_root / root_name
        if not skill_root.is_dir():
            issues.append(
                AuditIssue(
                    "skill_root_missing",
                    "configured skill root does not exist",
                    _relative(skill_root, repository_root),
                )
            )
            continue

        directories = discover_skill_directories(skill_root)
        root_counts = {"invalid": 0, "legacy": 0, "verified": 0}
        for directory in directories:
            validation = validate_skill_directory(
                directory, require_contract=require_contract
            )
            if not validation.ok:
                status = "invalid"
                for finding in validation.errors:
                    field = f" ({finding.field})" if finding.field else ""
                    issues.append(
                        AuditIssue(
                            finding.code,
                            f"{finding.message}{field}",
                            _relative(validation.path, repository_root),
                        )
                    )
            elif validation.status == "verified":
                status = "verified"
                for finding in source_freshness_blockers(validation):
                    field = f" ({finding.field})" if finding.field else ""
                    issues.append(
                        AuditIssue(
                            finding.code,
                            f"{finding.message}{field}",
                            _relative(validation.path, repository_root),
                        )
                    )
            else:
                status = "legacy"
            counts[status] += 1
            root_counts[status] += 1

        root_records.append(
            {
                "path": _relative(skill_root, repository_root),
                "total": len(directories),
                **root_counts,
            }
        )

    bundled_root = repository_root / "skills"
    bundled_index_bytes = (
        _rendered_index_bytes(bundled_root) if bundled_root.is_dir() else 0
    )
    if bundled_index_bytes > max_bundled_index_bytes:
        issues.append(
            AuditIssue(
                "bundled_skill_index_budget_exceeded",
                (
                    f"rendered bundled skill index is {bundled_index_bytes} bytes; "
                    f"budget is {max_bundled_index_bytes} bytes. Introduce bounded "
                    "routing or explicitly revise the architecture budget."
                ),
                "skills",
            )
        )

    serialized_issues = [
        asdict(issue)
        for issue in sorted(issues, key=lambda item: (item.path, item.code, item.message))
    ]
    return {
        "bundled_index_budget_bytes": max_bundled_index_bytes,
        "bundled_index_bytes": bundled_index_bytes,
        **counts,
        "issues": serialized_issues,
        "ok": not serialized_issues,
        "require_contract": require_contract,
        "roots": sorted(root_records, key=lambda item: str(item["path"])),
        "total": sum(counts.values()),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roots",
        nargs="*",
        default=list(DEFAULT_ROOTS),
        help="repository-relative skill roots (default: skills optional-skills)",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--require-contract", action="store_true")
    parser.add_argument(
        "--max-bundled-index-bytes",
        type=int,
        default=DEFAULT_MAX_BUNDLED_INDEX_BYTES,
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.max_bundled_index_bytes < 0:
        raise SystemExit("--max-bundled-index-bytes must be nonnegative")
    report = audit_repository(
        args.repository_root,
        roots=args.roots,
        require_contract=args.require_contract,
        max_bundled_index_bytes=args.max_bundled_index_bytes,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            "Skill governance audit: "
            f"{report['verified']} verified, {report['legacy']} legacy, "
            f"{report['invalid']} invalid; bundled index "
            f"{report['bundled_index_bytes']}/{report['bundled_index_budget_bytes']} bytes"
        )
        for issue in report["issues"]:
            print(
                f"ERROR {issue['code']} {issue['path']}: {issue['message']}"
            )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
