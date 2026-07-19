"""Tests for the config-native ``fabric dashboard register`` command."""

from __future__ import annotations

import argparse
import copy
import json
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

import fabric_cli.dashboard_register as dr


def _ns(**values):
    defaults = {"name": None, "redirect_uri": None, "portal_url": None}
    defaults.update(values)
    return argparse.Namespace(**defaults)


def _fake_http_ok(payload: dict):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    return response


def _portal_response(
    *,
    client_id: str = "agent:selfhost-1",
    name: str = "dreamy_tesla",
) -> dict:
    return {
        "client_id": client_id,
        "id": client_id.removeprefix("agent:"),
        "name": name,
        "kind": "SELF_HOSTED",
    }


def _run_registration(
    *,
    args=None,
    config=None,
    response=None,
    portal="https://portal.nousresearch.com",
):
    """Run registration against in-memory config and return saved config/request."""
    config = copy.deepcopy(config or {})
    response = response or _portal_response()
    captured: dict = {}
    saved: dict = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return _fake_http_ok(response)

    def fake_save(value):
        saved["config"] = copy.deepcopy(value)

    with (
        patch(
            "fabric_cli.auth.resolve_nous_access_token",
            return_value="tok_abc",
            create=True,
        ),
        patch("fabric_cli.config.is_managed", return_value=False),
        patch("fabric_cli.config.load_config", return_value=config),
        patch("fabric_cli.config.save_config", side_effect=fake_save),
        patch.object(dr, "_resolve_portal_base_url", return_value=portal),
        patch.object(dr.urllib.request, "urlopen", side_effect=fake_urlopen),
    ):
        dr.cmd_dashboard_register(args or _ns())

    return saved["config"], captured


class TestNameGenerator:
    def test_shape_is_adjective_underscore_noun(self):
        for _ in range(50):
            name = dr._generate_dashboard_name()
            adjective, separator, noun = name.partition("_")
            assert separator
            assert adjective in dr._NAME_ADJECTIVES
            assert noun in dr._NAME_NOUNS


class TestFastFails:
    def test_not_logged_in_exits_with_setup_hint(self, capsys):
        from fabric_cli.auth import AuthError

        error = AuthError("not logged in", provider="nous", relogin_required=True)
        with (
            patch(
                "fabric_cli.auth.resolve_nous_access_token",
                side_effect=error,
                create=True,
            ),
            patch("fabric_cli.config.is_managed", return_value=False),
            pytest.raises(SystemExit) as exc,
        ):
            dr.cmd_dashboard_register(_ns())

        assert exc.value.code == 1
        output = capsys.readouterr().out
        assert "not logged into Nous Portal" in output
        assert (
            "fabric auth add nous --client-id <registered-client-id>"
            in output
        )

    def test_managed_install_refuses(self, capsys):
        with (
            patch(
                "fabric_cli.auth.resolve_nous_access_token",
                return_value="unused",
                create=True,
            ),
            patch("fabric_cli.config.is_managed", return_value=True),
            pytest.raises(SystemExit) as exc,
        ):
            dr.cmd_dashboard_register(_ns())

        assert exc.value.code == 1
        assert "not available in a managed" in capsys.readouterr().out

    def test_invalid_dashboard_config_refuses(self, capsys):
        with (
            patch(
                "fabric_cli.auth.resolve_nous_access_token",
                return_value="tok",
                create=True,
            ),
            patch("fabric_cli.config.is_managed", return_value=False),
            patch("fabric_cli.config.load_config", return_value={"dashboard": "bad"}),
            pytest.raises(SystemExit) as exc,
        ):
            dr.cmd_dashboard_register(_ns())

        assert exc.value.code == 1
        assert "Could not load dashboard config" in capsys.readouterr().out


