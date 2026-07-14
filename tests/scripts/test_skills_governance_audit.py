from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "skills-governance-audit.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("skills_governance_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SkillsGovernanceAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = _load_audit_module()
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "skills").mkdir()
        (self.root / "optional-skills").mkdir()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_skill(self, root: str, category: str, name: str) -> Path:
        directory = self.root / root / category / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            "---\n"
            f"name: {name}\n"
            f"description: Use {name} for a deterministic test.\n"
            "version: 1.0.0\n"
            "---\n\n"
            f"# {name}\n\nDo the test workflow.\n",
            encoding="utf-8",
        )
        return directory

    def test_legacy_inventory_passes_and_reports_prompt_footprint(self) -> None:
        self._write_skill("skills", "testing", "one-skill")
        self._write_skill("optional-skills", "testing", "two-skill")

        report = self.audit.audit_repository(self.root)

        self.assertTrue(report["ok"])
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["legacy"], 2)
        self.assertGreater(report["bundled_index_bytes"], 0)

    def test_present_invalid_contract_fails_even_during_legacy_migration(self) -> None:
        directory = self._write_skill("skills", "testing", "bad-contract")
        (directory / "skill.contract.yaml").write_text(
            "schema_version: 999\n",
            encoding="utf-8",
        )

        report = self.audit.audit_repository(self.root)

        self.assertFalse(report["ok"])
        self.assertEqual(report["invalid"], 1)
        self.assertIn(
            "schema_version_unsupported",
            {issue["code"] for issue in report["issues"]},
        )

    def test_strict_mode_rejects_missing_contract(self) -> None:
        self._write_skill("skills", "testing", "legacy-skill")

        report = self.audit.audit_repository(self.root, require_contract=True)

        self.assertFalse(report["ok"])
        self.assertIn(
            "contract_missing", {issue["code"] for issue in report["issues"]}
        )

    def test_prompt_budget_is_an_invariant_not_a_snapshot(self) -> None:
        self._write_skill("skills", "testing", "budgeted-skill")

        report = self.audit.audit_repository(
            self.root, max_bundled_index_bytes=1
        )

        self.assertFalse(report["ok"])
        self.assertIn(
            "bundled_skill_index_budget_exceeded",
            {issue["code"] for issue in report["issues"]},
        )

    def test_large_catalog_budget_measures_bounded_taxonomy(self) -> None:
        for index in range(40):
            self._write_skill(
                "skills",
                "development" if index % 2 == 0 else "operations",
                f"skill-{index:02d}",
            )

        report = self.audit.audit_repository(
            self.root, max_bundled_index_bytes=4096
        )

        self.assertTrue(report["ok"])
        self.assertLess(report["bundled_index_bytes"], 4096)

    def test_verified_skill_with_expired_source_fails_release_audit(self) -> None:
        self._write_skill("skills", "testing", "freshness-skill")

        original_validate = self.audit.validate_skill_directory

        def verified(*args, **kwargs):
            result = original_validate(*args, **kwargs)
            return SimpleNamespace(
                errors=(),
                issues=(),
                ok=True,
                path=result.path,
                status="verified",
            )

        expired = SimpleNamespace(
            code="source_expired",
            field="sources[0]",
            message="declared source expired",
        )
        with (
            patch.object(self.audit, "validate_skill_directory", verified),
            patch.object(
                self.audit,
                "source_freshness_blockers",
                return_value=(expired,),
            ),
        ):
            report = self.audit.audit_repository(self.root)

        self.assertFalse(report["ok"])
        self.assertIn(
            "source_expired", {issue["code"] for issue in report["issues"]}
        )

    def test_missing_configured_root_fails_closed(self) -> None:
        report = self.audit.audit_repository(
            self.root, roots=("skills", "missing-skills")
        )

        self.assertFalse(report["ok"])
        self.assertIn(
            "skill_root_missing", {issue["code"] for issue in report["issues"]}
        )


if __name__ == "__main__":
    unittest.main()
