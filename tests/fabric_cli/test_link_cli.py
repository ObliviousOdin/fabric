from __future__ import annotations

import argparse
import json
import stat
import sys
from argparse import Namespace

from fabric_cli.config import load_config
from fabric_cli.subcommands.link import build_link_parser
from fabric_link.cli import _private_exclusive_write, link_command
from fabric_link.core import LinkCoreUnavailable
from fabric_link.store import LinkDevice, LinkDeviceStore, link_home

NOW = 1_784_840_000


def _add_device(store: LinkDeviceStore) -> LinkDevice:
    handle = b"h" * 32
    marker = b"m" * 32
    store.register_pending(
        handle=handle,
        secret_marker=marker,
        requested_grants=("observe", "chat", "dispatch"),
        created_at=NOW,
        expires_at=NOW + 300,
    )
    device = LinkDevice(
        device_id="device_0123456789abcdef01234567",
        credential_hash=b"c" * 32,
        controller_name="Test phone",
        platform="ios",
        grants=("chat", "dispatch", "observe"),
        group_id=b"g" * 32,
        host_state=b"opaque-host-state",
        relay_public_key=b"r" * 32,
        credential_serial=b"s" * 16,
        admission_certificate=b"signed-certificate",
        status="active",
        created_at=NOW,
        updated_at=NOW,
        revoked_at=None,
        final_remove_commit=None,
    )
    store.consume_pending_and_add_device(
        handle=handle,
        secret_marker=marker,
        device=device,
        now=NOW + 1,
    )
    return device


def test_link_parser_exposes_explicit_local_management_contract():
    parser = argparse.ArgumentParser(prog="fabric")
    subparsers = parser.add_subparsers(dest="command")
    build_link_parser(subparsers, cmd_link=lambda args: args)

    pair = parser.parse_args(
        [
            "link",
            "pair",
            "desktop",
            "--grants",
            "observe,dispatch",
            "--request-file",
            "request.cbor",
            "--response-file",
            "response.cbor",
        ]
    )
    assert pair.controller == "desktop"
    assert pair.grants == "observe,dispatch"

    reset = parser.parse_args(["link", "reset", "--confirm", "ABCD"])
    assert reset.confirm == "ABCD"

    controller = parser.parse_args(
        [
            "link",
            "controller",
            "pair",
            "https://relay.example/link/pair#pair=opaque",
            "--platform",
            "desktop",
        ]
    )
    assert controller.link_action == "controller_pair"
    assert controller.platform == "desktop"

    dispatch = parser.parse_args(
        ["link", "dispatch", "controller_12345678", "Run the checks"]
    )
    assert dispatch.link_action == "dispatch"
    assert dispatch.prompt == "Run the checks"

    service = parser.parse_args(["link", "service", "status", "--json"])
    assert service.link_action == "service"
    assert service.service_action == "status"

    core = parser.parse_args(["link", "core", "status", "--json"])
    assert core.link_action == "core"
    assert core.core_action == "status"

    relay = parser.parse_args(
        [
            "link",
            "relay",
            "serve",
            "--origin",
            "https://relay.example",
            "--database",
            "relay.sqlite3",
        ]
    )
    assert relay.link_action == "relay_serve"


def test_enable_status_disable_and_fingerprint_confirmed_reset(capsys):
    assert link_command(Namespace(link_action="enable", relay="")) == 0
    config = load_config()
    assert config["link"]["enabled"] is True
    assert (link_home() / "route.key").is_file()
    assert (link_home() / "state.sqlite3").is_file()

    assert link_command(Namespace(link_action="status", json_output=True)) == 0
    status = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert status["enabled"] is True
    assert status["initialized"] is True
    fingerprint = status["machine_fingerprint"]

    assert link_command(Namespace(link_action="disable")) == 0
    assert load_config()["link"]["enabled"] is False
    assert (link_home() / "route.key").is_file()

    assert (
        link_command(Namespace(link_action="reset", confirm="WRONG-FINGERPRINT"))
        == 2
    )
    assert link_home().is_dir()

    assert link_command(Namespace(link_action="reset", confirm=fingerprint)) == 0
    assert not (link_home() / "route.key").exists()
    assert not (link_home() / "state.sqlite3").exists()
    assert (link_home() / "broker.lock").is_file()
    assert load_config()["link"]["enabled"] is False


def test_enable_canonicalizes_relay_as_outbound_wss(capsys):
    assert (
        link_command(
            Namespace(
                link_action="enable",
                relay="https://relay.example:443/",
            )
        )
        == 0
    )
    assert load_config()["link"]["relay_url"] == "wss://relay.example/link"
    assert "no social login" in capsys.readouterr().out


