"""Pure trust-contract tests for application AI egress policy."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import socket

import pytest

from agent.egress_policy import (
    EgressMode,
    EgressPolicyConfigurationError,
    EgressPolicyUnavailable,
    EgressPolicyViolation,
    authorize_inference_route,
    canonical_inference_provider,
    policy_from_config,
    require_policy_available,
)


def _local(*cidrs: str):
    return policy_from_config(
        {
            "security": {
                "egress_mode": "local_ai",
                "local_ai_allowed_cidrs": list(cidrs),
            }
        }
    )


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("claude", "anthropic"),
        ("github-models", "copilot"),
        ("codex", "openai-codex"),
        ("nousresearch", "nous"),
        ("qwen", "qwen-oauth"),
        ("minimax-oauth-io", "minimax-oauth"),
        ("aws-bedrock", "bedrock"),
        ("vertex-ai", "vertex"),
        ("azure-ai", "azure-foundry"),
        ("unknown-local", "unknown-local"),
    ],
)
def test_provider_alias_normalization_is_pure(alias, canonical):
    assert canonical_inference_provider(alias) == canonical


def test_default_and_explicit_online_preserve_route_without_normalizing():
    assert policy_from_config({}).mode is EgressMode.ONLINE
    assert (
        authorize_inference_route(
            policy_from_config({"security": {"egress_mode": "online"}}),
            purpose="primary",
            provider="openrouter",
            base_url="HTTPS://Example.COM/v1/?token=kept-by-legacy",
        )
        is None
    )


def test_air_gapped_is_configured_but_unavailable():
    policy = policy_from_config({"security": {"egress_mode": "air_gapped"}})
    assert policy.available is False
    assert policy.unavailable_reason == "whole_process_network_boundary_missing"

    with pytest.raises(EgressPolicyUnavailable) as caught:
        require_policy_available(policy, surface="primary")
    assert caught.value.reason == "whole_process_network_boundary_missing"


def test_localhost_is_rewritten_to_canonical_loopback_before_client_use():
    route = authorize_inference_route(
        _local(),
        purpose="primary",
        provider="custom",
        base_url="HTTP://localhost:11434/v1/",
    )

    assert route is not None
    assert route.base_url == "http://127.0.0.1:11434/v1"
    assert route.address == "127.0.0.1"
    assert route.allow_environment_proxy is False


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("http://127.0.0.2:8000/v1", "http://127.0.0.2:8000/v1"),
        ("http://[0:0:0:0:0:0:0:1]:8000/v1", "http://[::1]:8000/v1"),
    ],
)
def test_literal_loopback_is_automatic(raw, normalized):
    route = authorize_inference_route(
        _local(), purpose="primary", provider="custom", base_url=raw
    )
    assert route is not None
    assert route.base_url == normalized


@pytest.mark.parametrize(
    ("cidr", "address"),
    [
        ("10.42.0.0/16", "10.42.1.9"),
        ("172.20.8.0/24", "172.20.8.4"),
        ("192.168.50.0/24", "192.168.50.12"),
        ("100.96.0.0/16", "100.96.4.2"),
        ("fd12:3456::/48", "fd12:3456::9"),
    ],
)
def test_explicit_private_cidr_allows_only_contained_literal(cidr, address):
    bracketed = f"[{address}]" if ":" in address else address
    route = authorize_inference_route(
        _local(cidr),
        purpose="primary",
        provider="custom",
        base_url=f"http://{bracketed}:8080/v1",
    )
    assert route is not None
    assert route.address == address


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.4:11434/v1",  # private, but not approved
        "http://8.8.8.8/v1",  # public
        "http://0.0.0.0:11434/v1",  # unspecified bind address
        "http://169.254.169.254/latest",  # link-local metadata
        "http://224.0.0.1/v1",  # multicast
        "http://192.0.2.10/v1",  # documentation range
        "http://[::ffff:127.0.0.1]/v1",  # alternate mapped identity
    ],
)
def test_unapproved_or_ambiguous_literals_are_rejected(url):
    with pytest.raises(EgressPolicyViolation) as caught:
        authorize_inference_route(
            _local(), purpose="primary", provider="custom", base_url=url
        )
    assert caught.value.reason == "address_not_approved"


def test_cgnat_metadata_is_denied_even_inside_approved_cidr():
    with pytest.raises(EgressPolicyViolation) as caught:
        authorize_inference_route(
            _local("100.64.0.0/10"),
            purpose="primary",
            provider="custom",
            base_url="http://100.100.100.200/latest/meta-data",
        )
    assert caught.value.reason == "address_not_approved"


def test_ipv6_metadata_is_denied_even_inside_approved_ula():
    with pytest.raises(EgressPolicyViolation) as caught:
        authorize_inference_route(
            _local("fd00:ec2::/64"),
            purpose="primary",
            provider="custom",
            base_url="http://[fd00:ec2::254]/latest/meta-data",
        )
    assert caught.value.reason == "address_not_approved"


def test_hostname_is_rejected_without_dns(monkeypatch):
    def unexpected_dns(*_args, **_kwargs):
        raise AssertionError("policy authorization must never perform DNS")

    monkeypatch.setattr(socket, "getaddrinfo", unexpected_dns)
    with pytest.raises(EgressPolicyViolation) as caught:
        authorize_inference_route(
            _local("192.168.0.0/16"),
            purpose="primary",
            provider="custom",
            base_url="http://model-server.internal:11434/v1",
        )
    assert caught.value.reason == "hostname_not_allowed"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://127.0.0.1/model",
        "http://user:password@127.0.0.1/v1",
        "http://127.0.0.1/v1?token=secret",
        "http://127.0.0.1/v1#fragment",
        "http://[fe80::1%25en0]/v1",
        "http://127.0.0.1:99999/v1",
        "http://127.0.0.1:0/v1",
        "http://127.0.0.1/v1\nignored",
    ],
)
def test_malformed_or_secret_bearing_origins_are_invalid(url):
    with pytest.raises(EgressPolicyViolation) as caught:
        authorize_inference_route(
            _local(), purpose="primary", provider="custom", base_url=url
        )
    assert caught.value.reason == "invalid_endpoint"


def test_failure_text_never_contains_url_userinfo_query_or_provider_garbage():
    raw = "https://alice:super-secret@example.com/v1?token=top-secret"
    with pytest.raises(EgressPolicyViolation) as caught:
        authorize_inference_route(
            _local(),
            purpose="primary",
            provider="provider?token=also-secret",
            base_url=raw,
        )

    rendered = str(caught.value)
    for forbidden in (
        raw,
        "alice",
        "super-secret",
        "example.com",
        "top-secret",
        "also-secret",
    ):
        assert forbidden not in rendered
    assert caught.value.provider == "unknown"
    assert len(caught.value.origin_digest) == 12


def test_failure_digest_depends_only_on_sanitized_origin():
    failures = []
    for raw in (
        "https://alice:first-secret@example.com/private-a?token=one",
        "https://bob:second-secret@example.com/private-b?token=two",
        "https://example.com:443/another-path?api_key=three",
    ):
        with pytest.raises(EgressPolicyViolation) as caught:
            authorize_inference_route(
                _local(), purpose="primary", provider="custom", base_url=raw
            )
        failures.append(caught.value)

    assert len({failure.origin_digest for failure in failures}) == 1
    for failure in failures:
        rendered = str(failure)
        assert "first-secret" not in rendered
        assert "second-secret" not in rendered
        assert "token" not in rendered
        assert "api_key" not in rendered


def test_unparseable_origins_use_constant_non_secret_digest():
    digests = []
    for raw in (
        "not-a-url secret-one",
        "http://127.0.0.1:99999/?token=secret-two",
    ):
        with pytest.raises(EgressPolicyViolation) as caught:
            authorize_inference_route(
                _local(), purpose="primary", provider="custom", base_url=raw
            )
        digests.append(caught.value.origin_digest)
    assert len(set(digests)) == 1


@pytest.mark.parametrize(
    "security",
    [
        {"egress_mode": "sometimes"},
        {"egress_mode": 1},
        {"local_ai_allowed_cidrs": "192.168.1.0/24"},
        {"local_ai_allowed_cidrs": ["192.168.1.7/24"]},
        {"local_ai_allowed_cidrs": ["127.0.0.0/8"]},
        {"local_ai_allowed_cidrs": ["169.254.0.0/16"]},
        {"local_ai_allowed_cidrs": ["2001:db8::/32"]},
        {"local_ai_allowed_cidrs": ["0.0.0.0/0"]},
    ],
)
def test_invalid_policy_config_fails_closed_without_echoing_value(security):
    with pytest.raises(EgressPolicyConfigurationError) as caught:
        policy_from_config({"security": security})
    assert "192.168.1.7" not in str(caught.value)
    assert "2001:db8" not in str(caught.value)


def test_policy_and_authorized_route_are_immutable():
    policy = _local()
    route = authorize_inference_route(
        policy,
        purpose="primary",
        provider="custom",
        base_url="http://127.0.0.1:11434/v1",
    )
    with pytest.raises(FrozenInstanceError):
        policy.mode = EgressMode.ONLINE  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        route.base_url = "https://example.com"  # type: ignore[misc,union-attr]
