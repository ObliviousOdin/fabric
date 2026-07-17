"""Tests for the shared GitHub OAuth device-code flow in fabric_cli.copilot_auth.

Covers the generic ``device_code_login`` used by both the Copilot provider
login and ``fabric setup github``: polling outcomes (success, slow_down,
expired, denied), initiation failure, and Ctrl+C cancellation.
"""

import json
from unittest import mock

from fabric_cli.copilot_auth import (
    COPILOT_OAUTH_CLIENT_ID,
    copilot_device_code_login,
    device_code_login,
)
from fabric_cli.github_account import GITHUB_OAUTH_CLIENT_ID, github_device_code_login


class _FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_DEVICE_GRANT = {
    "device_code": "dev123",
    "user_code": "ABCD-1234",
    "verification_uri": "https://github.com/login/device",
    "interval": 1,
}


def _urlopen_script(*poll_payloads):
    """Return a fake urlopen: first call yields the device grant, then polls."""
    responses = [_FakeResponse(_DEVICE_GRANT)] + [
        _FakeResponse(p) for p in poll_payloads
    ]
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        return responses.pop(0)

    return fake_urlopen, calls


def test_success_after_pending_polls():
    fake, calls = _urlopen_script(
        {"error": "authorization_pending"},
        {"access_token": "gho_ok"},
    )
    with mock.patch("urllib.request.urlopen", side_effect=fake), \
         mock.patch("time.sleep"):
        token = device_code_login("client123", "public_repo")
    assert token == "gho_ok"
    # First request carries the client_id and scope
    body = calls[0].data.decode()
    assert "client_id=client123" in body
    assert "public_repo" in body


def test_slow_down_honors_server_interval_then_succeeds():
    fake, _ = _urlopen_script(
        {"error": "slow_down", "interval": 7},
        {"access_token": "gho_ok"},
    )
    sleeps = []
    with mock.patch("urllib.request.urlopen", side_effect=fake), \
         mock.patch("time.sleep", side_effect=lambda s: sleeps.append(s)):
        token = device_code_login("client123", "public_repo")
    assert token == "gho_ok"
    # The sleep after the slow_down response must reflect the server interval
    assert sleeps[-1] >= 7


def test_expired_token_returns_none():
    fake, _ = _urlopen_script({"error": "expired_token"})
    with mock.patch("urllib.request.urlopen", side_effect=fake), \
         mock.patch("time.sleep"):
        assert device_code_login("client123", "s") is None


def test_access_denied_returns_none():
    fake, _ = _urlopen_script({"error": "access_denied"})
    with mock.patch("urllib.request.urlopen", side_effect=fake), \
         mock.patch("time.sleep"):
        assert device_code_login("client123", "s") is None


def test_initiation_failure_returns_none():
    with mock.patch("urllib.request.urlopen", side_effect=OSError("no network")):
        assert device_code_login("client123", "s") is None


def test_missing_device_code_returns_none():
    def fake(req, timeout=None):
        return _FakeResponse({"interval": 5})

    with mock.patch("urllib.request.urlopen", side_effect=fake):
        assert device_code_login("client123", "s") is None


def test_ctrl_c_during_poll_is_clean_cancel():
    """KeyboardInterrupt while waiting must cancel (None), not crash the wizard."""
    fake, _ = _urlopen_script({"access_token": "never_reached"})
    with mock.patch("urllib.request.urlopen", side_effect=fake), \
         mock.patch("time.sleep", side_effect=KeyboardInterrupt):
        assert device_code_login("client123", "s") is None


def test_copilot_wrapper_uses_copilot_client_id():
    fake, calls = _urlopen_script({"access_token": "gho_copilot"})
    with mock.patch("urllib.request.urlopen", side_effect=fake), \
         mock.patch("time.sleep"):
        token = copilot_device_code_login()
    assert token == "gho_copilot"
    assert f"client_id={COPILOT_OAUTH_CLIENT_ID}" in calls[0].data.decode()


def test_github_account_wrapper_discloses_gh_attribution_and_scope(capsys):
    fake, calls = _urlopen_script({"access_token": "gho_fabric"})
    with mock.patch("urllib.request.urlopen", side_effect=fake), \
         mock.patch("time.sleep"):
        token = github_device_code_login()
    assert token == "gho_fabric"
    body = calls[0].data.decode()
    assert f"client_id={GITHUB_OAUTH_CLIENT_ID}" in body
    assert "public_repo" in body
    output = capsys.readouterr().out
    assert "GitHub CLI" in output
    assert "read/write access to your public repositories" in output
    assert "no private repos" in output
