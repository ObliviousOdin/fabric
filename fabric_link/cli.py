"""Local command implementation for ``fabric link``."""

from __future__ import annotations

import io
import json
import os
import secrets
import time
from argparse import Namespace
from pathlib import Path
from urllib.parse import urlsplit

from fabric_cli.config import load_config, save_config

from .capabilities import DEFAULT_GRANTS, normalize_grants
from .core import LinkCoreUnavailable, load_openmls_core
from .core_install import (
    LinkCoreInstallError,
    core_status,
    install_from_source,
    install_release_wheel,
)
from .controller import (
    LinkControllerError,
)
from .broker import BrokerOwnershipLease, LinkBrokerError
from .controller_manager import (
    controller_profiles,
    dispatch_controller_work,
    finish_controller_pairing,
    invoke_controller,
    list_controller_profiles,
    start_controller_pairing,
)
from .controller_profile import ControllerProfileError
from .controller_store import LinkControllerStateError
from .enrollment import (
    EnrollmentManager,
    LinkEnrollmentError,
    LinkRevocationIncomplete,
    revoke_device,
)
from .protocol import normalize_relay_origin
from .relay_auth import create_host_authentication, create_relay_revocation
from .relay_client import LinkRelayClient, LinkRelayClientError
from .relay_contract import (
    RelayEnrollmentAcknowledgement,
    RelayEnrollmentMailbox,
    RelayEnrollmentPoll,
    RelayEnrollmentPublish,
)
from .relay_service import BlindRelayError
from .service import LinkServiceError, LinkServiceManager
from .store import (
    LinkDevice,
    LinkDeviceStore,
    LinkStorageError,
    credential_fingerprint,
    link_db_path,
    link_home,
    route_key_path,
)

_LINK_CONFIG_KEYS = {
    ("link", "enabled"),
    ("link", "relay_url"),
    ("link", "default_grants"),
    ("link", "enrollment_ttl_seconds"),
    ("link", "request_ttl_seconds"),
    ("link", "stale_device_days"),
}
_HOST_RESET_FILES = frozenset(
    {
        "state.sqlite3",
        "state.sqlite3-wal",
        "state.sqlite3-shm",
        "route.key",
    }
)
_PRESERVED_LINK_FILES = frozenset(
    {
        "broker.lock",
        "controllers.sqlite3",
        "controllers.sqlite3-wal",
        "controllers.sqlite3-shm",
    }
)


def _link_config() -> tuple[dict, dict]:
    config = load_config()
    section = config.get("link")
    if not isinstance(section, dict):
        section = {}
        config["link"] = section
    return config, section


def _save_link_config(config: dict) -> None:
    save_config(config, preserve_keys=_LINK_CONFIG_KEYS)


def _parse_grants(value: str) -> tuple[str, ...]:
    return normalize_grants(
        item.strip() for item in str(value or "").split(",") if item.strip()
    )


