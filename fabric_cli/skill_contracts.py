"""Read-only CLI orchestration for Fabric skill-contract validation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional

from rich.console import Console
from rich.markup import escape

from agent import skill_contract
from agent.skill_utils import parse_frontmatter
from fabric_constants import get_skills_dir


_console = Console()


def _normalized_path(path: Path) -> Path:
    """Return a stable absolute path without requiring that it exists."""

    return path.expanduser().resolve(strict=False)


def _is_explicit_path_target(target: str | Path, raw_target: str) -> bool:
    """Whether *target* uses syntax that unambiguously requests a path."""

    if isinstance(target, Path):
        return True
    return (
        Path(raw_target).is_absolute()
        or raw_target.startswith(("./", "../", "~"))
        or "/" in raw_target
        or "\\" in raw_target
        or bool(re.match(r"^[A-Za-z]:", raw_target))
    )


def _directories_for_path(path_target: Path) -> tuple[Path, ...]:
    """Return skill directories selected by one explicit filesystem path."""

    if not path_target.exists():
        return ()
    if path_target.is_file() and path_target.name in {
        "SKILL.md",
        skill_contract.CONTRACT_FILENAME,
    }:
        return (path_target.parent,)
    if path_target.is_dir() and (path_target / "SKILL.md").is_file():
        return (path_target,)
    if path_target.is_dir():
        return skill_contract.discover_skill_directories(path_target)
    return ()


def _installed_name_matches(
    installed: tuple[Path, ...],
    raw_target: str,
) -> tuple[Path, ...]:
    """Resolve a bare name only within the active profile's installed skills."""

    normalized_name = raw_target.casefold()
    matches: list[Path] = []
    for path in installed:
        declared_name = path.name
        try:
            frontmatter, _body = parse_frontmatter(
                (path / "SKILL.md").read_text(encoding="utf-8")
            )
            candidate = frontmatter.get("name")
            if isinstance(candidate, str) and candidate.strip():
                declared_name = candidate.strip()
        except (OSError, UnicodeError, ValueError):
            # Validation will surface malformed content when the directory name
            # itself was selected; name lookup must remain read-only and bounded
            # to skills discovered under the active profile root.
            pass
        if (
            path.name.casefold() == normalized_name
            or declared_name.casefold() == normalized_name
        ):
            matches.append(path)
    return tuple(sorted(matches, key=lambda path: str(path).casefold()))


def _discover_target(target: str | Path | None) -> tuple[str, tuple[Path, ...]]:
    """Resolve a path or installed skill name to deterministic skill directories."""

    installed_root = _normalized_path(get_skills_dir())
    if target is None or not str(target).strip():
        return str(installed_root), tuple(
            sorted(
                skill_contract.discover_skill_directories(installed_root),
                key=lambda path: str(path).casefold(),
            )
        )

    raw_target = str(target).strip()
    explicit_path = _is_explicit_path_target(target, raw_target)
    if explicit_path:
        path_target = _normalized_path(Path(raw_target))
        directories = _directories_for_path(path_target)
        return str(path_target), tuple(
            sorted(directories, key=lambda path: str(path).casefold())
        )

    installed = tuple(skill_contract.discover_skill_directories(installed_root))
    matches = _installed_name_matches(installed, raw_target)
    if matches:
        return raw_target, matches

    # Preserve the convenient bare-directory form only when it cannot shadow
    # an installed skill. Files require explicit path syntax such as ./SKILL.md.
    path_target = _normalized_path(Path(raw_target))
    if path_target.is_dir():
        directories = _directories_for_path(path_target)
        return str(path_target), tuple(
            sorted(directories, key=lambda path: str(path).casefold())
        )
    return raw_target, ()


def _contract_name(validation: Any, skill_dir: Path) -> str:
    contract = validation.contract
    if isinstance(contract, Mapping):
        identity = contract.get("identity")
        if isinstance(identity, Mapping):
            name = identity.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return skill_dir.name


