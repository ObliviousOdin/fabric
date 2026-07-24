from __future__ import annotations

import asyncio
import copy
import json
import threading
import time

from fabric_cli import mcp_startup
from tui_gateway import server
from tui_gateway import ws as ws_mod


class RecordingTransport:
    def __init__(self) -> None:
        self.frames: list[dict] = []
        self.closed = False
        self._lock = threading.Lock()

    def write(self, obj: dict) -> bool:
        with self._lock:
            self.frames.append(copy.deepcopy(obj))
        return True

    def close(self) -> None:
        self.closed = True


def _session(owner: RecordingTransport) -> dict:
    now = time.time()
    return {
        "agent": object(),
        "attached_images": [],
        "cols": 80,
        "created_at": now,
        "history": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
        "history_lock": threading.RLock(),
        "history_version": 1,
        "inflight_turn": None,
        "last_active": now,
        "profile_home": None,
        "running": False,
        "session_key": "durable-remote",
        "show_reasoning": False,
        "source": "tui",
        "tool_progress_mode": "all",
        "transport": owner,
    }


def _rpc(
    method: str,
    params: dict,
    *,
    transport: RecordingTransport,
    rid: str = "rpc",
) -> dict:
    response = server.dispatch(
        {
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
            "params": params,
        },
        transport=transport,
    )
    assert response is not None
    return response


def test_publish_attach_stream_detach_preserves_owner_transport(monkeypatch) -> None:
    sid = "live-remote"
    owner = RecordingTransport()
    phone = RecordingTransport()
    session = _session(owner)
    monkeypatch.setitem(server._sessions, sid, session)

    published = _rpc(
        "session.publish",
        {"session_id": sid},
        transport=owner,
    )["result"]
    assert published["published"] is True
    assert published["owner"] is True
    assert published["attached_controllers"] == []

    attached = _rpc(
        "session.attach",
        {"session_id": sid, "controller_id": "phone-1"},
        transport=phone,
    )["result"]
    assert attached["snapshot_seq"] == 0
    assert attached["snapshot"]["session_id"] == sid
    assert attached["snapshot"]["messages"] == [
        {"role": "user", "text": "hello"},
        {"role": "assistant", "text": "hi"},
    ]
    assert session["transport"] is owner
    assert session["event_hub"].owner_transport is owner

    server._emit("message.delta", sid, {"text": "same stream"})
    deadline = time.monotonic() + 2
    while len(phone.frames) < 1 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert owner.frames == phone.frames
    assert owner.frames[0]["params"]["publication"] == {
        "event_seq": 1,
        "generation": published["generation"],
    }

    status = _rpc(
        "session.remote_status",
        {"session_id": sid},
        transport=phone,
    )["result"]
    assert status["owner"] is False
    assert status["subscriber_id"] == "phone-1"

    detached = _rpc(
        "session.detach",
        {"session_id": sid, "controller_id": "phone-1"},
        transport=phone,
    )["result"]
    assert detached["detached"] is True
    assert phone.closed is False
    assert session["transport"] is owner
    session["event_hub"].disable_remote()


def test_subscriber_cannot_take_owner_or_publish(monkeypatch) -> None:
    sid = "live-owner-fence"
    owner = RecordingTransport()
    phone = RecordingTransport()
    session = _session(owner)
    monkeypatch.setitem(server._sessions, sid, session)

    _rpc("session.publish", {"session_id": sid}, transport=owner)
    _rpc(
        "session.attach",
        {"session_id": sid, "controller_id": "phone-1"},
        transport=phone,
    )

    denied = _rpc(
        "session.publish",
        {"session_id": sid},
        transport=phone,
    )
    assert denied["error"]["code"] == 4030
    assert session["transport"] is owner
    assert session["event_hub"].owner_transport is owner
    session["event_hub"].disable_remote()


def test_remote_control_rpc_rejects_non_loopback_websocket_peer(
    monkeypatch,
) -> None:
    sid = "live-local-only"

    class RemotePeerTransport(RecordingTransport):
        peer_host = "203.0.113.20"

    remote_peer = RemotePeerTransport()
    session = _session(remote_peer)
    monkeypatch.setitem(server._sessions, sid, session)

    denied = _rpc(
        "session.publish",
        {"session_id": sid},
        transport=remote_peer,
    )
    assert denied["error"]["code"] == 4031
    assert "local-only" in denied["error"]["message"]
    assert session.get("event_hub") is None