def _relay_origin(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise LinkEnrollmentError("relay_not_configured")
    parsed = urlsplit(raw)
    if parsed.scheme == "wss":
        if parsed.path not in {"", "/", "/link"} or parsed.query or parsed.fragment:
            raise LinkEnrollmentError("invalid_relay_url")
        raw = f"https://{parsed.netloc}"
    try:
        return normalize_relay_origin(raw)
    except Exception as exc:
        raise LinkEnrollmentError("invalid_relay_url") from exc


def _relay_config_url(value: str) -> str:
    origin = _relay_origin(value)
    parsed = urlsplit(origin)
    return f"wss://{parsed.netloc}/link"


def _configured_relay(section: dict, override: str = "") -> str:
    return _relay_origin(override or str(section.get("relay_url", "") or ""))


def _render_qr(value: str) -> str | None:
    try:
        import qrcode

        qr = qrcode.QRCode(border=4)
        qr.add_data(value)
        qr.make(fit=True)
        output = io.StringIO()
        qr.print_ascii(out=output, invert=True)
        return output.getvalue()
    except Exception:
        return None


def _device_ref(store: LinkDeviceStore, reference: str) -> LinkDevice:
    exact = store.get_device(reference)
    if exact is not None:
        return exact
    if len(reference) < 8:
        raise LinkStorageError("device_reference_too_short")
    matches = [
        device
        for device in store.list_devices()
        if device.device_id.startswith(reference)
        or credential_fingerprint(device.credential_hash) == reference.upper()
    ]
    if len(matches) != 1:
        raise LinkStorageError(
            "device_not_found" if not matches else "device_reference_ambiguous"
        )
    return matches[0]


def _private_exclusive_write(path: Path, content: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise LinkStorageError("response_file_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise LinkStorageError("response_file_exists") from exc
    except OSError as exc:
        raise LinkStorageError("response_file_create_failed") from exc
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _enable(args: Namespace) -> int:
    config, section = _link_config()
    relay = str(getattr(args, "relay", "") or "").strip()
    if relay:
        section["relay_url"] = _relay_config_url(relay)
    with LinkDeviceStore() as store:
        identity = store.machine_identity()
    section["enabled"] = True
    _save_link_config(config)
    print("\n  ✓ Fabric Link enabled")
    print(f"  Machine fingerprint: {identity.fingerprint}")
    if section.get("relay_url"):
        print(f"  Relay: {section['relay_url']}")
    else:
        print("  Relay: configure later (no network connection is started)")
    print("  Authentication: per-device keys + local approval; no social login.\n")
    return 0


def _disable() -> int:
    config, section = _link_config()
    section["enabled"] = False
    _save_link_config(config)
    print("\n  ✓ Fabric Link disabled")
    print("  Machine identity, grants, and paired devices were preserved.\n")
    return 0


def _status(args: Namespace) -> int:
    _config, section = _link_config()
    initialized = link_db_path().is_file() and route_key_path().is_file()
    payload: dict[str, object] = {
        "enabled": bool(section.get("enabled", False)),
        "initialized": initialized,
        "relay": str(section.get("relay_url", "") or ""),
        "machine_fingerprint": None,
        "devices": 0,
        "active_devices": 0,
        "cleanup_pending": 0,
    }
    if initialized:
        with LinkDeviceStore() as store:
            identity = store.machine_identity()
            devices = store.list_devices()
        payload.update(
            {
                "machine_fingerprint": identity.fingerprint,
                "devices": len(devices),
                "active_devices": sum(
                    device.status == "active" for device in devices
                ),
                "cleanup_pending": sum(
                    device.status == "revoked"
                    and device.final_remove_commit is None
                    for device in devices
                ),
            }
        )
    if getattr(args, "json_output", False):
        print(json.dumps(payload, sort_keys=True))
        return 0
    state = "enabled" if payload["enabled"] else "disabled"
    print(f"\n  Fabric Link: {state}")
    if initialized:
        print(f"  Machine fingerprint: {payload['machine_fingerprint']}")
        print(
            f"  Controllers: {payload['active_devices']} active / "
            f"{payload['devices']} total"
        )
        if payload["cleanup_pending"]:
            print(f"  MLS cleanup pending: {payload['cleanup_pending']}")
    else:
        print("  Identity: not initialized")
    print(f"  Relay: {payload['relay'] or 'not configured'}")
    print("  Network listener: none\n")
    return 0


def _core(args: Namespace) -> int:
    action = str(getattr(args, "core_action", "") or "status")
    if action == "install":
        wheel = str(getattr(args, "wheel", "") or "").strip()
        if wheel:
            status = install_release_wheel(
                Path(wheel),
                expected_sha256=str(getattr(args, "sha256", "") or ""),
            )
        elif getattr(args, "from_source", False):
            status = install_from_source()
        else:
            raise LinkCoreInstallError("native_core_install_source_required")
        print(
            "\n  ✓ Fabric Link native core installed"
            f"\n  Protocol: v{status.protocol_version}"
            f"\n  Ciphersuite: {status.ciphersuite}"
            f"\n  Module: {status.module_path}\n"
        )
        return 0
    if action != "status":
        raise LinkCoreInstallError("unknown_native_core_action")
    status = core_status()
    if getattr(args, "json_output", False):
        print(json.dumps(status.to_dict(), sort_keys=True))
        return 0 if status.installed else 2
    if not status.installed:
        print("\n  Fabric Link native core: not installed")
        print("  Run `fabric link core install --from-source` from a checkout,")
        print("  or install the matching release wheel with its SHA-256.\n")
        return 2
    print("\n  Fabric Link native core: ready")
    print(f"  Version: {status.package_version or 'source build'}")
    print(f"  Protocol: v{status.protocol_version}")
    print(f"  Ciphersuite: {status.ciphersuite}")
    print(f"  Module: {status.module_path}\n")
    return 0


def _devices(args: Namespace) -> int:
    if not link_db_path().is_file():
        devices: list[LinkDevice] = []
    else:
        with LinkDeviceStore() as store:
            devices = store.list_devices()
    if getattr(args, "json_output", False):
        print(
            json.dumps(
                [
                    {
                        "id": device.device_id,
                        "name": device.controller_name,
                        "platform": device.platform,
                        "status": device.status,
                        "grants": list(device.grants),
                        "fingerprint": credential_fingerprint(
                            device.credential_hash
                        ),
                        "cleanup_pending": (
                            device.status == "revoked"
                            and device.final_remove_commit is None
                        ),
                    }
                    for device in devices
                ],
                sort_keys=True,
            )
        )
        return 0
    if not devices:
        print("\n  No paired Fabric Link controllers.\n")
        return 0
    print("\n  Fabric Link controllers")
    for device in devices:
        cleanup = (
            " · MLS cleanup pending"
            if device.status == "revoked" and device.final_remove_commit is None
            else ""
        )
        print(
            f"  {device.device_id}  {device.controller_name} ({device.platform})\n"
            f"    {device.status} · {','.join(device.grants)} · "
            f"{credential_fingerprint(device.credential_hash)}{cleanup}"
        )
    print()
    return 0


def _grant(args: Namespace) -> int:
    preset = str(getattr(args, "preset", "") or "")
    custom = str(getattr(args, "grants", "") or "")
    if bool(preset) == bool(custom):
        raise LinkStorageError("choose_one_grant_mode")
    if preset == "standard":
        grants = DEFAULT_GRANTS
    elif preset == "observe":
        grants = ("observe",)
    elif preset == "dispatch":
        grants = ("observe", "dispatch")
    else:
        grants = _parse_grants(custom)
    if getattr(args, "approve", False):
        grants = normalize_grants((*grants, "approve"))
    with LinkDeviceStore() as store:
        device = _device_ref(store, args.device)
        updated = store.set_grants(device.device_id, grants)
    print(
        f"\n  ✓ Updated {updated.controller_name}: {','.join(updated.grants)}\n"
    )
    return 0


def _revoke(args: Namespace) -> int:
    _config, section = _link_config()
    relay_cleanup_error: Exception | None = None
    with LinkDeviceStore() as store:
        device = _device_ref(store, args.device)
        if device.status == "active" and not getattr(args, "yes", False):
            answer = input(
                f"Revoke {device.controller_name} ({device.device_id})? Type yes: "
            ).strip()
            if answer != "yes":
                print("  Cancelled.")
                return 1
        if device.status == "active":
            device = store.deny_device(device.device_id)
        try:
            core = load_openmls_core()
            updated = revoke_device(
                store=store,
                core=core,
                device_id=device.device_id,
                now=int(time.time()),
            )
        except (LinkCoreUnavailable, LinkRevocationIncomplete) as exc:
            print("\n  ✓ Controller denied locally.")
            print(f"  ! MLS cleanup pending: {exc}\n")
            return 2
        try:
            relay_origin = _configured_relay(section)
            identity = store.machine_identity()
            client = LinkRelayClient(
                relay_origin=relay_origin,
                authentication_factory=lambda challenge: create_host_authentication(
                    machine_identity=identity,
                    challenge=challenge,
                    relay_origin=relay_origin,
                    now=int(time.time()),
                ),
            )
            try:
                client.connect()
                client.revoke(
                    create_relay_revocation(
                        machine_identity=identity,
                        credential_serial=updated.credential_serial,
                        relay_origin=relay_origin,
                        now=int(time.time()),
                    )
                )
                store.mark_relay_revocation_delivered(
                    credential_serial=updated.credential_serial,
                    relay_origin=relay_origin,
                )
            finally:
                client.close()
        except (LinkEnrollmentError, LinkRelayClientError) as exc:
            # Local denial remains authoritative. The broker retries this
            # machine-signed relay revocation the next time it connects.
            relay_cleanup_error = exc
    if relay_cleanup_error is not None:
        print(
            "\n  ✓ Revoked locally and stored the MLS Remove Commit."
            "\n  ! Relay cleanup is pending and will retry automatically: "
            f"{relay_cleanup_error}\n"
        )
        return 2
    print(
        f"\n  ✓ Revoked {updated.controller_name}; local, MLS, and relay "
        "authority were removed.\n"
    )
    return 0


def _pair_manual(args: Namespace) -> int:
    request_value = str(getattr(args, "request_file", "") or "").strip()
    response_value = str(getattr(args, "response_file", "") or "").strip()
    request_path = Path(request_value).expanduser()
    response_path = Path(response_value).expanduser()
    if request_path.is_symlink():
        raise LinkStorageError("request_file_not_regular")
    if response_path.exists() or response_path.is_symlink():
        raise LinkStorageError("response_file_exists")
    core = load_openmls_core()
    _config, section = _link_config()
    grants = _parse_grants(getattr(args, "grants", ""))
    relay = _configured_relay(section, getattr(args, "relay", ""))
    ttl = int(section.get("enrollment_ttl_seconds", 300) or 300)
    with LinkDeviceStore() as store:
        manager = EnrollmentManager(store=store, core=core)
        payload = manager.open_pairing(
            relay=relay,
            requested_grants=grants,
            now=int(time.time()),
            ttl_seconds=ttl,
        )
        pairing_url = payload.to_url()
        identity = store.machine_identity()
        # Register proof-of-possession for the random route before revealing
        # the QR. This closes the otherwise-small first-registration race in
        # which someone who saw the QR could reach a fresh relay first.
        with LinkRelayClient(
            relay_origin=relay,
            authentication_factory=lambda challenge: create_host_authentication(
                machine_identity=identity,
                challenge=challenge,
                relay_origin=relay,
                now=int(time.time()),
            ),
        ):
            pass
        print(f"\n  Fabric Link v3 pairing ({args.controller})")
        print(f"  Machine fingerprint: {store.machine_identity().fingerprint}")
        print(f"  Maximum grants: {','.join(grants)}")
        if getattr(args, "name", ""):
            print(f"  Controller hint: {args.name}")
        rendered = _render_qr(pairing_url)
        if rendered:
            print(rendered)
        print(f"  Pairing link: {pairing_url}")
        print(f"  Waiting for encrypted request: {request_path}")
        deadline = payload.expires_at
        while not request_path.is_file():
            if int(time.time()) >= deadline:
                manager.deny(handle=payload.handle)
                raise LinkEnrollmentError("enrollment_expired")
            time.sleep(0.25)
        if request_path.stat().st_size > 256 * 1024:
            manager.deny(handle=payload.handle)
            raise LinkEnrollmentError("enrollment_record_too_large")
        approval = manager.receive_request(
            request_path.read_bytes(),
            now=int(time.time()),
        )
        print("\n  Controller requests access:")
        print(f"    Name: {approval.controller_name}")
        print(f"    Platform: {approval.platform}")
        print(f"    Fingerprint: {approval.device_fingerprint}")
        print(f"    Short authentication string: {approval.short_auth_string}")
        print(f"    Grants: {','.join(approval.requested_grants)}")
        try:
            answer = input("  Type yes after comparing the controller screen: ").strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer != "yes":
            manager.deny(handle=payload.handle)
            print("  Pairing denied.")
            return 1
        response = manager.approve(
            handle=payload.handle,
            approved_grants=approval.requested_grants,
            now=int(time.time()),
        )
        _private_exclusive_write(response_path, response)
    print(f"\n  ✓ Controller paired. Encrypted response: {response_path}\n")
    return 0


def _pair_relay(args: Namespace) -> int:
    _config, section = _link_config()
    grants = _parse_grants(getattr(args, "grants", ""))
    relay = _configured_relay(section, getattr(args, "relay", ""))
    ttl = int(section.get("enrollment_ttl_seconds", 300) or 300)
    core = load_openmls_core()
    now = int(time.time())
    with LinkDeviceStore() as store:
        manager = EnrollmentManager(store=store, core=core)
        payload = manager.open_pairing(
            relay=relay,
            requested_grants=grants,
            now=now,
            ttl_seconds=ttl,
        )
        identity = store.machine_identity()
        pairing_url = payload.to_url()
        print(f"\n  Fabric Link v3 pairing ({args.controller})")
        print(f"  Machine fingerprint: {identity.fingerprint}")
        print(f"  Maximum grants: {','.join(grants)}")
        if getattr(args, "name", ""):
            print(f"  Controller hint: {args.name}")
        rendered = _render_qr(pairing_url)
        if rendered:
            print(rendered)
        print(f"  Pairing link: {pairing_url}")
        print("  Waiting for the encrypted controller request through the relay…")

        with LinkRelayClient(
            relay_origin=relay,
            authentication_factory=lambda challenge: create_host_authentication(
                machine_identity=identity,
                challenge=challenge,
                relay_origin=relay,
                now=int(time.time()),
            ),
        ) as client:
            mailbox = RelayEnrollmentMailbox(
                route_id=payload.route,
                pairing_handle=payload.handle,
                recipient="host",
            )
            delivery = None
            after_sequence = 0
            while int(time.time()) < payload.expires_at:
                deliveries, sync = client.poll_enrollment(
                    RelayEnrollmentPoll(
                        mailbox=mailbox,
                        request_id=secrets.token_bytes(16),
                        after_sequence=after_sequence,
                    )
                )
                after_sequence = max(after_sequence, sync.high_watermark)
                if deliveries:
                    delivery = deliveries[0]
                    break
                time.sleep(0.25)
            if delivery is None:
                manager.deny(handle=payload.handle)
                raise LinkEnrollmentError("enrollment_expired")
            approval = manager.receive_request(
                delivery.opaque_record,
                now=int(time.time()),
            )
            print("\n  Controller requests access:")
            print(f"    Name: {approval.controller_name}")
            print(f"    Platform: {approval.platform}")
            print(f"    Fingerprint: {approval.device_fingerprint}")
            print(f"    Short authentication string: {approval.short_auth_string}")
            print(f"    Grants: {','.join(approval.requested_grants)}")
            try:
                answer = input(
                    "  Type yes after comparing the controller screen: "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                answer = ""
            if answer != "yes":
                manager.deny(handle=payload.handle)
                client.acknowledge_enrollment(
                    RelayEnrollmentAcknowledgement(
                        mailbox=mailbox,
                        sequence=delivery.sequence,
                        message_id=delivery.message_id,
                    )
                )
                print("  Pairing denied.")
                return 1
            response = manager.approve(
                handle=payload.handle,
                approved_grants=approval.requested_grants,
                now=int(time.time()),
            )
            response_mailbox = RelayEnrollmentMailbox(
                route_id=payload.route,
                pairing_handle=payload.handle,
                recipient="controller",
            )
            client.publish_enrollment(
                RelayEnrollmentPublish(
                    mailbox=response_mailbox,
                    message_id=delivery.message_id,
                    expires_at=payload.expires_at,
                    opaque_record=response,
                )
            )
            client.acknowledge_enrollment(
                RelayEnrollmentAcknowledgement(
                    mailbox=mailbox,
                    sequence=delivery.sequence,
                    message_id=delivery.message_id,
                )
            )
    print("\n  ✓ Controller paired through the blind relay.\n")
    return 0


def _pair(args: Namespace) -> int:
    request_value = str(getattr(args, "request_file", "") or "").strip()
    response_value = str(getattr(args, "response_file", "") or "").strip()
    if bool(request_value) != bool(response_value):
        raise LinkEnrollmentError("manual_pairing_files_incomplete")
    if request_value:
        return _pair_manual(args)
    return _pair_relay(args)


def _controller_pair(args: Namespace) -> int:
    start = start_controller_pairing(
        pairing_url=str(args.pairing_url),
        label=str(args.name),
        platform=str(args.platform),
        requested_grants=_parse_grants(args.grants),
    )
    print("\n  Fabric Link controller enrollment")
    print(f"  Machine fingerprint: {start.machine_fingerprint}")
    print(f"  Short authentication string: {start.short_auth_string}")
    print("  Compare this code with the host before approving.")
    profile = finish_controller_pairing(controller_id=start.controller_id)
    print(f"\n  ✓ Paired controller profile: {profile['id']}")
    print(f"  Grants: {','.join(profile['grants'])}\n")
    return 0


def _controller_list(args: Namespace) -> int:
    payload = list_controller_profiles()
    if getattr(args, "json_output", False):
        print(json.dumps(payload, sort_keys=True))
        return 0
    if not payload:
        print("\n  No Fabric Link controller profiles.\n")
        return 0
    print("\n  Fabric Link machines")
    for item in payload:
        print(
            f"  {item['id']}  {item['label']} · {item['status']}\n"
            f"    {item['relay']} · {','.join(item['grants']) or 'pending'} · "
            f"{item['machine_fingerprint']}"
        )
    print()
    return 0


def _controller_call(args: Namespace) -> int:
    try:
        params = json.loads(str(args.params_json or "{}"))
    except json.JSONDecodeError as exc:
        raise LinkControllerError("invalid_controller_params_json") from exc
    if not isinstance(params, dict):
        raise LinkControllerError("controller_params_must_be_object")
    result = invoke_controller(
        profile_reference=args.controller,
        method=args.method,
        params=params,
        timeout_seconds=float(args.timeout),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _dispatch(args: Namespace) -> int:
    prompt = str(args.prompt or "").strip()
    if not prompt:
        raise LinkControllerError("dispatch_prompt_required")
    result = dispatch_controller_work(
        profile_reference=args.controller,
        prompt=prompt,
        title=str(args.title or "Dispatched from Fabric Link"),
        timeout_seconds=float(args.timeout),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _host(args: Namespace) -> int:
    from .broker import (
        BrokerOwnershipLease,
        FabricLinkBroker,
        LinkBrokerError,
    )

    _config, section = _link_config()
    if not section.get("enabled", False):
        raise LinkBrokerError("link_not_enabled")
    relay = _configured_relay(section, getattr(args, "relay", ""))
    core = load_openmls_core()
    with BrokerOwnershipLease():
        with LinkDeviceStore() as store:
            broker = FabricLinkBroker(
                relay_origin=relay,
                store=store,
                core=core,
            )
            try:
                if getattr(args, "once", False):
                    result = broker.run_once()
                    print(json.dumps(result.__dict__, sort_keys=True))
                    return 0
                print("Fabric Link host is online. Press Ctrl-C to stop.")
                try:
                    broker.run_forever()
                except KeyboardInterrupt:
                    pass
            finally:
                broker.close()
    return 0


def _relay_serve(args: Namespace) -> int:
    from .relay_server import run_reference_relay

    run_reference_relay(
        relay_origin=str(args.origin),
        db_path=Path(args.database).expanduser(),
        bind_host=str(args.bind),
        port=int(args.port),
        behind_tls_proxy=bool(args.behind_tls_proxy),
    )
    return 0


def _service(args: Namespace) -> int:
    service_action = str(getattr(args, "service_action", "") or "status")
    if service_action in {"install", "start", "restart"}:
        _config, section = _link_config()
        if not section.get("enabled", False):
            raise LinkServiceError("link_not_enabled")
        _configured_relay(section)
    workspace_value = str(getattr(args, "workspace", "") or "").strip()
    manager = LinkServiceManager(
        workspace=Path(workspace_value).expanduser() if workspace_value else None,
    )
    status = manager.execute(
        service_action,
        force=bool(getattr(args, "force", False)),
        start_now=bool(getattr(args, "start_now", True)),
        start_on_login=bool(getattr(args, "start_on_login", True)),
    )
    if getattr(args, "json_output", False):
        print(json.dumps(status.to_dict(), sort_keys=True))
        return 0
    installed = "installed" if status.installed else "not installed"
    running = "running" if status.running else "stopped"
    login = "enabled" if status.starts_on_login else "disabled"
    print(f"\n  Fabric Link service: {installed}, {running}")
    print(f"  Manager: {status.manager}")
    print(f"  Start on login: {login}")
    print(f"  Definition: {status.definition}\n")
    return 0


def _reset(args: Namespace) -> int:
    if not link_db_path().is_file() or not route_key_path().is_file():
        raise LinkStorageError("link_not_initialized")
    with LinkDeviceStore() as store:
        fingerprint = store.machine_identity().fingerprint
    if args.confirm != fingerprint:
        raise LinkStorageError("machine_fingerprint_mismatch")
    root = link_home()
    if (
        root.name != "link"
        or root.parent != link_db_path().parent.parent
        or root.is_symlink()
    ):
        raise LinkStorageError("unsafe_reset_path")
    if LinkServiceManager().definition_path.exists():
        raise LinkStorageError("link_service_must_be_uninstalled_before_reset")
    lease = BrokerOwnershipLease(root / "broker.lock")
    with lease:
        entries = list(root.iterdir())
        allowed = _HOST_RESET_FILES | _PRESERVED_LINK_FILES
        unexpected = [entry.name for entry in entries if entry.name not in allowed]
        if unexpected or any(entry.is_dir() or entry.is_symlink() for entry in entries):
            raise LinkStorageError("unexpected_link_state_files")
        config, section = _link_config()
        section["enabled"] = False
        _save_link_config(config)
        for entry in entries:
            if entry.name in _HOST_RESET_FILES:
                entry.unlink()
    print(
        "\n  ✓ Fabric Link host identity and paired-device authority were destroyed."
        "\n  Controller profiles on this machine were preserved.\n"
    )
    return 0


def link_command(args: Namespace) -> int:
    action = getattr(args, "link_action", None) or "status"
    try:
        if action in {"setup", "enable"}:
            return _enable(args)
        if action == "disable":
            return _disable()
        if action == "status":
            return _status(args)
        if action == "core":
            return _core(args)
        if action == "pair":
            return _pair(args)
        if action == "devices":
            return _devices(args)
        if action == "grant":
            return _grant(args)
        if action == "revoke":
            return _revoke(args)
        if action == "controller_pair":
            return _controller_pair(args)
        if action == "controller_list":
            return _controller_list(args)
        if action == "call":
            return _controller_call(args)
        if action == "dispatch":
            return _dispatch(args)
        if action == "host":
            return _host(args)
        if action == "relay_serve":
            return _relay_serve(args)
        if action == "service":
            return _service(args)
        if action == "reset":
            return _reset(args)
        raise LinkStorageError("unknown_link_action")
    except (
        BlindRelayError,
        ControllerProfileError,
        LinkCoreUnavailable,
        LinkBrokerError,
        LinkControllerError,
        LinkControllerStateError,
        LinkCoreInstallError,
        LinkEnrollmentError,
        LinkRelayClientError,
        LinkServiceError,
        LinkStorageError,
        ValueError,
    ) as exc:
        code = getattr(exc, "code", str(exc))
        print(f"Fabric Link error: {code}")
        return 2
