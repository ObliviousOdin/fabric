from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from fabric_cli.work_ledger import WorkStoreUnavailable
from tui_gateway import server
from tui_gateway import work_service as work_service_module
from tui_gateway.work_service import (
    GlobalWorkScheduler,
    SchedulerLimits,
    service_for_profile,
    shutdown_work_services,
)


class RecordingTransport:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self._closed = False
        self.changed = threading.Condition()

    def write(self, message: dict[str, Any]) -> None:
        with self.changed:
            self.messages.append(message)
            self.changed.notify_all()

    def event(self, event_type: str, *, timeout: float = 5) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        with self.changed:
            while time.monotonic() < deadline:
                for message in self.messages:
                    params = message.get("params", {})
                    if params.get("type") == event_type:
                        return params
                self.changed.wait(max(0.0, deadline - time.monotonic()))
        raise AssertionError(f"event {event_type!r} not received: {self.messages!r}")


@pytest.fixture(autouse=True)
def isolated_runtime() -> None:
    shutdown_work_services(wait_for_scheduler=True)
    server._work_attention_by_request.clear()
    yield
    server._sessions.clear()
    server._work_attention_by_request.clear()
    shutdown_work_services(wait_for_scheduler=True)


def _session(profile: Path, *, sid: str = "mobile") -> tuple[dict, RecordingTransport]:
    profile.mkdir(parents=True)
    transport = RecordingTransport()
    value = {
        "agent": None,
        "cwd": str(profile),
        "history": [],
        "history_lock": threading.Lock(),
        "profile_home": str(profile),
        "session_key": f"conversation-{sid}",
        "source": "mobile",
        "transport": transport,
    }
    server._sessions[sid] = value
    return value, transport


def _rpc(method: str, params: dict[str, Any], rid: str = "rpc") -> dict:
    return server._methods[method](rid, params)


def _wait_terminal(profile: Path, job_id: str, timeout: float = 5) -> dict:
    service = service_for_profile(profile)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = service.ledger.get_job(job_id)
        if job["status"] in {"succeeded", "failed", "cancelled", "interrupted"}:
            return job
        time.sleep(0.01)
    raise AssertionError(f"Job did not terminate: {job}")