def _serialize_issue(issue: Any) -> dict[str, Any]:
    return {
        "code": str(issue.code),
        "field": str(issue.field) if issue.field is not None else None,
        "message": str(issue.message),
        "severity": str(issue.severity),
    }


def collect_validation(
    target: str | Path | None = None,
    *,
    require_contract: bool = False,
) -> dict[str, Any]:
    """Validate a target and return a deterministic, machine-readable summary.

    This function never mutates a skill and never exits. The CLI wrapper below
    turns ``ok=False`` into a non-zero exit status after printing the report.
    """

    resolved_target, directories = _discover_target(target)
    if not directories:
        message = (
            f"No skills found for target '{resolved_target}'. Pass an installed "
            "skill name or a path containing SKILL.md."
        )
        return {
            "invalid": 0,
            "issues": [
                {
                    "code": "no_skills_found",
                    "field": "target",
                    "message": message,
                    "severity": "error",
                }
            ],
            "legacy": 0,
            "ok": False,
            "require_contract": bool(require_contract),
            "skills": [],
            "target": resolved_target,
            "total": 0,
            "verified": 0,
        }

    records: list[dict[str, Any]] = []
    counts = {"verified": 0, "legacy": 0, "invalid": 0}
    for directory in directories:
        validation = skill_contract.validate_skill_directory(
            directory,
            require_contract=require_contract,
        )
        if validation.ok and validation.status == "verified":
            status = "verified"
        elif validation.ok and validation.status == "legacy_unverified":
            status = "legacy"
        else:
            status = "invalid"
        counts[status] += 1
        records.append(
            {
                "contract_path": str(_normalized_path(validation.path)),
                "digest": validation.digest,
                "issues": [
                    _serialize_issue(issue)
                    for issue in sorted(
                        validation.issues,
                        key=lambda item: (
                            str(item.severity),
                            str(item.code),
                            str(item.field or ""),
                            str(item.message),
                        ),
                    )
                ],
                "name": _contract_name(validation, directory),
                "path": str(_normalized_path(directory)),
                "status": status,
            }
        )

    records.sort(key=lambda record: (record["path"].casefold(), record["name"]))
    return {
        "invalid": counts["invalid"],
        "issues": [],
        "legacy": counts["legacy"],
        "ok": counts["invalid"] == 0,
        "require_contract": bool(require_contract),
        "skills": records,
        "target": resolved_target,
        "total": len(records),
        "verified": counts["verified"],
    }


def _print_human(summary: Mapping[str, Any], console: Console) -> None:
    console.print("[bold]Skill contract validation[/]")
    for issue in summary["issues"]:
        console.print(
            f"[bold red]ERROR {escape(str(issue['code']))}:[/] "
            f"{escape(str(issue['message']))}"
        )

    status_styles = {
        "verified": "green",
        "legacy": "yellow",
        "invalid": "bold red",
    }
    for record in summary["skills"]:
        status = record["status"]
        style = status_styles[status]
        console.print(
            f"[{style}][{status}][/] {escape(str(record['name']))} — "
            f"{escape(str(record['path']))}"
        )
        for issue in record["issues"]:
            field = (
                f" ({escape(str(issue['field']))})" if issue["field"] else ""
            )
            console.print(
                f"  {escape(str(issue['severity']).upper())} "
                f"{escape(str(issue['code']))}{field}: "
                f"{escape(str(issue['message']))}"
            )

    console.print(
        "[bold]Summary:[/] "
        f"{summary['verified']} verified, {summary['legacy']} legacy, "
        f"{summary['invalid']} invalid ({summary['total']} total)"
    )


def do_validate(
    target: str | Path | None = None,
    *,
    require_contract: bool = False,
    as_json: bool = False,
    console: Optional[Console] = None,
) -> dict[str, Any]:
    """Print a validation summary and exit non-zero when it is not valid."""

    summary = collect_validation(target, require_contract=require_contract)
    c = console or _console
    if as_json:
        c.print(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            markup=False,
            highlight=False,
            soft_wrap=True,
        )
    else:
        _print_human(summary, c)

    if not summary["ok"]:
        raise SystemExit(1)
    return summary
