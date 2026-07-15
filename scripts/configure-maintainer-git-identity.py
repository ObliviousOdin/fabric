#!/usr/bin/env python3
"""Configure or verify the canonical Git identity for Fabric maintainers."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence


CANONICAL_NAME = "PrimeOdin"
CANONICAL_EMAIL = "11676741+ObliviousOdin@users.noreply.github.com"


def _run_git(
    args: Sequence[str], *, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=False,
        capture_output=capture,
        text=True,
    )


def _scopes(scope: str) -> tuple[str, ...]:
    if scope == "both":
        return ("global", "local")
    return (scope,)


def _read_config(scope: str, key: str) -> str | None:
    result = _run_git(["config", f"--{scope}", "--get", key], capture=True)
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        detail = result.stderr.strip() or "git config failed"
        raise RuntimeError(f"Unable to read {scope} Git configuration: {detail}")
    return result.stdout.strip()


def _write_config(scope: str, key: str, value: str) -> None:
    result = _run_git(["config", f"--{scope}", key, value], capture=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or "git config failed"
        raise RuntimeError(f"Unable to update {scope} Git configuration: {detail}")


def configure(scope: str) -> None:
    for selected_scope in _scopes(scope):
        _write_config(selected_scope, "user.name", CANONICAL_NAME)
        _write_config(selected_scope, "user.email", CANONICAL_EMAIL)
        if selected_scope == "global":
            _write_config(selected_scope, "user.useConfigOnly", "true")


def check(scope: str) -> list[str]:
    mismatches: list[str] = []
    for selected_scope in _scopes(scope):
        if _read_config(selected_scope, "user.name") != CANONICAL_NAME:
            mismatches.append(f"{selected_scope} user.name is not canonical")
        if _read_config(selected_scope, "user.email") != CANONICAL_EMAIL:
            mismatches.append(f"{selected_scope} user.email is not canonical")
        if (
            selected_scope == "global"
            and (_read_config(selected_scope, "user.useConfigOnly") or "").lower()
            != "true"
        ):
            mismatches.append("global user.useConfigOnly is not enabled")
    return mismatches


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Configure PrimeOdin's canonical GitHub noreply identity for Fabric "
            "maintenance. Other contributors should use their own identity."
        )
    )
    parser.add_argument(
        "--scope",
        choices=("local", "global", "both"),
        default="both",
        help="Git config scope to update or verify (default: both)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the canonical identity without changing configuration",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.check:
            mismatches = check(args.scope)
            if mismatches:
                print("Git identity check failed:", file=sys.stderr)
                for mismatch in mismatches:
                    print(f"- {mismatch}", file=sys.stderr)
                return 1
            print(f"Canonical Git identity is configured for {args.scope} scope.")
            return 0

        configure(args.scope)
        print(f"Configured canonical Git identity for {args.scope} scope.")
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
