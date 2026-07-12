#!/usr/bin/env python3
"""Build or verify the deterministic capability-pack distribution catalog."""

from __future__ import annotations

import argparse
import os
import secrets
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from fabric_cli.capability_packs import (  # noqa: E402
    CATALOG_OUTPUT_NAME,
    MAX_COMPILED_BYTES,
    CapabilityPackValidationError,
    SourceRepository,
    build_catalog_bytes,
)
from tools.skill_install import is_path_redirect, resolve_relative_path  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT / "capability-packs",
        help="authoring catalog root (default: repository capability-packs/)",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="root used for repository-relative evidence paths",
    )
    parser.add_argument(
        "--bundled-skills-root",
        type=Path,
        default=REPOSITORY_ROOT / "skills",
    )
    parser.add_argument(
        "--optional-skills-root",
        type=Path,
        default=REPOSITORY_ROOT / "optional-skills",
    )
    parser.add_argument(
        "--source-repository",
        action="append",
        default=[],
        metavar="CANONICAL_URL=LOCAL_GIT_OR_SOURCE_ROOT",
        help="offline pinned-source repository; repeat for each provenance URL",
    )
    parser.add_argument(
        "--source-ref",
        action="append",
        default=[],
        metavar="CANONICAL_URL=REFS/REMOTES/ORIGIN/PROTECTED_BRANCH",
        help="explicit trusted remote ref for each Git source repository",
    )
    parser.add_argument(
        "--platform-evidence-verifier",
        type=Path,
        help=(
            "trusted Python verifier for signed platform evidence; receives the exact "
            "evidence bytes on stdin and the original path as context argv[1]"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=f"compiled catalog path (default: ROOT/{CATALOG_OUTPUT_NAME})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the existing output is missing or differs; never write",
    )
    return parser


def _directory_identity(path: Path) -> tuple[int, int]:
    value = path.lstat()
    if not stat.S_ISDIR(value.st_mode):
        raise OSError("catalog output parent must remain a directory")
    return value.st_dev, value.st_ino


def _open_output_directory(path: Path) -> tuple[int | None, tuple[int, int]]:
    identity = _directory_identity(path)
    if os.name == "nt" or not all(
        hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")
    ):
        return None, identity
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    opened = os.fstat(descriptor)
    if (opened.st_dev, opened.st_ino) != identity:
        os.close(descriptor)
        raise OSError("catalog output parent changed before open")
    return descriptor, identity


def _verify_output_parent(
    path: Path,
    *,
    directory_fd: int | None,
    expected_identity: tuple[int, int],
) -> None:
    if _directory_identity(path.parent) != expected_identity:
        raise OSError("catalog output parent changed during compilation")
    if directory_fd is not None:
        opened = os.fstat(directory_fd)
        if (opened.st_dev, opened.st_ino) != expected_identity:
            raise OSError("catalog output directory descriptor changed identity")


def _atomic_write(
    path: Path,
    payload: bytes,
    *,
    directory_fd: int | None,
    expected_parent_identity: tuple[int, int],
) -> None:
    _verify_output_parent(
        path,
        directory_fd=directory_fd,
        expected_identity=expected_parent_identity,
    )
    if directory_fd is not None:
        temporary_name = f".{path.name}.{secrets.token_hex(12)}.tmp"
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o644,
            dir_fd=directory_fd,
        )
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o644)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            _verify_output_parent(
                path,
                directory_fd=directory_fd,
                expected_identity=expected_parent_identity,
            )
            os.replace(
                temporary_name,
                path.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            os.fsync(directory_fd)
        finally:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        return

    # Native Windows lacks Python's descriptor-relative rename API. Revalidate
    # immediately before the path-based operation within the documented
    # single-trusted-operator boundary.
    _verify_output_parent(
        path,
        directory_fd=None,
        expected_identity=expected_parent_identity,
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _verify_output_parent(
            path,
            directory_fd=None,
            expected_identity=expected_parent_identity,
        )
        os.replace(temporary, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _source_repositories(
    values: list[str],
    ref_values: list[str],
) -> dict[str, SourceRepository]:
    roots: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(
                "--source-repository must be CANONICAL_URL=LOCAL_GIT_OR_SOURCE_ROOT"
            )
        canonical_url, raw_path = value.split("=", 1)
        if not canonical_url or not raw_path:
            raise ValueError(
                "--source-repository must include a non-empty URL and path"
            )
        if canonical_url in roots:
            raise ValueError(f"duplicate --source-repository URL: {canonical_url}")
        roots[canonical_url] = Path(raw_path).resolve(strict=True)
    refs: dict[str, str] = {}
    for value in ref_values:
        if "=" not in value:
            raise ValueError("--source-ref must be CANONICAL_URL=FULL_REMOTE_REF")
        canonical_url, trusted_ref = value.split("=", 1)
        if not canonical_url or not trusted_ref:
            raise ValueError("--source-ref must include a non-empty URL and ref")
        if canonical_url in refs:
            raise ValueError(f"duplicate --source-ref URL: {canonical_url}")
        if canonical_url not in roots:
            raise ValueError(
                f"--source-ref URL has no --source-repository: {canonical_url}"
            )
        refs[canonical_url] = trusted_ref
    return {
        canonical_url: SourceRepository(
            root=root,
            trusted_ref=refs.get(canonical_url),
        )
        for canonical_url, root in roots.items()
    }


def _output_path(root: Path, requested: Path | None) -> Path:
    candidate = root / CATALOG_OUTPUT_NAME if requested is None else requested
    if not candidate.is_absolute():
        candidate = root / candidate
    expected = root / CATALOG_OUTPUT_NAME
    try:
        parent = candidate.parent.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"--output must be exactly {expected}") from exc
    if parent != root or candidate.name != CATALOG_OUTPUT_NAME:
        raise ValueError(f"--output must be exactly {expected}")
    return resolve_relative_path(root, CATALOG_OUTPUT_NAME, must_exist=False)


def _read_existing_output(
    path: Path,
    *,
    directory_fd: int | None,
    expected_parent_identity: tuple[int, int],
) -> bytes:
    _verify_output_parent(
        path,
        directory_fd=directory_fd,
        expected_identity=expected_parent_identity,
    )
    if directory_fd is None:
        if is_path_redirect(path):
            raise OSError("compiled catalog output must not be a redirect")
        before = path.lstat()
    else:
        before = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise OSError("compiled catalog output must be a regular file")
    if before.st_size > MAX_COMPILED_BYTES:
        raise OSError("compiled catalog exceeds the maximum supported size")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = (
        os.open(path, flags)
        if directory_fd is None
        else os.open(path.name, flags, dir_fd=directory_fd)
    )
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (
            before.st_dev,
            before.st_ino,
        ) != (opened.st_dev, opened.st_ino):
            raise OSError("compiled catalog output changed before open")
        chunks: list[bytes] = []
        remaining = MAX_COMPILED_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        getattr(before, "st_mtime_ns", None),
        getattr(before, "st_ctime_ns", None),
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        getattr(after, "st_mtime_ns", None),
        getattr(after, "st_ctime_ns", None),
    ):
        raise OSError("compiled catalog output changed while being read")
    if len(raw) > MAX_COMPILED_BYTES:
        raise OSError("compiled catalog exceeds the maximum supported size")
    final = (
        path.lstat()
        if directory_fd is None
        else os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
    )
    if (
        after.st_dev,
        after.st_ino,
        after.st_size,
        getattr(after, "st_mtime_ns", None),
        getattr(after, "st_ctime_ns", None),
    ) != (
        final.st_dev,
        final.st_ino,
        final.st_size,
        getattr(final, "st_mtime_ns", None),
        getattr(final, "st_ctime_ns", None),
    ):
        raise OSError("compiled catalog output changed after being read")
    _verify_output_parent(
        path,
        directory_fd=directory_fd,
        expected_identity=expected_parent_identity,
    )
    return raw


def _platform_verifier(path: Path | None):
    if path is None:
        return None
    if is_path_redirect(path):
        raise ValueError("platform evidence verifier must not be a redirect")
    verifier = path.resolve(strict=True)
    if not verifier.is_file():
        raise ValueError("platform evidence verifier must be a regular file")

    def verify(
        evidence_path: Path,
        raw: bytes,
        _evidence: Mapping[str, Any],
    ) -> None:
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": "",
        }
        if system_root := os.environ.get("SystemRoot"):
            environment["SystemRoot"] = system_root
        completed = subprocess.run(
            [sys.executable, str(verifier), str(evidence_path)],
            input=raw,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
            env=environment,
        )
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()[:2000]
            raise ValueError(detail or "trusted platform verifier rejected evidence")

    return verify


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output_directory_fd: int | None = None
    try:
        root = args.root.resolve(strict=True)
        output = _output_path(root, args.output)
        output_directory_fd, output_parent_identity = _open_output_directory(root)
        source_repositories = _source_repositories(
            args.source_repository,
            args.source_ref,
        )
        platform_evidence_verifier = _platform_verifier(args.platform_evidence_verifier)
    except (OSError, ValueError) as exc:
        print(f"capability-pack catalog arguments are invalid: {exc}", file=sys.stderr)
        if output_directory_fd is not None:
            os.close(output_directory_fd)
        return 2
    try:
        payload = build_catalog_bytes(
            root,
            bundled_skills_root=args.bundled_skills_root.resolve(),
            optional_skills_root=args.optional_skills_root.resolve(),
            repository_root=args.repository_root.resolve(),
            source_repositories=source_repositories,
            platform_evidence_verifier=platform_evidence_verifier,
        )
    except CapabilityPackValidationError as exc:
        print(str(exc), file=sys.stderr)
        if output_directory_fd is not None:
            os.close(output_directory_fd)
        return 2

    try:
        if args.check:
            try:
                actual = _read_existing_output(
                    output,
                    directory_fd=output_directory_fd,
                    expected_parent_identity=output_parent_identity,
                )
            except OSError as exc:
                print(f"capability-pack catalog check failed: {exc}", file=sys.stderr)
                return 1
            if actual != payload:
                print(
                    f"capability-pack catalog is stale: run {Path(__file__).name}",
                    file=sys.stderr,
                )
                return 1
            print(f"capability-pack catalog is current: {output}")
            return 0

        try:
            _atomic_write(
                output,
                payload,
                directory_fd=output_directory_fd,
                expected_parent_identity=output_parent_identity,
            )
        except OSError as exc:
            print(f"capability-pack catalog write failed: {exc}", file=sys.stderr)
            return 1
        print(f"wrote capability-pack catalog: {output}")
        return 0
    finally:
        if output_directory_fd is not None:
            os.close(output_directory_fd)


if __name__ == "__main__":
    raise SystemExit(main())
