from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POST_CLONE = ROOT / "apps" / "mobile" / "ios" / "ci_scripts" / "ci_post_clone.sh"
PROJECT_SPEC = ROOT / "apps" / "mobile" / "ios" / "project.yml"
BOOTSTRAP_PROJECT = (
    ROOT / "apps" / "mobile" / "ios" / "FabricMobile.xcodeproj" / "project.pbxproj"
)
BOOTSTRAP_SCHEME = (
    ROOT
    / "apps"
    / "mobile"
    / "ios"
    / "FabricMobile.xcodeproj"
    / "xcshareddata"
    / "xcschemes"
    / "Fabric.xcscheme"
)
BOOTSTRAP_INFO = ROOT / "apps" / "mobile" / "ios" / "Fabric" / "Info.plist"


class IOSProjectGenerationTests(unittest.TestCase):
    def test_committed_xcode_cloud_bootstrap_is_generic_and_complete(self) -> None:
        project = BOOTSTRAP_PROJECT.read_text(encoding="utf-8")
        scheme = BOOTSTRAP_SCHEME.read_text(encoding="utf-8")
        info = BOOTSTRAP_INFO.read_text(encoding="utf-8")

        self.assertIn(
            "PRODUCT_BUNDLE_IDENTIFIER = io.github.obliviousodin.fabric.mobile;",
            project,
        )
        self.assertIn("CURRENT_PROJECT_VERSION = 1;", project)
        self.assertIn('BlueprintName = "Fabric"', scheme)
        self.assertIn("io.github.obliviousodin.fabric.mobile.pairing", info)
        self.assertIn("<key>FabricSourceRevision</key>", info)
        self.assertIn("<string>development</string>", info)
        self.assertNotIn("com.example.fabric.mobile", project)
        self.assertNotIn("com.example.fabric.mobile", info)
        self.assertEqual(POST_CLONE.parent.parent, PROJECT_SPEC.parent)
        self.assertTrue(os.access(POST_CLONE, os.X_OK))

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.checkout = Path(self.temp_dir.name)
        self.ios_dir = self.checkout / "apps" / "mobile" / "ios"
        self.ios_dir.mkdir(parents=True)
        self.project_spec = self.ios_dir / "project.yml"
        shutil.copy2(PROJECT_SPEC, self.project_spec)
        self.original_spec = self.project_spec.read_bytes()

        subprocess.run(
            ["git", "init"],
            cwd=self.checkout,
            check=True,
            capture_output=True,
            text=True,
        )
        self.source_revision = self._commit_spec("add iOS project manifest")

        self.capture = self.checkout / "captured-project.yml"
        self.fake_xcodegen = self.checkout / "fake-xcodegen"
        self.fake_xcodegen.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import os
                import shutil
                import sys
                from pathlib import Path

                arguments = sys.argv[1:]
                spec = Path(arguments[arguments.index("--spec") + 1])
                shutil.copy2(spec, Path(os.environ["FABRIC_TEST_CAPTURE_SPEC"]))
                """
            ),
            encoding="utf-8",
        )
        self.fake_xcodegen.chmod(0o755)

    def _commit_spec(self, message: str) -> str:
        relative_spec = self.project_spec.relative_to(self.checkout)
        subprocess.run(
            ["git", "add", str(relative_spec)],
            cwd=self.checkout,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Fabric Tests",
                "-c",
                "user.email=fabric-tests@users.noreply.github.com",
                "commit",
                "-m",
                message,
            ],
            cwd=self.checkout,
            check=True,
            capture_output=True,
            text=True,
        )
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.checkout,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def run_post_clone(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "CI_PRIMARY_REPOSITORY_PATH": str(self.checkout),
                "FABRIC_XCODEGEN_BIN": str(self.fake_xcodegen),
                "FABRIC_TEST_CAPTURE_SPEC": str(self.capture),
            }
        )
        environment.pop("CI_BUILD_NUMBER", None)
        environment.pop("FABRIC_IOS_BUILD_NUMBER", None)
        environment.pop("FABRIC_IOS_BUNDLE_ID", None)
        environment.update(overrides)
        return subprocess.run(
            [str(POST_CLONE)],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def assert_source_manifest_unchanged(self) -> None:
        self.assertEqual(self.project_spec.read_bytes(), self.original_spec)

    def test_default_generation_uses_source_manifest_without_mutating_it(self) -> None:
        result = self.run_post_clone()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.capture.read_bytes(), self.original_spec)
        self.assert_source_manifest_unchanged()

    def test_non_executable_configured_generator_fails_closed(self) -> None:
        self.fake_xcodegen.chmod(0o644)

        result = self.run_post_clone()

        self.assertEqual(result.returncode, 2)
        self.assertIn("FABRIC_XCODEGEN_BIN is not executable", result.stderr)
        self.assertFalse(self.capture.exists())
        self.assert_source_manifest_unchanged()

    def test_release_overrides_are_applied_only_to_temporary_spec(self) -> None:
        result = self.run_post_clone(
            FABRIC_IOS_BUNDLE_ID="com.example.fabric.mobile",
            FABRIC_IOS_BUILD_NUMBER="42",
            CI_BUILD_NUMBER="99",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = self.capture.read_text(encoding="utf-8")
        self.assertIn(
            "PRODUCT_BUNDLE_IDENTIFIER: com.example.fabric.mobile\n", rendered
        )
        self.assertIn(
            "CFBundleURLName: com.example.fabric.mobile.pairing\n", rendered
        )
        self.assertIn(
            "PRODUCT_BUNDLE_IDENTIFIER: com.example.fabric.mobile.tests\n", rendered
        )
        self.assertIn('CURRENT_PROJECT_VERSION: "42"', rendered)
        self.assertIn(f"FabricSourceRevision: {self.source_revision}", rendered)
        self.assertNotIn("FabricSourceRevision: development", rendered)
        self.assertNotIn("io.github.obliviousodin.fabric.mobile", rendered)
        self.assert_source_manifest_unchanged()

    def test_release_requires_a_clean_tracked_checkout(self) -> None:
        self.project_spec.write_text(
            self.project_spec.read_text(encoding="utf-8") + "\n# tracked dirt\n",
            encoding="utf-8",
        )
        self.original_spec = self.project_spec.read_bytes()

        result = self.run_post_clone(
            FABRIC_IOS_BUNDLE_ID="com.example.fabric.mobile",
            FABRIC_IOS_BUILD_NUMBER="42",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("requires a clean tracked checkout", result.stderr)
        self.assertFalse(self.capture.exists())
        self.assert_source_manifest_unchanged()

        subprocess.run(
            ["git", "add", str(self.project_spec.relative_to(self.checkout))],
            cwd=self.checkout,
            check=True,
            capture_output=True,
            text=True,
        )
        result = self.run_post_clone(
            FABRIC_IOS_BUNDLE_ID="com.example.fabric.mobile",
            FABRIC_IOS_BUILD_NUMBER="42",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("requires a clean tracked checkout", result.stderr)
        self.assertFalse(self.capture.exists())
        self.assert_source_manifest_unchanged()

    def test_xcode_cloud_build_number_is_used_when_no_explicit_number_exists(self) -> None:
        result = self.run_post_clone(
            FABRIC_IOS_BUNDLE_ID="com.example.fabric.mobile",
            CI_BUILD_NUMBER="314",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = self.capture.read_text(encoding="utf-8")
        self.assertIn('CURRENT_PROJECT_VERSION: "314"', rendered)
        self.assert_source_manifest_unchanged()

    def test_release_overrides_require_bundle_and_build_number_together(self) -> None:
        incomplete_overrides = (
            {"FABRIC_IOS_BUNDLE_ID": "com.example.fabric.mobile"},
            {"FABRIC_IOS_BUILD_NUMBER": "42"},
            {"CI_BUILD_NUMBER": "42"},
        )
        for overrides in incomplete_overrides:
            with self.subTest(overrides=overrides):
                self.capture.unlink(missing_ok=True)
                result = self.run_post_clone(**overrides)
                self.assertEqual(result.returncode, 2)
                self.assertIn("requires", result.stderr)
                self.assertFalse(self.capture.exists())
                self.assert_source_manifest_unchanged()

    def test_invalid_bundle_identifier_fails_closed(self) -> None:
        result = self.run_post_clone(FABRIC_IOS_BUNDLE_ID="not/a/bundle")

        self.assertEqual(result.returncode, 2)
        self.assertIn("reverse-DNS identifier", result.stderr)
        self.assertFalse(self.capture.exists())
        self.assert_source_manifest_unchanged()

    def test_invalid_build_numbers_fail_closed(self) -> None:
        for build_number in ("0", "-1", "two"):
            with self.subTest(build_number=build_number):
                self.capture.unlink(missing_ok=True)
                result = self.run_post_clone(
                    FABRIC_IOS_BUILD_NUMBER=build_number
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("must be", result.stderr)
                self.assertFalse(self.capture.exists())
                self.assert_source_manifest_unchanged()

    def test_release_fails_closed_when_source_bundle_marker_drifts(self) -> None:
        changed_spec = self.project_spec.read_text(encoding="utf-8").replace(
            "io.github.obliviousodin.fabric.mobile",
            "com.changed.fabric.mobile",
        )
        self.project_spec.write_text(changed_spec, encoding="utf-8")
        self.original_spec = self.project_spec.read_bytes()
        self.source_revision = self._commit_spec("change bundle marker")

        result = self.run_post_clone(
            FABRIC_IOS_BUNDLE_ID="com.example.fabric.mobile",
            FABRIC_IOS_BUILD_NUMBER="42",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("source iOS bundle marker changed", result.stderr)
        self.assertFalse(self.capture.exists())
        self.assert_source_manifest_unchanged()

    def test_release_fails_closed_when_source_build_marker_drifts(self) -> None:
        changed_spec = self.project_spec.read_text(encoding="utf-8").replace(
            'CURRENT_PROJECT_VERSION: "1"',
            "CURRENT_PROJECT_VERSION: development",
        )
        self.project_spec.write_text(changed_spec, encoding="utf-8")
        self.original_spec = self.project_spec.read_bytes()
        self.source_revision = self._commit_spec("change build marker")

        result = self.run_post_clone(
            FABRIC_IOS_BUNDLE_ID="com.example.fabric.mobile",
            FABRIC_IOS_BUILD_NUMBER="42",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("source iOS build marker changed", result.stderr)
        self.assertFalse(self.capture.exists())
        self.assert_source_manifest_unchanged()

    def test_release_fails_closed_when_source_revision_marker_drifts(self) -> None:
        changed_spec = self.project_spec.read_text(encoding="utf-8").replace(
            "FabricSourceRevision: development",
            "FabricSourceRevision: unavailable",
        )
        self.project_spec.write_text(changed_spec, encoding="utf-8")
        self.original_spec = self.project_spec.read_bytes()
        self.source_revision = self._commit_spec("change source revision marker")

        result = self.run_post_clone(
            FABRIC_IOS_BUNDLE_ID="com.example.fabric.mobile",
            FABRIC_IOS_BUILD_NUMBER="42",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("source iOS revision marker changed", result.stderr)
        self.assertFalse(self.capture.exists())
        self.assert_source_manifest_unchanged()


if __name__ == "__main__":
    unittest.main()
