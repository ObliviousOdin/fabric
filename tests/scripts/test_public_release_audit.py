from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "public-release-audit.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("public_release_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PublicReleaseAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = _load_audit_module()
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        for relative, fragments in self.audit.CANONICAL_REQUIREMENTS.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(fragments), encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _issues(self):
        return self.audit.audit_repository(self.root)

    def test_clean_public_snapshot_passes(self) -> None:
        (self.root / "website/docs/guide.md").parent.mkdir(parents=True)
        (self.root / "website/docs/guide.md").write_text(
            "# Fabric\n\nRun `fabric setup`. Hermes 3 is an optional model.\n",
            encoding="utf-8",
        )

        self.assertEqual(self._issues(), [])

    def test_rejects_private_brand_and_distribution_language(self) -> None:
        private = "ra" + "bot"
        path = self.root / "notes.md"
        path.write_text(
            f"{private.upper()}_HOME=/tmp/x\nThis is a white" + "-label private" + " fork.\n",
            encoding="utf-8",
        )

        rules = {issue.rule for issue in self._issues()}
        self.assertIn("private-brand", rules)
        self.assertIn("distribution-origin", rules)

    def test_rejects_private_paths_and_personal_email(self) -> None:
        private = "ra" + "bot"
        path = self.root / "debug.txt"
        path.write_text(
            f"/Users/{private}-channa-mac/Documents/workspace/{private}inc/project\n"
            + "channa" + "@example.com\n",
            encoding="utf-8",
        )

        rules = {issue.rule for issue in self._issues()}
        self.assertIn("private-brand", rules)
        self.assertIn("personal-email", rules)
        self.assertIn("personal-workspace", rules)

    def test_rejects_legacy_routes_commands_and_product_copy(self) -> None:
        guide = self.root / "website/docs/legacy.md"
        guide.parent.mkdir(parents=True, exist_ok=True)
        guide.write_text(
            "# Hermes CLI\n\nRun `hermes setup`.\n"
            "https://github.com/NousResearch/" + "fabric-agent\n",
            encoding="utf-8",
        )

        rules = {issue.rule for issue in self._issues()}
        self.assertIn("customer-product", rules)
        self.assertIn("customer-command", rules)
        self.assertIn("repository-route", rules)

    def test_rejects_standalone_labels_in_yaml_and_omitted_runtime_prefixes(self) -> None:
        locale = self.root / "locales/en.yaml"
        locale.parent.mkdir(parents=True)
        locale.write_text('header: "Hermes Chat"\n', encoding="utf-8")
        runtime = self.root / "gateway/run.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text('TOPIC_TITLE = "Hermes Commands"\n', encoding="utf-8")

        issues = self._issues()
        paths = {issue.path for issue in issues if issue.rule in {"customer-product", "customer-source"}}
        self.assertIn("locales/en.yaml", paths)
        self.assertIn("gateway/run.py", paths)

    def test_rejects_any_formatted_legacy_subcommand(self) -> None:
        config = self.root / "plugins/example/plugin.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            'help = "Run `hermes brand-new-command --safe`."\n'
            "```sh\nhermes another-future-command\n```\n",
            encoding="utf-8",
        )

        issues = [issue for issue in self._issues() if issue.rule == "customer-command"]
        self.assertGreaterEqual(len(issues), 2)
        self.assertEqual({issue.path for issue in issues}, {"plugins/example/plugin.toml"})

    def test_rejects_legacy_home_guidance_in_structured_metadata(self) -> None:
        config = self.root / "plugins/example/plugin.yaml"
        config.parent.mkdir(parents=True)
        config.write_text(
            'description: "Store config under /home/user/.hermes and set HERMES_HOME."\n',
            encoding="utf-8",
        )

        self.assertIn("customer-home", {issue.rule for issue in self._issues()})

    def test_rejects_legacy_home_literal_in_runtime_source(self) -> None:
        runtime = self.root / "plugins/platforms/example/adapter.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            'SCRIPT_DIR = Path.home() / ".hermes" / "scripts"\n',
            encoding="utf-8",
        )

        self.assertIn("customer-source", {issue.rule for issue in self._issues()})

    def test_rejects_legacy_outbound_identity_in_platform_source(self) -> None:
        adapter = self.root / "plugins/platforms/example/adapter.py"
        adapter.parent.mkdir(parents=True)
        adapter.write_text(
            "# public-release-audit: allow-legacy-compat -- wire fallback\n"
            'HEADERS = {"User-Agent": "HermesAgent/1.0"}\n',
            encoding="utf-8",
        )

        self.assertIn("customer-source", {issue.rule for issue in self._issues()})

    def test_compatibility_annotation_does_not_hide_legacy_command(self) -> None:
        runtime = self.root / "agent/compat.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            "# public-release-audit: allow-legacy-compat -- executable fallback\n"
            "COMMAND = 'hermes future-command --safe'\n",
            encoding="utf-8",
        )

        self.assertIn("customer-source", {issue.rule for issue in self._issues()})

    def test_ignores_comment_only_shell_legacy_examples(self) -> None:
        script = self.root / "docker/entrypoint.sh"
        script.parent.mkdir(parents=True)
        script.write_text(
            "#!/bin/sh\n"
            "# Historical command example: `hermes setup`\n"
            "# OLD_NAME='Hermes'\n"
            "exec fabric gateway\n",
            encoding="utf-8",
        )

        self.assertEqual(self._issues(), [])

    def test_rejects_legacy_shell_shebang_assignment_and_echo(self) -> None:
        script = self.root / "docker/entrypoint.sh"
        script.parent.mkdir(parents=True)
        script.write_text(
            "#!/usr/bin/env hermes\n"
            "OLD_NAME='Hermes'\n"
            "echo 'Hermes CLI is ready'\n",
            encoding="utf-8",
        )

        issues = [issue for issue in self._issues() if issue.rule == "customer-source"]
        self.assertGreaterEqual(len(issues), 3)

    def test_allows_legacy_compatibility_identifiers_in_runtime_source(self) -> None:
        runtime = self.root / "agent/compat.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            "# public-release-audit: allow-legacy-compat -- one-window home migration\n"
            "LEGACY_HOME_NAMES = ('.fabric', '.hermes')\n"
            "WIRE_PROTOCOL = 'hermes.session.v1'\n"
            "ENV_KEY = 'HERMES_HOME'\n",
            encoding="utf-8",
        )

        self.assertEqual(self._issues(), [])

    def test_rejects_unannotated_compatibility_literal_in_source(self) -> None:
        runtime = self.root / "agent/compat.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            "LEGACY_HOME_NAMES = ('.fabric', '.hermes')\n",
            encoding="utf-8",
        )

        self.assertIn("customer-source", {issue.rule for issue in self._issues()})

    def test_allows_annotated_old_install_folder_constant(self) -> None:
        runtime = self.root / "agent/compat.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            "# public-release-audit: allow-legacy-compat -- desktop upgrade fallback\n"
            "LEGACY_INSTALL_NAMES = ('Fabric', 'Hermes')\n",
            encoding="utf-8",
        )

        self.assertEqual(self._issues(), [])

    def test_compatibility_annotation_does_not_hide_rendered_copy(self) -> None:
        runtime = self.root / "agent/compat.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            "# public-release-audit: allow-legacy-compat -- old install fallback\n"
            "print('Hermes')\n",
            encoding="utf-8",
        )

        self.assertIn("customer-source", {issue.rule for issue in self._issues()})

    def test_non_python_compatibility_annotation_only_allows_literal_tables(self) -> None:
        runtime = self.root / "apps/bootstrap/src/main.rs"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            "// public-release-audit: allow-legacy-compat -- desktop upgrade fallback\n"
            'let legacy_candidates = ["Fabric", "Hermes"];\n',
            encoding="utf-8",
        )

        self.assertEqual(self._issues(), [])

        runtime.write_text(
            "// public-release-audit: allow-legacy-compat -- desktop upgrade fallback\n"
            'println!("Hermes");\n',
            encoding="utf-8",
        )

        self.assertIn("customer-source", {issue.rule for issue in self._issues()})

    def test_compatibility_annotation_must_be_adjacent_and_justified(self) -> None:
        runtime = self.root / "agent/compat.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            "# public-release-audit: allow-legacy-compat\n"
            "UNRELATED = 'value'\n"
            "LEGACY_INSTALL_NAMES = ('Fabric', 'Hermes')\n",
            encoding="utf-8",
        )

        self.assertIn("customer-source", {issue.rule for issue in self._issues()})

    def test_allows_models_legal_attribution_and_explicit_home_migration(self) -> None:
        guide = self.root / "website/docs/models.md"
        guide.parent.mkdir(parents=True)
        guide.write_text(
            "Hermes 3, Hermes-4-70B, and HermesBench are model or benchmark names.\n"
            "Migrate the legacy ~/.hermes directory to ~/.fabric.\n",
            encoding="utf-8",
        )

        self.assertEqual(self._issues(), [])

    def test_model_reference_does_not_hide_nearby_legacy_product_label(self) -> None:
        guide = self.root / "website/docs/models.md"
        guide.parent.mkdir(parents=True)
        guide.write_text(
            "# Hermes CLI\n\nHermes 3 is an optional model.\n",
            encoding="utf-8",
        )

        self.assertIn("customer-product", {issue.rule for issue in self._issues()})

    def test_allows_original_repository_links_as_third_party_story_provenance(self) -> None:
        stories = self.root / "website/src/data/userStories.json"
        stories.parent.mkdir(parents=True)
        stories.write_text(
            '{"issue":"https://github.com/NousResearch/hermes-agent/issues/1",'
            '"pull":"https://github.com/NousResearch/hermes-agent/pull/42"}\n',
            encoding="utf-8",
        )

        self.assertEqual(self._issues(), [])

    def test_rejects_non_provenance_upstream_routes_in_story_data(self) -> None:
        stories = self.root / "website/src/data/userStories.json"
        stories.parent.mkdir(parents=True)
        rejected_routes = (
            "https://github.com/NousResearch/hermes-agent",
            "https://github.com/NousResearch/hermes-agent/tree/main/docs",
            "https://github.com/NousResearch/hermes-agent/releases/latest",
            "https://github.com/NousResearch/hermes-agent/issues/new",
            "https://github.com/NousResearch/hermes-agent/issues/12/comments",
            "https://github.com/NousResearch/fabric-agent/issues/12",
        )
        stories.write_text(
            "\n".join(f'{{"url":"{route}"}}' for route in rejected_routes),
            encoding="utf-8",
        )

        self.assertIn("repository-route", {issue.rule for issue in self._issues()})

    def test_rejects_non_placeholder_macos_paths_in_docs(self) -> None:
        guide = self.root / "guide.md"
        guide.write_text("Open /Users/somebody/secret.txt\n", encoding="utf-8")

        self.assertIn("personal-doc-path", {issue.rule for issue in self._issues()})

    def test_rejects_private_identity_in_reachable_commit_metadata(self) -> None:
        private = "ra" + "bot"
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Example",
            "GIT_AUTHOR_EMAIL": "channa" + f"@{private}.us",
            "GIT_COMMITTER_NAME": "Example",
            "GIT_COMMITTER_EMAIL": "channa" + f"@{private}.us",
        }
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-q", "-m", "Initial snapshot"],
            check=True,
            env=env,
        )

        issues = self.audit.audit_git_history(self.root)

        self.assertTrue(issues)
        self.assertEqual({issue.rule for issue in issues}, {"git-history"})

    def test_rejects_noncanonical_origin(self) -> None:
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "remote",
                "add",
                "origin",
                "https://github.com/example/not-fabric.git",
            ],
            check=True,
        )

        issues = self.audit.audit_git_history(self.root)

        self.assertEqual({issue.rule for issue in issues}, {"git-remote"})

    def test_rejects_inherited_or_extra_workflows(self) -> None:
        extra = self.root / ".github/workflows/private-deploy.yml"
        extra.write_text("name: Deploy\n", encoding="utf-8")

        self.assertIn("workflow-surface", {issue.rule for issue in self._issues()})

    def test_rejects_privileged_public_workflow(self) -> None:
        workflow = self.root / ".github/workflows/public-ci.yml"
        workflow.write_text(
            workflow.read_text(encoding="utf-8")
            + "\npull_request_target:\npermissions:\n  contents: write\n",
            encoding="utf-8",
        )

        self.assertIn("workflow-surface", {issue.rule for issue in self._issues()})

    def test_rejects_unpinned_external_actions(self) -> None:
        workflow = self.root / ".github/workflows/public-ci.yml"
        workflow.write_text(
            workflow.read_text(encoding="utf-8")
            + "\nsteps:\n  - uses: example/action@main\n",
            encoding="utf-8",
        )

        self.assertIn("workflow-surface", {issue.rule for issue in self._issues()})

    def test_rejects_publish_capability(self) -> None:
        workflow = self.root / ".github/workflows/public-ci.yml"
        workflow.write_text(
            workflow.read_text(encoding="utf-8") + "\nrun: npm publish\n",
            encoding="utf-8",
        )

        self.assertIn("workflow-surface", {issue.rule for issue in self._issues()})

    def test_pages_workflow_cannot_write_repository_contents(self) -> None:
        workflow = self.root / ".github/workflows/docs-pages.yml"
        workflow.write_text(
            workflow.read_text(encoding="utf-8") + "\ncontents: write\n",
            encoding="utf-8",
        )

        self.assertIn("workflow-surface", {issue.rule for issue in self._issues()})

    def test_rejects_private_planning_directories(self) -> None:
        plan = self.root / ".hermes/plans/internal.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("Internal plan\n", encoding="utf-8")

        self.assertIn("private-topology", {issue.rule for issue in self._issues()})


if __name__ == "__main__":
    unittest.main()
