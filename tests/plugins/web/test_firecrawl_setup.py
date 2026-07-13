"""Focused tests for Firecrawl's provider-owned onboarding connector."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from plugins.web.firecrawl import setup as firecrawl_setup


@pytest.mark.parametrize(
    ("platform", "parts"),
    [
        ("darwin", ("Library", "Application Support", "firecrawl-cli", "credentials.json")),
        ("win32", ("AppData", "Roaming", "firecrawl-cli", "credentials.json")),
        ("linux", (".config", "firecrawl-cli", "credentials.json")),
    ],
)
def test_credentials_path_matches_official_cli_layout(tmp_path, platform, parts):
    assert firecrawl_setup.firecrawl_cli_credentials_path(tmp_path, platform) == tmp_path.joinpath(*parts)


def test_read_credentials_accepts_only_valid_official_api_key(tmp_path):
    path = firecrawl_setup.firecrawl_cli_credentials_path(tmp_path, "linux")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"apiKey": "fc-valid"}), encoding="utf-8")
    assert firecrawl_setup.read_firecrawl_cli_credentials(tmp_path, "linux") == "fc-valid"

    path.write_text(json.dumps({"apiKey": "not-a-firecrawl-key"}), encoding="utf-8")
    assert firecrawl_setup.read_firecrawl_cli_credentials(tmp_path, "linux") is None

    path.write_text("not-json", encoding="utf-8")
    assert firecrawl_setup.read_firecrawl_cli_credentials(tmp_path, "linux") is None


def test_browser_login_uses_pinned_cli_scrubbed_env_and_imports_key(
    monkeypatch,
    tmp_path,
):
    calls = []
    saved = []
    monkeypatch.setenv("OPENAI_API_KEY", "process-secret-must-not-leak")
    monkeypatch.setenv("XAI_API_KEY", "process-secret-must-not-leak")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "process-secret-must-not-leak")
    monkeypatch.setenv("DATABASE_URL", "process-secret-must-not-leak")
    monkeypatch.setenv("NPM_TOKEN", "process-secret-must-not-leak")
    monkeypatch.setattr(firecrawl_setup, "_browser_open_is_safe", lambda: True)

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        path = firecrawl_setup.firecrawl_cli_credentials_path(tmp_path, "linux")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"apiKey": "fc-browser"}), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    result = firecrawl_setup.connect_firecrawl(
        home=tmp_path,
        platform="linux",
        environ={
            "HOME": str(tmp_path),
            "PATH": "/test/bin",
            "OPENAI_API_KEY": "must-not-leak",
            "XAI_API_KEY": "must-not-leak-either",
        },
        runner=runner,
        which=lambda name: "/test/bin/npx",
        prompt=lambda *args, **kwargs: pytest.fail("manual prompt must not run"),
        save_secret=lambda key, value: saved.append((key, value)),
        present_link=lambda *args, **kwargs: pytest.fail("manual link must not run"),
    )

    assert result == "fc-browser"
    assert saved == [("FIRECRAWL_API_KEY", "fc-browser")]
    argv, kwargs = calls[0]
    assert argv == [
        "/test/bin/npx",
        "-y",
        "firecrawl-cli@1.19.24",
        "login",
        "--method",
        "browser",
    ]
    assert kwargs["timeout"] == 360
    assert kwargs["check"] is False
    assert kwargs["env"]["FIRECRAWL_NO_TELEMETRY"] == "1"
    assert kwargs["env"]["HOME"] == str(tmp_path)
    assert kwargs["env"]["PATH"] == "/test/bin"
    assert "OPENAI_API_KEY" not in kwargs["env"]
    assert "XAI_API_KEY" not in kwargs["env"]
    assert "AWS_SECRET_ACCESS_KEY" not in kwargs["env"]
    assert "DATABASE_URL" not in kwargs["env"]
    assert "NPM_TOKEN" not in kwargs["env"]


def test_browser_login_reads_credentials_from_the_exact_child_home(
    monkeypatch,
    tmp_path,
):
    child_home = tmp_path / "profile-home"
    saved = []
    monkeypatch.setattr(firecrawl_setup, "_browser_open_is_safe", lambda: True)
    monkeypatch.setattr(
        "tools.environments.local.hermes_subprocess_env",
        lambda **_kwargs: {
            "HOME": str(child_home),
            "PATH": "/test/bin",
            "WSL_INTEROP": "/run/WSL/456_interop",
            "DATABASE_URL": "must-not-leak",
        },
    )

    def runner(argv, **kwargs):
        assert kwargs["env"]["HOME"] == str(child_home)
        assert kwargs["env"]["WSL_INTEROP"] == "/run/WSL/456_interop"
        assert "DATABASE_URL" not in kwargs["env"]
        path = firecrawl_setup.firecrawl_cli_credentials_path(child_home, "linux")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"apiKey": "fc-profile-home"}), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    result = firecrawl_setup.connect_firecrawl(
        platform="linux",
        runner=runner,
        which=lambda _name: "/test/bin/npx",
        prompt=lambda *_args, **_kwargs: pytest.fail("manual fallback must not run"),
        save_secret=lambda key, value: saved.append((key, value)),
        present_link=lambda *_args, **_kwargs: pytest.fail("manual link must not run"),
    )

    assert result == "fc-profile-home"
    assert saved == [("FIRECRAWL_API_KEY", "fc-profile-home")]


def test_missing_npx_uses_manual_key_link_and_profile_secret_writer(
    monkeypatch,
    tmp_path,
):
    presented = []
    saved = []
    monkeypatch.setattr(firecrawl_setup, "_browser_open_is_safe", lambda: False)

    result = firecrawl_setup.connect_firecrawl(
        home=tmp_path,
        platform="linux",
        which=lambda name: None,
        prompt=lambda *args, **kwargs: "fc-manual",
        save_secret=lambda key, value: saved.append((key, value)),
        present_link=lambda url, **kwargs: presented.append((url, kwargs)),
    )

    assert result == "fc-manual"
    assert saved == [("FIRECRAWL_API_KEY", "fc-manual")]
    assert presented == [
        (
            "https://firecrawl.dev/app/api-keys",
            {"label": "Firecrawl API keys", "open_browser": False},
        )
    ]


def test_remote_session_skips_browser_callback_and_uses_phone_link(
    monkeypatch,
    tmp_path,
):
    presented = []
    monkeypatch.setattr(firecrawl_setup, "_browser_open_is_safe", lambda: False)

    result = firecrawl_setup.connect_firecrawl(
        home=tmp_path,
        platform="linux",
        which=lambda _name: "/test/bin/npx",
        runner=lambda *_args, **_kwargs: pytest.fail(
            "remote setup must not start a local browser callback"
        ),
        prompt=lambda *_args, **_kwargs: "fc-remote",
        save_secret=lambda *_args: None,
        present_link=lambda url, **kwargs: presented.append((url, kwargs)),
    )

    assert result == "fc-remote"
    assert presented == [
        (
            "https://firecrawl.dev/app/api-keys",
            {"label": "Firecrawl API keys", "open_browser": False},
        )
    ]


def test_invalid_manual_key_can_be_cancelled_without_mutation(monkeypatch, tmp_path):
    answers = iter(["wrong", ""])
    saved = []
    monkeypatch.setattr(firecrawl_setup, "_browser_open_is_safe", lambda: False)

    result = firecrawl_setup.connect_firecrawl(
        home=tmp_path,
        platform="linux",
        which=lambda name: None,
        prompt=lambda *args, **kwargs: next(answers),
        save_secret=lambda key, value: saved.append((key, value)),
        present_link=lambda *args, **kwargs: None,
    )

    assert result is None
    assert saved == []


def test_browser_login_interrupt_does_not_fall_through_to_manual(tmp_path):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    result = firecrawl_setup.connect_firecrawl(
        home=tmp_path,
        platform="linux",
        runner=interrupted,
        which=lambda name: "/test/bin/npx",
        prompt=lambda *args, **kwargs: pytest.fail("manual prompt must not run"),
        save_secret=lambda *args, **kwargs: pytest.fail("secret must not be saved"),
        present_link=lambda *args, **kwargs: pytest.fail("manual link must not run"),
    )

    assert result is None


def test_firecrawl_schemas_expose_shared_setup_flow_and_key_page():
    from plugins.browser.firecrawl.provider import FirecrawlBrowserProvider
    from plugins.web.firecrawl.provider import FirecrawlWebSearchProvider

    for schema in (
        FirecrawlWebSearchProvider().get_setup_schema(),
        FirecrawlBrowserProvider().get_setup_schema(),
    ):
        assert schema["setup_flow"] == "firecrawl"
        assert schema["env_vars"][0]["url"] == "https://firecrawl.dev/app/api-keys"
        assert "free tier" in schema["badge"]
