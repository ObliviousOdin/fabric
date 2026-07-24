from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POST_CLONE = ROOT / "apps" / "mobile" / "ios" / "ci_scripts" / "ci_post_clone.sh"
PROJECT_SPEC = ROOT / "apps" / "mobile" / "ios" / "project.yml"
LINK_PACKAGE_SPEC = ROOT / "apps" / "mobile" / "ios" / "project.fabric-link.yml"
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
PRIVACY_MANIFEST = (
    ROOT / "apps" / "mobile" / "ios" / "Fabric" / "PrivacyInfo.xcprivacy"
)


class IOSProjectGenerationTests(unittest.TestCase):
    def test_committed_privacy_manifest_covers_required_app_apis(self) -> None:
        with PRIVACY_MANIFEST.open("rb") as handle:
            manifest = plistlib.load(handle)

        declared = {
            entry["NSPrivacyAccessedAPIType"]: set(
                entry["NSPrivacyAccessedAPITypeReasons"]
            )
            for entry in manifest["NSPrivacyAccessedAPITypes"]
        }
        required = {
            "NSPrivacyAccessedAPICategoryUserDefaults": {"CA92.1"},
            "NSPrivacyAccessedAPICategoryFileTimestamp": {"C617.1"},
        }
        for category, reasons in required.items():
            with self.subTest(category=category):
                self.assertTrue(reasons.issubset(declared.get(category, set())))

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
        self.assertNotIn("XCLocalSwiftPackageReference", project)
        self.assertNotIn("FabricLinkCore", project)
        self.assertNotIn("com.example.fabric.mobile", project)
        self.assertNotIn("com.example.fabric.mobile", info)
        self.assertEqual(POST_CLONE.parent.parent, PROJECT_SPEC.parent)
        self.assertTrue(os.access(POST_CLONE, os.X_OK))

    def test_fabric_link_package_is_an_explicit_post_clone_overlay(self) -> None:
        bootstrap_spec = PROJECT_SPEC.read_text(encoding="utf-8")
        link_spec = LINK_PACKAGE_SPEC.read_text(encoding="utf-8")

        self.assertIn("path: ${XCODEGEN_LINK_OVERLAY_PATH}", bootstrap_spec)
        self.assertIn("enable: ${XCODEGEN_INCLUDE_LINK_CORE}", bootstrap_spec)
        self.assertNotIn("FabricLinkCore:", bootstrap_spec)
        self.assertIn("FabricLinkCore:", link_spec)
        self.assertIn("path: ${XCODEGEN_LINK_CORE_PACKAGE_PATH}", link_spec)
        self.assertIn("- package: FabricLinkCore", link_spec)

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.checkout = Path(self.temp_dir.name)
        self.ios_dir = self.checkout / "apps" / "mobile" / "ios"
        self.ios_dir.mkdir(parents=True)
        self.project_spec = self.ios_dir / "project.yml"
        shutil.copy2(PROJECT_SPEC, self.project_spec)
        self.link_package_spec = self.ios_dir / "project.fabric-link.yml"
        shutil.copy2(LINK_PACKAGE_SPEC, self.link_package_spec)
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
        self.link_include_capture = self.checkout / "captured-link-include"
        self.link_overlay_capture = self.checkout / "captured-link-overlay"
        self.link_package_path_capture = self.checkout / "captured-link-package-path"
        self.link_build_capture = self.checkout / "captured-link-build"
        self.rust_paths_capture = self.checkout / "captured-rust-paths"
        self.rustup_args_capture = self.checkout / "captured-rustup-args"
        self.swift_args_capture = self.checkout / "captured-swift-args"
        self.fake_tools = self.checkout / "fake-tools"
        self.fake_tools.mkdir()
        fake_curl = self.fake_tools / "curl"
        fake_curl.write_text(
            textwrap.dedent(
                """\
                #!/bin/sh
                set -eu
                output=""
                while [ "$#" -gt 0 ]; do
                  case "$1" in
                    --output)
                      output="$2"
                      shift 2
                      ;;
                    *)
                      shift
                      ;;
                  esac
                done
                test -n "$output"
                printf '#!/bin/sh\\nprintf "%%s\\\\n" "$@" > "$FABRIC_TEST_CAPTURE_RUSTUP_ARGS"\\n' \
                  > "$output"
                """
            ),
            encoding="utf-8",
        )
        fake_curl.chmod(0o755)
        fake_shasum = self.fake_tools / "shasum"
        fake_shasum.write_text(
            "#!/bin/sh\ncat >/dev/null\n",
            encoding="utf-8",
        )
        fake_shasum.chmod(0o755)
        fake_swift = self.fake_tools / "swift"
        fake_swift.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$FABRIC_TEST_CAPTURE_SWIFT_ARGS\"\nexit \"${FABRIC_TEST_SWIFT_EXIT:-0}\"\n",
            encoding="utf-8",
        )
        fake_swift.chmod(0o755)

        link_build = (
            self.checkout
            / "apps"
            / "fabric-link-core"
            / "apple"
            / "build-xcframework.sh"
        )
        link_build.parent.mkdir(parents=True)
        link_build.write_text(
            textwrap.dedent(
                """\
                #!/bin/sh
                set -eu
                : "${FABRIC_TEST_CAPTURE_LINK_BUILD:?}"
                : "${FABRIC_TEST_CAPTURE_RUST_PATHS:?}"
                printf 'built\\n' > "$FABRIC_TEST_CAPTURE_LINK_BUILD"
                printf '%s\\n%s\\n' "$CARGO_HOME" "$RUSTUP_HOME" \
                  > "$FABRIC_TEST_CAPTURE_RUST_PATHS"
                """
            ),
            encoding="utf-8",
        )
        link_build.chmod(0o755)

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
                Path(os.environ["FABRIC_TEST_CAPTURE_LINK_INCLUDE"]).write_text(
                    os.environ.get("XCODEGEN_INCLUDE_LINK_CORE", ""),
                    encoding="utf-8",
                )
                Path(os.environ["FABRIC_TEST_CAPTURE_LINK_OVERLAY"]).write_text(
                    os.environ.get("XCODEGEN_LINK_OVERLAY_PATH", ""),
                    encoding="utf-8",
                )
                Path(os.environ["FABRIC_TEST_CAPTURE_LINK_PACKAGE_PATH"]).write_text(
                    os.environ.get("XCODEGEN_LINK_CORE_PACKAGE_PATH", ""),
                    encoding="utf-8",
                )
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
                "FABRIC_TEST_CAPTURE_LINK_INCLUDE": str(self.link_include_capture),
                "FABRIC_TEST_CAPTURE_LINK_OVERLAY": str(self.link_overlay_capture),
                "FABRIC_TEST_CAPTURE_LINK_PACKAGE_PATH": str(
                    self.link_package_path_capture
                ),
                "FABRIC_TEST_CAPTURE_LINK_BUILD": str(self.link_build_capture),
                "FABRIC_TEST_CAPTURE_RUST_PATHS": str(self.rust_paths_capture),
                "FABRIC_TEST_CAPTURE_RUSTUP_ARGS": str(self.rustup_args_capture),
                "FABRIC_TEST_CAPTURE_SWIFT_ARGS": str(self.swift_args_capture),
                "PATH": f"{self.fake_tools}{os.pathsep}{environment['PATH']}",
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
        self.assertEqual(
            self.link_build_capture.read_text(encoding="utf-8"),
            "built\n",
        )
        self.assertEqual(
            self.link_include_capture.read_text(encoding="utf-8"), "true"
        )
        self.assertEqual(
            self.link_overlay_capture.read_text(encoding="utf-8"),
            str(self.link_package_spec),
        )
        self.assertEqual(
            self.link_package_path_capture.read_text(encoding="utf-8"),
            str(self.checkout / "apps" / "fabric-link-core" / "apple"),
        )
        self.assertEqual(
            self.swift_args_capture.read_text(encoding="utf-8").splitlines(),
            [
                "package",
                "--package-path",
                str(self.checkout / "apps" / "fabric-link-core" / "apple"),
                "describe",
            ],
        )
        self.assert_source_manifest_unchanged()

    def test_rustup_cannot_modify_the_user_shell_profile(self) -> None:
        result = self.run_post_clone()

        self.assertEqual(result.returncode, 0, result.stderr)
        rustup_args = self.rustup_args_capture.read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertIn("--no-modify-path", rustup_args)
        self.assert_source_manifest_unchanged()

    def test_unresolvable_staged_link_package_fails_before_generation(self) -> None:
        result = self.run_post_clone(FABRIC_TEST_SWIFT_EXIT="1")

        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "Fabric Link XCFramework is not a resolvable Swift package after staging",
            result.stderr,
        )
        self.assertFalse(self.capture.exists())
        self.assertFalse(self.link_include_capture.exists())
        self.assert_source_manifest_unchanged()

    def test_rust_bootstrap_uses_physical_paths_beneath_a_symlinked_tmpdir(
        self,
    ) -> None:
        physical_tmp = self.checkout / "physical-tmp"
        physical_tmp.mkdir()
        linked_tmp = self.checkout / "linked-tmp"
        linked_tmp.symlink_to(physical_tmp, target_is_directory=True)
        fake_mktemp = self.fake_tools / "mktemp"
        fake_mktemp.write_text(
            textwrap.dedent(
                """\
                #!/bin/sh
                set -eu
                : "${FABRIC_TEST_MKTEMP_DIR:?}"
                mkdir "$FABRIC_TEST_MKTEMP_DIR"
                printf '%s\\n' "$FABRIC_TEST_MKTEMP_DIR"
                """
            ),
            encoding="utf-8",
        )
        fake_mktemp.chmod(0o755)

        result = self.run_post_clone(
            FABRIC_TEST_MKTEMP_DIR=str(linked_tmp / "work")
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        cargo_home, rustup_home = self.rust_paths_capture.read_text(
            encoding="utf-8"
        ).splitlines()
        physical_prefix = f"{physical_tmp.resolve()}{os.sep}"
        self.assertTrue(cargo_home.startswith(physical_prefix), cargo_home)
        self.assertTrue(rustup_home.startswith(physical_prefix), rustup_home)
        self.assertNotIn(str(linked_tmp), cargo_home)
        self.assertNotIn(str(linked_tmp), rustup_home)
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

    def test_release_rejects_untracked_recursive_app_inputs(self) -> None:
        app_source = self.ios_dir / "Fabric"
        asset_catalog = app_source / "Assets.xcassets" / "Injected.imageset"
        asset_catalog.mkdir(parents=True)
        # XcodeGen still discovers ignored files under a recursive source root;
        # prove the release gate covers both ordinary and ignored untracked data.
        (self.checkout / ".git" / "info" / "exclude").write_text(
            "*.png\n",
            encoding="utf-8",
        )

        candidates = (
            app_source / "Injected.swift",
            asset_catalog / "injected.png",
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate.name):
                candidate.write_bytes(b"untracked release input")

                result = self.run_post_clone(
                    FABRIC_IOS_BUNDLE_ID="com.example.fabric.mobile",
                    FABRIC_IOS_BUILD_NUMBER="42",
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn("found untracked app source or resources", result.stderr)
                self.assertIn(
                    str(candidate.relative_to(self.checkout)),
                    result.stderr,
                )
                self.assertFalse(self.capture.exists())
                self.assert_source_manifest_unchanged()

                candidate.unlink()

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

    def test_release_fails_closed_when_recursive_app_source_marker_drifts(self) -> None:
        changed_spec = self.project_spec.read_text(encoding="utf-8").replace(
            "      - Fabric\n",
            "      - Application\n",
            1,
        )
        self.project_spec.write_text(changed_spec, encoding="utf-8")
        self.original_spec = self.project_spec.read_bytes()
        self.source_revision = self._commit_spec("change recursive app source root")

        result = self.run_post_clone(
            FABRIC_IOS_BUNDLE_ID="com.example.fabric.mobile",
            FABRIC_IOS_BUILD_NUMBER="42",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("recursive iOS app source root changed", result.stderr)
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
