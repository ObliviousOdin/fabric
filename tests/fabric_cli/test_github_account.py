"""Tests for fabric_cli.github_account — token resolution and REST helpers."""

import io
import json
import urllib.error
from unittest import mock

from fabric_cli import github_account as gha


class _FakeResponse:
    def __init__(self, status: int, payload=None):
        self.status = status
        self._raw = json.dumps(payload).encode() if payload is not None else b""

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ── Token resolution ────────────────────────────────────────────────────────


def test_resolve_token_prefers_process_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "gho_env_token")
    token, source = gha.resolve_github_token()
    assert token == "gho_env_token"
    assert source == "GITHUB_TOKEN"


def test_resolve_token_falls_back_to_fabric_env(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with mock.patch("fabric_cli.config.get_env_value", return_value="gho_dotenv"):
        token, source = gha.resolve_github_token()
    assert token == "gho_dotenv"
    assert source == "fabric .env"


def test_resolve_token_empty_when_nothing_available(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with mock.patch("fabric_cli.config.get_env_value", return_value=None), \
         mock.patch("fabric_cli.copilot_auth._try_gh_cli_token", return_value=None):
        token, source = gha.resolve_github_token()
    assert token == ""
    assert source == ""


# ── REST request plumbing ───────────────────────────────────────────────────


def test_api_request_put_sends_content_length_zero():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        return _FakeResponse(204)

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        status, data = gha._github_api_request(
            "PUT", "/user/starred/ObliviousOdin/fabric", "tok"
        )

    req = captured["req"]
    assert status == 204
    assert data is None
    assert req.get_method() == "PUT"
    assert req.get_full_url() == "https://api.github.com/user/starred/ObliviousOdin/fabric"
    assert req.headers.get("Content-length") == "0"
    assert req.headers.get("Authorization") == "Bearer tok"


def test_api_request_returns_http_error_status():
    err = urllib.error.HTTPError(
        "https://api.github.com/user", 401, "Unauthorized",
        hdrs=None, fp=io.BytesIO(b'{"message": "Bad credentials"}'),
    )
    with mock.patch("urllib.request.urlopen", side_effect=err):
        status, data = gha._github_api_request("GET", "/user", "bad")
    assert status == 401
    assert data == {"message": "Bad credentials"}


# ── User / star / issue helpers ─────────────────────────────────────────────


def test_fetch_github_user_ok():
    with mock.patch.object(
        gha, "_github_api_request", return_value=(200, {"login": "octocat"})
    ):
        user = gha.fetch_github_user("tok")
    assert user == {"login": "octocat"}


def test_fetch_github_user_bad_token():
    with mock.patch.object(
        gha, "_github_api_request", return_value=(401, {"message": "Bad credentials"})
    ):
        assert gha.fetch_github_user("tok") is None


def test_is_repo_starred_states():
    with mock.patch.object(gha, "_github_api_request", return_value=(204, None)):
        assert gha.is_repo_starred("tok") is True
    with mock.patch.object(gha, "_github_api_request", return_value=(404, None)):
        assert gha.is_repo_starred("tok") is False
    with mock.patch.object(gha, "_github_api_request", return_value=(401, None)):
        assert gha.is_repo_starred("tok") is None
    with mock.patch.object(gha, "_github_api_request", side_effect=OSError("net down")):
        assert gha.is_repo_starred("tok") is None


def test_star_repo_targets_fabric_repo_by_default():
    with mock.patch.object(
        gha, "_github_api_request", return_value=(204, None)
    ) as api:
        assert gha.star_repo("tok") is True
    method, path, token = api.call_args.args
    assert method == "PUT"
    assert path == "/user/starred/ObliviousOdin/fabric"
    assert token == "tok"


def test_star_repo_failure_and_network_error():
    with mock.patch.object(gha, "_github_api_request", return_value=(403, None)):
        assert gha.star_repo("tok") is False
    with mock.patch.object(gha, "_github_api_request", side_effect=OSError("net down")):
        assert gha.star_repo("tok") is False


def test_create_issue_payload_and_url():
    issue = {"number": 7, "html_url": "https://github.com/ObliviousOdin/fabric/issues/7"}
    with mock.patch.object(
        gha, "_github_api_request", return_value=(201, issue)
    ) as api:
        result = gha.create_issue(
            "tok", "Add dark mode", "## Feature\nPlease", labels=["enhancement"]
        )
    assert result == issue
    method, path, token = api.call_args.args
    assert method == "POST"
    assert path == "/repos/ObliviousOdin/fabric/issues"
    payload = api.call_args.kwargs["data"]
    assert payload == {
        "title": "Add dark mode",
        "body": "## Feature\nPlease",
        "labels": ["enhancement"],
    }


def test_create_issue_failure_returns_none():
    with mock.patch.object(
        gha, "_github_api_request", return_value=(410, {"message": "Issues disabled"})
    ):
        assert gha.create_issue("tok", "t", "b") is None


def test_setup_parser_accepts_github_section():
    import argparse

    from fabric_cli.subcommands.setup import build_setup_parser

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    build_setup_parser(sub, cmd_setup=lambda args: None)
    args = parser.parse_args(["setup", "github"])
    assert args.section == "github"


def test_save_github_token_writes_env(monkeypatch):
    saved = {}
    with mock.patch(
        "fabric_cli.config.save_env_value",
        side_effect=lambda k, v: saved.update({k: v}),
    ):
        gha.save_github_token("  gho_x  ")
    assert saved == {"GITHUB_TOKEN": "gho_x"}
