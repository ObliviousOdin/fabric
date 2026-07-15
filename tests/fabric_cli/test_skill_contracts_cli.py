from __future__ import annotations

import argparse
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from fabric_cli import skill_contracts
from fabric_cli.subcommands.skills import build_skills_parser


def _issue(
    severity: str,
    code: str,
    message: str,
    field: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        severity=severity,
        code=code,
        message=message,
        field=field,
    )


def _validation(
    directory: Path,
    *,
    status: str,
    ok: bool,
    contract=None,
    digest: str | None = None,
    issues=(),
) -> SimpleNamespace:
    return SimpleNamespace(
        path=directory / "skill.contract.yaml",
        status=status,
        ok=ok,
        contract=contract,
        digest=digest,
        issues=tuple(issues),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fabric")
    subparsers = parser.add_subparsers(dest="command")
    build_skills_parser(subparsers, cmd_skills=lambda _args: None)
    return parser


def test_validate_parser_accepts_target_contract_gate_and_json() -> None:
    args = _parser().parse_args(
        ["skills", "validate", "research", "--require-contract", "--json"]
    )

    assert args.skills_action == "validate"
    assert args.target == "research"
    assert args.require_contract is True
    assert args.json is True


def test_evaluate_parser_requires_pending_id_and_observations() -> None:
    args = _parser().parse_args(
        [
            "skills",
            "evaluate",
            "0123456789abcdef0123456789abcdef",
            "--observations",
            "observations.json",
            "--json",
        ]
    )

    assert args.skills_action == "evaluate"
    assert args.pending_id == "0123456789abcdef0123456789abcdef"
    assert args.observations == "observations.json"
    assert args.json is True


def test_rollback_parser_accepts_exact_transaction_argument() -> None:
    args = _parser().parse_args(
        [
            "skills",
            "rollback",
            "0123456789abcdef0123456789abcdef",
            "--json",
            "--now",
        ]
    )

    assert args.skills_action == "rollback"
    assert args.transaction_id == "0123456789abcdef0123456789abcdef"
    assert args.json is True
    assert args.now is True


def test_collect_validation_reports_verified_legacy_and_invalid_deterministically(
    monkeypatch, tmp_path: Path
) -> None:
    skills_root = tmp_path / "skills"
    legacy = skills_root / "z-category" / "legacy"
    verified = skills_root / "a-category" / "verified"
    invalid = skills_root / "m-category" / "invalid"
    for directory in (legacy, verified, invalid):
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text("---\nname: test\n---\n", encoding="utf-8")

    results = {
        legacy: _validation(
            legacy,
            status="legacy_unverified",
            ok=True,
            issues=(
                _issue(
                    "warning",
                    "missing_contract",
                    "Add skill.contract.yaml to opt into governed validation.",
                ),
            ),
        ),
        verified: _validation(
            verified,
            status="verified",
            ok=True,
            contract={"identity": {"name": "verified-contract"}},
            digest="sha256:abc",
        ),
        invalid: _validation(
            invalid,
            status="invalid",
            ok=False,
            issues=(
                _issue(
                    "error",
                    "invalid_permission",
                    "Use a supported permission lane.",
                    "permissions.risk_lane",
                ),
            ),
        ),
    }
    monkeypatch.setattr(skill_contracts, "get_skills_dir", lambda: skills_root)
    monkeypatch.setattr(
        skill_contracts.skill_contract,
        "discover_skill_directories",
        lambda _root: [legacy, invalid, verified],
    )
    monkeypatch.setattr(
        skill_contracts.skill_contract,
        "validate_skill_directory",
        lambda path, require_contract=False: results[path],
    )

    summary = skill_contracts.collect_validation()

    assert summary["ok"] is False
    assert (summary["verified"], summary["legacy"], summary["invalid"]) == (
        1,
        1,
        1,
    )
    assert [record["status"] for record in summary["skills"]] == [
        "verified",
        "invalid",
        "legacy",
    ]
    assert summary["skills"][0]["name"] == "verified-contract"
    assert summary["skills"][1]["issues"][0]["field"] == (
        "permissions.risk_lane"
    )


def test_installed_name_resolution_is_profile_scoped_and_case_insensitive(
    monkeypatch, tmp_path: Path
) -> None:
    skills_root = tmp_path / "profile" / "skills"
    selected = skills_root / "research" / "Web-Research"
    other = skills_root / "other"
    selected.mkdir(parents=True)
    other.mkdir(parents=True)
    (selected / "SKILL.md").write_text("# selected\n", encoding="utf-8")
    (other / "SKILL.md").write_text("# other\n", encoding="utf-8")

    seen: list[Path] = []
    monkeypatch.setattr(skill_contracts, "get_skills_dir", lambda: skills_root)
    monkeypatch.setattr(
        skill_contracts.skill_contract,
        "discover_skill_directories",
        lambda root: [selected, other] if root == skills_root.resolve() else [],
    )

    def validate(path: Path, *, require_contract: bool):
        seen.append(path)
        return _validation(path, status="legacy_unverified", ok=True)

    monkeypatch.setattr(
        skill_contracts.skill_contract, "validate_skill_directory", validate
    )

    summary = skill_contracts.collect_validation("web-research")

    assert summary["ok"] is True
    assert summary["total"] == 1
    assert seen == [selected]


def _write_legacy_skill(directory: Path, name: str) -> None:
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill.\n---\n# {name}\n",
        encoding="utf-8",
    )