class TestCanonicalConfigPersistence:
    def test_generated_name_is_posted_and_client_id_is_saved(self, capsys):
        config, request = _run_registration()

        assert request["url"].endswith("/api/oauth/self-hosted-client")
        assert request["headers"]["Authorization"] == "Bearer tok_abc"
        assert request["body"]["name"]
        assert config["dashboard"]["oauth"]["client_id"] == "agent:selfhost-1"
        assert "portal_url" not in config["dashboard"]["oauth"]
        assert "Registered dashboard" in capsys.readouterr().out

    def test_explicit_name_and_redirect_uri_are_forwarded(self):
        _, request = _run_registration(
            args=_ns(
                name="office_dashboard",
                redirect_uri="https://fabric.example.com/auth/callback",
            )
        )

        assert request["body"]["name"] == "office_dashboard"
        assert (
            request["body"]["custom_redirect_uri"]
            == "https://fabric.example.com/auth/callback"
        )

    def test_explicit_portal_url_is_saved_even_when_default(self):
        config, _ = _run_registration(
            args=_ns(portal_url="https://portal.nousresearch.com")
        )

        assert (
            config["dashboard"]["oauth"]["portal_url"]
            == "https://portal.nousresearch.com"
        )

    def test_inferred_nondefault_portal_is_saved(self):
        config, _ = _run_registration(portal="https://preview.example.com")

        assert config["dashboard"]["oauth"]["portal_url"] == "https://preview.example.com"

    def test_existing_portal_is_preserved_without_explicit_override(self):
        config, _ = _run_registration(
            config={
                "dashboard": {
                    "oauth": {"portal_url": "https://configured.example.com"}
                }
            },
            portal="https://configured.example.com",
        )

        assert (
            config["dashboard"]["oauth"]["portal_url"]
            == "https://configured.example.com"
        )

    def test_redirect_origin_is_saved_as_public_url(self):
        config, _ = _run_registration(
            args=_ns(
                redirect_uri="https://fabric.example.com:8443/auth/callback"
            )
        )

        assert config["dashboard"]["public_url"] == "https://fabric.example.com:8443"

    def test_no_redirect_preserves_existing_public_url(self):
        config, _ = _run_registration(
            config={"dashboard": {"public_url": "https://existing.example.com"}}
        )

        assert config["dashboard"]["public_url"] == "https://existing.example.com"

    def test_malformed_redirect_does_not_create_public_url(self):
        config, _ = _run_registration(args=_ns(redirect_uri="not-a-url"))

        assert "public_url" not in config["dashboard"]


class TestIdempotentRerun:
    def test_existing_client_id_is_sent_and_name_is_omitted(self, capsys):
        config, request = _run_registration(
            config={
                "dashboard": {
                    "oauth": {"client_id": "agent:selfhost-1"}
                }
            }
        )

        assert request["body"]["client_id"] == "agent:selfhost-1"
        assert "name" not in request["body"]
        assert config["dashboard"]["oauth"]["client_id"] == "agent:selfhost-1"
        assert "Updated dashboard" in capsys.readouterr().out

    def test_explicit_name_is_sent_on_update(self):
        _, request = _run_registration(
            args=_ns(name="renamed_dashboard"),
            config={
                "dashboard": {
                    "oauth": {"client_id": "agent:selfhost-1"}
                }
            },
        )

        assert request["body"]["name"] == "renamed_dashboard"

    def test_stale_client_id_is_replaced_with_portal_result(self, capsys):
        config, request = _run_registration(
            config={
                "dashboard": {
                    "oauth": {"client_id": "agent:stale"}
                }
            },
            response=_portal_response(client_id="agent:selfhost-new"),
        )

        assert request["body"]["client_id"] == "agent:stale"
        assert config["dashboard"]["oauth"]["client_id"] == "agent:selfhost-new"
        assert "Registered dashboard" in capsys.readouterr().out


class TestPortalResolution:
    def test_override_arg_wins(self):
        assert (
            dr._resolve_portal_base_url("https://preview.example.com/")
            == "https://preview.example.com"
        )

    def test_falls_back_to_stored_login_portal(self):
        with patch(
            "fabric_cli.auth.get_provider_auth_state",
            return_value={"portal_base_url": "https://portal.staging-nousresearch.com"},
        ):
            assert (
                dr._resolve_portal_base_url(None)
                == "https://portal.staging-nousresearch.com"
            )

    def test_blank_override_is_ignored(self):
        with patch(
            "fabric_cli.auth.get_provider_auth_state",
            return_value={"portal_base_url": "https://portal.staging-nousresearch.com"},
        ):
            assert (
                dr._resolve_portal_base_url("   ")
                == "https://portal.staging-nousresearch.com"
            )


class TestPortalErrors:
    def _run_http_error(self, code, body):
        error = urllib.error.HTTPError(
            url="https://portal.nousresearch.com/api/oauth/self-hosted-client",
            code=code,
            msg="error",
            hdrs=None,
            fp=BytesIO(json.dumps(body).encode()),
        )
        with (
            patch(
                "fabric_cli.auth.resolve_nous_access_token",
                return_value="tok",
                create=True,
            ),
            patch("fabric_cli.config.is_managed", return_value=False),
            patch("fabric_cli.config.load_config", return_value={}),
            patch.object(
                dr, "_resolve_portal_base_url",
                return_value="https://portal.nousresearch.com",
            ),
            patch.object(dr.urllib.request, "urlopen", side_effect=error),
            pytest.raises(SystemExit) as exc,
        ):
            dr.cmd_dashboard_register(_ns())
        return exc.value.code

    def test_401_maps_to_reauthentication_message(self, capsys):
        assert self._run_http_error(401, {"error": "invalid_token"}) == 1
        assert "re-authenticate" in capsys.readouterr().out

    def test_403_surfaces_server_detail(self, capsys):
        assert self._run_http_error(
            403,
            {
                "error": "access_denied",
                "error_description": "Not permitted here.",
            },
        ) == 1
        assert "Not permitted here." in capsys.readouterr().out
