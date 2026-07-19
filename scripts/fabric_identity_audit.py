#!/usr/bin/env python3
"""Fail-closed audit for Fabric's tracked product identity.

The audit reads the Git index and the exact blob objects it names. This makes
the result independent of text decoding, working-tree filters, symlink
handling, or binary-file heuristics.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]

# Construct the retired identity so this audit can enforce its absence in its
# own tracked source. Do not replace this with a contiguous literal.
_RETIRED_IDENTITY = ("her" + "mes").encode("ascii")
_RETIRED_IDENTITY_ENCODINGS = tuple(
    _RETIRED_IDENTITY.decode("ascii").encode(encoding)
    for encoding in ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")
)

# These assets were manually inspected and retired because they contain the
# previous product's mythology/statue identity or visibly stale branding. A
# digest check prevents the same bytes from surviving under a different path.
RETIRED_ASSET_SHA256 = frozenset(
    {
        "26c711b9b6deaab1d1a82bb8d1dc53b2316c985fc10b7e201cfb4ab128128045",
        "26dd629bdd14edf9dc9b129ae814eb3765c62fe0b2f238082344dd71d0f6fa40",
        "3c112050e108ba0c98622443ede1dfafdfd97c8a823edc514d8894ef0447e9c2",
        "62361978541c8c13aa51a4ff0e066fd405990f7c7d6857ab2ba85f5b6d7ccc95",
        "7027eba4849e24d7071911aea2fcd10f4d7d0024786ed88d53b83321dd65b5eb",
        "7c27720fde5a812998c24aab0a7be50b9f49ed704e45e11da1c748d6c6dede17",
        "7eb1cc84a2d74a6de931485814921ded37f2b8b109625d988c0eba459f5d6f7c",
        "a4dcb6847809df705e186202e28bdeb2a1a557b127863b4921cbba0aeb000fe0",
        "b54be8664b9e0c63dd22f1e25588daf37d1e193bf8320fb01fed37410a470818",
        "b18f286117b7096870cb1f71cbbfda30c5def4e5e58af552616513e681cfa541",
        "c666a61de324b2691af7fd02e63f4a8b495ee0219a3c981157bf2b7f6808be32",
        "ca40ce8c043353a31205efc545100c3112024ce7a34e01c2c3f2d01cac780c43",
        "f204ae42453d069a29169d8feebdf9ddb9c5ff696151b8bbf6e5b12d5832f22f",
        "f5e4c57b09052b60be95cb954f221d3e8b3d95746562f263c58f0a06d73194f4",
    }
)


@dataclass(frozen=True, order=True)
class IdentityIssue:
    """One forbidden path, blob occurrence, or retired asset."""

    path: str
    kind: str
    line: int = 0

    def render(self) -> str:
        location = self.path if self.line <= 0 else f"{self.path}:{self.line}"
        return f"{location}: {self.kind}"


@dataclass(frozen=True)
class IndexEntry:
    """A stage-zero path and object from the Git index."""

    mode: bytes
    oid: bytes
    path: bytes

    @property
    def display_path(self) -> str:
        return self.path.decode("utf-8", errors="surrogateescape")


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        timeout=60,
    )


def read_index(root: Path = ROOT) -> tuple[list[IndexEntry], list[IdentityIssue]]:
    """Return every stage-zero index entry and fail-closed parse issues."""

    result = _run_git(root, "ls-files", "--stage", "-z")
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        return [], [
            IdentityIssue(
                ".git/index",
                f"could not read tracked index ({detail or 'git failed'})",
            )
        ]

    entries: list[IndexEntry] = []
    issues: list[IdentityIssue] = []
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        metadata, separator, path = record.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or not path:
            issues.append(IdentityIssue(".git/index", "malformed tracked entry"))
            continue
        mode, oid, stage = fields
        display_path = path.decode("utf-8", errors="surrogateescape")
        if stage != b"0":
            issues.append(IdentityIssue(display_path, "unmerged index entry"))
            continue
        entries.append(IndexEntry(mode=mode, oid=oid, path=path))
    return entries, issues


def _read_exact(stream, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError("truncated git object stream")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def iter_index_blobs(
    root: Path,
    entries: list[IndexEntry],
) -> Iterator[tuple[IndexEntry, bytes | None, str | None]]:
    """Yield exact blob bytes for index entries through one batch process."""

    process = subprocess.Popen(
        ["git", "-C", str(root), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    returncode = 0
    stderr = ""
    try:
        for entry in entries:
            process.stdin.write(entry.oid + b"\n")
            process.stdin.flush()
            header = process.stdout.readline()
            fields = header.rstrip(b"\n").split()
            if len(fields) == 2 and fields[1] == b"missing":
                yield entry, None, "missing index object"
                continue
            if len(fields) != 3:
                yield entry, None, "malformed index object header"
                continue
            _oid, object_type, raw_size = fields
            try:
                size = int(raw_size)
            except ValueError:
                yield entry, None, "invalid index object size"
                continue
            try:
                payload = _read_exact(process.stdout, size)
                terminator = _read_exact(process.stdout, 1)
            except EOFError as exc:
                yield entry, None, str(exc)
                return
            if terminator != b"\n":
                yield entry, None, "malformed index object framing"
                return
            if object_type != b"blob":
                # Gitlinks point at commits rather than repository-owned blob
                # bytes. Their tracked path is still audited above.
                yield entry, None, None
                continue
            yield entry, payload, None
    finally:
        process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace").strip()
        returncode = process.wait(timeout=60)
    if returncode != 0:
        detail = stderr or f"git cat-file exited with status {returncode}"
        sentinel = IndexEntry(mode=b"", oid=b"", path=b".git/index")
        yield sentinel, None, f"could not read tracked blobs ({detail})"


def audit_tracked_identity(root: Path = ROOT) -> list[IdentityIssue]:
    """Reject the retired identity in every tracked path and blob byte."""

    root = root.resolve()
    entries, issues = read_index(root)
    needle = _RETIRED_IDENTITY.lower()

    for entry in entries:
        if needle in entry.path.lower():
            issues.append(IdentityIssue(entry.display_path, "retired identity in tracked path"))

    for entry, payload, error in iter_index_blobs(root, entries):
        if error is not None:
            issues.append(IdentityIssue(entry.display_path, error))
            continue
        if payload is None:
            continue
        lowered_payload = payload.lower()
        offsets = [lowered_payload.find(needle)]
        offsets.extend(
            lowered_payload.find(encoded_needle)
            for encoded_needle in _RETIRED_IDENTITY_ENCODINGS
        )
        offset = min((candidate for candidate in offsets if candidate >= 0), default=-1)
        if offset >= 0:
            line = payload.count(b"\n", 0, offset) + 1
            issues.append(
                IdentityIssue(
                    entry.display_path,
                    "retired identity in tracked blob",
                    line,
                )
            )
        if hashlib.sha256(payload).hexdigest() in RETIRED_ASSET_SHA256:
            issues.append(IdentityIssue(entry.display_path, "retired visual asset bytes"))

    return sorted(set(issues))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    issues = audit_tracked_identity(args.root)
    if issues:
        print(f"FABRIC IDENTITY AUDIT FAILED: {len(issues)} issue(s)")
        for issue in issues[:200]:
            print(f"  - {issue.render()}")
        if len(issues) > 200:
            print(f"  ... {len(issues) - 200} additional issue(s) omitted")
        return 1

    print("fabric-identity-audit: OK (tracked paths, blobs, symlinks, and retired assets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
