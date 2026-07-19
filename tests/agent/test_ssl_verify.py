"""Tests for agent.ssl_verify.resolve_httpx_verify."""

import ssl

import certifi
import pytest

from agent.ssl_verify import resolve_httpx_verify

_CA_ENV_VARS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")


@pytest.fixture
def clean_ca_env(monkeypatch):
    for var in _CA_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_ssl_verify_false_disables_verification(clean_ca_env):
    assert resolve_httpx_verify(ssl_verify=False) is False


def test_ssl_cert_file_returns_ssl_context(clean_ca_env, monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", certifi.where())
    result = resolve_httpx_verify()
    assert isinstance(result, ssl.SSLContext)


def test_explicit_ca_bundle_param(clean_ca_env):
    result = resolve_httpx_verify(ca_bundle=certifi.where())
    assert isinstance(result, ssl.SSLContext)


def test_missing_ssl_cert_file_falls_back_to_true(clean_ca_env, monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/root-ca.pem")
    assert resolve_httpx_verify() is True


def test_default_without_env_is_true(clean_ca_env):
    assert resolve_httpx_verify() is True
