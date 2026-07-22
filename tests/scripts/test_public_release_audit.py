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
FORMER_PRODUCT = "Her" + "mes"
FORMER_LOWER = FORMER_PRODUCT.lower()
FORMER_UPPER = FORMER_PRODUCT.upper()


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
        (self.root / ".github/workflows/release-channels.yml").write_text(
            self._valid_release_workflow(),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _issues(self):
        return self.audit.audit_repository(self.root)

    def _init_git(self) -> None:
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def _commit_with_private_identity(self, message: str, marker: str) -> str:
        private = "ra" + "bot"
        (self.root / f"history-{marker}.txt").write_text(
            f"public marker {marker}\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Example",
            "GIT_AUTHOR_EMAIL": "channa" + f"@{private}.us",
            "GIT_COMMITTER_NAME": "Example",
            "GIT_COMMITTER_EMAIL": "channa" + f"@{private}.us",
        }
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-q", "-m", message],
            check=True,
            env=env,
        )
        return subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _docs_workflow_contract(self, text: str):
        return self.audit._audit_brand_workflow_contract(  # noqa: SLF001
            ".github/workflows/docs-pages.yml",
            text,
        )

    def _workflow_safety(self, relative: str, text: str):
        return self.audit._audit_workflow_safety(relative, text)  # noqa: SLF001

    def _release_workflow_contract(self, text: str):
        return self.audit._audit_release_workflow_contract(  # noqa: SLF001
            ".github/workflows/release-channels.yml",
            text,
        )

    def _valid_docs_workflow(self) -> str:
        return """jobs:
  build:
    steps:
      - name: Audit public release
        run: python3 scripts/public-release-audit.py
      - name: Audit source brand
        run: python3 scripts/fabric-brand-audit.py --mode public
      - name: Build docs
        run: npm run --prefix website build
      - name: Audit rendered brand
        run: python3 scripts/fabric-brand-audit.py --mode public --build-dir website/build
      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@56afc609e74202658d3ffba0e8f6dda462b719fa
"""

    def _valid_release_workflow(self) -> str:
        return """name: Fabric release channels
on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
jobs:
  deploy-alpha:
    environment:
      name: alpha
    steps:
      - run: python3 scripts/ci/release_candidate.py
  deploy-beta:
    environment:
      name: beta
    steps:
      - run: python3 scripts/ci/validate_release_run.py
  validate-production-source:
    steps:
      - run: python3 scripts/ci/release_candidate.py
  promote-production:
    if: github.event_name == 'workflow_dispatch' && inputs.channel == 'production'
    needs: validate-production-source
    permissions:
      contents: write
    environment:
      name: production
    steps:
      - run: python3 scripts/ci/publish_release.py
"""

    def test_clean_public_snapshot_passes(self) -> None:
        (self.root / "website/docs/guide.md").parent.mkdir(parents=True)
        (self.root / "website/docs/guide.md").write_text(
            "# Fabric\n\nRun `fabric setup`.\n",
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
            f"# {FORMER_PRODUCT} CLI\n\nRun `{FORMER_LOWER} setup`.\n"
            "https://github.com/NousResearch/" + "fabric-agent\n",
            encoding="utf-8",
        )

        rules = {issue.rule for issue in self._issues()}
        self.assertIn("retired-identity", rules)
        self.assertIn("repository-route", rules)

    def test_rejects_standalone_labels_in_yaml_and_omitted_runtime_prefixes(self) -> None:
        locale = self.root / "locales/en.yaml"
        locale.parent.mkdir(parents=True)
        locale.write_text(f'header: "{FORMER_PRODUCT} Chat"\n', encoding="utf-8")
        runtime = self.root / "gateway/run.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            f'TOPIC_TITLE = "{FORMER_PRODUCT} Commands"\n',
            encoding="utf-8",
        )

        issues = self._issues()
        paths = {issue.path for issue in issues if issue.rule == "retired-identity"}
        self.assertIn("locales/en.yaml", paths)
        self.assertIn("gateway/run.py", paths)

    def test_rejects_any_formatted_legacy_subcommand(self) -> None:
        config = self.root / "plugins/example/plugin.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            f'help = "Run `{FORMER_LOWER} brand-new-command --safe`."\n'
            f"```sh\n{FORMER_LOWER} another-future-command\n```\n",
            encoding="utf-8",
        )

        issues = [issue for issue in self._issues() if issue.rule == "retired-identity"]
        self.assertGreaterEqual(len(issues), 2)
        self.assertEqual({issue.path for issue in issues}, {"plugins/example/plugin.toml"})

    def test_rejects_legacy_home_guidance_in_structured_metadata(self) -> None:
        config = self.root / "plugins/example/plugin.yaml"
        config.parent.mkdir(parents=True)
        config.write_text(
            f'description: "Store config under /home/user/.{FORMER_LOWER} '
            f'and set {FORMER_UPPER}_HOME."\n',
            encoding="utf-8",
        )

        self.assertIn("retired-identity", {issue.rule for issue in self._issues()})

    def test_rejects_legacy_home_literal_in_runtime_source(self) -> None:
        runtime = self.root / "plugins/platforms/example/adapter.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            f'SCRIPT_DIR = Path.home() / ".{FORMER_LOWER}" / "scripts"\n',
            encoding="utf-8",
        )

        self.assertIn("retired-identity", {issue.rule for issue in self._issues()})

    def test_rejects_legacy_outbound_identity_in_platform_source(self) -> None:
        adapter = self.root / "plugins/platforms/example/adapter.py"
        adapter.parent.mkdir(parents=True)
        adapter.write_text(
            "# public-release-audit: allow-legacy-compat -- wire fallback\n"
            f'HEADERS = {{"User-Agent": "{FORMER_PRODUCT}Agent/1.0"}}\n',
            encoding="utf-8",
        )

        self.assertIn("retired-identity", {issue.rule for issue in self._issues()})

    def test_compatibility_annotation_does_not_hide_legacy_command(self) -> None:
        runtime = self.root / "agent/compat.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            "# public-release-audit: allow-legacy-compat -- executable fallback\n"
            f"COMMAND = '{FORMER_LOWER} future-command --safe'\n",
            encoding="utf-8",
        )

        self.assertIn("retired-identity", {issue.rule for issue in self._issues()})

    def test_rejects_comment_only_shell_retired_identity(self) -> None:
        script = self.root / "scripts/launcher.sh"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            "#!/bin/sh\n"
            f"# Historical command example: `{FORMER_LOWER} setup`\n"
            f"# OLD_NAME='{FORMER_PRODUCT}'\n"
            "exec fabric gateway\n",
            encoding="utf-8",
        )

        self.assertIn("retired-identity", {issue.rule for issue in self._issues()})

    def test_rejects_legacy_shell_shebang_assignment_and_echo(self) -> None:
        script = self.root / "scripts/launcher.sh"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            f"#!/usr/bin/env {FORMER_LOWER}\n"
            f"OLD_NAME='{FORMER_PRODUCT}'\n"
            f"echo '{FORMER_PRODUCT} CLI is ready'\n",
            encoding="utf-8",
        )

        issues = [issue for issue in self._issues() if issue.rule == "retired-identity"]
        self.assertGreaterEqual(len(issues), 3)

    def test_rejects_annotated_compatibility_identifiers_in_runtime_source(self) -> None:
        runtime = self.root / "agent/compat.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            "# public-release-audit: allow-legacy-compat -- one-window home migration\n"
            f"LEGACY_HOME_NAMES = ('.fabric', '.{FORMER_LOWER}')\n"
            f"WIRE_PROTOCOL = '{FORMER_LOWER}.session.v1'\n"
            f"ENV_KEY = '{FORMER_UPPER}_HOME'\n",
            encoding="utf-8",
        )

        self.assertIn("retired-identity", {issue.rule for issue in self._issues()})

    def test_rejects_unannotated_compatibility_literal_in_source(self) -> None:
        runtime = self.root / "agent/compat.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            f"LEGACY_HOME_NAMES = ('.fabric', '.{FORMER_LOWER}')\n",
            encoding="utf-8",
        )

        self.assertIn("retired-identity", {issue.rule for issue in self._issues()})

    def test_rejects_annotated_old_install_folder_constant(self) -> None:
        runtime = self.root / "agent/compat.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            "# public-release-audit: allow-legacy-compat -- desktop upgrade fallback\n"
            f"LEGACY_INSTALL_NAMES = ('Fabric', '{FORMER_PRODUCT}')\n",
            encoding="utf-8",
        )

        self.assertIn("retired-identity", {issue.rule for issue in self._issues()})

    def test_compatibility_annotation_does_not_hide_rendered_copy(self) -> None:
        runtime = self.root / "agent/compat.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            "# public-release-audit: allow-legacy-compat -- old install fallback\n"
            f"print('{FORMER_PRODUCT}')\n",
            encoding="utf-8",
        )

        self.assertIn("retired-identity", {issue.rule for issue in self._issues()})

    def test_non_python_compatibility_annotation_only_allows_literal_tables(self) -> None:
        runtime = self.root / "apps/bootstrap/src/main.rs"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            "// public-release-audit: allow-legacy-compat -- desktop upgrade fallback\n"
            f'let legacy_candidates = ["Fabric", "{FORMER_PRODUCT}"];\n',
            encoding="utf-8",
        )

        self.assertIn("retired-identity", {issue.rule for issue in self._issues()})

        runtime.write_text(
            "// public-release-audit: allow-legacy-compat -- desktop upgrade fallback\n"
            f'println!("{FORMER_PRODUCT}");\n',
            encoding="utf-8",
        )

        self.assertIn("retired-identity", {issue.rule for issue in self._issues()})

    def test_compatibility_annotation_must_be_adjacent_and_justified(self) -> None:
        runtime = self.root / "agent/compat.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(
            "# public-release-audit: allow-legacy-compat\n"
            "UNRELATED = 'value'\n"
            f"LEGACY_INSTALL_NAMES = ('Fabric', '{FORMER_PRODUCT}')\n",
            encoding="utf-8",
        )

        self.assertIn("retired-identity", {issue.rule for issue in self._issues()})

    def test_rejects_models_attribution_and_explicit_home_migration(self) -> None:
        guide = self.root / "website/docs/models.md"
        guide.parent.mkdir(parents=True)
        guide.write_text(
            f"{FORMER_PRODUCT} 3, {FORMER_PRODUCT}-4-70B, and "
            f"{FORMER_PRODUCT}Bench are model or benchmark names.\n"
            f"Migrate the legacy ~/.{FORMER_LOWER} directory to ~/.fabric.\n",
            encoding="utf-8",
        )

        self.assertIn("retired-identity", {issue.rule for issue in self._issues()})

    def test_model_reference_does_not_hide_nearby_legacy_product_label(self) -> None:
        guide = self.root / "website/docs/models.md"
        guide.parent.mkdir(parents=True)
        guide.write_text(
            f"# {FORMER_PRODUCT} CLI\n\n{FORMER_PRODUCT} 3 is an optional model.\n",
            encoding="utf-8",
        )

        self.assertIn("retired-identity", {issue.rule for issue in self._issues()})

    def test_rejects_original_repository_links_as_story_provenance(self) -> None:
        stories = self.root / "website/src/data/userStories.json"
        stories.parent.mkdir(parents=True)
        stories.write_text(
            f'{{"issue":"https://github.com/NousResearch/{FORMER_LOWER}-agent/issues/1",'
            f'"pull":"https://github.com/NousResearch/{FORMER_LOWER}-agent/pull/42"}}\n',
            encoding="utf-8",
        )

        rules = {issue.rule for issue in self._issues()}
        self.assertIn("retired-identity", rules)
        self.assertIn("repository-route", rules)

    def test_rejects_non_provenance_upstream_routes_in_story_data(self) -> None:
        stories = self.root / "website/src/data/userStories.json"
        stories.parent.mkdir(parents=True)
        rejected_routes = (
            f"https://github.com/NousResearch/{FORMER_LOWER}-agent",
            f"https://github.com/NousResearch/{FORMER_LOWER}-agent/tree/main/docs",
            f"https://github.com/NousResearch/{FORMER_LOWER}-agent/releases/latest",
            f"https://github.com/NousResearch/{FORMER_LOWER}-agent/issues/new",
            f"https://github.com/NousResearch/{FORMER_LOWER}-agent/issues/12/comments",
            "https://example.invalid/retired-product/issues/12",
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

    def test_main_retains_reachable_commit_metadata_gate(self) -> None:
        self._init_git()
        self._commit_with_private_identity("Initial snapshot", "one")

        result = self.audit.main(["--root", str(self.root)])

        self.assertEqual(result, 1)

    def test_history_gate_ignores_transient_pull_request_merge_refs(self) -> None:
        self._init_git()
        (self.root / "history-main.txt").write_text("public main\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        canonical_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "PrimeOdin",
            "GIT_AUTHOR_EMAIL": "11676741+ObliviousOdin@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "PrimeOdin",
            "GIT_COMMITTER_EMAIL": "11676741+ObliviousOdin@users.noreply.github.com",
        }
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-q", "-m", "Clean public history"],
            check=True,
            env=canonical_env,
        )
        base_ref = subprocess.run(
            ["git", "-C", str(self.root), "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "-C", str(self.root), "checkout", "-q", "-b", "pull-test"],
            check=True,
        )
        transient_merge = self._commit_with_private_identity(
            "Synthetic pull request merge",
            "transient",
        )
        for ref in ("refs/pull/123/merge", "refs/remotes/pull/123/merge"):
            subprocess.run(
                ["git", "-C", str(self.root), "update-ref", ref, transient_merge],
                check=True,
            )
        subprocess.run(["git", "-C", str(self.root), "checkout", "-q", base_ref], check=True)
        subprocess.run(["git", "-C", str(self.root), "branch", "-D", "pull-test"], check=True)

        self.assertEqual(self.audit.audit_git_history(self.root), [])

    def test_history_gate_does_not_apply_tracked_identity_rule_to_messages(self) -> None:
        self._init_git()
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Example",
            "GIT_AUTHOR_EMAIL": "example@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "Example",
            "GIT_COMMITTER_EMAIL": "example@users.noreply.github.com",
        }
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "commit",
                "-q",
                "-m",
                f"Import {FORMER_PRODUCT} history",
            ],
            check=True,
            env=env,
        )

        self.assertEqual(self.audit.audit_git_history(self.root), [])

    def test_history_baseline_matches_only_the_exact_rule_pair(self) -> None:
        self._init_git()
        commit = self._commit_with_private_identity("Initial snapshot", "one")
        self.audit.LEGACY_GIT_HISTORY_BASELINE = frozenset(
            {(commit, "personal-email")}
        )

        issues = self.audit.audit_git_history(self.root)
        messages = {issue.message for issue in issues}

        self.assertNotIn(
            "reachable commit metadata violates personal-email",
            messages,
        )
        self.assertIn(
            "reachable commit metadata violates private-brand",
            messages,
        )

    def test_history_baseline_requires_the_full_commit_sha(self) -> None:
        self._init_git()
        commit = self._commit_with_private_identity("Initial snapshot", "one")
        self.audit.LEGACY_GIT_HISTORY_BASELINE = frozenset(
            {(commit[:12], "personal-email")}
        )

        issues = self.audit.audit_git_history(self.root)

        self.assertTrue(
            any(
                issue.path == f"git:{commit[:12]}"
                and issue.message.endswith("violates personal-email")
                for issue in issues
            ),
            issues,
        )

    def test_history_baseline_does_not_cover_a_new_commit(self) -> None:
        self._init_git()
        baseline_commit = self._commit_with_private_identity(
            "Initial snapshot",
            "one",
        )
        self.audit.LEGACY_GIT_HISTORY_BASELINE = frozenset(
            {
                (baseline_commit, "personal-email"),
                (baseline_commit, "private-brand"),
            }
        )
        new_commit = self._commit_with_private_identity("Follow-up", "two")

        issues = [
            issue
            for issue in self.audit.audit_git_history(self.root)
            if issue.rule == "git-history"
        ]

        self.assertEqual({issue.path for issue in issues}, {f"git:{new_commit[:12]}"})
        self.assertEqual(
            {issue.message.rsplit(" ", 1)[-1] for issue in issues},
            {"personal-email", "private-brand"},
        )

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

    def test_release_publication_is_confined_to_production_gate(self) -> None:
        workflow = self._valid_release_workflow()

        self.assertEqual(self._release_workflow_contract(workflow), [])
        self.assertEqual(
            self._workflow_safety(
                ".github/workflows/release-channels.yml",
                workflow,
            ),
            [],
        )

    def test_release_workflow_rejects_unguarded_publish_or_write(self) -> None:
        workflow = self._valid_release_workflow()
        workflow = workflow.replace(
            "if: github.event_name == 'workflow_dispatch' && inputs.channel == 'production'",
            "if: github.event_name == 'push'",
        )
        workflow += "\njobs-write:\n  permissions:\n    contents: write\n"
        issues = self._release_workflow_contract(workflow)

        self.assertTrue(issues)
        self.assertTrue(
            any("required gate" in issue.message for issue in issues)
        )
        self.assertTrue(
            any("confined" in issue.message for issue in issues)
        )

    def test_pages_workflow_cannot_write_repository_contents(self) -> None:
        workflow = self.root / ".github/workflows/docs-pages.yml"
        workflow.write_text(
            workflow.read_text(encoding="utf-8") + "\ncontents: write\n",
            encoding="utf-8",
        )

        self.assertIn("workflow-surface", {issue.rule for issue in self._issues()})

    def test_pages_brand_audits_must_be_active_and_ordered(self) -> None:
        workflow = self.root / ".github/workflows/docs-pages.yml"
        text = workflow.read_text(encoding="utf-8")
        workflow.write_text(
            text.replace(
                "run: python3 scripts/fabric-brand-audit.py --mode public",
                "# run: python3 scripts/fabric-brand-audit.py --mode public",
                1,
            ),
            encoding="utf-8",
        )

        self.assertIn("workflow-brand-gate", {issue.rule for issue in self._issues()})

    def test_public_ci_tracked_identity_audit_must_be_active(self) -> None:
        workflow = self.root / ".github/workflows/public-ci.yml"
        text = workflow.read_text(encoding="utf-8")
        workflow.write_text(
            text.replace(
                "run: python3 scripts/fabric_identity_audit.py",
                "# run: python3 scripts/fabric_identity_audit.py",
            ),
            encoding="utf-8",
        )

        self.assertIn("workflow-brand-gate", {issue.rule for issue in self._issues()})

    def test_pages_rendered_brand_audit_must_precede_upload(self) -> None:
        workflow = self.root / ".github/workflows/docs-pages.yml"
        text = workflow.read_text(encoding="utf-8")
        rendered = "run: python3 scripts/fabric-brand-audit.py --mode public --build-dir website/build"
        upload = "actions/upload-pages-artifact@56afc609e74202658d3ffba0e8f6dda462b719fa"
        text = text.replace(rendered, "__RENDERED__").replace(upload, rendered)
        workflow.write_text(text.replace("__RENDERED__", upload), encoding="utf-8")

        self.assertIn("workflow-brand-gate", {issue.rule for issue in self._issues()})

    def test_pages_upload_must_be_an_active_uses_directive(self) -> None:
        workflow = self.root / ".github/workflows/docs-pages.yml"
        text = workflow.read_text(encoding="utf-8")
        workflow.write_text(
            text.replace(
                "uses: actions/upload-pages-artifact@",
                "# uses: actions/upload-pages-artifact@",
            ),
            encoding="utf-8",
        )

        issues = self._issues()

        self.assertTrue(
            any(
                issue.rule == "workflow-brand-gate"
                and "active Pages artifact upload" in issue.message
                for issue in issues
            )
        )

    def test_public_history_workflows_must_fetch_full_history(self) -> None:
        for relative in (
            ".github/workflows/public-ci.yml",
            ".github/workflows/docs-pages.yml",
        ):
            with self.subTest(relative=relative):
                ref = (
                    "          ref: ${{ github.event.pull_request.head.sha || github.sha }}\n"
                    if relative.endswith("public-ci.yml")
                    else ""
                )
                text = (
                    "steps:\n"
                    "  - uses: actions/checkout@"
                    "11bd71901bbe5b1630ceea73d27597364c9af683\n"
                    "    with:\n"
                    "      fetch-depth: 1\n"
                    "      persist-credentials: false\n"
                    + ref
                )

                issues = self._workflow_safety(relative, text)

                self.assertTrue(
                    any(
                        issue.rule == "workflow-surface"
                        and "fetch-depth: 0" in issue.message
                        for issue in issues
                    ),
                    issues,
                )

    def test_public_ci_must_audit_pr_head_not_synthetic_merge_ref(self) -> None:
        text = (
            "steps:\n"
            "  - uses: actions/checkout@"
            "11bd71901bbe5b1630ceea73d27597364c9af683\n"
            "    with:\n"
            "      fetch-depth: 0\n"
            "      persist-credentials: false\n"
            "      ref: ${{ github.sha }}\n"
        )

        issues = self._workflow_safety(".github/workflows/public-ci.yml", text)

        self.assertTrue(
            any(
                issue.rule == "workflow-surface"
                and "actual head SHA" in issue.message
                for issue in issues
            ),
            issues,
        )

    def test_required_pages_steps_may_not_be_conditional(self) -> None:
        cases = (
            (
                "run: python3 scripts/public-release-audit.py",
                "${{ 1 == 2 }}",
            ),
            (
                "run: python3 scripts/fabric-brand-audit.py --mode public",
                "${{ false }}",
            ),
            ("run: npm run --prefix website build", "0"),
            (
                "run: python3 scripts/fabric-brand-audit.py --mode public "
                "--build-dir website/build",
                "${{ 0 }}",
            ),
            (
                "uses: actions/upload-pages-artifact@"
                "56afc609e74202658d3ffba0e8f6dda462b719fa",
                "null",
            ),
        )
        for directive, condition in cases:
            with self.subTest(directive=directive, condition=condition):
                text = self._valid_docs_workflow().replace(
                    directive,
                    f"{directive}\n        if: {condition}",
                )

                issues = self._docs_workflow_contract(text)

                self.assertTrue(
                    any("must be unconditional" in issue.message for issue in issues),
                    issues,
                )

    def test_brand_audits_may_not_continue_on_error(self) -> None:
        workflow = self.root / ".github/workflows/public-ci.yml"
        workflow.write_text(
            workflow.read_text(encoding="utf-8")
            + "\ncontinue-on-error: true\n",
            encoding="utf-8",
        )

        self.assertIn("workflow-brand-gate", {issue.rule for issue in self._issues()})

    def test_rejects_private_planning_directories(self) -> None:
        plan = self.root / f".{FORMER_LOWER}/plans/internal.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("Internal plan\n", encoding="utf-8")

        self.assertIn("retired-identity", {issue.rule for issue in self._issues()})


if __name__ == "__main__":
    unittest.main()
