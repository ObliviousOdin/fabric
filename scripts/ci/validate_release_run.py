#!/usr/bin/env python3
"""Validate that a production promotion comes from a successful beta run."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class RunValidationError(ValueError):
    """Raised when a workflow run is not an eligible beta source."""


def validate_run(
    run: dict,
    *,
    repository: str,
    workflow_name: str,
    workflow_path: str,
) -> str:
    """Return the source SHA when a run satisfies the beta provenance rules."""
    expected = {
        "name": workflow_name,
        "path": workflow_path,
        "event": "push",
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
    }
    for key, value in expected.items():
        if run.get(key) != value:
            raise RunValidationError(
                f"source run {key} {run.get(key)!r} does not match {value!r}"
            )

    head_repository = run.get("head_repository")
    if (
        not isinstance(head_repository, dict)
        or head_repository.get("full_name") != repository
    ):
        raise RunValidationError("source run belongs to a different repository")

    source_sha = run.get("head_sha")
    if not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha):
        raise RunValidationError("source run does not contain a valid commit SHA")
    return source_sha


def _write_output(source_sha: str, output_path: Path | None) -> None:
    destination = output_path or (
        Path(os.environ["GITHUB_OUTPUT"]) if os.environ.get("GITHUB_OUTPUT") else None
    )
    if destination is not None:
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(f"source_sha={source_sha}\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-json", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow-name", default="Fabric release channels")
    parser.add_argument(
        "--workflow-path",
        default=".github/workflows/release-channels.yml",
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        run = json.loads(args.run_json.read_text(encoding="utf-8"))
        source_sha = validate_run(
            run,
            repository=args.repository,
            workflow_name=args.workflow_name,
            workflow_path=args.workflow_path,
        )
    except (OSError, json.JSONDecodeError, RunValidationError) as exc:
        parser.error(str(exc))
    _write_output(source_sha, args.output)
    print(f"eligible beta run verified: {source_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
