from __future__ import annotations

import threading
import time

from fabric_link.gateway_bridge import LinkGatewayBridge
from fabric_link.protocol import LinkRequest, canonical_dumps
from fabric_link.store import LinkDevice, LinkDeviceStore
from tui_gateway import server

NOW = 1_784_840_000


class OwnerTransport:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    def write(self, obj: dict) -> bool:
        self.frames.append(obj)
        return True

    def close(self) -> None:
        return None


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
        device_id="device_0123456789abcdef01234567",
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
        request_id=method.encode("utf-8")[:16].ljust(16, b"_"),
        idempotency_key=b"i" * 16,
        issued_at=NOW,
        expires_at=NOW + 120,
        method=method,
        params_cbor=canonical_dumps({}),
    )


def live_session(owner: OwnerTransport) -> dict:
    now = time.time()
    return {
        "agent": object(),
        "attached_images": [],
        "cols": 80,
        "created_at": now,
        "history": [],
        "history_lock": threading.RLock(),
        "history_version": 0,
        "inflight_turn": None,
        "last_active": now,
        "profile_home": None,
        "running": False,
        "session_key": "durable-link-session",
        "show_reasoning": False,
        "source": "tui",
        "tool_progress_mode": "all",
        "transport": owner,
    }


def test_bridge_projects_verified_device_context(tmp_path):
    with make_store(tmp_path) as store:
        device = add_device(store)
        bridge = LinkGatewayBridge(machine_identity=store.machine_identity())
        result = bridge.dispatch(device, request("connection.context"), {})
        assert result["authenticated"] is True
        assert result["auth_kind"] == "device"
        assert result["device_id"] == device.device_id
        bridge.close()


def test_bridge_attaches_exact_published_session_and_polls_bounded_events(
    tmp_path,
    monkeypatch,
):
    owner = OwnerTransport()
    sid = "link-live"
    session = live_session(owner)
    monkeypatch.setitem(server._sessions, sid, session)
    published = server.dispatch(
        {
            "jsonrpc": "2.0",
            "id": "publish",
            "method": "session.publish",
            "params": {"session_id": sid},
        },
        transport=owner,
    )
    assert published is not None
    assert published["result"]["published"]

    with make_store(tmp_path) as store:
        device = add_device(store)
        bridge = LinkGatewayBridge(machine_identity=store.machine_identity())
        attached = bridge.dispatch(
            device,
            request("session.attach"),
            {
                "controller_id": device.device_id,
                "session_id": sid,
            },
        )
        assert attached["snapshot"]["session_id"] == sid

        server._emit("message.delta", sid, {"text": "same live stream"})
        page = bridge.dispatch(
            device,
            request("events.poll"),
            {"after_event_seq": 0, "limit": 20, "wait_ms": 1_000},
        )
        assert page["snapshot_required"] is False
        assert page["events"][0]["frame"]["params"]["payload"]["text"] == (
            "same live stream"
        )
        bridge.close()
    session["event_hub"].disable_remote()


def test_dispatch_grant_gets_internal_work_owner_without_exposing_session_create(
    tmp_path,
    monkeypatch,
):
    calls = []

    def create(rid, params):
        calls.append(("session.create", dict(params)))
        return {"id": rid, "jsonrpc": "2.0", "result": {"session_id": "link-work"}}

    def create_job(rid, params):
        calls.append(("job.create", dict(params)))
        return {
            "id": rid,
            "jsonrpc": "2.0",
            "result": {"job": {"job_id": "job-1"}},
        }

    monkeypatch.setitem(server._methods, "session.create", create)
    monkeypatch.setitem(server._methods, "job.create", create_job)
    with make_store(tmp_path) as store:
        device = add_device(store)
        bridge = LinkGatewayBridge(machine_identity=store.machine_identity())
        for suffix in ("one", "two"):
            result = bridge.dispatch(
                device,
                request("job.create"),
                {
                    "idempotency_key": suffix,
                    "kind": "background_prompt",
                    "text": suffix,
                },
            )
            assert result["job"]["job_id"] == "job-1"
        bridge.close()

    assert [name for name, _params in calls].count("session.create") == 1
    job_calls = [params for name, params in calls if name == "job.create"]
    assert [params["session_id"] for params in job_calls] == [
        "link-work",
        "link-work",
    ]
