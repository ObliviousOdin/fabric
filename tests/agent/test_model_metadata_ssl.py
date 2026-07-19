"""Tests for _resolve_requests_verify() env var precedence.

Verifies that custom provider `/models` fetches honour the supported standard
CA bundle env vars (REQUESTS_CA_BUNDLE, SSL_CERT_FILE)
in the documented priority order, and that non-existent paths are
skipped gracefully rather than breaking the request.

No filesystem or network I/O required — we use tmp_path to create real
CA bundle stand-in files and monkeypatch env vars.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agent.model_metadata import _resolve_requests_verify


_CA_ENV_VARS = ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE")


@pytest.fixture
def clean_env(monkeypatch):
    """Clear supported SSL env vars so each test starts from a known state."""
    for var in _CA_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


@pytest.fixture
def bundle_file(tmp_path: Path) -> str:
    """Create a placeholder CA bundle file and return its absolute path."""
    path = tmp_path / "ca.pem"
    path.write_text("-----BEGIN CERTIFICATE-----\nstub\n-----END CERTIFICATE-----\n")
    return str(path)


class TestResolveRequestsVerify:
    def test_no_env_returns_true(self, clean_env):
        assert _resolve_requests_verify() is True

    def test_requests_ca_bundle_returns_path(self, clean_env, bundle_file):
        clean_env.setenv("REQUESTS_CA_BUNDLE", bundle_file)
        assert _resolve_requests_verify() == bundle_file

    def test_ssl_cert_file_returns_path(self, clean_env, bundle_file):
        clean_env.setenv("SSL_CERT_FILE", bundle_file)
        assert _resolve_requests_verify() == bundle_file

    def test_priority_requests_over_ssl_cert_file(self, clean_env, tmp_path, bundle_file):
        other = tmp_path / "other.pem"
        other.write_text("stub")
        clean_env.setenv("REQUESTS_CA_BUNDLE", bundle_file)
        clean_env.setenv("SSL_CERT_FILE", str(other))
        assert _resolve_requests_verify() == bundle_file

    def test_nonexistent_path_falls_through(self, clean_env, tmp_path, bundle_file):
        missing = tmp_path / "does_not_exist.pem"
        clean_env.setenv("REQUESTS_CA_BUNDLE", str(missing))
        clean_env.setenv("SSL_CERT_FILE", bundle_file)
        assert _resolve_requests_verify() == bundle_file

    def test_all_nonexistent_returns_true(self, clean_env, tmp_path):
        missing1 = tmp_path / "a.pem"
        missing2 = tmp_path / "b.pem"
        clean_env.setenv("REQUESTS_CA_BUNDLE", str(missing1))
        clean_env.setenv("SSL_CERT_FILE", str(missing2))
        assert _resolve_requests_verify() is True

    def test_empty_string_env_var_ignored(self, clean_env, bundle_file):
        clean_env.setenv("SSL_CERT_FILE", "")
        clean_env.setenv("REQUESTS_CA_BUNDLE", bundle_file)
        assert _resolve_requests_verify() == bundle_file
