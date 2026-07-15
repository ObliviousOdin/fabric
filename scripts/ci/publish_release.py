#!/usr/bin/env python3
"""Publish a verified beta candidate as an annotated GitHub release."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

try:
    from .release_candidate import CandidateError, verify_candidate
except ImportError:  # Direct execution: python scripts/ci/publish_release.py
    from release_candidate import CandidateError, verify_candidate


TAG_RE = re.compile(
    r"^v20\d{2}\.(?:[1-9]|1[0-2])\.(?:[1-9]|[12]\d|3[01])(?:\.[2-9]\d*)?$"
)


class PublishError(RuntimeError):
    """Raised when an approved production release cannot be published safely."""


def _run_gh(
    args: list[str],
    *,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["gh", *args],
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise PublishError(f"gh {' '.join(args)} failed: {detail}")
    return completed


def _validate_tag(tag: str) -> None:
    if not TAG_RE.fullmatch(tag):
        raise PublishError("release tag must use CalVer form vYYYY.M.D or vYYYY.M.D.N")
    year, month, day = tag.removeprefix("v").split(".")[:3]
    try:
        date(int(year), int(month), int(day))
    except ValueError as exc:
        raise PublishError("release tag contains an invalid calendar date") from exc


def _ensure_release_target_is_new(repository: str, tag: str) -> None:
    release = _run_gh(
        ["release", "view", tag, "--repo", repository],
        check=False,
    )
    if release.returncode == 0:
        raise PublishError(f"GitHub release {tag} already exists")

    tag_ref = _run_gh(
        ["api", f"repos/{repository}/git/ref/tags/{tag}"],
        check=False,
    )
    if tag_ref.returncode == 0:
        raise PublishError(f"Git tag {tag} already exists without a release")


def _create_annotated_tag(
    repository: str,
    *,
    tag: str,
    source_sha: str,
    title: str,
) -> None:
    tag_payload = json.dumps({
        "tag": tag,
        "message": title,
        "object": source_sha,
        "type": "commit",
    })
    created = _run_gh(
        ["api", "--method", "POST", f"repos/{repository}/git/tags", "--input", "-"],
        input_text=tag_payload,
    )
    try:
        tag_sha = json.loads(created.stdout)["sha"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PublishError(
            "GitHub did not return the annotated tag object SHA"
        ) from exc

    ref_payload = json.dumps({"ref": f"refs/tags/{tag}", "sha": tag_sha})
    _run_gh(
        ["api", "--method", "POST", f"repos/{repository}/git/refs", "--input", "-"],
        input_text=ref_payload,
    )


def _delete_tag_ref(repository: str, tag: str) -> None:
    _run_gh(
        ["api", "--method", "DELETE", f"repos/{repository}/git/refs/tags/{tag}"],
        check=False,
    )


def publish_release(
    dist_dir: Path,
    *,
    repository: str,
    source_sha: str,
    tag: str,
    dry_run: bool = False,
) -> str:
    """Verify and publish the exact candidate bytes under a new CalVer tag."""
    _validate_tag(tag)
    try:
        manifest = verify_candidate(
            dist_dir,
            source_sha=source_sha,
            repository=repository,
        )
    except CandidateError as exc:
        raise PublishError(str(exc)) from exc

    version = manifest["version"]
    title = f"Fabric v{version} ({tag.removeprefix('v')})"
    if dry_run:
        return title
    if shutil.which("gh") is None:
        raise PublishError("gh CLI is required to publish a production release")
    if not os.environ.get("GH_TOKEN"):
        raise PublishError("GH_TOKEN is required to publish a production release")

    _ensure_release_target_is_new(repository, tag)
    _create_annotated_tag(
        repository,
        tag=tag,
        source_sha=source_sha,
        title=title,
    )
    assets = sorted(str(path) for path in dist_dir.iterdir() if path.is_file())
    try:
        _run_gh([
            "release",
            "create",
            tag,
            "--repo",
            repository,
            "--verify-tag",
            "--title",
            title,
            "--generate-notes",
            "--latest",
            *assets,
        ])
    except PublishError:
        _delete_tag_ref(repository, tag)
        raise
    return title


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        title = publish_release(
            args.dist,
            repository=args.repository,
            source_sha=args.source_sha,
            tag=args.tag,
            dry_run=args.dry_run,
        )
    except PublishError as exc:
        parser.error(str(exc))
    action = "validated" if args.dry_run else "published"
    print(f"production release {action}: {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
