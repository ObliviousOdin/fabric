#!/usr/bin/env python3
"""Classify a PR's changed files into CI work lanes.

Reads newline-separated changed paths on stdin, or computes a NUL-safe local
Git diff with ``--git-diff BASE HEAD``, and writes ``key=value`` booleans (one
per lane) to ``$GITHUB_OUTPUT`` and stdout. The ``detect-changes`` composite
action consumes them so jobs gate on its lane outputs.

Lanes:

* ``python``      — pytest / ruff / ty / footguns.
* ``docker_meta`` — Dockerfiles etc.
* ``frontend``    — TS typecheck matrix + desktop build.
* ``site``        — Docusaurus + generated skill docs.
* ``scan``        — supply-chain scan (Python files, .pth, setup hooks).
* ``deps``        — pyproject.toml dependency bounds check.
* ``mcp_catalog`` — bundled MCP catalog / installer review.
* ``pack_catalog`` — capability-pack compiler and catalog checks.

Docker is not a lane — it builds on push-to-main and release only,
never per-PR.

Contract — *fail open, never closed*. We may run a lane we didn't need, but
must never skip one a change could break:

* An unprovable local diff runs every lane. Empty stdin and ``.github/``
  changes run every general lane; MCP review remains tied to MCP paths unless
  the diff itself could not be proven.
* ``python`` is a denylist: skipped only when *every* file is provably prose
  or a frontend-only package; an unrecognized path keeps it on.
* ``skills/`` and ``capability-packs/`` (incl. ``SKILL.md``) are
  python-relevant — validation tests read those trees, so a doc-looking edit
  can still break Python.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_FRONTEND = ("ui-tui/", "web/", "apps/")  # TS typecheck-matrix packages
_ROOT_NPM = {"package.json", "package-lock.json"}  # shifts every package's tree
_DOCKER_META = ("docker/", ".hadolint.yml", "Dockerfile")  # docker setup
_SITE = (
    "website/",
    "skills/",
    "optional-skills/",
    "capability-packs/",
)  # docs site + skill/pack pages
# Prose/frontend trees that can't touch Python. skills/ is excluded on purpose.
_PY_SKIP = ("docs/", "website/") + _FRONTEND

# Supply-chain scan: files that can execute code at install/import time.
_SCAN_EXTS = (".py", ".pth")
_SCAN_FILES = {"setup.cfg", "pyproject.toml"}

# MCP catalog files that require explicit security review.
_MCP_CATALOG_PATHS = ("optional-mcps/",)
_MCP_CATALOG_FILES = {"fabric_cli/mcp_catalog.py"}

# Capability-pack sources and their deterministic compiler require the
# dedicated catalog lane even when a changed skill/manifest is Markdown/YAML.
_PACK_CATALOG_PATHS = (
    "capability-packs/",
    "skills/",
    "optional-skills/",
)
_PACK_CATALOG_FILES = {
    "MANIFEST.in",
    "fabric_cli/capability_pack_lifecycle.py",
    "fabric_cli/capability_pack_transactions.py",
    "fabric_cli/skills_hub.py",
    "fabric_cli/capability_packs.py",
    "fabric_constants.py",
    "pyproject.toml",
    "scripts/build_capability_pack_catalog.py",
    "scripts/verify_capability_pack_platform_attestation.py",
    "scripts/ci/classify_changes.py",
    "setup.py",
    "tools/skill_install.py",
    "tools/skill_mutation.py",
    "tools/skills_guard.py",
    "tools/skills_hub.py",
    "tests/fabric_cli/test_capability_pack_catalog.py",
    "tests/fabric_cli/test_capability_pack_lifecycle.py",
    "tests/fabric_cli/test_capability_pack_transactions.py",
    "tests/fabric_cli/test_skills_install_flags.py",
    "tests/fabric_cli/test_skills_skip_confirm.py",
    "tests/fabric_cli/test_skills_hub.py",
    "tests/fabric_cli/test_compound_engineering_pack_skills.py",
    "tests/fabric_cli/test_product_design_pack_skills.py",
    "tests/tools/test_skill_install.py",
    "tests/tools/test_skill_mutation.py",
    "tests/tools/test_skills_guard.py",
    "tests/tools/test_skills_hub.py",
    "tests/tools/test_skills_hub_browse_sh.py",
    "tests/tools/test_skills_hub_clawhub.py",
    "uv.lock",
}


def _is_docs(p: str) -> bool:
    if p.startswith(("skills/", "optional-skills/", "capability-packs/")):
        return False
    return (
        p.endswith((".md", ".mdx")) or p.startswith("docs/") or p.startswith("LICENSE")
    )


def _py_irrelevant(p: str) -> bool:
    return (
        _is_docs(p)
        or p in _ROOT_NPM
        or p.startswith(_PY_SKIP)
        or p.startswith(_DOCKER_META)
    )


def _is_scan(p: str) -> bool:
    return p.endswith(_SCAN_EXTS) or p in _SCAN_FILES


def _is_mcp_catalog(p: str) -> bool:
    return p.startswith(_MCP_CATALOG_PATHS) or p in _MCP_CATALOG_FILES


def _is_pack_catalog(p: str) -> bool:
    return p.startswith(_PACK_CATALOG_PATHS) or p in _PACK_CATALOG_FILES


def classify(files: list[str]) -> dict[str, bool]:
    """Map changed paths to ``{lane: should_run}``."""
    files = [f.strip() for f in files if f.strip()]
    ret = {
        "python": any(not _py_irrelevant(f) for f in files),
        "docker_meta": any(f.startswith(_DOCKER_META) for f in files),
        "frontend": any(f.startswith(_FRONTEND) or f in _ROOT_NPM for f in files),
        "site": any(f.startswith(_SITE) for f in files),
        "scan": any(_is_scan(f) or _is_pack_catalog(f) for f in files),
        "deps": any(f == "pyproject.toml" for f in files),
        "mcp_catalog": any(_is_mcp_catalog(f) for f in files),
        "pack_catalog": any(_is_pack_catalog(f) for f in files),
    }
    if not files or any(f.startswith(".github/") for f in files):
        ret["python"] = True
        ret["docker_meta"] = True
        ret["frontend"] = True
        ret["site"] = True
        ret["scan"] = True
        ret["deps"] = True
        ret["pack_catalog"] = True

        # explicitly skip mcp catalog here. it's not needed unless those files are modified.
    return ret


def all_lanes() -> dict[str, bool]:
    """Return the explicit fail-open result for an unprovable diff."""

    return {lane: True for lane in classify([])}


def changed_files_from_git(
    base_sha: str,
    head_sha: str,
    *,
    repository: Path = Path("."),
) -> list[str] | None:
    """Return the complete PR path set, or ``None`` when Git cannot prove it.

    Rename detection is disabled deliberately: Git then reports a rename as a
    deletion at the old path plus an addition at the new path.  That prevents a
    protected file from escaping its CI lane merely by being renamed into an
    otherwise-irrelevant tree.  NUL framing preserves every path Git permits,
    including names containing newlines.

    ``None`` is the fail-open signal.  Callers must classify it like an empty
    diff, which enables every safety lane.
    """

    try:
        completed = subprocess.run(
            [
                "git",
                "diff",
                "--no-ext-diff",
                "--name-only",
                "--no-renames",
                "-z",
                f"{base_sha}...{head_sha}",
                "--",
            ],
            cwd=repository,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return [os.fsdecode(path) for path in completed.stdout.split(b"\0") if path]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--git-diff",
        nargs=2,
        metavar=("BASE_SHA", "HEAD_SHA"),
        help="classify a local three-dot Git diff; failures enable every lane",
    )
    mode.add_argument(
        "--all-lanes",
        action="store_true",
        help="enable every lane without reading a diff",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    force_all = args.all_lanes
    if force_all:
        files = []
    elif args.git_diff:
        base_sha, head_sha = args.git_diff
        files = changed_files_from_git(base_sha, head_sha)
        if files is None:
            print(
                "::warning::Could not compute the complete local PR diff; "
                "running every CI lane.",
                file=sys.stderr,
            )
            files = []
            force_all = True
    else:
        files = sys.stdin.read().splitlines()

    print("Changed files:")
    if files:
        for path in files:
            print(repr(path))
    else:
        print("(none; all safety lanes enabled)")

    lanes = all_lanes() if force_all else classify(files)
    out = "\n".join(f"{k}={str(v).lower()}" for k, v in lanes.items())
    if dest := os.environ.get("GITHUB_OUTPUT"):
        with open(dest, "a", encoding="utf-8") as fh:
            fh.write(out + "\n")
    print(out)  # echo for local runs + CI step logs
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
