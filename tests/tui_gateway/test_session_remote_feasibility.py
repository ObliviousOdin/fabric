from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from unittest.mock import patch

from run_agent import AIAgent
from fabric_cli.remote_control import compose_stream_delta_callback
from tui_gateway import server
from tui_gateway.session_event_hub import SessionEventHub
from tui_gateway.session_input_arbiter import InputReceipt, SessionInputArbiter


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


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


def _event_hashes(transport: RecordingTransport) -> list[str]:
    return [
        hashlib.sha256(
            json.dumps(frame, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        for frame in transport.frames
    ]


def _real_agent(session_key: str) -> AIAgent:
    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        return AIAgent(
            api_key="phase-zero-test-key",
            base_url="https://example.invalid/v1",
            model="phase-zero/test-model",
            quiet_mode=True,
            session_id=session_key,
            skip_context_files=True,
            skip_memory=True,
        )


def test_one_real_gateway_agent_fans_out_and_serializes_all_inputs(
    monkeypatch,
) -> None:
    sid = "phase-zero-live"
    session_key = "phase-zero-durable"
    constructions = 0

    def construct_agent() -> AIAgent:
        nonlocal constructions
        constructions += 1
        return _real_agent(session_key)

    agent = construct_agent()
    owner = RecordingTransport()
    phone = RecordingTransport()
    desktop = RecordingTransport()
    fence = threading.RLock()
    session = {
        "agent": agent,
        "attached_images": [],
        "cols": 80,
        "created_at": time.time(),
        "history": [],
        "history_lock": threading.RLock(),
        "history_version": 0,
        "image_counter": 0,
        "inflight_turn": None,
        "last_active": time.time(),
        "profile_home": None,
        "running": False,
        "session_key": session_key,
        "show_reasoning": False,
        "slash_worker": None,
        "source": "tui",
        "tool_progress_mode": "all",
        "transport": owner,
    }
    hub = SessionEventHub(
        sid,
        owner,
        fence_lock=fence,
        generation_factory=lambda: "phase-zero-generation",
    )
    session["event_hub"] = hub
    monkeypatch.setitem(server._sessions, sid, session)

    def snapshot() -> dict:
        with session["history_lock"]:
            return {
                "agent_object": id(session["agent"]),
                "messages": copy.deepcopy(session["history"]),
                "session_id": sid,
                "session_key": session["session_key"],
            }

    try:
        assert hub.enable_remote() == "phase-zero-generation"
        phone_attach = hub.attach("phone", phone, snapshot)
        desktop_attach = hub.attach("desktop", desktop, snapshot)
        assert phone_attach.snapshot == desktop_attach.snapshot
        assert phone_attach.snapshot == {
            "agent_object": id(agent),
            "messages": [],
            "session_id": sid,
            "session_key": session_key,
        }

        # This is the real gateway emission path. write_json detects the hub
        # on the existing live session and never swaps its owner transport.
        server._emit("message.delta", sid, {"text": "streaming"})
        _wait_for(lambda: len(phone.frames) == 1 and len(desktop.frames) == 1)

        arbiter = SessionInputArbiter(max_queue=2)
        barrier = threading.Barrier(3)
        submitted: list[tuple[InputReceipt, str]] = []
        submitted_lock = threading.Lock()
        requests = [
            ("local-owner", "local-1", "from terminal"),
            ("phone", "phone-1", "from phone"),
            ("desktop", "desktop-1", "from desktop"),
        ]

        def submit(controller_id: str, request_id: str, text: str) -> None:
            barrier.wait()
            receipt = arbiter.submit(
                controller_id=controller_id,
                request_id=request_id,
                payload=text,
            )
            with submitted_lock:
                submitted.append((receipt, text))

        threads = [
            threading.Thread(target=submit, args=request)
            for request in requests
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        ordered = sorted(submitted, key=lambda item: item[0].ordinal or 0)
        assert [receipt.ordinal for receipt, _text in ordered] == [1, 2, 3]
        assert [receipt.state for receipt, _text in ordered].count("accepted") == 1

        for position, (receipt, text) in enumerate(ordered):
            assert arbiter.active is not None
            assert arbiter.active.ordinal == receipt.ordinal

            def mutate() -> dict:
                with session["history_lock"]:
                    session["history"].extend(
                        [
                            {
                                "attribution": receipt.controller_id,
                                "content": text,
                                "role": "user",
                            },
                            {"content": f"ack:{text}", "role": "assistant"},
                        ]
                    )
                    session["history_version"] += 1
                return {
                    "jsonrpc": "2.0",
                    "method": "event",
                    "params": {
                        "payload": {
                            "controller_id": receipt.controller_id,
                            "request_id": receipt.request_id,
                        },
                        "session_id": sid,
                        "type": "message.complete",
                    },
                }

            assert hub.mutate_and_emit(mutate)
            promoted = arbiter.complete(
                controller_id=receipt.controller_id,
                request_id=receipt.request_id,
            )
            if position < 2:
                assert promoted is not None
                assert promoted.ordinal == ordered[position + 1][0].ordinal
            else:
                assert promoted is None

        duplicate = arbiter.submit(
            controller_id="phone",
            request_id="phone-1",
            payload="from phone",
        )
        assert duplicate.state == "duplicate"
        assert duplicate.original_state == "completed"

        _wait_for(lambda: len(phone.frames) == 4 and len(desktop.frames) == 4)
        assert owner.frames == phone.frames == desktop.frames
        assert _event_hashes(owner) == _event_hashes(phone) == _event_hashes(desktop)
        assert session["transport"] is owner
        assert session["agent"] is agent
        assert agent.session_id == session_key
        assert constructions == 1
        assert [message["role"] for message in session["history"]] == [
            "user",
            "assistant",
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        assert len(session["history"]) == 6

        # Owner exit is the publication boundary: the exact-session stream is
        # withdrawn and all remote transports close independently.
        server._finalize_session(session, end_reason="phase_zero_owner_exit")
        assert not hub.published
        assert phone.closed
        assert desktop.closed
    finally:
        server._sessions.pop(sid, None)
        hub.disable_remote()
        agent.close()


def test_classic_cli_callback_publishes_same_contract_without_replacing_agent() -> None:
    sid = "classic-live"
    session_key = "classic-durable"
    agent = _real_agent(session_key)
    owner = RecordingTransport()
    phone = RecordingTransport()
    desktop = RecordingTransport()
    local_deltas: list[str | None] = []
    hub = SessionEventHub(
        sid,
        owner,
        generation_factory=lambda: "classic-generation",
    )

    try:
        hub.enable_remote()
        hub.attach("phone", phone, lambda: {"session_id": sid})
        hub.attach("desktop", desktop, lambda: {"session_id": sid})
        original_agent = agent
        agent.stream_delta_callback = compose_stream_delta_callback(
            session_id=sid,
            event_hub=hub,
            local_callback=local_deltas.append,
        )

        agent.stream_delta_callback("same agent")
        agent.stream_delta_callback(None)
        _wait_for(lambda: len(phone.frames) == 1 and len(desktop.frames) == 1)

        assert agent is original_agent
        assert agent.session_id == session_key
        assert local_deltas == ["same agent", None]
        assert owner.frames == phone.frames == desktop.frames
        assert owner.frames[0]["params"]["type"] == "message.delta"
        assert owner.frames[0]["params"]["session_id"] == sid
        assert owner.frames[0]["params"]["payload"] == {"text": "same agent"}
    finally:
        hub.disable_remote()
        agent.close()