def test_devices_and_grant_replace_authority_without_display_name_lookup(capsys):
    with LinkDeviceStore() as store:
        device = _add_device(store)

    assert link_command(Namespace(link_action="devices", json_output=True)) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["id"] == device.device_id
    assert listed[0]["grants"] == ["chat", "dispatch", "observe"]

    assert (
        link_command(
            Namespace(
                link_action="grant",
                device=device.device_id[:18],
                preset="observe",
                grants="",
                approve=True,
            )
        )
        == 0
    )
    with LinkDeviceStore() as store:
        updated = store.get_device(device.device_id)
    assert updated is not None
    assert updated.grants == ("approve", "observe")


def test_revoke_denies_locally_when_native_mls_cleanup_is_unavailable(
    monkeypatch,
    capsys,
):
    with LinkDeviceStore() as store:
        device = _add_device(store)

    monkeypatch.setattr(
        "fabric_link.cli.load_openmls_core",
        lambda: (_ for _ in ()).throw(LinkCoreUnavailable("not installed")),
    )
    result = link_command(
        Namespace(link_action="revoke", device=device.device_id, yes=True)
    )

    assert result == 2
    with LinkDeviceStore() as store:
        denied = store.get_device(device.device_id)
    assert denied is not None
    assert denied.status == "revoked"
    assert denied.final_remove_commit is None
    assert "denied locally" in capsys.readouterr().out


def test_pair_without_configured_relay_fails_before_native_load(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        "fabric_link.cli.load_openmls_core",
        lambda: (_ for _ in ()).throw(AssertionError("must not load native core")),
    )
    result = link_command(
            Namespace(
                link_action="pair",
                request_file="",
                response_file="",
                grants="observe,chat,dispatch",
                relay="",
            )
    )
    assert result == 2
    assert "relay_not_configured" in capsys.readouterr().out


def test_manual_file_pairing_does_not_connect_to_the_relay(
    monkeypatch,
    tmp_path,
    capsys,
):
    request_path = tmp_path / "request.cbor"
    response_path = tmp_path / "response.cbor"
    request_path.write_bytes(b"encrypted-request")

    class OfflineStore:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def machine_identity(self):
            return Namespace(fingerprint="AA:BB:CC")

    class OfflinePayload:
        handle = b"h" * 32
        expires_at = NOW + 300

        def to_url(self):
            return "fabric-link-v3://pair#offline"

    class OfflineEnrollmentManager:
        def __init__(self, *, store, core):
            assert isinstance(store, OfflineStore)
            assert core == "native-core"

        def open_pairing(self, **_kwargs):
            return OfflinePayload()

        def receive_request(self, encrypted_request, *, now):
            assert encrypted_request == b"encrypted-request"
            assert isinstance(now, int)
            return Namespace(
                controller_name="Test phone",
                platform="ios",
                device_fingerprint="11:22:33",
                short_auth_string="alpha beta gamma",
                requested_grants=("observe", "chat"),
            )

        def approve(self, **_kwargs):
            return b"encrypted-response"

        def deny(self, **_kwargs):
            raise AssertionError("valid manual pairing must not be denied")

    monkeypatch.setattr("fabric_link.cli.LinkDeviceStore", OfflineStore)
    monkeypatch.setattr(
        "fabric_link.cli.EnrollmentManager",
        OfflineEnrollmentManager,
    )
    monkeypatch.setattr(
        "fabric_link.cli.load_openmls_core",
        lambda: "native-core",
    )
    monkeypatch.setattr(
        "fabric_link.cli._link_config",
        lambda: (
            {},
            {
                "relay_url": "wss://relay.example/link",
                "enrollment_ttl_seconds": 300,
            },
        ),
    )
    monkeypatch.setattr("fabric_link.cli._render_qr", lambda _value: None)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    monkeypatch.setattr(
        "fabric_link.cli.LinkRelayClient",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("manual file pairing must not contact the relay")
        ),
    )

    result = link_command(
        Namespace(
            link_action="pair",
            request_file=str(request_path),
            response_file=str(response_path),
            grants="observe,chat",
            relay="",
            controller="mobile",
            name="",
        )
    )

    assert result == 0
    assert response_path.read_bytes() == b"encrypted-response"
    assert "Controller paired" in capsys.readouterr().out


def test_private_response_write_is_owner_only_and_never_overwrites(tmp_path):
    path = tmp_path / "response.cbor"
    _private_exclusive_write(path, b"encrypted")
    assert path.read_bytes() == b"encrypted"
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    try:
        _private_exclusive_write(path, b"replacement")
    except Exception as exc:
        assert getattr(exc, "code", "") == "response_file_exists"
    else:
        raise AssertionError("existing response file must not be overwritten")
    assert path.read_bytes() == b"encrypted"
