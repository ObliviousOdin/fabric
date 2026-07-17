"""Tests for fabric_cli.github_account and the ``fabric setup github`` section."""

import io
import json
import urllib.error
from unittest import mock

import pytest

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


@pytest.fixture
def no_ambient_tokens(monkeypatch):
    """Keep resolution hermetic: no env tokens, no .env, no real gh binary."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with mock.patch("fabric_cli.config.get_env_value", return_value=None) as dotenv, \
         mock.patch("fabric_cli.copilot_auth._try_gh_cli_token", return_value=None) as gh:
        yield {"dotenv": dotenv, "gh": gh}


def test_resolve_token_prefers_github_token_env(no_ambient_tokens, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "gho_env_token")
    monkeypatch.setenv("GH_TOKEN", "gho_gh_env")
    assert gha.resolve_github_token() == ("gho_env_token", "GITHUB_TOKEN")


def test_resolve_token_gh_token_env_second(no_ambient_tokens, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "gho_gh_env")
    assert gha.resolve_github_token() == ("gho_gh_env", "GH_TOKEN")


def test_resolve_token_dotenv_beats_gh_cli(no_ambient_tokens):
    no_ambient_tokens["dotenv"].return_value = "gho_dotenv"
    no_ambient_tokens["gh"].return_value = "gho_from_gh"
    assert gha.resolve_github_token() == ("gho_dotenv", "fabric .env")


def test_resolve_token_gh_cli_last(no_ambient_tokens):
    no_ambient_tokens["gh"].return_value = "gho_from_gh"
    assert gha.resolve_github_token() == ("gho_from_gh", "gh auth token")


def test_resolve_token_empty_when_nothing_available(no_ambient_tokens):
    assert gha.resolve_github_token() == ("", "")


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


# ── User / star helpers ─────────────────────────────────────────────────────


def test_fetch_github_user_ok():
    with mock.patch.object(
        gha, "_github_api_request", return_value=(200, {"login": "octocat"})
    ):
        assert gha.fetch_github_user("tok") == {"login": "octocat"}


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


def test_star_repo_targets_fabric_repo():
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


def test_save_github_token_writes_env():
    saved = {}
    with mock.patch(
        "fabric_cli.config.save_env_value",
        side_effect=lambda k, v: saved.update({k: v}),
    ):
        gha.save_github_token("  gho_x  ")
    assert saved == {"GITHUB_TOKEN": "gho_x"}


# ── Setup parser ────────────────────────────────────────────────────────────


def test_setup_parser_accepts_github_section():
    import argparse

    from fabric_cli.subcommands.setup import build_setup_parser

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    build_setup_parser(sub, cmd_setup=lambda args: None)
    args = parser.parse_args(["setup", "github"])
    assert args.section == "github"


# ── setup_github_account wizard flow ────────────────────────────────────────


class _SectionHarness:
    """Patch every prompt and github_account call the section touches."""

    def __init__(self, stack, *, resolved=("", ""), user=None, choice=2,
                 yes_no=None, pat="", device_token=None, starred=False):
        self.resolve = stack.enter_context(mock.patch(
            "fabric_cli.github_account.resolve_github_token", return_value=resolved))
        self.fetch = stack.enter_context(mock.patch(
            "fabric_cli.github_account.fetch_github_user", return_value=user))
        self.save = stack.enter_context(mock.patch(
            "fabric_cli.github_account.save_github_token"))
        self.login = stack.enter_context(mock.patch(
            "fabric_cli.github_account.github_device_code_login",
            return_value=device_token))
        self.is_starred = stack.enter_context(mock.patch(
            "fabric_cli.github_account.is_repo_starred", return_value=starred))
        self.star = stack.enter_context(mock.patch(
            "fabric_cli.github_account.star_repo", return_value=True))
        self.choice = stack.enter_context(mock.patch(
            "fabric_cli.setup.prompt_choice", return_value=choice))
        self.yes_no = stack.enter_context(mock.patch(
            "fabric_cli.setup.prompt_yes_no",
            side_effect=yes_no if yes_no is not None else lambda q, d: d))
        self.pat_prompt = stack.enter_context(mock.patch(
            "fabric_cli.setup.prompt", return_value=pat))


def _run_section(**kwargs):
    from contextlib import ExitStack

    from fabric_cli.setup import setup_github_account

    with ExitStack() as stack:
        h = _SectionHarness(stack, **kwargs)
        result = setup_github_account({})
    return result, h


def test_section_skip_choice_does_nothing():
    result, h = _run_section(choice=2)
    assert result is False
    h.login.assert_not_called()
    h.save.assert_not_called()


def test_section_device_flow_failure_returns_false():
    result, h = _run_section(choice=0, device_token=None)
    assert result is False
    h.save.assert_not_called()


def test_section_device_flow_success_saves_and_offers_star():
    result, h = _run_section(
        choice=0, device_token="gho_new", user={"login": "octocat"})
    assert result is True
    h.save.assert_called_once_with("gho_new")
    # Star offer must default to No so EOF/non-interactive never auto-stars.
    star_calls = [c for c in h.yes_no.call_args_list if "Star" in c.args[0]]
    assert len(star_calls) == 1
    assert star_calls[0].args[1] is False


def test_section_pat_invalid_token_fails_without_saving():
    result, h = _run_section(choice=1, pat="ghp_bad", user=None)
    assert result is False
    h.save.assert_not_called()


def test_section_pat_empty_input_fails():
    result, h = _run_section(choice=1, pat="")
    assert result is False
    h.fetch.assert_not_called()
    h.save.assert_not_called()


def test_section_existing_token_kept_is_not_persisted():
    """Reusing a gh/env token must NOT copy it into .env (consent + scope)."""
    result, h = _run_section(
        resolved=("gho_ambient", "gh auth token"),
        user={"login": "octocat"},
    )
    assert result is True
    h.save.assert_not_called()
    h.login.assert_not_called()


def test_section_star_accepted_stars_repo():
    def answer(question, default):
        return "Star" in question  # yes only to the star prompt

    result, h = _run_section(
        resolved=("gho_ambient", "GITHUB_TOKEN"),
        user={"login": "octocat"},
        yes_no=answer,
    )
    assert result is True
    h.star.assert_called_once_with("gho_ambient")


def test_section_already_starred_skips_prompt():
    result, h = _run_section(
        resolved=("gho_ambient", "GITHUB_TOKEN"),
        user={"login": "octocat"},
        starred=True,
    )
    assert result is True
    h.star.assert_not_called()
    assert not [c for c in h.yes_no.call_args_list if "Star" in c.args[0]]
