from __future__ import annotations

import json
import queue
import threading
from unittest.mock import patch

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from cli import FabricCLI
from fabric_cli.classic_remote_control import (
    ClassicArbitratedInput,
    ClassicRemoteControlHost,
    ClassicRemoteInputQueue,
    snapshot_messages,
)


def _request(connection, rid: str, method: str, params: dict) -> None:
    connection.send(
        json.dumps(
            {
                "id": rid,
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )
    )


def _receive_until(connection, predicate, *, limit: int = 80) -> tuple[dict, list[dict]]:
    seen = []
    for _ in range(limit):
        frame = json.loads(connection.recv(timeout=2))
        seen.append(frame)
        if predicate(frame):
            return frame, seen
    raise AssertionError("expected WebSocket frame was not received")


def test_loopback_host_runs_owner_and_controller_turns_on_one_agent() -> None:
    session_id = "classic-live"
    history: list[dict] = []
    fence = threading.RLock()

    class CLI:
        _classic_remote_control = None

        def _console_print(self, _message: str) -> None:
            return None

    cli = CLI()
    pending = ClassicRemoteInputQueue(cli)
    agent_calls: list[str] = []
    agent_constructions = 0

    class Agent:
        def __init__(self) -> None:
            nonlocal agent_constructions
            agent_constructions += 1

        def run(self, text: str) -> str:
            agent_calls.append(text)
            return f"reply:{text}"

    agent = Agent()

    def snapshot() -> dict:
        return {
            "messages": snapshot_messages(history),
            "pending_interactions": [],
            "running": False,
            "session_id": session_id,
        }

    host = ClassicRemoteControlHost(
        session_id=session_id,
        snapshot_builder=snapshot,
        accepted_input=pending.put_accepted,
        fence_lock=fence,
    )
    cli._classic_remote_control = host
    status = host.start()
    assert status["published"] is True
    endpoint = status["endpoint"]
    assert endpoint.startswith("ws://127.0.0.1:")

    try:
        with connect(endpoint) as controller:
            ready = json.loads(controller.recv(timeout=2))
            assert ready["params"]["type"] == "gateway.ready"

            _request(
                controller,
                "attach",
                "session.attach",
                {
                    "controller_id": "phone-1",
                    "session_id": session_id,
                },
            )
            attached, _frames = _receive_until(
                controller,
                lambda frame: frame.get("id") == "attach",
            )
            assert attached["result"]["snapshot"] == snapshot()
            generation = attached["result"]["generation"]

            pending.put("owner first")
            first = pending.get(timeout=2)
            assert isinstance(first, ClassicArbitratedInput)
            assert first.controller_id == "owner"

            _request(
                controller,
                "input",
                "session.input.submit",
                {
                    "controller_id": "phone-1",
                    "request_id": "phone-request-1",
                    "session_id": session_id,
                    "text": "phone second",
                },
            )
            submitted, submitted_frames = _receive_until(
                controller,
                lambda frame: frame.get("id") == "input",
            )
            assert submitted["result"]["receipt"]["state"] == "queued"

            all_events = [
                frame
                for frame in submitted_frames
                if frame.get("method") == "event"
                and frame.get("params", {}).get("publication")
            ]

            def run_entry(entry: ClassicArbitratedInput) -> None:
                text = str(entry.payload)
                host.begin_turn(
                    entry,
                    text=text,
                    mutation=lambda: history.append(
                        {"role": "user", "content": text}
                    ),
                )
                host.emit("message.delta", {"text": f"delta:{text}"})
                response = agent.run(text)
                host.complete_turn(
                    entry,
                    response=response,
                    mutation=lambda: history.append(
                        {"role": "assistant", "content": response}
                    ),
                )
                host.release_turn(entry)

            run_entry(first)
            second = pending.get(timeout=2)
            assert isinstance(second, ClassicArbitratedInput)
            assert second.controller_id == "phone-1"
            assert second.payload == "phone second"
            run_entry(second)

            _completed, turn_frames = _receive_until(
                controller,
                lambda frame: (
                    frame.get("params", {}).get("type") == "input.receipt"
                    and frame.get("params", {}).get("payload", {}).get(
                        "controller_id"
                    )
                    == "phone-1"
                    and frame.get("params", {}).get("payload", {}).get("state")
                    == "completed"
                ),
            )
            all_events.extend(
                frame
                for frame in turn_frames
                if frame.get("method") == "event"
                and frame.get("params", {}).get("publication")
            )

            assert agent_calls == ["owner first", "phone second"]
            assert [message["role"] for message in history] == [
                "user",
                "assistant",
                "user",
                "assistant",
            ]
            assert agent_constructions == 1
            publication = [
                frame["params"]["publication"]
                for frame in all_events
            ]
            assert publication
            assert {
                item["generation"] for item in publication
            } == {generation}
            event_sequences = [item["event_seq"] for item in publication]
            assert event_sequences == sorted(event_sequences)
            assert len(event_sequences) == len(set(event_sequences))

            _request(
                controller,
                "detach",
                "session.detach",
                {
                    "controller_id": "phone-1",
                    "session_id": session_id,
                },
            )
            detached, _frames = _receive_until(
                controller,
                lambda frame: frame.get("id") == "detach",
            )
            assert detached["result"]["detached"] is True
            assert host.status(owner=True)["attached_controllers"] == []
    finally:
        stopped = host.stop(require_idle=False)
        assert stopped["published"] is False


def test_loopback_host_rejects_wrong_token_and_browser_origin() -> None:
    session_id = "classic-auth"
    accepted: list[ClassicArbitratedInput] = []
    host = ClassicRemoteControlHost(
        session_id=session_id,
        snapshot_builder=lambda: {"session_id": session_id},
        accepted_input=accepted.append,
    )
    status = host.start()
    endpoint = status["endpoint"]
    assert endpoint is not None
    wrong = endpoint.rsplit("=", 1)[0] + "=wrong"
    wrong_path = endpoint.replace("/remote?", "/other?")

    try:
        with connect(wrong) as connection:
            with pytest.raises(ConnectionClosed):
                connection.recv(timeout=2)
        with connect(wrong_path) as connection:
            with pytest.raises(ConnectionClosed):
                connection.recv(timeout=2)
        with connect(
            endpoint,
            origin="https://attacker.example",
        ) as connection:
            with pytest.raises(ConnectionClosed):
                connection.recv(timeout=2)
        assert accepted == []
    finally:
        host.stop(require_idle=False)


def test_unpublish_refuses_to_drop_accepted_or_queued_input() -> None:
    session_id = "classic-busy-off"
    accepted: list[ClassicArbitratedInput] = []
    host = ClassicRemoteControlHost(
        session_id=session_id,
        snapshot_builder=lambda: {"session_id": session_id},
        accepted_input=accepted.append,
    )
    host.start()
    try:
        receipt = host.submit_owner("still pending")
        assert receipt.state == "accepted"
        with pytest.raises(RuntimeError, match="session busy"):
            host.stop(require_idle=True)
        assert host.published is True
        host.release_turn(accepted[0])
    finally:
        host.stop(require_idle=False)


def test_classic_cli_remote_command_starts_statuses_and_stops_host() -> None:
    cli = FabricCLI.__new__(FabricCLI)
    cli._agent_running = False
    cli._approval_state = None
    cli._clarify_state = None
    cli._classic_remote_control = None
    cli._remote_control_lock = threading.RLock()
    cli._remote_current_input = None
    cli._session_db = None
    cli.agent = None
    cli.conversation_history = []
    cli.session_id = "classic-command"
    cli.streaming_enabled = False
    output: list[str] = []
    cli._console_print = output.append
    cli._pending_input = ClassicRemoteInputQueue(cli)

    cli._handle_remote_command("/remote")
    host = cli._classic_remote_control
    assert host is not None
    assert host.published is True
    assert any("exact live session" in line for line in output)
    assert any("ws://127.0.0.1:" in line for line in output)

    output.clear()
    cli._handle_remote_command("/remote status")
    assert any("Attached: 0 controllers" in line for line in output)

    output.clear()
    assert cli.process_command("/clear") is True
    assert any(
        "/clear changes this live session" in line
        for line in output
    )

    output.clear()
    cli._handle_remote_command("/remote off")
    assert cli._classic_remote_control is None
    assert any("Remote Control is off" in line for line in output)


def test_classic_remote_interactions_are_scoped_and_exclude_secrets() -> None:
    cli = FabricCLI.__new__(FabricCLI)
    cli._agent_running = False
    cli._approval_state = None
    cli._clarify_state = None
    cli._classic_remote_control = None
    cli._remote_control_lock = threading.RLock()
    cli._remote_current_input = None
    cli._session_db = None
    cli.agent = None
    cli.conversation_history = []
    cli.session_id = "classic-interactions"
    cli.streaming_enabled = False
    cli._console_print = lambda _message: None
    cli._pending_input = ClassicRemoteInputQueue(cli)
    cli._handle_remote_command("/remote")
    host = cli._classic_remote_control
    assert host is not None
    endpoint = host.endpoint
    assert endpoint is not None

    approval_queue: queue.Queue[str] = queue.Queue()
    clarify_queue: queue.Queue[str] = queue.Queue()
    cli._approval_state = {
        "choices": ["once", "deny"],
        "request_id": "approval-1",
        "response_queue": approval_queue,
    }
    cli._clarify_state = {
        "choices": ["A", "B"],
        "request_id": "clarify-1",
        "response_queue": clarify_queue,
    }

    try:
        with connect(endpoint) as controller:
            ready = json.loads(controller.recv(timeout=2))
            methods = set(ready["params"]["payload"]["methods"])
            assert {"approval.respond", "clarify.respond"} <= methods
            assert {"secret.respond", "sudo.respond"}.isdisjoint(methods)

            _request(
                controller,
                "attach",
                "session.attach",
                {
                    "controller_id": "phone-1",
                    "session_id": cli.session_id,
                },
            )
            _receive_until(controller, lambda frame: frame.get("id") == "attach")

            _request(
                controller,
                "wrong-approval",
                "approval.respond",
                {
                    "choice": "once",
                    "request_id": "approval-other",
                    "session_id": cli.session_id,
                },
            )
            wrong, _ = _receive_until(
                controller,
                lambda frame: frame.get("id") == "wrong-approval",
            )
            assert wrong["error"]["code"] == 4009
            assert approval_queue.empty()

            _request(
                controller,
                "approval",
                "approval.respond",
                {
                    "choice": "once",
                    "request_id": "approval-1",
                    "session_id": cli.session_id,
                },
            )
            approved, _ = _receive_until(
                controller,
                lambda frame: frame.get("id") == "approval",
            )
            assert approved["result"] == {
                "choice": "once",
                "request_id": "approval-1",
                "resolved": 1,
            }
            assert approval_queue.get_nowait() == "once"

            _request(
                controller,
                "clarify",
                "clarify.respond",
                {
                    "answer": "B",
                    "request_id": "clarify-1",
                    "session_id": cli.session_id,
                },
            )
            clarified, _ = _receive_until(
                controller,
                lambda frame: frame.get("id") == "clarify",
            )
            assert clarified["result"] == {
                "request_id": "clarify-1",
                "status": "ok",
            }
            assert clarify_queue.get_nowait() == "B"

            _request(
                controller,
                "secret",
                "secret.respond",
                {
                    "request_id": "secret-1",
                    "session_id": cli.session_id,
                    "value": "must-not-cross",
                },
            )
            denied, _ = _receive_until(
                controller,
                lambda frame: frame.get("id") == "secret",
            )
            assert denied["error"]["code"] == -32601
    finally:
        cli._stop_classic_remote_control(require_idle=False)


def test_interrupt_clears_remote_interactions_under_one_event_fence() -> None:
    session_id = "classic-interrupt-fence"
    cli = FabricCLI.__new__(FabricCLI)
    cli._agent_running = True
    cli._approval_deadline = 1
    cli._approval_state = {
        "choices": ["once", "deny"],
        "request_id": "approval-interrupt",
        "response_queue": queue.Queue(),
    }
    cli._clarify_deadline = 1
    cli._clarify_freetext = False
    cli._clarify_state = {
        "choices": ["A", "B"],
        "request_id": "clarify-interrupt",
        "response_queue": queue.Queue(),
    }
    cli._sudo_state = None
    cli._secret_state = None
    cli._classic_remote_control = None
    cli._remote_control_lock = threading.RLock()
    cli._remote_current_input = None
    cli.agent = None
    cli.conversation_history = []
    cli.session_id = session_id
    cli.streaming_enabled = False
    cli._pending_input = ClassicRemoteInputQueue(cli)
    cli._console_print = lambda _message: None

    host = ClassicRemoteControlHost(
        session_id=session_id,
        snapshot_builder=cli._classic_remote_snapshot,
        accepted_input=cli._pending_input.put_accepted,
        fence_lock=cli._remote_control_lock,
    )
    cli._classic_remote_control = host
    endpoint = host.start()["endpoint"]

    try:
        with connect(endpoint) as controller:
            controller.recv(timeout=2)
            _request(
                controller,
                "attach",
                "session.attach",
                {
                    "controller_id": "phone-1",
                    "session_id": session_id,
                },
            )
            attached, _ = _receive_until(
                controller,
                lambda frame: frame.get("id") == "attach",
            )
            assert len(
                attached["result"]["snapshot"]["pending_interactions"]
            ) == 2

            approval_queue = cli._approval_state["response_queue"]
            clarify_queue = cli._clarify_state["response_queue"]
            cli._clear_active_overlays_for_interrupt()

            completed = []
            for _ in range(2):
                frame, _ = _receive_until(
                    controller,
                    lambda item: (
                        item.get("params", {}).get("type")
                        == "interaction.complete"
                    ),
                )
                completed.append(frame["params"]["payload"])

            assert {item["kind"] for item in completed} == {
                "approval",
                "clarify",
            }
            assert all(item["cancelled"] is True for item in completed)
            assert cli._approval_state is None
            assert cli._clarify_state is None
            assert approval_queue.get_nowait() == "deny"
            assert "cancelled" in clarify_queue.get_nowait()
            assert cli._classic_remote_snapshot()["pending_interactions"] == []
    finally:
        host.stop(require_idle=False)


def test_classic_snapshot_keeps_publication_id_across_continuation() -> None:
    cli = FabricCLI.__new__(FabricCLI)
    cli._agent_running = False
    cli._approval_state = None
    cli._clarify_state = None
    cli._classic_remote_control = None
    cli._remote_control_lock = threading.RLock()
    cli.conversation_history = []
    cli.session_id = "parent-session"

    host = ClassicRemoteControlHost(
        session_id="parent-session",
        snapshot_builder=cli._classic_remote_snapshot,
        accepted_input=lambda _entry: None,
        fence_lock=cli._remote_control_lock,
    )
    cli._classic_remote_control = host
    host.start()
    try:
        cli.session_id = "continuation-session"
        snapshot = cli._classic_remote_snapshot()
        assert snapshot["session_id"] == "parent-session"
        assert snapshot["session_key"] == "continuation-session"
    finally:
        host.stop(require_idle=False)


def test_owner_shutdown_closes_attached_controller() -> None:
    session_id = "classic-owner-exit"
    host = ClassicRemoteControlHost(
        session_id=session_id,
        snapshot_builder=lambda: {"session_id": session_id},
        accepted_input=lambda _entry: None,
    )
    endpoint = host.start()["endpoint"]
    controller = connect(endpoint)
    try:
        controller.recv(timeout=2)
        _request(
            controller,
            "attach",
            "session.attach",
            {
                "controller_id": "phone-1",
                "session_id": session_id,
            },
        )
        _receive_until(controller, lambda frame: frame.get("id") == "attach")

        stopped = host.stop(require_idle=False)
        assert stopped["published"] is False
        assert stopped["detached_controllers"] == ["phone-1"]
        with pytest.raises(ConnectionClosed):
            controller.recv(timeout=2)
    finally:
        controller.close()
        if host.published:
            host.stop(require_idle=False)


def test_real_classic_chat_path_publishes_one_agent_turn(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path / "fabric-home"))
    with patch("cli.get_tool_definitions", return_value=[]):
        cli = FabricCLI()

    agent_constructions = 0
    agent_calls: list[dict] = []

    class Agent:
        def __init__(self) -> None:
            nonlocal agent_constructions
            agent_constructions += 1
            self._active_children = []
            self._interrupt_requested = False
            self.max_iterations = 90
            self.model = "test/model"
            self.platform = "cli"
            self.session_id = cli.session_id
            self.stream_delta_callback = None

        def run_conversation(self, **kwargs) -> dict:
            agent_calls.append(kwargs)
            return {
                "api_calls": 1,
                "completed": True,
                "final_response": "reply from the same agent",
                "messages": [
                    {"role": "user", "content": kwargs["user_message"]},
                    {
                        "role": "assistant",
                        "content": "reply from the same agent",
                    },
                ],
                "partial": True,
                "response_previewed": True,
            }

    cli.agent = Agent()
    cli._active_agent_route_signature = ("same-agent",)
    cli._console_print = lambda _message: None
    cli._handle_remote_command("/remote")
    host = cli._classic_remote_control
    assert host is not None
    endpoint = host.endpoint
    assert endpoint is not None

    try:
        with connect(endpoint) as controller:
            controller.recv(timeout=2)
            _request(
                controller,
                "attach",
                "session.attach",
                {
                    "controller_id": "phone-1",
                    "session_id": cli.session_id,
                },
            )
            _receive_until(controller, lambda frame: frame.get("id") == "attach")
            _request(
                controller,
                "input",
                "session.input.submit",
                {
                    "controller_id": "phone-1",
                    "request_id": "phone-turn-1",
                    "session_id": cli.session_id,
                    "text": "/clear @file:private.txt",
                },
            )
            accepted, _ = _receive_until(
                controller,
                lambda frame: frame.get("id") == "input",
            )
            assert accepted["result"]["receipt"]["state"] == "accepted"

            entry = cli._pending_input.get(timeout=2)
            assert isinstance(entry, ClassicArbitratedInput)
            cli._remote_current_input = entry
            with (
                patch.object(cli, "_ensure_runtime_credentials", return_value=True),
                patch.object(
                    cli,
                    "_resolve_turn_agent_config",
                    return_value={
                        "model": None,
                        "request_overrides": None,
                        "runtime": None,
                        "signature": ("same-agent",),
                    },
                ),
                patch.object(cli, "_init_agent", return_value=True),
                patch(
                    "agent.context_references.preprocess_context_references"
                ) as context_references,
            ):
                response = cli.chat(entry.payload)
            host.release_turn(entry)
            cli._remote_current_input = None

            completed, frames = _receive_until(
                controller,
                lambda frame: (
                    frame.get("params", {}).get("type") == "input.receipt"
                    and frame.get("params", {}).get("payload", {}).get("state")
                    == "completed"
                ),
            )
            event_types = {
                frame.get("params", {}).get("type")
                for frame in frames
                if frame.get("method") == "event"
            }

            assert completed["params"]["payload"]["request_id"] == "phone-turn-1"
            assert {"message.start", "message.complete"} <= event_types
            assert response == "reply from the same agent"
            assert agent_constructions == 1
            assert len(agent_calls) == 1
            assert agent_calls[0]["user_message"] == "/clear @file:private.txt"
            assert context_references.call_count == 0
            assert cli.conversation_history == [
                {"role": "user", "content": "/clear @file:private.txt"},
                {
                    "role": "assistant",
                    "content": "reply from the same agent",
                },
            ]
    finally:
        cli._stop_classic_remote_control(require_idle=False)
