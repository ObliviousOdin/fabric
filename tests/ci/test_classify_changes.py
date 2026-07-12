"""Tests for scripts/ci/classify_changes.py.

Check some common patterns of file modifications and the CI lanes they should run.
We should always fail open. We may run a lane we didn't need, never skip one a
change could have broken.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "classify_changes.py"
_spec = importlib.util.spec_from_file_location("classify_changes", _PATH)
if _spec is None or _spec.loader is None:
    raise ImportError("Failed to load classify_changes.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
classify = _mod.classify
all_lanes = _mod.all_lanes
changed_files_from_git = _mod.changed_files_from_git

DEFAULT = {
    "python": True,
    "frontend": True,
    "docker_meta": True,
    "site": True,
    "scan": True,
    "deps": True,
    "mcp_catalog": False,
    "pack_catalog": True,
}
ALL = {lane: True for lane in DEFAULT}


def _lanes(
    python=False,
    frontend=False,
    site=False,
    scan=False,
    deps=False,
    mcp_catalog=False,
    pack_catalog=False,
    docker_meta=False,
) -> dict[str, bool]:
    return {
        "python": python,
        "frontend": frontend,
        "docker_meta": docker_meta,
        "site": site,
        "scan": scan,
        "deps": deps,
        "mcp_catalog": mcp_catalog,
        "pack_catalog": pack_catalog,
    }


CASES = {
    "docs-only → nothing heavy": (["README.md", "docs/guide.md"], _lanes()),
    "python source → python": (["run_agent.py"], _lanes(python=True, scan=True)),
    "dep manifest → python + pack_catalog": (
        ["pyproject.toml"],
        _lanes(python=True, scan=True, deps=True, pack_catalog=True),
    ),
    "uv.lock → python + pack_catalog": (
        ["uv.lock"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "ts package → frontend": (["apps/desktop/src/app.tsx"], _lanes(frontend=True)),
    "ui-tui → frontend": (["ui-tui/src/entry.ts"], _lanes(frontend=True)),
    # Lockfile bump shifts every TS package's tree, but not the Python suite.
    "root lockfile → frontend, not python": (
        ["package-lock.json"],
        _lanes(frontend=True),
    ),
    "website → site": (["website/docs/intro.md"], _lanes(site=True)),
    # SKILL.md reads like docs, but the skill-doc tests read skills/, so a
    # skill edit must still run Python.
    "skill md → python + site + pack_catalog": (
        ["skills/github/SKILL.md"],
        _lanes(python=True, site=True, scan=True, pack_catalog=True),
    ),
    "capability pack skill → python + site + pack_catalog": (
        ["capability-packs/fabric.product-design/1.0.0/router/SKILL.md"],
        _lanes(python=True, site=True, scan=True, pack_catalog=True),
    ),
    "dockerfile → docker meta": (["Dockerfile"], _lanes(docker_meta=True)),
    # Unknown top-level file keeps Python on rather than risk a silent skip.
    "unknown toplevel → python": (["Makefile"], _lanes(python=True)),
    "mixed docs+python → python": (
        ["README.md", "agent/x.py"],
        _lanes(python=True, scan=True),
    ),
    "mixed docs+frontend → frontend": (
        ["README.md", "apps/x.tsx"],
        _lanes(frontend=True),
    ),
    # Supply-chain lanes
    ".pth file → scan": (["evil.pth"], _lanes(python=True, scan=True)),
    "setup.py → scan + pack_catalog": (
        ["setup.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "mcp catalog manifest → mcp_catalog": (
        ["optional-mcps/foo/manifest.yaml"],
        _lanes(python=True, mcp_catalog=True),
    ),
    "mcp_catalog.py → mcp_catalog": (
        ["fabric_cli/mcp_catalog.py"],
        _lanes(python=True, scan=True, mcp_catalog=True),
    ),
    "capability pack compiler → pack_catalog": (
        ["fabric_cli/capability_packs.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "capability pack lifecycle → pack_catalog": (
        ["fabric_cli/capability_pack_transactions.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "shared skill mutation lock → pack_catalog": (
        ["tools/skill_mutation.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "pack scanner dependency → pack_catalog": (
        ["tools/skills_guard.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "pack effective-tree promotion dependency → pack_catalog": (
        ["tools/skills_hub.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "public Hub install surface → pack_catalog": (
        ["fabric_cli/skills_hub.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "pack scanner regression → pack_catalog": (
        ["tests/tools/test_skills_guard.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "pack effective-tree regression → pack_catalog": (
        ["tests/tools/test_skills_hub.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "public Hub install regression → pack_catalog": (
        ["tests/fabric_cli/test_skills_hub.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "public Hub adapter regression → pack_catalog": (
        ["tests/tools/test_skills_hub_clawhub.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "public Hub flag regression → pack_catalog": (
        ["tests/fabric_cli/test_skills_skip_confirm.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "pack transaction regression → pack_catalog": (
        ["tests/fabric_cli/test_capability_pack_transactions.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "shared path regression → pack_catalog": (
        ["tests/tools/test_skill_install.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "capability pack build script → pack_catalog": (
        ["scripts/build_capability_pack_catalog.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    "capability pack attestation verifier → pack_catalog": (
        ["scripts/verify_capability_pack_platform_attestation.py"],
        _lanes(python=True, scan=True, pack_catalog=True),
    ),
    # CI-config / empty / blank inputs run every general lane. An actual Git
    # diff failure is stricter and enables the MCP review lane too (tested below).
    ".github change → all": ([".github/workflows/tests.yml"], DEFAULT),
    "action change → all": ([".github/actions/detect-changes/action.yml"], DEFAULT),
    "empty diff → all": ([], DEFAULT),
    "blank lines → all": (["", "  "], DEFAULT),
}


@pytest.mark.parametrize("files,expected", CASES.values(), ids=CASES.keys())
def test_classify(files, expected):
    assert classify(files) == expected


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_local_git_diff_reports_both_sides_of_rename(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "ci@example.com")
    _git(repository, "config", "user.name", "CI Fixture")
    protected = repository / "scripts" / "build_capability_pack_catalog.py"
    protected.parent.mkdir()
    protected.write_text("# protected\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-q", "-m", "base")
    base = _git(repository, "rev-parse", "HEAD")

    destination = repository / "docs" / "catalog-builder.md"
    destination.parent.mkdir()
    _git(
        repository,
        "mv",
        str(protected.relative_to(repository)),
        str(destination.relative_to(repository)),
    )
    _git(repository, "commit", "-q", "-m", "rename protected file")
    head = _git(repository, "rev-parse", "HEAD")

    files = changed_files_from_git(base, head, repository=repository)

    assert files is not None
    assert set(files) == {
        "docs/catalog-builder.md",
        "scripts/build_capability_pack_catalog.py",
    }
    assert classify(files)["pack_catalog"] is True


def test_local_git_diff_is_not_limited_to_api_sized_file_lists(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "ci@example.com")
    _git(repository, "config", "user.name", "CI Fixture")
    (repository / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-q", "-m", "base")
    base = _git(repository, "rev-parse", "HEAD")

    changed = repository / "changed"
    changed.mkdir()
    for index in range(305):
        (changed / f"file-{index:03}.txt").write_text(
            f"{index}\n",
            encoding="utf-8",
        )
    _git(repository, "add", ".")
    _git(repository, "commit", "-q", "-m", "large path set")
    head = _git(repository, "rev-parse", "HEAD")

    files = changed_files_from_git(base, head, repository=repository)

    assert files is not None
    assert len(files) == 305
    assert files[0] == "changed/file-000.txt"
    assert files[-1] == "changed/file-304.txt"


def test_local_git_diff_failure_returns_fail_open_signal(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q")

    files = changed_files_from_git("0" * 40, "f" * 40, repository=repository)

    assert files is None
    assert all_lanes() == ALL


def test_cli_git_diff_failure_writes_every_lane_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q")
    output = tmp_path / "github-output"
    monkeypatch.chdir(repository)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert _mod.main(["--git-diff", "0" * 40, "f" * 40]) == 0

    emitted = dict(
        line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines()
    )
    assert emitted == {lane: "true" for lane in ALL}
