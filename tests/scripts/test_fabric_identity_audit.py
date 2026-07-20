from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fabric_identity_audit.py"
RETIRED = "Her" + "mes"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("fabric_identity_audit_unit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FabricIdentityAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = _load_audit_module()
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        subprocess.run(
            ["git", "init", "--quiet", str(self.root)],
            check=True,
            capture_output=True,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write(self, relative: str, payload: bytes) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def _stage(self, *relative: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.root), "add", "--", *relative],
            check=True,
            capture_output=True,
        )

    def test_clean_text_and_binary_blobs_pass(self) -> None:
        self._write("fabric.txt", b"Fabric only\n")
        self._write("asset.bin", b"\x00\xffFabric\x10")
        self._stage("fabric.txt", "asset.bin")

        self.assertEqual(self.audit.audit_tracked_identity(self.root), [])

    def test_rejects_case_insensitive_identity_in_path(self) -> None:
        relative = f"docs/{RETIRED.lower()}-notes.md"
        self._write(relative, b"Fabric\n")
        self._stage(relative)

        issues = self.audit.audit_tracked_identity(self.root)

        self.assertTrue(any(issue.kind.endswith("tracked path") for issue in issues))

    def test_rejects_identity_in_binary_blob(self) -> None:
        self._write("asset.bin", b"\x00prefix" + RETIRED.swapcase().encode() + b"\xff")
        self._stage("asset.bin")

        issues = self.audit.audit_tracked_identity(self.root)

        self.assertTrue(any(issue.kind.endswith("tracked blob") for issue in issues))

    def test_rejects_identity_in_utf16_blob(self) -> None:
        self._write("encoded.txt", ("prefix " + RETIRED.upper()).encode("utf-16-le"))
        self._stage("encoded.txt")

        issues = self.audit.audit_tracked_identity(self.root)

        self.assertTrue(any(issue.kind.endswith("tracked blob") for issue in issues))

    @unittest.skipIf(os.name == "nt", "symlink creation is not generally available")
    def test_rejects_identity_in_symlink_target(self) -> None:
        link = self.root / "current"
        link.symlink_to(f"../{RETIRED.lower()}/config")
        self._stage("current")

        issues = self.audit.audit_tracked_identity(self.root)

        self.assertTrue(any(issue.path == "current" and issue.line == 1 for issue in issues))

    def test_rejects_retired_asset_bytes_under_a_new_name(self) -> None:
        payload = b"manually retired visual fixture"
        self.audit.RETIRED_ASSET_SHA256 = frozenset(
            {hashlib.sha256(payload).hexdigest()}
        )
        self._write("renamed.png", payload)
        self._stage("renamed.png")

        issues = self.audit.audit_tracked_identity(self.root)

        self.assertTrue(any(issue.kind == "retired visual asset bytes" for issue in issues))

    def test_reads_the_exact_index_blob(self) -> None:
        path = self._write("identity.txt", b"Fabric\n")
        self._stage("identity.txt")
        path.write_bytes(RETIRED.encode())

        self.assertEqual(self.audit.audit_tracked_identity(self.root), [])

        self._stage("identity.txt")
        self.assertTrue(self.audit.audit_tracked_identity(self.root))

    def test_batch_blob_reader_closes_every_subprocess_stream(self) -> None:
        self._write("fabric.txt", b"Fabric only\n")
        self._stage("fabric.txt")
        entries, issues = self.audit.read_index(self.root)
        self.assertEqual(issues, [])

        real_popen = subprocess.Popen
        processes = []

        def capture_process(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            processes.append(process)
            return process

        with mock.patch.object(
            self.audit.subprocess,
            "Popen",
            side_effect=capture_process,
        ):
            rows = list(self.audit.iter_index_blobs(self.root, entries))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], b"Fabric only\n")
        self.assertEqual(len(processes), 1)
        process = processes[0]
        self.assertIsNotNone(process.stdin)
        self.assertIsNotNone(process.stdout)
        self.assertIsNotNone(process.stderr)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)
        self.assertEqual(process.returncode, 0)

    def test_missing_repository_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            issues = self.audit.audit_tracked_identity(Path(raw_root))

        self.assertTrue(any("could not read tracked index" in issue.kind for issue in issues))


if __name__ == "__main__":
    unittest.main()