def test_bare_installed_name_is_not_shadowed_by_same_named_cwd_directory(
    monkeypatch, tmp_path: Path
) -> None:
    skills_root = tmp_path / "profile" / "skills"
    installed = skills_root / "research" / "web-research"
    cwd = tmp_path / "workspace"
    shadow = cwd / "web-research"
    _write_legacy_skill(installed, "web-research")
    _write_legacy_skill(shadow, "shadow-research")
    monkeypatch.setattr(skill_contracts, "get_skills_dir", lambda: skills_root)
    monkeypatch.chdir(cwd)

    summary = skill_contracts.collect_validation("web-research")

    assert summary["ok"] is True
    assert summary["total"] == 1
    assert summary["skills"][0]["path"] == str(installed.resolve())


def test_explicit_relative_path_can_select_same_named_cwd_directory(
    monkeypatch, tmp_path: Path
) -> None:
    skills_root = tmp_path / "profile" / "skills"
    installed = skills_root / "research" / "web-research"
    cwd = tmp_path / "workspace"
    shadow = cwd / "web-research"
    _write_legacy_skill(installed, "web-research")
    _write_legacy_skill(shadow, "shadow-research")
    monkeypatch.setattr(skill_contracts, "get_skills_dir", lambda: skills_root)
    monkeypatch.chdir(cwd)

    summary = skill_contracts.collect_validation("./web-research")

    assert summary["ok"] is True
    assert summary["total"] == 1
    assert summary["skills"][0]["path"] == str(shadow.resolve())


def test_existing_bare_directory_remains_a_fallback_without_installed_match(
    monkeypatch, tmp_path: Path
) -> None:
    skills_root = tmp_path / "profile" / "skills"
    cwd = tmp_path / "workspace"
    local = cwd / "local-research"
    skills_root.mkdir(parents=True)
    _write_legacy_skill(local, "local-research")
    monkeypatch.setattr(skill_contracts, "get_skills_dir", lambda: skills_root)
    monkeypatch.chdir(cwd)

    summary = skill_contracts.collect_validation("local-research")

    assert summary["ok"] is True
    assert summary["total"] == 1
    assert summary["skills"][0]["path"] == str(local.resolve())


def test_do_validate_json_is_parseable_and_legacy_warning_passes(
    monkeypatch, tmp_path: Path
) -> None:
    skill_dir = tmp_path / "legacy"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# legacy\n", encoding="utf-8")
    monkeypatch.setattr(
        skill_contracts.skill_contract,
        "validate_skill_directory",
        lambda path, require_contract=False: _validation(
            path,
            status="legacy_unverified",
            ok=True,
            issues=(
                _issue(
                    "warning",
                    "missing_contract",
                    "Add skill.contract.yaml for stronger guarantees.",
                ),
            ),
        ),
    )

    sink = StringIO()
    summary = skill_contracts.do_validate(
        skill_dir,
        as_json=True,
        console=Console(
            file=sink,
            force_terminal=False,
            color_system=None,
            width=200,
        ),
    )

    assert summary["legacy"] == 1
    assert json.loads(sink.getvalue()) == summary


def test_do_validate_exits_nonzero_for_required_legacy_contract(
    monkeypatch, tmp_path: Path
) -> None:
    skill_dir = tmp_path / "legacy"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# legacy\n", encoding="utf-8")

    def validate(path: Path, *, require_contract: bool):
        assert require_contract is True
        return _validation(
            path,
            status="invalid",
            ok=False,
            issues=(
                _issue(
                    "error",
                    "missing_contract",
                    "Create skill.contract.yaml before promotion.",
                ),
            ),
        )

    monkeypatch.setattr(
        skill_contracts.skill_contract, "validate_skill_directory", validate
    )
    sink = StringIO()

    with pytest.raises(SystemExit) as exc:
        skill_contracts.do_validate(
            skill_dir,
            require_contract=True,
            console=Console(file=sink, force_terminal=False, color_system=None),
        )

    assert exc.value.code == 1
    assert "missing_contract" in sink.getvalue()
    assert "1 invalid" in sink.getvalue()


def test_do_validate_exits_nonzero_when_target_has_no_skills(
    monkeypatch, tmp_path: Path
) -> None:
    skills_root = tmp_path / "skills"
    monkeypatch.setattr(skill_contracts, "get_skills_dir", lambda: skills_root)
    monkeypatch.setattr(
        skill_contracts.skill_contract,
        "discover_skill_directories",
        lambda _root: [],
    )
    sink = StringIO()

    with pytest.raises(SystemExit) as exc:
        skill_contracts.do_validate(
            "does-not-exist",
            as_json=True,
            console=Console(file=sink, force_terminal=False, color_system=None),
        )

    payload = json.loads(sink.getvalue())
    assert exc.value.code == 1
    assert payload["issues"][0]["code"] == "no_skills_found"
    assert payload["total"] == 0
