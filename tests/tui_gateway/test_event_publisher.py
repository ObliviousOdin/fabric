from __future__ import annotations

import json
import threading
import time

from tui_gateway import event_publisher


class _Socket:
    def __init__(self, *, fail_send: bool = False) -> None:
        self.fail_send = fail_send
        self.sent: list[str] = []
        self.closed = False

    def send(self, value: str) -> None:
        if self.fail_send:
            self.fail_send = False
            raise OSError("dropped")
        self.sent.append(value)

    def close(self) -> None:
        self.closed = True


def _wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition did not become true")


def _event(event_type: str, payload: dict | None = None) -> dict:
    params = {"type": event_type, "session_id": "sid-1"}
    if payload is not None:
        params["payload"] = payload
    return {"jsonrpc": "2.0", "method": "event", "params": params}


def test_publisher_queues_while_connecting_and_recovers_initial_failure(monkeypatch):
    socket = _Socket()
    attempts = 0

    def connect(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("not ready")
        return socket

    monkeypatch.setattr(event_publisher, "ws_connect", connect)
    publisher = event_publisher.WsPublisherTransport(
        "ws://dashboard/api/pub",
        retry_initial=0.005,
        retry_max=0.01,
    )
    try:
        assert publisher.write(_event("tool.start", {"tool_id": "t1"}))
        _wait_until(lambda: bool(socket.sent))
        assert json.loads(socket.sent[0])["params"]["type"] == "tool.start"
        assert attempts >= 2
    finally:
        publisher.close()


def test_publisher_reconnects_and_retries_frame_after_send_failure(monkeypatch):
    first = _Socket(fail_send=True)
    second = _Socket()
    sockets = iter((first, second))
    monkeypatch.setattr(event_publisher, "ws_connect", lambda *_a, **_k: next(sockets))
    publisher = event_publisher.WsPublisherTransport(
        "ws://dashboard/api/pub",
        retry_initial=0.005,
        retry_max=0.01,
    )
    try:
        assert publisher.write(_event("tool.complete", {"tool_id": "t1"}))
        _wait_until(lambda: bool(second.sent))
        assert json.loads(second.sent[0])["params"]["type"] == "tool.complete"
        assert first.closed
    finally:
        publisher.close()


def test_publisher_drops_token_streams_and_sanitizes_session_info(monkeypatch):
    socket = _Socket()
    monkeypatch.setattr(event_publisher, "ws_connect", lambda *_a, **_k: socket)
    publisher = event_publisher.WsPublisherTransport(
        "ws://dashboard/api/pub",
        retry_initial=0.005,
    )
    try:
        assert publisher.write(_event("message.delta", {"text": "secret token"}))
        assert publisher.write(_event("reasoning.delta", {"text": "chain"}))
        assert publisher.write(_event("subagent.text", {"text": "child tokens"}))
        assert publisher.write(_event("background.complete", {"text": "answer"}))
        assert publisher.write(
            {"jsonrpc": "2.0", "id": "rpc-secret", "result": {"secret": True}}
        )
        info = _event(
            "session.info",
            {
                "credential_warning": "refresh",
                "cwd": "/repo",
                "model": "openai/gpt-5",
                "provider": "openai",
                "running": True,
                "system_prompt": "must not leave the TUI",
                "tools": {"terminal": {}},
                "skills": {"private": {}},
                "mcp_servers": ["secret"],
                "title": "Live task",
            },
        )
        info["params"]["private_transport_metadata"] = "strip-me"
        assert publisher.write(info)
        _wait_until(lambda: bool(socket.sent))
        assert len(socket.sent) == 1
        payload = json.loads(socket.sent[0])["params"]["payload"]
        assert payload == {
            "credential_warning": "refresh",
            "cwd": "/repo",
            "model": "openai/gpt-5",
            "provider": "openai",
            "running": True,
            "title": "Live task",
        }
    finally:
        publisher.close()


def test_projection_strips_transcript_results_and_nested_private_fields():
    tool = event_publisher._sidecar_projection(
        _event(
            "tool.complete",
            {
                "args": {"prompt": "private prompt"},
                "duration_s": 1.5,
                "error": "short failure",
                "files_written": ["/tmp/report.md", 7],
                "inline_diff": "private diff",
                "name": "write_file",
                "result": {"secret": "raw result"},
                "result_text": "raw result text",
                "summary": "Wrote report",
                "tool_id": "tool-1",
                "todos": [
                    {
                        "content": "Verify report",
                        "id": "todo-1",
                        "private": "strip-me",
                        "status": "pending",
                    }
                ],
            },
        )
    )
    complete = event_publisher._sidecar_projection(
        _event(
            "message.complete",
            {
                "reasoning": "private reasoning",
                "rendered": "private ansi",
                "text": "private final answer",
                "usage": {"input_tokens": 42},
            },
        )
    )

    assert tool == {
        "jsonrpc": "2.0",
        "method": "event",
        "params": {
            "type": "tool.complete",
            "session_id": "sid-1",
            "payload": {
                "duration_s": 1.5,
                "error": "short failure",
                "files_written": ["/tmp/report.md"],
                "name": "write_file",
                "summary": "Wrote report",
                "tool_id": "tool-1",
                "todos": [
                    {
                        "content": "Verify report",
                        "id": "todo-1",
                        "status": "pending",
                    }
                ],
            },
        },
    }
    assert complete == {
        "jsonrpc": "2.0",
        "method": "event",
        "params": {"type": "message.complete", "session_id": "sid-1"},
    }


def test_projection_extracts_bounded_artifact_paths_without_raw_result():
    projected = event_publisher._sidecar_projection(
        _event(
            "tool.complete",
            {
                "args": {
                    "path": "/repo/output/report.md",
                    "private_prompt": "do not mirror this",
                },
                "name": "write_file",
                "result": {
                    "download_url": "https://example.test/export/report.pdf",
                    "raw": "private result body",
                },
                "tool_id": "tool-2",
            },
        )
    )

    assert projected["params"]["payload"] == {
        "files_written": [
            "/repo/output/report.md",
            "https://example.test/export/report.pdf",
        ],
        "name": "write_file",
        "tool_id": "tool-2",
    }
    assert "private" not in json.dumps(projected)


def test_projection_caps_adversarial_list_and_artifact_scans():
    class BombList(list):
        def __iter__(self):
            yield from ({} for _ in range(event_publisher._MAX_INPUT_LIST_SCAN))
            raise AssertionError("todo compactor scanned beyond its cap")

    class BombDict(dict):
        def items(self):
            # The root args node consumes one scan unit before this iterator.
            for index in range(event_publisher._MAX_ARTIFACT_SCAN_NODES - 1):
                yield f"ignored_{index}", object()
            raise AssertionError("artifact compactor scanned beyond its cap")

    projected = event_publisher._sidecar_projection(
        _event(
            "tool.complete",
            {
                "args": BombDict(),
                "tool_id": "bounded",
                "todos": BombList(),
            },
        )
    )

    assert projected["params"]["payload"] == {"tool_id": "bounded"}


def test_publisher_rejects_oversized_semantic_frame_before_queueing(monkeypatch):
    release = threading.Event()
    socket = _Socket()

    def connect(*_args, **_kwargs):
        release.wait(1)
        return socket

    monkeypatch.setattr(event_publisher, "ws_connect", connect)
    publisher = event_publisher.WsPublisherTransport("ws://dashboard/api/pub")
    try:
        assert not publisher.write(
            _event("status.update", {"kind": "process", "text": "x" * 40_000})
        )
        assert publisher._q.empty()
    finally:
        release.set()
        publisher.close()


def test_queue_overflow_evicts_oldest_and_retains_newest_metadata(monkeypatch):
    release = threading.Event()
    socket = _Socket()

    def connect(*_args, **_kwargs):
        release.wait(1)
        return socket

    monkeypatch.setattr(event_publisher, "ws_connect", connect)
    publisher = event_publisher.WsPublisherTransport(
        "ws://dashboard/api/pub",
        retry_initial=0.005,
    )
    try:
        for index in range(event_publisher._QUEUE_MAX):
            assert publisher.write(
                _event("tool.start", {"name": "terminal", "tool_id": f"old-{index}"})
            )
        assert publisher.write(_event("session.title", {"title": "Newest title"}))

        release.set()
        _wait_until(lambda: len(socket.sent) == event_publisher._QUEUE_MAX)
        frames = [json.loads(line)["params"] for line in socket.sent]
        assert not any(
            frame.get("payload", {}).get("tool_id") == "old-0" for frame in frames
        )
        assert frames[-1] == {
            "type": "session.title",
            "session_id": "sid-1",
            "payload": {"title": "Newest title"},
        }
    finally:
        release.set()
        publisher.close()


def test_close_does_not_wait_on_a_blocked_socket_send(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    class BlockingSocket(_Socket):
        def send(self, value: str) -> None:
            entered.set()
            release.wait(2)
            self.sent.append(value)

        def close(self) -> None:
            self.closed = True
            release.set()

    socket = BlockingSocket()
    monkeypatch.setattr(event_publisher, "ws_connect", lambda *_a, **_k: socket)
    publisher = event_publisher.WsPublisherTransport(
        "ws://dashboard/api/pub",
        connect_timeout=0.05,
    )
    closer = threading.Thread(target=publisher.close)
    try:
        assert publisher.write(_event("tool.start", {"tool_id": "blocked"}))
        assert entered.wait(1)
        closer.start()
        closer.join(0.25)
        assert not closer.is_alive()
    finally:
        release.set()
        if closer.ident is not None:
            closer.join(1)
        if publisher._worker is not None:
            publisher.close()
