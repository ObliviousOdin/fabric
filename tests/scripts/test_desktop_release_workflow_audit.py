"""Contract audit for the desktop release workflow and its dispatch wiring.

Named ``test_*audit.py`` so ``public-ci.yml``'s
``python3 -m unittest discover -s tests/scripts -p 'test_*audit.py'`` runs it on
every PR. It pins the ordering and trigger guarantees that the audit's
substring-only ``CANONICAL_REQUIREMENTS`` cannot express: resolve -> collect ->
verify -> attach, and dispatch strictly after the Python release is published.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DESKTOP_RELEASE = ROOT / ".github/workflows/desktop-release.yml"
RELEASE_CHANNELS = ROOT / ".github/workflows/release-channels.yml"


class DesktopReleaseWorkflowAudit(unittest.TestCase):
    def setUp(self) -> None:
        self.desktop = DESKTOP_RELEASE.read_text(encoding="utf-8")
        self.channels = RELEASE_CHANNELS.read_text(encoding="utf-8")

    def test_only_a_scoped_push_registers_the_manual_workflow(self) -> None:
        # A workflow-file-only push registers the manual trigger on GitHub; all
        # packaging jobs remain gated to workflow_dispatch below.
        on_block = self.desktop[
            self.desktop.index("\non:") : self.desktop.index("\npermissions:")
        ]
        self.assertIn("workflow_dispatch:", on_block)
        self.assertIn("push:\n    branches: [main]", on_block)
        self.assertIn("- .github/workflows/desktop-release.yml", on_block)
        for trigger in ("pull_request:", "release:", "schedule:"):
            self.assertNotIn(trigger, on_block)
        self.assertIn("if: github.event_name == 'push'", self.desktop)
        self.assertIn("if: github.event_name == 'workflow_dispatch'", self.desktop)

    def test_workflow_is_valid_yaml(self) -> None:
        with DESKTOP_RELEASE.open(encoding="utf-8") as handle:
            self.assertIsInstance(yaml.safe_load(handle), dict)

    def test_serial_per_tag_concurrency(self) -> None:
        self.assertIn(
            "group: desktop-release-${{ inputs.release_tag }}", self.desktop
        )
        self.assertIn("cancel-in-progress: false", self.desktop)

    def test_pipeline_runs_resolve_then_collect_then_verify_then_attach(self) -> None:
        resolve = self.desktop.index("desktop_release_assets.py resolve")
        collect = self.desktop.index("desktop_release_assets.py collect")
        verify = self.desktop.index("desktop_release_assets.py verify")
        attach = self.desktop.index("desktop_release_assets.py attach")

        self.assertLess(resolve, collect)
        self.assertLess(collect, verify)
        self.assertLess(verify, attach)

    def test_resolve_binds_tag_releases_and_limits_backfills_to_main(self) -> None:
        self.assertIn("--github-sha \"${{ github.sha }}\"", self.desktop)
        self.assertIn("--github-ref \"${{ github.ref }}\"", self.desktop)
        self.assertIn("backfill_from_main:", self.desktop)
        self.assertIn("args+=(--allow-main-backfill)", self.desktop)
        self.assertIn("git show \"${RELEASE_TAG}:apps/desktop/package.json\"", self.desktop)

    def test_only_the_attach_job_can_write_contents(self) -> None:
        # Exactly one contents: write in the file, belonging to the attach job.
        self.assertEqual(self.desktop.count("contents: write"), 1)
        attach_at = self.desktop.index("attach-assets:")
        write_at = self.desktop.index("contents: write")
        self.assertLess(attach_at, write_at)

    def test_signing_secrets_are_step_scoped_not_job_level(self) -> None:
        # The secrets appear only under the packaging step's env, after npm ci.
        npm_ci = self.desktop.index("run: npm ci")
        first_secret = self.desktop.index("secrets.CSC_LINK")
        self.assertLess(npm_ci, first_secret)

    def test_promotion_dispatches_desktop_release_after_publishing(self) -> None:
        publish = self.channels.index("python3 scripts/ci/publish_release.py")
        dispatch = self.channels.index("gh workflow run desktop-release.yml")
        self.assertLess(publish, dispatch)
        self.assertIn("--ref \"${{ inputs.release_tag }}\"", self.channels)

    def test_prepublish_desktop_version_gate_precedes_publish(self) -> None:
        gate = self.channels.index("desktop_release_assets.py preflight")
        publish = self.channels.index("python3 scripts/ci/publish_release.py")
        self.assertLess(gate, publish)

    def test_release_asset_api_paths_are_safe_for_windows_git_bash(self) -> None:
        asset_path = "repos/${{ github.repository }}/releases/assets/${asset_id}"
        tag_path = "repos/${{ github.repository }}/releases/tags/${{ inputs.release_tag }}"
        self.assertIn(asset_path, self.desktop)
        self.assertIn(tag_path, self.desktop)
        self.assertNotIn(f'/{asset_path}', self.desktop)
        self.assertNotIn(f'/{tag_path}', self.desktop)


if __name__ == "__main__":
    unittest.main()