def test_legacy_background_executes_fresh_agent_and_emits_additive_job_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "profile"
    value, transport = _session(profile)
    value["model_override"] = {
        "model": "reviewed-model",
        "provider": "reviewed-provider",
        "api_key": "must-never-enter-run-snapshot",
    }
    constructed: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    calls: list[tuple[str, str]] = []

    class RecordingAgent:
        def __init__(self) -> None:
            self.closed = False

        def run_conversation(self, *, user_message: str, task_id: str) -> dict:
            calls.append((user_message, task_id))
            return {"final_response": "agent result", "messages": [{"role": "user", "content": user_message}]}

        def interrupt(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    def make_agent(*args: Any, **kwargs: Any) -> RecordingAgent:
        constructed.append((args, kwargs))
        return RecordingAgent()

    monkeypatch.setattr(server, "_make_agent", make_agent)
    response = _rpc(
        "prompt.background",
        {"session_id": "mobile", "text": "build from immutable input"},
    )["result"]
    assert set(response) == {"job_id", "task_id"}
    terminal = _wait_terminal(profile, response["job_id"])
    assert terminal["status"] == "succeeded"

    completion = transport.event("background.complete")["payload"]
    assert completion == {
        "job_id": response["job_id"],
        "task_id": response["task_id"],
        "text": "agent result",
    }
    assert calls == [("build from immutable input", response["task_id"])]
    assert len(constructed) == 1
    _args, kwargs = constructed[0]
    assert kwargs["session_id"] == response["task_id"]
    assert kwargs["model_override"] == "reviewed-model"
    assert kwargs["provider_override"] == "reviewed-provider"
    assert "api_key" not in kwargs
    assert "parent_agent" not in kwargs
    assert "session" not in kwargs
    assert isinstance(kwargs["callbacks_override"], dict)


def test_clarify_legacy_adapter_commits_and_resolves_exact_attention(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    _value, transport = _session(profile)
    answer: list[str] = []

    thread = threading.Thread(
        target=lambda: answer.append(
            server._block_user_attention(
                "clarify.request",
                "mobile",
                {"question": "Choose", "choices": ["A", "B"]},
                timeout=5,
            )
        )
    )
    thread.start()
    request = transport.event("clarify.request")["payload"]
    response = _rpc(
        "clarify.respond",
        {
            "session_id": "mobile",
            "request_id": request["request_id"],
            "answer": "private free-form answer",
        },
    )
    thread.join(timeout=5)

    assert response["result"]["request_id"] == request["request_id"]
    assert response["result"]["attention_id"] == request["attention_id"]
    assert answer == ["private free-form answer"]
    attention = service_for_profile(profile).ledger.get_attention(request["attention_id"])
    assert attention["state"] == "resolved"
    assert "private free-form answer" not in json.dumps(attention)


def test_foreground_attention_timeout_expires_with_reason_and_event(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    _value, transport = _session(profile)

    answer = server._block_user_attention(
        "clarify.request",
        "mobile",
        {"question": "Will expire", "choices": ["A", "B"]},
        timeout=0,
    )

    assert answer == ""
    request = transport.event("clarify.request")["payload"]
    service = service_for_profile(profile)
    attention = service.ledger.get_attention(request["attention_id"])
    assert attention["state"] == "expired"
    assert attention["terminal_reason"] == "waiter_timeout"
    assert any(
        event["subject_id"] == request["attention_id"]
        and event["event_type"] == "attention.expired"
        for event in service.ledger.list_events()
    )


def test_foreground_emit_failure_keeps_durable_attention_actionable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    session, _transport = _session(profile)
    original_emit = server._emit

    def fail_legacy_request(event: str, sid: str, payload: dict | None = None):
        if event == "clarify.request":
            raise BrokenPipeError("simulated disconnected legacy transport")
        return original_emit(event, sid, payload)

    monkeypatch.setattr(server, "_emit", fail_legacy_request)
    answers: list[str] = []
    thread = threading.Thread(
        target=lambda: answers.append(
            server._block_user_attention(
                "clarify.request",
                "mobile",
                {"question": "Still actionable"},
                timeout=5,
            )
        )
    )
    thread.start()
    service = server._work_service_for_session(session)
    deadline = time.monotonic() + 5
    pending: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        pending = service.ledger.list_attention(states=["pending"])
        if pending:
            break
        time.sleep(0.01)

    assert len(pending) == 1
    assert thread.is_alive()
    assert service.waiters.active_count == 1
    response = _rpc(
        "attention.respond",
        {
            "session_id": "mobile",
            "attention_id": pending[0]["attention_id"],
            "expected_version": pending[0]["version"],
            "idempotency_key": "foreground-broken-emit-response",
            "action": "submit",
            "value": "reconnected answer",
        },
    )
    thread.join(timeout=5)

    assert "result" in response
    assert not thread.is_alive()
    assert answers == ["reconnected answer"]
    assert service.ledger.get_attention(pending[0]["attention_id"])["state"] == "resolved"
    assert service.waiters.active_count == 0


def test_approval_emit_failure_keeps_queue_and_attention_actionable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from tools import approval as approval_module

    profile = tmp_path / "profile"
    session, _transport = _session(profile)
    original_emit = server._emit

    def fail_legacy_request(event: str, sid: str, payload: dict | None = None):
        if event == "approval.request":
            raise BrokenPipeError("simulated disconnected approval transport")
        return original_emit(event, sid, payload)

    monkeypatch.setattr(server, "_emit", fail_legacy_request)
    routing_key = server._approval_routing_key(session)
    decisions: list[dict[str, Any]] = []
    request_id = "approval-broken-emit-request"
    thread = threading.Thread(
        target=lambda: decisions.append(
            approval_module._await_gateway_decision(
                routing_key,
                lambda payload: server._emit_approval_request("mobile", payload),
                {
                    "request_id": request_id,
                    "command": "echo safe",
                    "description": "Confirm command",
                    "pattern_key": "echo",
                    "pattern_keys": ["echo"],
                },
                surface="tui",
            )
        )
    )
    thread.start()
    service = server._work_service_for_session(session)
    deadline = time.monotonic() + 5
    pending: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        pending = service.ledger.list_attention(states=["pending"])
        if pending and approval_module.has_blocking_approval(routing_key):
            break
        time.sleep(0.01)

    assert len(pending) == 1
    assert pending[0]["kind"] == "approval"
    assert thread.is_alive()
    response = _rpc(
        "attention.respond",
        {
            "session_id": "mobile",
            "attention_id": pending[0]["attention_id"],
            "expected_version": pending[0]["version"],
            "idempotency_key": "approval-broken-emit-response",
            "action": "once",
        },
    )
    thread.join(timeout=5)

    assert "result" in response
    assert not thread.is_alive()
    assert decisions == [{"resolved": True, "choice": "once", "reason": None}]
    assert service.ledger.get_attention(pending[0]["attention_id"])["state"] == "resolved"
    assert not approval_module.has_blocking_approval(routing_key)
    assert service.waiters.active_count == 0


@pytest.mark.parametrize(
    ("event", "payload", "wrong_method", "wrong_field", "right_method", "right_field"),
    [
        (
            "clarify.request",
            {"question": "Choose", "choices": ["A", "B"]},
            "sudo.respond",
            "password",
            "clarify.respond",
            "answer",
        ),
        (
            "sudo.request",
            {},
            "secret.respond",
            "value",
            "sudo.respond",
            "password",
        ),
        (
            "secret.request",
            {"env_var": "TEST_KEY", "prompt": "Credential"},
            "clarify.respond",
            "answer",
            "secret.respond",
            "value",
        ),
    ],
)
def test_legacy_response_method_cannot_cross_attention_kind(
    tmp_path: Path,
    event: str,
    payload: dict[str, Any],
    wrong_method: str,
    wrong_field: str,
    right_method: str,
    right_field: str,
) -> None:
    profile = tmp_path / "profile"
    _value, transport = _session(profile)
    answer: list[str] = []
    thread = threading.Thread(
        target=lambda: answer.append(
            server._block_user_attention(event, "mobile", payload, timeout=5)
        )
    )
    thread.start()
    request = transport.event(event)["payload"]

    wrong = _rpc(
        wrong_method,
        {
            "session_id": "mobile",
            "request_id": request["request_id"],
            wrong_field: "wrong-kind-value",
        },
    )
    assert "error" in wrong
    assert thread.is_alive()
    pending = service_for_profile(profile).ledger.get_attention(
        request["attention_id"]
    )
    assert pending["state"] == "pending"

    correct = _rpc(
        right_method,
        {
            "session_id": "mobile",
            "request_id": request["request_id"],
            right_field: "right-kind-value",
        },
    )
    thread.join(timeout=5)
    assert "result" in correct
    assert answer == ["right-kind-value"]


@pytest.mark.parametrize(
    ("event", "payload", "method", "field"),
    [
        ("clarify.request", {"question": "Choose"}, "clarify.respond", "answer"),
        ("sudo.request", {}, "sudo.respond", "password"),
        (
            "secret.request",
            {"env_var": "TEST_KEY", "prompt": "Credential"},
            "secret.respond",
            "value",
        ),
    ],
)
def test_unavailable_work_store_falls_back_to_one_exact_legacy_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    event: str,
    payload: dict[str, Any],
    method: str,
    field: str,
) -> None:
    profile = tmp_path / "profile"
    _value, transport = _session(profile)
    monkeypatch.setattr(
        server,
        "_work_service_for_session",
        lambda _session: (_ for _ in ()).throw(WorkStoreUnavailable("unavailable")),
    )
    answer: list[str] = []
    thread = threading.Thread(
        target=lambda: answer.append(
            server._block_user_attention(event, "mobile", payload, timeout=5)
        )
    )
    thread.start()
    request = transport.event(event)["payload"]

    assert "attention_id" not in request
    assert len(
        [
            message
            for message in transport.messages
            if message.get("params", {}).get("type") == event
        ]
    ) == 1
    response = _rpc(
        method,
        {
            "session_id": "mobile",
            "request_id": request["request_id"],
            field: "legacy answer",
        },
    )
    thread.join(timeout=5)

    assert response["result"]["status"] == "ok"
    assert answer == ["legacy answer"]
    assert server._work_attention_by_request == {}


def test_background_job_resumes_only_after_last_open_attention(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    session, _transport = _session(profile)
    ready = threading.Event()
    release = threading.Event()
    delivered = [threading.Event(), threading.Event()]
    attention: list[dict[str, Any]] = []

    def runner(spec, control):
        for index in range(2):
            attention.append(
                server._create_background_attention(
                    spec,
                    control,
                    kind="clarify",
                    payload={"question": f"Question {index}"},
                    deliver=lambda _value, index=index: delivered[index].set() or True,
                    cancel=lambda index=index: delivered[index].set(),
                )
            )
        ready.set()
        assert all(item.wait(timeout=5) for item in delivered)
        assert release.wait(timeout=5)
        return {"final_response": "done"}

    monkeypatch.setattr(server, "_run_durable_background_agent", runner)
    created = _rpc(
        "job.create",
        {
            "session_id": "mobile",
            "kind": "background_prompt",
            "text": "ask twice",
            "idempotency_key": "two-attention-create-key-01",
        },
    )["result"]
    assert ready.wait(timeout=5)
    service = server._work_service_for_session(session)
    job_id = created["job"]["job_id"]
    waiting = service.ledger.get_job(job_id)
    assert waiting["status"] == "waiting_attention"
    assert waiting["open_attention_count"] == 2

    for index, item in enumerate(attention):
        response = _rpc(
            "attention.respond",
            {
                "session_id": "mobile",
                "attention_id": item["attention_id"],
                "expected_version": 1,
                "idempotency_key": f"two-attention-response-{index:02d}",
                "action": "submit",
                "value": f"answer {index}",
            },
        )
        assert "result" in response
        current = service.ledger.get_job(job_id)
        if index == 0:
            assert current["status"] == "waiting_attention"
            assert current["open_attention_count"] == 1
        else:
            assert current["status"] == "running"
            assert current["open_attention_count"] == 0
    release.set()
    assert _wait_terminal(profile, job_id)["status"] == "succeeded"


def test_background_attention_timeout_expires_with_reason_and_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    session, transport = _session(profile)
    answers: list[str] = []

    def runner(spec, control):
        answers.append(
            server._block_background_attention(
                spec,
                control,
                "clarify",
                {"question": "Background timeout"},
                timeout=0,
            )
        )
        return {"final_response": "continued after timeout"}

    monkeypatch.setattr(server, "_run_durable_background_agent", runner)
    created = _rpc(
        "job.create",
        {
            "session_id": "mobile",
            "kind": "background_prompt",
            "text": "wait for a response",
            "idempotency_key": "background-timeout-create-key",
        },
    )["result"]

    assert _wait_terminal(profile, created["job"]["job_id"])["status"] == "succeeded"
    assert answers == [""]
    request = transport.event("clarify.request")["payload"]
    service = server._work_service_for_session(session)
    attention = service.ledger.get_attention(request["attention_id"])
    assert attention["state"] == "expired"
    assert attention["terminal_reason"] == "waiter_timeout"
    assert any(
        event["subject_id"] == request["attention_id"]
        and event["event_type"] == "attention.expired"
        for event in service.ledger.list_events()
    )


def test_background_emit_failure_keeps_durable_attention_actionable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    session, _transport = _session(profile)
    original_emit = server._emit

    def fail_legacy_request(event: str, sid: str, payload: dict | None = None):
        if event == "clarify.request":
            raise BrokenPipeError("simulated disconnected legacy transport")
        return original_emit(event, sid, payload)

    monkeypatch.setattr(server, "_emit", fail_legacy_request)
    answers: list[str] = []

    def runner(spec, control):
        answers.append(
            server._block_background_attention(
                spec,
                control,
                "clarify",
                {"question": "Reconnect to answer"},
                timeout=5,
            )
        )
        return {"final_response": "done"}

    monkeypatch.setattr(server, "_run_durable_background_agent", runner)
    created = _rpc(
        "job.create",
        {
            "session_id": "mobile",
            "kind": "background_prompt",
            "text": "request durable attention",
            "idempotency_key": "background-broken-emit-create",
        },
    )["result"]
    service = server._work_service_for_session(session)
    deadline = time.monotonic() + 5
    pending: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        pending = service.ledger.list_attention(states=["pending"])
        if (
            pending
            and service.ledger.get_job(created["job"]["job_id"])["status"]
            == "waiting_attention"
        ):
            break
        time.sleep(0.01)

    assert len(pending) == 1
    assert service.ledger.get_job(created["job"]["job_id"])["status"] == "waiting_attention"
    response = _rpc(
        "attention.respond",
        {
            "session_id": "mobile",
            "attention_id": pending[0]["attention_id"],
            "expected_version": pending[0]["version"],
            "idempotency_key": "background-broken-emit-response",
            "action": "submit",
            "value": "reconnected background answer",
        },
    )

    assert "result" in response
    assert _wait_terminal(profile, created["job"]["job_id"])["status"] == "succeeded"
    assert answers == ["reconnected background answer"]
    assert service.ledger.get_attention(pending[0]["attention_id"])["state"] == "resolved"
    assert service.waiters.active_count == 0


def test_queued_shutdown_callback_cannot_resurrect_global_work_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    _session(profile)
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 1))
    monkeypatch.setattr(work_service_module, "_global_scheduler", scheduler)
    started = threading.Event()
    release = threading.Event()

    def runner(spec, _control):
        if spec.prompt == "running during shutdown":
            started.set()
            assert release.wait(timeout=5)
            return {"final_response": "released"}
        raise AssertionError("queued runner must never start")

    monkeypatch.setattr(server, "_run_durable_background_agent", runner)
    first = _rpc(
        "job.create",
        {
            "session_id": "mobile",
            "kind": "background_prompt",
            "text": "running during shutdown",
            "idempotency_key": "queued-shutdown-running-key",
        },
    )["result"]
    assert started.wait(timeout=5)
    second = _rpc(
        "job.create",
        {
            "session_id": "mobile",
            "kind": "background_prompt",
            "text": "queued during shutdown",
            "idempotency_key": "queued-shutdown-waiting-key",
        },
    )["result"]
    service = service_for_profile(profile)
    first_future = service._job_futures[first["job"]["job_id"]]

    shutdown_work_services(wait_for_scheduler=False)

    assert service.ledger.get_job(second["job"]["job_id"])["status"] == "interrupted"
    assert work_service_module._global_service_cache is None
    assert work_service_module._global_scheduler is None
    release.set()
    first_future.result(timeout=5)
    scheduler.shutdown(wait=True, timeout=5)
    assert work_service_module._global_service_cache is None
    assert work_service_module._global_scheduler is None


def test_running_shutdown_cleanup_cannot_resurrect_global_work_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    _session(profile)
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    monkeypatch.setattr(work_service_module, "_global_scheduler", scheduler)
    started = threading.Event()
    release = threading.Event()

    class BlockingAgent:
        def run_conversation(self, *, user_message: str, task_id: str) -> dict:
            assert user_message == "running agent shutdown"
            assert task_id
            started.set()
            assert release.wait(timeout=5)
            return {"final_response": "stopped"}

        def interrupt(self) -> None:
            release.set()

        def close(self) -> None:
            return None

    monkeypatch.setattr(server, "_make_agent", lambda *_args, **_kwargs: BlockingAgent())
    created = _rpc(
        "job.create",
        {
            "session_id": "mobile",
            "kind": "background_prompt",
            "text": "running agent shutdown",
            "idempotency_key": "running-shutdown-agent-key",
        },
    )["result"]
    service = service_for_profile(profile)
    future = service._job_futures[created["job"]["job_id"]]
    assert started.wait(timeout=5)

    shutdown_work_services(wait_for_scheduler=False)

    assert work_service_module._global_service_cache is None
    assert work_service_module._global_scheduler is None
    future.result(timeout=5)
    scheduler.shutdown(wait=True, timeout=5)
    assert work_service_module._global_service_cache is None
    assert work_service_module._global_scheduler is None


def test_background_approval_reason_taints_result_and_event_egress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    session, transport = _session(profile)
    ready = threading.Event()
    delivered = threading.Event()
    release = threading.Event()
    attention: list[dict[str, Any]] = []
    raw_delivery: list[object] = []
    reason = "OPENAI_API_KEY=" + "d" * 48

    def runner(spec, control):
        def accept(value: object) -> bool:
            raw_delivery.append(value)
            delivered.set()
            return True

        attention.append(
            server._create_background_attention(
                spec,
                control,
                kind="approval",
                payload={"description": "Review action"},
                deliver=accept,
                cancel=lambda: delivered.set(),
            )
        )
        ready.set()
        assert delivered.wait(timeout=5)
        assert release.wait(timeout=5)
        callbacks = server._background_agent_callbacks(spec, control)
        callbacks["reasoning_callback"](reason)
        return {"final_response": reason}

    monkeypatch.setattr(server, "_run_durable_background_agent", runner)
    created = _rpc(
        "job.create",
        {
            "session_id": "mobile",
            "kind": "background_prompt",
            "text": "request approval",
            "idempotency_key": "approval-reason-background-create",
        },
    )["result"]
    assert ready.wait(timeout=5)
    response = _rpc(
        "attention.respond",
        {
            "session_id": "mobile",
            "attention_id": attention[0]["attention_id"],
            "expected_version": 1,
            "idempotency_key": "approval-reason-background-reply",
            "action": "deny",
            "reason": reason,
        },
    )
    assert response["result"]["state"] == "denied"
    assert raw_delivery == [{"choice": "deny", "reason": reason}]
    running = server._work_service_for_session(session).ledger.get_job(
        created["job"]["job_id"]
    )
    assert running["status"] == "running"
    release.set()
    terminal = _wait_terminal(profile, created["job"]["job_id"])
    assert terminal["result"] is None
    assert terminal["result_omitted_reason"] == "sensitive_input"

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not any(
        message.get("params", {}).get("type") == "background.complete"
        for message in transport.messages
    ):
        time.sleep(0.01)
    serialized_events = json.dumps(transport.messages)
    conn = sqlite3.connect(profile / "work.db")
    try:
        dump = "\n".join(conn.iterdump())
    finally:
        conn.close()
    assert reason not in serialized_events
    assert reason not in dump
    assert "Background work completed" in serialized_events


@pytest.mark.parametrize("detach_mode", ["detached", "removed"])
def test_detached_background_callbacks_emit_nothing_and_job_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    detach_mode: str,
) -> None:
    profile = tmp_path / "profile"
    session, transport = _session(profile)
    started = threading.Event()
    release = threading.Event()

    def runner(spec, control):
        started.set()
        assert release.wait(timeout=5)
        callbacks = server._background_agent_callbacks(spec, control)
        callbacks["thinking_callback"]("detached thinking")
        callbacks["reasoning_callback"]("detached reasoning")
        callbacks["status_callback"]("working", "detached status")
        callbacks["tool_start_callback"]("tool-id", "terminal", {"cmd": "pwd"})
        assert callbacks["read_terminal_callback"]() == ""
        return {"final_response": "detached done"}

    monkeypatch.setattr(server, "_run_durable_background_agent", runner)
    created = _rpc(
        "job.create",
        {
            "session_id": "mobile",
            "kind": "background_prompt",
            "text": "continue away",
            "idempotency_key": f"detached-create-key-{detach_mode}",
        },
    )["result"]
    assert started.wait(timeout=5)
    messages_before = list(transport.messages)
    fallback_frames: list[dict[str, Any]] = []
    monkeypatch.setattr(
        server,
        "write_json",
        lambda frame: fallback_frames.append(frame) or True,
    )
    if detach_mode == "detached":
        session["transport"] = server._detached_ws_transport
    else:
        server._sessions.pop("mobile")
    release.set()

    terminal = _wait_terminal(profile, created["job"]["job_id"])
    assert terminal["status"] == "succeeded"
    assert transport.messages == messages_before
    assert fallback_frames == []


