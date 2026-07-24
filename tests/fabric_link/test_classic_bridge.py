from __future__ import annotations

from fabric_cli.classic_remote_control import ClassicRemoteControlHost
from fabric_link.classic_bridge import ClassicLinkGatewayBridge
from fabric_link.protocol import LinkRequest, canonical_dumps
from fabric_link.store import LinkDevice, LinkDeviceStore

NOW = 1_784_840_000


def make_store(tmp_path) -> LinkDeviceStore:
    root = tmp_path / "link"
    return LinkDeviceStore(
        db_path=root / "state.sqlite3",
        key_path=root / "route.key",
    )


def add_device(store: LinkDeviceStore) -> LinkDevice:
    store.register_pending(
        handle=b"h" * 32,
        secret_marker=b"s" * 32,
        requested_grants=("chat", "observe"),
        created_at=NOW,
        expires_at=NOW + 300,
    )
    device = LinkDevice(
        device_id="device_abcdef0123456789abcdef01",
        credential_hash=b"c" * 32,
        controller_name="Phone",
        platform="ios",
        grants=("chat", "observe"),
        group_id=b"g" * 32,
        host_state=b"state",
        relay_public_key=b"k" * 32,
        credential_serial=b"z" * 16,
        admission_certificate=b"certificate",
        status="active",
        created_at=NOW,
        updated_at=NOW,
        revoked_at=None,
        final_remove_commit=None,
    )
    store.consume_pending_and_add_device(
        handle=b"h" * 32,
        secret_marker=b"s" * 32,
        device=device,
        now=NOW + 1,
    )
    return device


def request(method: str) -> LinkRequest:
    return LinkRequest(
        request_id=method.encode()[:16].ljust(16, b"_"),
        idempotency_key=b"i" * 16,
        issued_at=NOW,
        expires_at=NOW + 120,
        method=method,
        params_cbor=canonical_dumps({}),
    )


def test_classic_bridge_discovers_attaches_streams_and_submits_exact_session(
    tmp_path,
):
    accepted = []
    host = ClassicRemoteControlHost(
        session_id="classic-live",
        snapshot_builder=lambda: {
            "messages": [{"role": "assistant", "text": "Current terminal"}],
            "running": False,
            "session_id": "classic-live",
            "session_key": "durable-classic",
            "status": "idle",
        },
        accepted_input=accepted.append,
    )
    host.start()
    try:
        with make_store(tmp_path) as store:
            device = add_device(store)
            bridge = ClassicLinkGatewayBridge(
                host=host,
                machine_identity=store.machine_identity(),
            )
            active = bridge.dispatch(
                device,
                request("session.active_list"),
                {},
            )
            assert active["sessions"][0]["id"] == "classic-live"

            attached = bridge.dispatch(
                device,
                request("session.attach"),
                {
                    "controller_id": device.device_id,
                    "session_id": "classic-live",
                },
            )
            assert attached["snapshot"]["session_key"] == "durable-classic"

            host.emit("message.delta", {"text": "same live terminal"})
            page = bridge.dispatch(
                device,
                request("events.poll"),
                {"after_event_seq": 0, "limit": 20, "wait_ms": 1_000},
            )
            assert page["events"][0]["frame"]["params"]["payload"]["text"] == (
                "same live terminal"
            )

            receipt = bridge.dispatch(
                device,
                request("session.input.submit"),
                {
                    "controller_id": device.device_id,
                    "request_id": "controller-turn-1",
                    "session_id": "classic-live",
                    "text": "continue",
                },
            )
            assert receipt["status"] == "streaming"
            assert accepted[0].payload == "continue"
            bridge.close()
    finally:
        host.stop(require_idle=False)
