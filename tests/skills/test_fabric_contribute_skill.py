"""Behavior and governance tests for the bundled fabric-contribute skill."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml
from agent.skill_preprocessing import preprocess_skill_content

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "github" / "fabric-contribute"
SKILL_PATH = SKILL_ROOT / "SKILL.md"
HELPER_PATH = SKILL_ROOT / "scripts" / "fabric_issue.py"
AUTH_HELPER_PATH = REPO_ROOT / "skills" / "github" / "github-auth" / "scripts" / "gh-env.sh"


def _load_helper():
    spec = importlib.util.spec_from_file_location("fabric_issue_helper", HELPER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_follows_bundled_authoring_contract():
    text = SKILL_PATH.read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)

    assert metadata["name"] == "fabric-contribute"
    assert len(metadata["description"]) <= 60
    assert metadata["description"].endswith(".")
    assert metadata["author"] != "Fabric"
    assert metadata["license"]
    assert set(metadata["platforms"]) == {"linux", "macos", "windows"}

    headings = [
        "# Fabric Contribute Skill",
        "## When to Use",
        "## How to Run",
        "## Quick Reference",
        "## Procedure",
        "## Pitfalls",
        "## Verification",
    ]
    positions = [body.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "source skills/github/" not in body
    assert "skills/github/fabric-contribute/scripts/" not in body
    assert "<skill-dir>" not in body
    assert "${HERMES_SKILL_DIR}" in body
    assert "fabric_issue.py" in body

    rendered = preprocess_skill_content(
        body,
        SKILL_ROOT,
        skills_cfg={"template_vars": True, "inline_shell": False},
    )
    assert "${HERMES_SKILL_DIR}" not in rendered
    assert str(HELPER_PATH) in rendered


def test_search_is_scoped_to_fabric_issues():
    helper = _load_helper()
    with mock.patch.object(
        helper,
        "_request",
        return_value=(200, {"items": [{"number": 42, "title": "Match", "html_url": "https://example/42"}]}),
    ) as request:
        results = helper.search_issues("duplicate bug", "token")

    assert results[0]["number"] == 42
    method, path, token, payload = request.call_args.args
    assert method == "GET"
    assert "repo%3AObliviousOdin%2Ffabric" in path
    assert "is%3Aissue" in path
    assert token == "token"
    assert payload is None


def test_create_posts_once_and_labels_best_effort():
    helper = _load_helper()
    with mock.patch.object(
        helper,
        "_request",
        side_effect=[
            (201, {"number": 123, "html_url": "https://github.com/ObliviousOdin/fabric/issues/123"}),
            (404, {"message": "label missing"}),
        ],
    ) as request:
        result = helper.create_issue("Title", "Body", "token", label="bug")

    assert result == "https://github.com/ObliviousOdin/fabric/issues/123"
    create_calls = [call for call in request.call_args_list if call.args[1] == "/repos/ObliviousOdin/fabric/issues"]
    assert len(create_calls) == 1
    assert create_calls[0].args == (
        "POST",
        "/repos/ObliviousOdin/fabric/issues",
        "token",
        {"title": "Title", "body": "Body"},
    )
    assert request.call_args_list[1].args == (
        "POST",
        "/repos/ObliviousOdin/fabric/issues/123/labels",
        "token",
        {"labels": ["bug"]},
    )


def test_create_cli_requires_explicit_confirmation(tmp_path):
    helper = _load_helper()
    body = tmp_path / "body.md"
    body.write_text("Details", encoding="utf-8")

    with mock.patch.object(helper, "resolve_github_token", return_value=("token", "test")), \
         mock.patch.object(helper, "create_issue") as create:
        with pytest.raises(SystemExit):
            helper.main(["create", "--title", "Title", "--body-file", str(body)])
    create.assert_not_called()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell compatibility check")
def test_github_auth_helper_honors_gh_token_without_gh(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *'token preferred'*) printf '%s\\n' '{\"login\":\"preferred-user\"}' ;;\n"
        "  *) printf '%s\\n' '{\"login\":\"wrong-user\"}' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)

    env = {
        "HOME": str(tmp_path),
        "FABRIC_HOME": str(tmp_path / ".fabric"),
        "GH_TOKEN": "preferred",
        "GITHUB_TOKEN": "fallback",
        "PATH": f"{bin_dir}:/usr/bin:/bin",
    }
    run = subprocess.run(
        ["/bin/bash", "-c", f"source {AUTH_HELPER_PATH!s}; printf '%s|%s\\n' \"$GH_AUTH_METHOD\" \"$GH_USER\""],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        timeout=30,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.splitlines()[-1] == "curl|preferred-user"