def test_bootstrap_pages_are_bounded_signed_and_converge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    session, _transport = _session(profile)
    service = server._work_service_for_session(session)
    created_jobs: list[dict[str, Any]] = []
    for number in range(3):
        created_jobs.append(
            service.ledger.create_job(
                kind="background_prompt",
                title=f"Job {number}",
                source="test",
                owner=service.owner,
                idempotency_key=f"bootstrap-create-key-{number:08d}",
                source_session_key="conversation-mobile",
                runtime_session_id=f"runtime-{number}",
                runtime_summary={"kind": "in_process_agent"},
                run_runtime={"kind": "in_process_agent"},
            )["job"]
        )

    token = None
    seen: set[str] = set()
    watermark = None
    changed_job_id = None
    projections: dict[str, dict[str, Any]] = {}
    while True:
        params: dict[str, Any] = {"session_id": "mobile", "limit": 1}
        if token is not None:
            params["page_token"] = token
        page = _rpc("job.sync", params)["result"]
        assert len(json.dumps(page).encode("utf-8")) <= 1024 * 1024
        assert page["work_profile_id"] == server._work_profile_id(session)
        watermark = page["watermark"] if watermark is None else watermark
        assert page["watermark"] == watermark
        seen.update(job["job_id"] for job in page["jobs"])
        for job in page["jobs"]:
            current = projections.get(job["job_id"])
            if current is None or job["version"] > current["version"]:
                projections[job["job_id"]] = job
        if changed_job_id is None:
            changed_job_id = next(
                job["job_id"] for job in created_jobs if job["job_id"] not in seen
            )
            service.ledger.transition_job(
                changed_job_id,
                expected_version=1,
                next_status="claimed",
                claim_token="post-watermark-claim",
            )
        token = page["next_page_token"]
        if token is None:
            break

    assert len(seen) == 3
    assert changed_job_id is not None
    delta = _rpc(
        "job.sync",
        {
            "session_id": "mobile",
            "ledger_id": service.ledger_id,
            "after": watermark,
            "limit": 100,
        },
    )["result"]
    for event in delta["events"]:
        subject = event.get("subject")
        if isinstance(subject, dict) and event["subject_type"] == "job":
            current = projections.get(event["subject_id"])
            if current is None or subject["version"] > current["version"]:
                projections[event["subject_id"]] = subject
    assert any(
        event["subject_id"] == changed_job_id
        and event["event_type"] == "job.status_changed"
        for event in delta["events"]
    )
    assert projections[changed_job_id]["status"] == "claimed"
    assert projections[changed_job_id]["version"] == 2
    bad = _rpc(
        "job.sync",
        {"session_id": "mobile", "page_token": "tampered-token", "limit": 1},
    )
    assert bad["error"]["data"]["code"] == "cursor_expired"
    assert bad["error"]["data"]["bootstrap"] is True

    expired = server._work_token_encode(
        {
            "event_floor": 1,
            "expires_at": 0,
            "kind": "work-bootstrap",
            "last_id": "",
            "ledger_id": service.ledger_id,
            "phase": "jobs",
            "profile_id": server._work_profile_id(session),
            "watermark": watermark,
        }
    )
    expired_result = _rpc(
        "job.sync",
        {"session_id": "mobile", "page_token": expired, "limit": 1},
    )
    assert expired_result["error"]["data"]["code"] == "cursor_expired"
    assert expired_result["error"]["data"]["bootstrap"] is True

    restart_token = server._work_token_encode(
        {
            "event_floor": 1,
            "expires_at": int(time.time()) + 300,
            "kind": "work-bootstrap",
            "last_id": "",
            "ledger_id": service.ledger_id,
            "phase": "jobs",
            "profile_id": server._work_profile_id(session),
            "watermark": watermark,
        }
    )
    monkeypatch.setattr(server, "_WORK_PAGE_TOKEN_SECRET", b"r" * 32)
    restarted = _rpc(
        "job.sync",
        {"session_id": "mobile", "page_token": restart_token, "limit": 1},
    )
    assert restarted["error"]["data"]["code"] == "cursor_expired"
    assert restarted["error"]["data"]["bootstrap"] is True


def test_default_profile_home_is_server_derived_not_client_supplied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    launch_home = tmp_path / "launch-home"
    launch_home.mkdir()
    transport = RecordingTransport()
    session = {
        "agent": None,
        "cwd": str(tmp_path),
        "history": [],
        "history_lock": threading.Lock(),
        "profile_home": None,
        "session_key": "default-conversation",
        "source": "mobile",
        "transport": transport,
    }
    server._sessions["default"] = session
    monkeypatch.setattr(server, "_fabric_home", str(launch_home))
    monkeypatch.setattr(
        server,
        "_run_durable_background_agent",
        lambda _spec, _control: {"final_response": "ok"},
    )
    created = _rpc(
        "job.create",
        {
            "session_id": "default",
            "kind": "background_prompt",
            "text": "default profile",
            "idempotency_key": "default-profile-key-00001",
        },
    )["result"]
    _wait_terminal(launch_home, created["job"]["job_id"])
    assert (launch_home / "work.db").is_file()
    assert not (tmp_path / "work.db").exists()
    assert server._lazy_resume_info(
        str(launch_home),
        profile_home=launch_home,
    )["work_profile_id"] == server._work_profile_id(session)
