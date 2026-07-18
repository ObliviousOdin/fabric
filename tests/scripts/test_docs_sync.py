from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "docs_sync.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("docs_sync_unit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DocsSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sync = _load_module()

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_dashboard_route_catalog_reads_canonical_typescript(self) -> None:
        catalog = self.sync.collect_dashboard_routes(ROOT)
        routes = {route["id"]: route for route in catalog["routes"]}

        self.assertEqual(catalog["default_route"], "/workspace/home")
        self.assertTrue(routes["chat"]["persistent"])
        self.assertEqual(routes["work-board"]["aliases"], ["/kanban", "/work"])
        self.assertEqual(routes["agents"]["surface"], "workspace")

    def test_dashboard_manifest_catalog_preserves_manifest_json(self) -> None:
        manifests = self.sync.collect_dashboard_manifests(ROOT)
        by_name = {item["manifest"]["name"]: item for item in manifests}

        self.assertEqual(
            by_name["kanban"]["manifest"]["tab"]["override"],
            "/workspace/work",
        )
        self.assertEqual(by_name["kanban"]["manifest"]["slots"], ["chat:rail"])

    def test_top_level_cli_catalog_covers_distributed_registrations(self) -> None:
        commands = {
            row["name"]: row for row in self.sync.collect_top_level_cli_commands(ROOT)
        }

        self.assertEqual(commands["console"]["alias_of"], None)
        self.assertEqual(commands["serve"]["alias_of"], None)
        self.assertEqual(commands["kanban"]["alias_of"], None)
        self.assertEqual(commands["journey"]["aliases"], ["learning", "memory-graph"])
        self.assertEqual(commands["learning"]["alias_of"], "journey")
        self.assertEqual(commands["login"]["visibility"], "compatibility")

    def test_generated_runtime_catalog_is_committed_and_current(self) -> None:
        self.assertEqual(self.sync.generate(ROOT, check=True), [])

    def test_documented_token_requires_non_doc_source(self) -> None:
        contracts = {
            "authored_docs": {
                "include": ["*.md", "**/*.md"],
                "exclude": [],
            },
            "documented_token_exemptions": {},
        }
        self._write("website/docs/guide.md", "Use `FABRIC_REAL_TOKEN` and `HERMES_GHOST`.\n")
        self._write("src/runtime.py", 'TOKEN = "FABRIC_REAL_TOKEN"\n')

        errors = self.sync.audit_documented_tokens(self.root, contracts)

        self.assertEqual(len(errors), 1)
        self.assertIn("HERMES_GHOST", errors[0])

    def test_test_fixture_cannot_back_a_documented_token(self) -> None:
        contracts = {
            "authored_docs": {
                "include": ["*.md", "**/*.md"],
                "exclude": [],
            },
            "documented_token_exemptions": {},
        }
        self._write("website/docs/guide.md", "Use `HERMES_TEST_ONLY_GHOST`.\n")
        self._write("tests/fixture.py", 'TOKEN = "HERMES_TEST_ONLY_GHOST"\n')

        errors = self.sync.audit_documented_tokens(self.root, contracts)

        self.assertEqual(len(errors), 1)
        self.assertIn("HERMES_TEST_ONLY_GHOST", errors[0])

    def test_token_exemption_requires_an_explicit_reason(self) -> None:
        contracts = {
            "authored_docs": {"include": ["**/*.md"], "exclude": []},
            "documented_token_exemptions": {
                "HERMES_PREFIX_": "Wildcard family whose concrete members are source-backed."
            },
        }
        self._write("website/docs/guide.md", "`HERMES_PREFIX_*`\n")

        self.assertEqual(
            self.sync.audit_documented_tokens(self.root, contracts),
            [],
        )

    def test_first_party_skill_rejects_legacy_metadata_namespace(self) -> None:
        self._write(
            "skills/example/SKILL.md",
            "---\nname: example\nmetadata:\n  hermes:\n    tags: [Example]\n---\n",
        )

        errors = self.sync.audit_first_party_skill_metadata(self.root)

        self.assertEqual(len(errors), 1)
        self.assertIn("metadata.fabric", errors[0])

    def test_skill_metadata_audit_parses_indented_and_inline_yaml(self) -> None:
        self._write(
            "skills/indented/SKILL.md",
            "---\nname: indented\nmetadata:\n    hermes:\n        tags: [Example]\n---\n",
        )
        self._write(
            "skills/inline/SKILL.md",
            "---\nname: inline\nmetadata: {hermes: {tags: [Example]}}\n---\n",
        )

        errors = self.sync.audit_first_party_skill_metadata(self.root)

        self.assertEqual(len(errors), 2)
        self.assertTrue(all("metadata.fabric" in error for error in errors))

    def test_impact_requires_mapped_doc_or_scoped_declaration(self) -> None:
        contracts = {
            "impact_contracts": [
                {
                    "id": "commands",
                    "code_paths": ["src/commands.py"],
                    "docs_paths": ["docs/commands.md"],
                }
            ]
        }
        errors, bypasses = self.sync.evaluate_impact(
            ["src/commands.py"], contracts, {}
        )
        self.assertEqual(len(errors), 1)
        self.assertEqual(bypasses, [])

        errors, bypasses = self.sync.evaluate_impact(
            ["src/commands.py", "docs/commands.md"], contracts, {}
        )
        self.assertEqual((errors, bypasses), ([], []))

        declarations = self.sync.parse_impact_declarations(
            "Docs-impact: none [commands] — Only comments and typing changed."
        )
        errors, bypasses = self.sync.evaluate_impact(
            ["src/commands.py"], contracts, declarations
        )
        self.assertEqual(errors, [])
        self.assertEqual(
            bypasses,
            ["commands: Only comments and typing changed."],
        )

    def test_impact_declaration_rejects_template_placeholder(self) -> None:
        self.assertEqual(
            self.sync.parse_impact_declarations(
                "Docs-impact: none [contract-id] — <explain why>"
            ),
            {},
        )

    def test_git_changed_paths_includes_deleted_contract_sources(self) -> None:
        repo = self.root / "repo"
        repo.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Docs Test",
            "GIT_AUTHOR_EMAIL": "docs@example.invalid",
            "GIT_COMMITTER_NAME": "Docs Test",
            "GIT_COMMITTER_EMAIL": "docs@example.invalid",
        }
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=env)
        source = repo / "src" / "commands.py"
        source.parent.mkdir()
        source.write_text("COMMANDS = {}\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, env=env)
        subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True, env=env)
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout.strip()
        source.unlink()
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
        subprocess.run(["git", "commit", "-q", "-m", "delete"], cwd=repo, check=True, env=env)

        self.assertEqual(
            self.sync._git_changed_paths(repo, base, "HEAD"),
            ["src/commands.py"],
        )

    def test_contract_map_is_canonical_json(self) -> None:
        path = ROOT / "docs" / "documentation-contracts.json"
        raw = path.read_text(encoding="utf-8")
        self.assertEqual(raw, self.sync.canonical_json(json.loads(raw)))


if __name__ == "__main__":
    unittest.main()
