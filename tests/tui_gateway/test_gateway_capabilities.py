"""Behavioral contract for mobile gateway capability negotiation."""

from fabric_cli import __release_date__, __version__
from tui_gateway import server
from tui_gateway.gateway_capabilities import (
    FEATURE_METHODS,
    GATEWAY_CONTRACT_VERSION,
    GATEWAY_MIN_COMPATIBLE,
    MOBILE_METHODS,
    build_gateway_capabilities,
)


def _build(registered_methods) -> dict:
    return build_gateway_capabilities(
        registered_methods,
        version="9.8.7",
        release_date="2099.12.31",
    )


def test_builder_returns_versioned_execution_contract() -> None:
    payload = _build(MOBILE_METHODS)

    assert payload["contract"] == {
        "name": "fabric.gateway",
        "version": GATEWAY_CONTRACT_VERSION,
        "min_compatible": GATEWAY_MIN_COMPATIBLE,
    }
    assert payload["server"] == {
        "version": "9.8.7",
        "release_date": "2099.12.31",
    }
    assert payload["execution"] == {
        "location": "gateway",
        "tool_execution": "gateway",
        "survives_client_disconnect": True,
        "survives_gateway_restart": False,
        "requires_gateway_host_online": True,
    }


def test_builder_advertises_only_registered_curated_methods_in_order() -> None:
    registered = set(reversed(MOBILE_METHODS))
    registered.update({
        "admin.dump_environment",
        "config.credentials",
        "plugins.inventory",
        "system_prompt.read",
    })

    payload = _build(registered)

    assert payload["methods"] == sorted(payload["methods"])
    assert len(payload["methods"]) == len(set(payload["methods"]))
    assert set(payload["methods"]) == set(MOBILE_METHODS)
    assert not {
        "admin.dump_environment",
        "config.credentials",
        "plugins.inventory",
        "system_prompt.read",
    }.intersection(payload["methods"])


def test_connection_context_is_an_explicit_mobile_projection_not_a_work_release_gate() -> None:
    payload = _build(MOBILE_METHODS)

    assert "connection.context" in payload["methods"]
    assert "durable_work" not in payload["features"]


def test_features_are_derived_from_required_method_relationships() -> None:
    registered = set(MOBILE_METHODS)
    registered.remove("file.attach")
    registered.remove("session.resume")

    payload = _build(registered)

    assert "file.attach" not in payload["methods"]
    assert "session.resume" not in payload["methods"]
    assert payload["features"]["files"] is False
    assert payload["features"]["baseline_chat"] is False
    for feature, required in FEATURE_METHODS.items():
        assert payload["features"][feature] is required.issubset(registered)


def test_mobile_manifest_excludes_gateway_host_voice_rpc_surface() -> None:
    payload = _build(server._methods)

    # These RPCs remain registered for the desktop/gateway host. They capture
    # and play audio on that host, so advertising them as phone voice would be
    # a false mobile capability claim.
    assert {"voice.record", "voice.tts"}.issubset(server._methods)
    assert "voice" not in payload["features"]
    assert "voice.record" not in payload["methods"]
    assert "voice.tts" not in payload["methods"]
    assert "code" not in payload["features"]
    assert payload["features"]["code_session_baseline"] is True


def test_builder_shape_has_no_surface_for_sensitive_gateway_state() -> None:
    payload = _build([
        *MOBILE_METHODS,
        "auth.token.fabric-audit-secret",
        "host./Users/example/private-project",
        "profile.user@example.com",
    ])

    assert set(payload) == {"contract", "server", "execution", "features", "methods"}
    assert set(payload["contract"]) == {"name", "version", "min_compatible"}
    assert set(payload["server"]) == {"version", "release_date"}
    assert set(payload["execution"]) == {
        "location",
        "tool_execution",
        "survives_client_disconnect",
        "survives_gateway_restart",
        "requires_gateway_host_online",
    }
    assert set(payload["features"]) == set(FEATURE_METHODS)
    assert set(payload["methods"]).issubset(MOBILE_METHODS)
    assert "fabric-audit-secret" not in repr(payload)
    assert "/Users/example/private-project" not in repr(payload)
    assert "user@example.com" not in repr(payload)


def test_live_rpc_is_registered_and_advertises_only_live_methods() -> None:
    response = server.handle_request({
        "jsonrpc": "2.0",
        "id": "cap-1",
        "method": "gateway.capabilities",
        "params": {"token": "must-not-be-reflected"},
    })

    assert response is not None
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "cap-1"
    payload = response["result"]
    assert payload["server"] == {
        "version": __version__,
        "release_date": __release_date__,
    }
    assert payload["features"]["baseline_chat"] is True
    assert payload["methods"] == sorted(payload["methods"])
    assert len(payload["methods"]) == len(set(payload["methods"]))
    assert set(payload["methods"]).issubset(server._methods)
    assert "must-not-be-reflected" not in repr(payload)
    for feature, required in FEATURE_METHODS.items():
        assert payload["features"][feature] is required.issubset(server._methods)


def test_missing_live_optional_method_is_omitted_and_disables_feature(
    monkeypatch,
) -> None:
    monkeypatch.delitem(server._methods, "visual.frame")

    payload = server._methods["gateway.capabilities"]("cap-2", {})["result"]

    assert "visual.frame" not in payload["methods"]
    assert payload["features"]["live_view"] is False
    assert payload["features"]["baseline_chat"] is True