def test_disconnect_detaches_subscriber_but_owner_keeps_publication(monkeypatch) -> None:
    sid = "live-disconnect"
    owner = RecordingTransport()
    phone = RecordingTransport()
    session = _session(owner)
    monkeypatch.setitem(server._sessions, sid, session)

    _rpc("session.publish", {"session_id": sid}, transport=owner)
    _rpc(
        "session.attach",
        {"session_id": sid, "controller_id": "phone-1"},
        transport=phone,
    )

    assert server._close_sessions_for_transport(phone) == (0, 0)
    assert session["event_hub"].subscriber_ids == ()
    assert session["event_hub"].published is True
    assert session["transport"] is owner
    session["event_hub"].disable_remote()


def test_owner_disconnect_ends_publication_and_closes_subscribers(monkeypatch) -> None:
    sid = "live-owner-disconnect"
    owner = RecordingTransport()
    phone = RecordingTransport()
    session = _session(owner)
    monkeypatch.setitem(server._sessions, sid, session)
    monkeypatch.setattr(server, "_WS_ORPHAN_REAP_GRACE_S", 0)

    _rpc("session.publish", {"session_id": sid}, transport=owner)
    _rpc(
        "session.attach",
        {"session_id": sid, "controller_id": "phone-1"},
        transport=phone,
    )

    assert server._close_sessions_for_transport(owner) == (0, 1)
    assert session["event_hub"].published is False
    assert session["event_hub"].subscriber_ids == ()
    assert session["transport"] is server._detached_ws_transport
    assert phone.closed is True


def test_attach_snapshot_includes_pending_interactions(monkeypatch) -> None:
    sid = "live-pending-snapshot"
    owner = RecordingTransport()
    phone = RecordingTransport()
    session = _session(owner)
    request_id = "clarify-1"
    pending_event = threading.Event()
    monkeypatch.setitem(server._sessions, sid, session)
    monkeypatch.setitem(server._pending, request_id, (sid, pending_event))
    monkeypatch.setitem(
        server._pending_prompt_payloads,
        request_id,
        (
            "clarify.request",
            {
                "question": "Which machine?",
                "request_id": request_id,
            },
        ),
    )

    _rpc("session.publish", {"session_id": sid}, transport=owner)
    attached = _rpc(
        "session.attach",
        {"session_id": sid, "controller_id": "phone-1"},
        transport=phone,
    )["result"]

    assert attached["snapshot"]["pending_interactions"] == [
        {
            "type": "clarify.request",
            "payload": {
                "question": "Which machine?",
                "request_id": request_id,
            },
        }
    ]
    session["event_hub"].disable_remote()


def test_owner_resume_rebinds_hub_without_changing_generation(monkeypatch) -> None:
    sid = "live-rebind"
    first_owner = RecordingTransport()
    reconnected_owner = RecordingTransport()
    session = _session(first_owner)
    monkeypatch.setitem(server._sessions, sid, session)

    published = _rpc(
        "session.publish",
        {"session_id": sid},
        transport=first_owner,
    )["result"]
    generation = published["generation"]

    payload = server._live_session_payload(
        sid,
        session,
        transport=reconnected_owner,
    )
    assert payload["session_id"] == sid
    assert session["transport"] is reconnected_owner
    assert session["event_hub"].owner_transport is reconnected_owner
    assert session["event_hub"].generation == generation
    session["event_hub"].disable_remote()


def test_live_published_owner_cannot_be_replaced_by_resume_or_activate(
    monkeypatch,
) -> None:
    sid = "live-owner-protected"
    owner = RecordingTransport()
    other = RecordingTransport()
    session = _session(owner)
    monkeypatch.setitem(server._sessions, sid, session)
    monkeypatch.setattr(server, "_get_db", lambda: object())

    _rpc("session.publish", {"session_id": sid}, transport=owner)

    transport_token = server.bind_transport(other)
    try:
        resumed = server._methods["session.resume"](
            "resume",
            {"session_id": session["session_key"]},
        )
    finally:
        server.reset_transport(transport_token)
    activated = _rpc(
        "session.activate",
        {"session_id": sid},
        transport=other,
    )

    assert resumed["error"]["code"] == 4091
    assert activated["error"]["code"] == 4091
    assert "session.attach" in resumed["error"]["message"]
    assert session["transport"] is owner
    assert session["event_hub"].owner_transport is owner
    session["event_hub"].disable_remote()


