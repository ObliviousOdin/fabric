from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.skill_promotion_gates import (
    SkillPromotionGateError,
    governed_origin,
    load_observations_file,
    materialized_final_skills,
    permission_expansion_details,
    virtual_tree_digest,
)


def _entry(kind: str, data: bytes = b"", mode: int = 0o600):
    return SimpleNamespace(kind=kind, data=data, mode=mode)


def test_private_materialization_preserves_exact_mode_sensitive_digest(
    tmp_path: Path,
) -> None:
    governance = tmp_path / "governance"
    governance.mkdir(mode=0o700)
    entries = {
        "": _entry("directory", mode=0o755),
        "SKILL.md": _entry("file", b"body\n", 0o640),
        "evals": _entry("directory", mode=0o750),
        "evals/cases.yaml": _entry("file", b"schema_version: 1\n", 0o600),
    }
    skill = SimpleNamespace(entries=entries)

    with materialized_final_skills({"demo": skill}, governance) as paths:
        materialized = paths["demo"]
        captured = {
            "": _entry("directory", mode=materialized.stat().st_mode & 0o7777),
            "SKILL.md": _entry(
                "file",
                (materialized / "SKILL.md").read_bytes(),
                (materialized / "SKILL.md").stat().st_mode & 0o7777,
            ),
            "evals": _entry(
                "directory", mode=(materialized / "evals").stat().st_mode & 0o7777
            ),
            "evals/cases.yaml": _entry(
                "file",
                (materialized / "evals" / "cases.yaml").read_bytes(),
                (materialized / "evals" / "cases.yaml").stat().st_mode & 0o7777,
            ),
        }
        assert virtual_tree_digest(captured) == virtual_tree_digest(entries)


def test_private_materialization_refuses_candidate_redirect(tmp_path: Path) -> None:
    governance = tmp_path / "governance"
    governance.mkdir(mode=0o700)
    skill = SimpleNamespace(
        entries={
            "": _entry("directory", mode=0o755),
            "SKILL.md": _entry("file", b"body\n"),
            "references/escape": _entry("symlink", b"/tmp", 0o777),
        }
    )

    with pytest.raises(SkillPromotionGateError, match="redirected entry"):
        with materialized_final_skills({"demo": skill}, governance):
            pass


def test_observations_reader_rejects_symlink_and_duplicate_keys(
    tmp_path: Path,
) -> None:
    source = tmp_path / "observations.json"
    source.write_text("{}", encoding="utf-8")
    link = tmp_path / "observations-link.json"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("Symlinks not supported")
    with pytest.raises(SkillPromotionGateError, match="non-symlink"):
        load_observations_file(link)

    source.write_text('{"case": [], "case": []}', encoding="utf-8")
    with pytest.raises(SkillPromotionGateError, match="duplicate JSON object key"):
        load_observations_file(source)


def test_observations_reader_returns_closed_plain_mapping(tmp_path: Path) -> None:
    source = tmp_path / "observations.json"
    value = {"case": [{"selected": True}]}
    source.write_text(json.dumps(value), encoding="utf-8")
    assert load_observations_file(source) == value


def test_permission_expansion_enumerates_authority_but_not_prohibitions() -> None:
    before = {
        "permissions": {
            "toolsets_required": [],
            "files": [],
            "network": [],
            "secrets": [],
            "actions": {
                "reversible": [],
                "approval_required": [],
                "prohibited": ["old-deny"],
            },
        }
    }
    after = {
        "permissions": {
            "toolsets_required": ["web"],
            "files": [{"scope": "workspace", "access": "read_write"}],
            "network": [{"host": "example.com", "methods": ["GET", "POST"]}],
            "secrets": ["EXAMPLE_TOKEN"],
            "actions": {
                "reversible": ["save"],
                "approval_required": ["publish"],
                "prohibited": ["new-deny"],
            },
        }
    }

    expansion = permission_expansion_details(before, after)
    assert "permissions.toolsets_required:+web" in expansion
    assert "permissions.files:workspace:+read" in expansion
    assert "permissions.files:workspace:+write" in expansion
    assert "permissions.network:example.com:+POST" in expansion
    assert "permissions.secrets:+EXAMPLE_TOKEN" in expansion
    assert "permissions.actions.reversible:+save" in expansion
    assert "permissions.actions.approval_required:+publish" in expansion
    assert not any("prohibited" in item for item in expansion)


def test_governed_origin_rejects_mixed_provenance() -> None:
    with pytest.raises(SkillPromotionGateError, match="mix write origins"):
        governed_origin(
            [
                {"origin": "learn_request"},
                {"origin": "background_review"},
            ]
        )