def test_unpublish_detaches_without_killing_reusable_controller_transport(
    monkeypatch,
) -> None:
    sid = "live-unpublish"
    owner = RecordingTransport()
    phone = RecordingTransport()
    session = _session(owner)
    monkeypatch.setitem(server._sessions, sid, session)

    first = _rpc("session.publish", {"session_id": sid}, transport=owner)["result"]
    _rpc(
        "session.attach",
        {"controller_id": "phone-1", "session_id": sid},
        transport=phone,
    )
    disabled = _rpc(
        "session.unpublish",
        {"session_id": sid},
        transport=owner,
    )["result"]
    assert disabled["detached_controllers"] == ["phone-1"]
    assert phone.closed is False

    second = _rpc("session.publish", {"session_id": sid}, transport=owner)["result"]
    assert second["generation"] != first["generation"]
    attached = _rpc(
        "session.attach",
        {"controller_id": "phone-1", "session_id": sid},
        transport=phone,
    )["result"]
    assert attached["generation"] == second["generation"]
    session["event_hub"].disable_remote()


def test_owner_phone_and_desktop_inputs_run_once_on_same_agent(monkeypatch) -> None:
    sid = "live-inputs"
    owner = RecordingTransport()
    phone = RecordingTransport()
    desktop = RecordingTransport()
    first_started = threading.Event()
    release_first = threading.Event()
    calls: list[str] = []

    class Agent:
        model = "remote-test-model"

        def clear_interrupt(self) -> None:
            return None

        def run_conversation(
            self,
            prompt,
            conversation_history=None,
            stream_callback=None,
        ):
            calls.append(prompt)
            if stream_callback is not None:
                stream_callback(f"delta:{prompt}")
            if len(calls) == 1:
                first_started.set()
                assert release_first.wait(2)
            return {
                "final_response": f"reply:{prompt}",
                "messages": [
                    *(conversation_history or []),
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": f"reply:{prompt}"},
                ],
            }

    session = _session(owner)
    agent = Agent()
    session["agent"] = agent
    session["history"] = []
    session["history_version"] = 0
    monkeypatch.setitem(server._sessions, sid, session)
    monkeypatch.setattr(server, "_ensure_session_db_row", lambda _session: None)
    monkeypatch.setattr(server, "_persist_branch_seed", lambda _session: None)
    monkeypatch.setattr(server, "_start_agent_build", lambda _sid, _session: None)
    monkeypatch.setattr(server, "_wait_agent", lambda _session, _rid: None)
    monkeypatch.setattr(server, "_load_busy_input_mode", lambda: "queue")
    monkeypatch.setattr(server, "make_stream_renderer", lambda _cols: None)
    monkeypatch.setattr(server, "render_message", lambda _raw, _cols: None)
    monkeypatch.setattr(server, "_get_db", lambda: None)

    published = _rpc(
        "session.publish",
        {"session_id": sid},
        transport=owner,
    )["result"]
    _rpc(
        "session.attach",
        {"session_id": sid, "controller_id": "phone-1"},
        transport=phone,
    )
    _rpc(
        "session.attach",
        {"session_id": sid, "controller_id": "desktop-2"},
        transport=desktop,
    )

    owner_submit = _rpc(
        "prompt.submit",
        {
            "request_id": "owner-1",
            "session_id": sid,
            "text": "from owner",
        },
        transport=owner,
    )["result"]
    assert owner_submit["receipt"]["state"] == "accepted"
    assert first_started.wait(2)

    phone_submit = _rpc(
        "session.input.submit",
        {
            "controller_id": "phone-1",
            "request_id": "phone-1",
            "session_id": sid,
            "text": "from phone",
        },
        transport=phone,
    )["result"]
    desktop_submit = _rpc(
        "session.input.submit",
        {
            "controller_id": "desktop-2",
            "request_id": "desktop-1",
            "session_id": sid,
            "text": "from desktop",
        },
        transport=desktop,
    )["result"]
    duplicate = _rpc(
        "session.input.submit",
        {
            "controller_id": "phone-1",
            "request_id": "phone-1",
            "session_id": sid,
            "text": "from phone",
        },
        transport=phone,
    )["result"]
    assert phone_submit["receipt"]["state"] == "queued"
    assert desktop_submit["receipt"]["state"] == "queued"
    assert duplicate["receipt"]["state"] == "duplicate"
    assert duplicate["receipt"]["original_state"] == "queued"

    release_first.set()
    deadline = time.monotonic() + 5
    while (
        (
            calls != ["from owner", "from phone", "from desktop"]
            or session.get("running")
            or session["input_arbiter"].active is not None
        )
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)
    assert calls == ["from owner", "from phone", "from desktop"]
    assert session["agent"] is agent
    assert [message["role"] for message in session["history"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert [message["content"] for message in session["history"][::2]] == calls

    deadline = time.monotonic() + 2
    while (
        (len(phone.frames) != len(owner.frames) or len(desktop.frames) != len(owner.frames))
        and time.monotonic() < deadline
    ):
        time.sleep(0.005)
    assert phone.frames == owner.frames == desktop.frames
    assert all(
        frame["params"]["publication"]["generation"] == published["generation"]
        for frame in owner.frames
    )
    starts = [
        frame["params"]["payload"]["input"]
        for frame in owner.frames
        if frame["params"]["type"] == "message.start"
    ]
    assert [
        (start["controller_id"], start["request_id"], start["origin"])
        for start in starts
    ] == [
        ("owner", "owner-1", "owner"),
        ("phone-1", "phone-1", "remote"),
        ("desktop-2", "desktop-1", "remote"),
    ]
    assert len(
        [
            frame
            for frame in owner.frames
            if frame["params"]["type"] == "message.complete"
        ]
    ) == 3
    session["event_hub"].disable_remote()


def test_remote_slash_aliases_execute_in_live_gateway_process(monkeypatch) -> None:
    sid = "live-remote-command"
    owner = RecordingTransport()
    session = _session(owner)
    monkeypatch.setitem(server._sessions, sid, session)

    enabled = _rpc(
        "command.dispatch",
        {"arg": "on", "name": "rc", "session_id": sid},
        transport=owner,
    )["result"]
    assert enabled["remote"]["published"] is True
    assert "exact live session" in enabled["output"]

    transport_token = server.bind_transport(owner)
    try:
        status = server._methods["slash.exec"](
            "slash-status",
            {"command": "remote-control status", "session_id": sid},
        )
    finally:
        server.reset_transport(transport_token)
    assert status["result"]["remote"]["published"] is True
    assert status["result"]["remote"]["generation"] == enabled["remote"]["generation"]

    disabled = _rpc(
        "command.dispatch",
        {"arg": "off", "name": "remote", "session_id": sid},
        transport=owner,
    )["result"]
    assert disabled["remote"]["published"] is False


def test_second_local_websocket_controls_exact_live_session_then_detaches(
    monkeypatch,
) -> None:
    sid = "live-ws-e2e"
    owner = RecordingTransport()
    first_started = threading.Event()
    release_first = threading.Event()
    calls: list[str] = []

    class Agent:
        model = "remote-ws-test-model"

        def clear_interrupt(self) -> None:
            return None

        def run_conversation(
            self,
            prompt,
            conversation_history=None,
            stream_callback=None,
        ):
            calls.append(prompt)
            if stream_callback is not None:
                stream_callback(f"stream:{prompt}")
            if len(calls) == 1:
                first_started.set()
                assert release_first.wait(2)
            return {
                "final_response": f"done:{prompt}",
                "messages": [
                    *(conversation_history or []),
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": f"done:{prompt}"},
                ],
            }

    session = _session(owner)
    agent = Agent()
    session["agent"] = agent
    session["history"] = []
    session["history_version"] = 0
    monkeypatch.setitem(server._sessions, sid, session)
    monkeypatch.setattr(server, "_ensure_session_db_row", lambda _session: None)
    monkeypatch.setattr(server, "_persist_branch_seed", lambda _session: None)
    monkeypatch.setattr(server, "_start_agent_build", lambda _sid, _session: None)
    monkeypatch.setattr(server, "_wait_agent", lambda _session, _rid: None)
    monkeypatch.setattr(server, "_load_busy_input_mode", lambda: "queue")
    monkeypatch.setattr(server, "make_stream_renderer", lambda _cols: None)
    monkeypatch.setattr(server, "render_message", lambda _raw, _cols: None)
    monkeypatch.setattr(server, "_get_db", lambda: None)
    monkeypatch.setattr(
        mcp_startup,
        "start_background_mcp_discovery",
        lambda **_kwargs: None,
    )

    enabled = _rpc(
        "command.dispatch",
        {"arg": "on", "name": "remote", "session_id": sid},
        transport=owner,
    )["result"]
    assert enabled["remote"]["published"] is True

    class LocalWebSocket:
        def __init__(self) -> None:
            self.incoming: asyncio.Queue[str | None] = asyncio.Queue()
            self.sent: list[dict] = []
            self.accepted = False
            self.closed = False
            self.client = type(
                "LoopbackClient",
                (),
                {"host": "127.0.0.1", "port": 49152},
            )()

        async def accept(self) -> None:
            self.accepted = True

        async def send_text(self, line: str) -> None:
            self.sent.append(json.loads(line))

        async def receive_text(self) -> str:
            value = await self.incoming.get()
            if value is None:
                raise ws_mod._WebSocketDisconnect()
            return value

        async def close(self) -> None:
            self.closed = True

        async def request(self, rid: str, method: str, params: dict) -> None:
            await self.incoming.put(
                json.dumps(
                    {
                        "id": rid,
                        "jsonrpc": "2.0",
                        "method": method,
                        "params": params,
                    }
                )
            )

        async def wait_for(self, predicate, timeout: float = 3.0) -> None:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if predicate():
                    return
                await asyncio.sleep(0.005)
            raise AssertionError("websocket condition was not reached before timeout")

    async def scenario() -> None:
        phone = LocalWebSocket()
        task = asyncio.create_task(ws_mod.handle_ws(phone))
        await phone.wait_for(
            lambda: any(
                frame.get("params", {}).get("type") == "gateway.ready"
                for frame in phone.sent
            )
        )
        await phone.request(
            "attach",
            "session.attach",
            {"controller_id": "phone-ws", "session_id": sid},
        )
        await phone.wait_for(
            lambda: any(frame.get("id") == "attach" for frame in phone.sent)
        )
        attach_response = next(
            frame for frame in phone.sent if frame.get("id") == "attach"
        )
        assert attach_response["result"]["snapshot"]["session_id"] == sid
        assert attach_response["result"]["snapshot"]["messages"] == []
        assert session["transport"] is owner

        owner_submit = _rpc(
            "prompt.submit",
            {
                "request_id": "owner-ws-1",
                "session_id": sid,
                "text": "owner first",
            },
            transport=owner,
        )["result"]
        assert owner_submit["receipt"]["state"] == "accepted"
        assert first_started.wait(2)

        await phone.request(
            "phone-input",
            "session.input.submit",
            {
                "controller_id": "phone-ws",
                "request_id": "phone-ws-1",
                "session_id": sid,
                "text": "phone next",
            },
        )
        await phone.wait_for(
            lambda: any(frame.get("id") == "phone-input" for frame in phone.sent)
        )
        input_response = next(
            frame for frame in phone.sent if frame.get("id") == "phone-input"
        )
        assert input_response["result"]["receipt"]["state"] == "queued"

        release_first.set()
        await phone.wait_for(
            lambda: calls == ["owner first", "phone next"]
            and not session.get("running")
            and session["input_arbiter"].active is None,
            timeout=5,
        )
        await phone.wait_for(
            lambda: len(
                [
                    frame
                    for frame in phone.sent
                    if frame.get("params", {}).get("session_id") == sid
                    and frame.get("params", {}).get("type") == "message.complete"
                ]
            )
            == 2,
        )

        await phone.request(
            "detach",
            "session.detach",
            {"controller_id": "phone-ws", "session_id": sid},
        )
        await phone.wait_for(
            lambda: any(frame.get("id") == "detach" for frame in phone.sent)
        )
        detached_at_owner_count = len(owner.frames)
        phone_events = [
            frame
            for frame in phone.sent
            if frame.get("method") == "event"
            and frame.get("params", {}).get("session_id") == sid
        ]
        assert phone_events == owner.frames[:detached_at_owner_count]
        assert session["event_hub"].subscriber_ids == ()
        assert session["transport"] is owner

        after_detach = _rpc(
            "prompt.submit",
            {
                "request_id": "owner-ws-2",
                "session_id": sid,
                "text": "owner after detach",
            },
            transport=owner,
        )["result"]
        assert after_detach["receipt"]["state"] == "accepted"
        await phone.wait_for(
            lambda: calls == ["owner first", "phone next", "owner after detach"]
            and not session.get("running"),
            timeout=5,
        )
        await asyncio.sleep(0.05)
        assert len(phone_events) < len(owner.frames)
        assert session["agent"] is agent
        assert [message["role"] for message in session["history"]] == [
            "user",
            "assistant",
            "user",
            "assistant",
            "user",
            "assistant",
        ]

        await phone.incoming.put(None)
        await task
        assert phone.closed is True

    asyncio.run(scenario())
    session["event_hub"].disable_remote()
