from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from fabric_cli.work_ledger import (
    AttentionNotActionable,
    CursorExpired,
    IdempotencyConflict,
    InvalidPublicData,
    InvalidTransition,
    RuntimeOwnerMismatch as LedgerRuntimeOwnerMismatch,
    VersionConflict,
    WorkNotFound,
    WorkOperationInProgress,
    WorkStoreReplacedError,
    WorkStoreUnavailable,
)
from tui_gateway import server
from tui_gateway.work_service import (
    DeliveryOutcomeUnknown,
    RuntimeOwnerMismatch,
    WaiterUnavailable,
    WorkCapacityExceeded,
    WorkStoreRebound,
    service_for_profile,
    shutdown_work_services,
)


class RecordingTransport:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self._closed = False

    def write(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


@pytest.fixture(autouse=True)
def isolated_work_runtime() -> None:
    shutdown_work_services(wait_for_scheduler=True)
    server._work_attention_by_request.clear()
    yield
    for sid in list(server._sessions):
        server._sessions.pop(sid, None)
    server._work_attention_by_request.clear()
    shutdown_work_services(wait_for_scheduler=True)


def _install_session(tmp_path: Path, sid: str = "mobile-session") -> tuple[dict, RecordingTransport]:
    profile = tmp_path / sid
    profile.mkdir()
    transport = RecordingTransport()
    session = {
        "agent": None,
        "cwd": str(tmp_path),
        "history": [],
        "history_lock": threading.Lock(),
        "profile_home": str(profile),
        "session_key": f"conversation-{sid}",
        "source": "mobile",
        "transport": transport,
    }
    server._sessions[sid] = session
    return session, transport


def _rpc(method: str, params: dict[str, Any], rid: str = "rpc") -> dict:
    return server._methods[method](rid, params)


def _wait_for_job(session: dict, job_id: str, status: str, timeout: float = 5) -> dict:
    service = server._work_service_for_session(session)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = service.ledger.get_job(job_id)
        if job["status"] == status:
            return job
        time.sleep(0.01)
    raise AssertionError(f"Job {job_id} did not reach {status}: {job}")


def test_job_create_is_idempotent_and_never_persists_raw_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session, _transport = _install_session(tmp_path)
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def runner(spec, _control):
        calls.append(spec.prompt)
        started.set()
        assert release.wait(timeout=5)
        return {"final_response": "finished"}

    monkeypatch.setattr(server, "_run_durable_background_agent", runner)
    base = {
        "session_id": "mobile-session",
        "kind": "background_prompt",
        "idempotency_key": "mobile-create-key-00000001",
        "title": "Compile release",
    }
    first = _rpc("job.create", {**base, "text": "RAW-FIRST-PROMPT"}, "first")
    replay = _rpc("job.create", {**base, "text": "RAW-CHANGED-PROMPT"}, "replay")

    assert first["result"]["job"]["job_id"] == replay["result"]["job"]["job_id"]
    assert replay["result"]["replayed"] is True
    assert started.wait(timeout=5)
    assert calls == ["RAW-FIRST-PROMPT"]
    release.set()
    job_id = first["result"]["job"]["job_id"]
    terminal = _wait_for_job(session, job_id, "succeeded")
    assert terminal["result"] == {"completed": True}
    assert terminal["runtime"]["survives_client_disconnect"] is True
    assert terminal["runtime"]["survives_gateway_restart"] is False

    profile = Path(session["profile_home"])
    conn = sqlite3.connect(profile / "work.db")
    try:
        dump = "\n".join(conn.iterdump())
    finally:
        conn.close()
    assert "RAW-FIRST-PROMPT" not in dump
    assert "RAW-CHANGED-PROMPT" not in dump
    assert '"final_response":"finished"' not in dump


def test_public_display_fields_are_recursively_redacted_before_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session, _ = _install_session(tmp_path)
    service = server._work_service_for_session(session)
    sentinel = "sk-proj-" + "S" * 64
    attention = service.create_attention_waiter(
        source_session_key="conversation-mobile-session",
        runtime_session_id="mobile-session",
        request_id="redacted-display-request",
        kind="clarify",
        title=f"Review {sentinel}",
        public_payload={
            "question": f"Use {sentinel}?",
            "choices": [{"label": sentinel, "nested": [sentinel]}],
        },
        deliver=lambda _value: True,
    )
    release = threading.Event()
    monkeypatch.setattr(
        server,
        "_run_durable_background_agent",
        lambda _spec, _control: (
            release.wait(timeout=5),
            {"final_response": "done"},
        )[1],
    )
    created = _rpc(
        "job.create",
        {
            "session_id": "mobile-session",
            "kind": "background_prompt",
            "text": sentinel,
            "title": f"Run {sentinel}",
            "idempotency_key": "redacted-title-create-key-1",
        },
    )["result"]

    public = service.ledger.get_attention(attention["attention_id"])
    job = service.ledger.get_job(created["job"]["job_id"])
    conn = sqlite3.connect(service.ledger.path)
    try:
        dump = "\n".join(conn.iterdump())
    finally:
        conn.close()
    serialized = json.dumps(
        {"attention": public, "job": job, "events": service.ledger.list_events()}
    )
    assert sentinel not in dump
    assert sentinel not in serialized
    assert "sk-pro...SSSS" in serialized
    release.set()


def test_background_exception_and_sensitive_completion_never_egress_raw_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session, transport = _install_session(tmp_path)
    sentinel = "OPENAI_API_KEY=" + "z" * 48

    def tainted_runner(spec, control):
        control.mark_sensitive_input()
        callbacks = server._background_agent_callbacks(spec, control)
        callbacks["thinking_callback"](sentinel)
        callbacks["reasoning_callback"](sentinel)
        callbacks["tool_start_callback"]("tool-id", "terminal", {"value": sentinel})
        return {"final_response": sentinel}

    monkeypatch.setattr(server, "_run_durable_background_agent", tainted_runner)
    with caplog.at_level(logging.DEBUG):
        created = _rpc(
            "job.create",
            {
                "session_id": "mobile-session",
                "kind": "background_prompt",
                "text": "safe prompt",
                "idempotency_key": "sensitive-egress-create-key",
            },
        )["result"]
        terminal = _wait_for_job(
            session,
            created["job"]["job_id"],
            "succeeded",
        )

    assert terminal["result"] is None
    assert terminal["result_omitted_reason"] == "sensitive_input"
    assert sentinel not in caplog.text
    assert sentinel not in json.dumps(transport.messages)
    deadline = time.monotonic() + 5
    completion: list[dict[str, Any]] = []
    while time.monotonic() < deadline and not completion:
        completion = [
            message["params"]["payload"]
            for message in transport.messages
            if message.get("params", {}).get("type") == "background.complete"
        ]
        if not completion:
            time.sleep(0.01)
    assert completion
    assert completion[-1]["text"] == "Background work completed"

    def raising_runner(_spec, _control):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(server, "_run_durable_background_agent", raising_runner)
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        failed = _rpc(
            "job.create",
            {
                "session_id": "mobile-session",
                "kind": "background_prompt",
                "text": "another safe prompt",
                "idempotency_key": "raising-egress-create-key-01",
            },
        )["result"]
        _wait_for_job(session, failed["job"]["job_id"], "failed")
    assert sentinel not in caplog.text
    assert sentinel not in json.dumps(transport.messages)


def test_job_rpc_profile_scope_and_exact_param_allowlists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session_a, _ = _install_session(tmp_path, "gateway-a")
    session_b, _ = _install_session(tmp_path, "gateway-b")
    release = threading.Event()
    monkeypatch.setattr(
        server,
        "_run_durable_background_agent",
        lambda _spec, _control: release.wait(timeout=5) or {"final_response": "done"},
    )
    created = _rpc(
        "job.create",
        {
            "session_id": "gateway-a",
            "kind": "background_prompt",
            "text": "scoped",
            "idempotency_key": "profile-scope-key-000001",
        },
    )["result"]
    job_id = created["job"]["job_id"]

    foreign = _rpc("job.get", {"session_id": "gateway-b", "job_id": job_id})
    assert foreign["error"] == {
        "code": -32004,
        "message": "Work item not found",
        "data": {"code": "not_found"},
    }
    assert _rpc(
        "job.get",
        {"session_id": "gateway-a", "job_id": job_id, "profile": "gateway-b"},
    )["error"]["data"]["code"] == "invalid_params"
    assert _rpc(
        "job.create",
        {
            "session_id": "gateway-a",
            "kind": "background_prompt",
            "text": "x",
            "idempotency_key": "unknown-field-key-00001",
            "source_session_key": "forged-owner",
        },
    )["error"]["data"]["code"] == "invalid_params"
    assert server._work_service_for_session(session_a).ledger.get_job(job_id)["job_id"] == job_id
    profile_a = server._work_profile_id(session_a)
    profile_b = server._work_profile_id(session_b)
    assert profile_a.startswith("profile_") and len(profile_a) == 40
    assert profile_a != profile_b
    listing = _rpc("job.list", {"session_id": "gateway-a"})["result"]
    assert listing["work_profile_id"] == profile_a
    assert str(session_a["profile_home"]) not in repr(listing["work_profile_id"])
    release.set()


def test_job_cancel_is_creator_owned_versioned_and_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session, _ = _install_session(tmp_path)
    started = threading.Event()

    def runner(_spec, control):
        started.set()
        while not control.cancelled:
            time.sleep(0.005)
        return {"final_response": "must not persist"}

    monkeypatch.setattr(server, "_run_durable_background_agent", runner)
    created = _rpc(
        "job.create",
        {
            "session_id": "mobile-session",
            "kind": "background_prompt",
            "text": "cancel this",
            "idempotency_key": "cancel-create-key-000001",
        },
    )["result"]
    job_id = created["job"]["job_id"]
    assert started.wait(timeout=5)
    running = _wait_for_job(session, job_id, "running")
    params = {
        "session_id": "mobile-session",
        "job_id": job_id,
        "expected_version": running["version"],
        "idempotency_key": "cancel-mutation-key-0001",
    }
    cancelled = _rpc("job.cancel", params, "cancel")
    replay = _rpc("job.cancel", params, "cancel-replay")

    assert cancelled["result"]["mutation_id"] == replay["result"]["mutation_id"]
    assert replay["result"]["replayed"] is True
    assert _wait_for_job(session, job_id, "cancelled")["result"] is None


def test_sync_reconstructs_completion_after_detach_and_reconnect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session, first_transport = _install_session(tmp_path)
    release = threading.Event()
    monkeypatch.setattr(
        server,
        "_run_durable_background_agent",
        lambda _spec, _control: (release.wait(timeout=5), {"final_response": "done"})[1],
    )
    created = _rpc(
        "job.create",
        {
            "session_id": "mobile-session",
            "kind": "background_prompt",
            "text": "continue detached",
            "idempotency_key": "disconnect-create-key-001",
        },
    )["result"]
    job_id = created["job"]["job_id"]
    session["transport"] = server._detached_ws_transport
    hints_before = len(first_transport.messages)
    release.set()
    _wait_for_job(session, job_id, "succeeded")
    assert len(first_transport.messages) == hints_before

    reconnected = RecordingTransport()
    session["transport"] = reconnected
    page = _rpc("job.sync", {"session_id": "mobile-session", "limit": 100})[
        "result"
    ]
    assert page["mode"] == "bootstrap"
    assert any(job["job_id"] == job_id and job["status"] == "succeeded" for job in page["jobs"])


def test_work_changed_hint_reads_only_cursor_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session, transport = _install_session(tmp_path)
    service = server._work_service_for_session(session)
    service.ledger.create_job(
        kind="background_prompt",
        title="Hint",
        source="mobile",
        owner=service.owner,
        source_session_key="conversation-mobile-session",
        runtime_session_id="mobile-session",
        runtime_summary={"kind": "in_process_agent"},
        run_runtime={"kind": "in_process_agent"},
        idempotency_key="work-hint-create-key-0001",
    )

    monkeypatch.setattr(
        service.ledger,
        "bootstrap_snapshot",
        lambda **_kwargs: pytest.fail("work.changed must not load projections"),
    )
    server._emit_work_changed("mobile-session", service)

    hints = [
        message["params"]
        for message in transport.messages
        if message.get("method") == "event"
        and message.get("params", {}).get("type") == "work.changed"
    ]
    assert hints[-1]["payload"] == {
        "ledger_id": service.ledger_id,
        "cursor_hint": 1,
        "work_profile_id": server._work_profile_id(session),
    }


def test_work_changed_broadcasts_only_to_live_same_profile_sessions(
    tmp_path: Path,
) -> None:
    source, source_transport = _install_session(tmp_path, "source-session")
    broken, broken_transport = _install_session(tmp_path, "broken-session")
    peer, peer_transport = _install_session(tmp_path, "peer-session")
    _foreign, foreign_transport = _install_session(tmp_path, "foreign-session")
    broken["profile_home"] = source["profile_home"]
    peer["profile_home"] = source["profile_home"]
    service = server._work_service_for_session(source)
    service.ledger.create_job(
        kind="background_prompt",
        title="Profile-wide hint",
        source="mobile",
        owner=service.owner,
        source_session_key="conversation-source",
        runtime_session_id="source-session",
        runtime_summary={"kind": "in_process_agent"},
        run_runtime={"kind": "in_process_agent"},
        idempotency_key="profile-broadcast-create-key",
    )
    source["transport"] = server._detached_ws_transport

    def fail_write(_message: dict[str, Any]) -> None:
        raise BrokenPipeError("simulated closed peer")

    broken_transport.write = fail_write  # type: ignore[method-assign]

    server._emit_work_changed("source-session", service)

    assert source_transport.messages == []
    assert foreign_transport.messages == []
    hints = [
        message["params"]
        for message in peer_transport.messages
        if message.get("params", {}).get("type") == "work.changed"
    ]
    assert len(hints) == 1
    assert hints[0]["session_id"] == "peer-session"
    assert hints[0]["payload"]["work_profile_id"] == server._work_profile_id(peer)


def test_bootstrap_pages_include_every_actionable_attention(tmp_path: Path) -> None:
    session, _ = _install_session(tmp_path)
    service = server._work_service_for_session(session)
    expected: set[str] = set()
    for index in range(101):
        item = service.create_attention_waiter(
            source_session_key="conversation-mobile-session",
            runtime_session_id="mobile-session",
            request_id=f"bootstrap-attention-{index:03d}",
            kind="clarify",
            title="Question",
            public_payload={"question": "Continue?"},
            deliver=lambda _value: True,
        )
        expected.add(item["attention_id"])

    page = _rpc("job.sync", {"session_id": "mobile-session", "limit": 17})[
        "result"
    ]
    seen = {item["attention_id"] for item in page["attention"]}
    while page["has_more"]:
        page = _rpc(
            "job.sync",
            {
                "session_id": "mobile-session",
                "limit": 17,
                "page_token": page["next_page_token"],
            },
        )["result"]
        seen.update(item["attention_id"] for item in page["attention"])

    assert seen == expected
    assert page["cursor"] == page["watermark"]


def test_attention_response_targets_exact_waiter_and_replays_once(tmp_path: Path) -> None:
    session, _ = _install_session(tmp_path)
    service = server._work_service_for_session(session)
    delivered: list[tuple[str, object]] = []
    first = service.create_attention_waiter(
        source_session_key="conversation-mobile-session",
        runtime_session_id="mobile-session",
        request_id="first-attention-request",
        kind="clarify",
        title="First",
        public_payload={"question": "first?"},
        deliver=lambda value: delivered.append(("first", value)) or True,
    )
    second = service.create_attention_waiter(
        source_session_key="conversation-mobile-session",
        runtime_session_id="mobile-session",
        request_id="second-attention-request",
        kind="clarify",
        title="Second",
        public_payload={"question": "second?"},
        deliver=lambda value: delivered.append(("second", value)) or True,
    )
    params = {
        "session_id": "mobile-session",
        "attention_id": second["attention_id"],
        "expected_version": second["version"],
        "idempotency_key": "attention-response-key-001",
        "action": "submit",
        "value": "second answer",
    }
    response = _rpc("attention.respond", params, "attention")
    replay = _rpc("attention.respond", params, "attention-replay")

    assert response["result"]["delivered"] is True
    assert replay["result"]["replayed"] is True
    assert delivered == [("second", "second answer")]
    assert service.ledger.get_attention(first["attention_id"])["state"] == "pending"
    assert service.ledger.get_attention(second["attention_id"])["state"] == "resolved"


def test_finalized_attention_replays_after_waiter_cleanup_and_service_reopen(
    tmp_path: Path,
) -> None:
    session, _ = _install_session(tmp_path)
    service = server._work_service_for_session(session)
    delivered: list[object] = []
    attention = service.create_attention_waiter(
        source_session_key="conversation-mobile-session",
        runtime_session_id="mobile-session",
        request_id="restart-replay-request",
        kind="clarify",
        title="Question",
        public_payload={"question": "Continue?"},
        deliver=lambda value: delivered.append(value) or True,
    )
    params = {
        "session_id": "mobile-session",
        "attention_id": attention["attention_id"],
        "expected_version": 1,
        "idempotency_key": "restart-replay-key-00001",
        "action": "submit",
        "value": "first raw answer",
    }

    first = _rpc("attention.respond", params, "first")["result"]
    assert service.waiters.active_count == 0
    shutdown_work_services(wait_for_scheduler=True)
    replay = _rpc(
        "attention.respond",
        {**params, "value": "different raw retry"},
        "replay",
    )["result"]

    assert replay == {**first, "replayed": True}
    assert delivered == ["first raw answer"]


def test_nonfinal_attention_response_after_service_reopen_fails_closed(
    tmp_path: Path,
) -> None:
    session, _ = _install_session(tmp_path)
    service = server._work_service_for_session(session)
    delivered: list[object] = []
    attention = service.create_attention_waiter(
        source_session_key="conversation-mobile-session",
        runtime_session_id="mobile-session",
        request_id="restart-inflight-request",
        kind="clarify",
        title="Question",
        public_payload={"question": "Continue?"},
        deliver=lambda value: delivered.append(value) or True,
    )
    identity = service.waiters.get_identity(attention["attention_id"])
    service.ledger.begin_attention_resolution(
        attention["attention_id"],
        expected_version=1,
        idempotency_key="restart-inflight-key-0001",
        kind="clarify",
        action="submit",
        owner=service.owner,
        waiter_generation=identity.waiter_generation,
    )
    shutdown_work_services(wait_for_scheduler=True)

    response = _rpc(
        "attention.respond",
        {
            "session_id": "mobile-session",
            "attention_id": attention["attention_id"],
            "expected_version": 1,
            "idempotency_key": "restart-inflight-key-0001",
            "action": "submit",
            "value": "must never be delivered after restart",
        },
    )

    assert response["error"]["data"]["code"] == "waiter_unavailable"
    assert delivered == []


def test_concurrent_identical_attention_responses_deliver_once_and_replay(
    tmp_path: Path,
) -> None:
    session, _ = _install_session(tmp_path)
    service = server._work_service_for_session(session)
    delivery_started = threading.Event()
    release_delivery = threading.Event()
    delivered: list[object] = []

    def deliver(value: object) -> bool:
        delivered.append(value)
        delivery_started.set()
        assert release_delivery.wait(timeout=5)
        return True

    attention = service.create_attention_waiter(
        source_session_key="conversation-mobile-session",
        runtime_session_id="mobile-session",
        request_id="concurrent-response-request",
        kind="clarify",
        title="Question",
        public_payload={"question": "Continue?"},
        deliver=deliver,
    )
    params = {
        "attention_id": attention["attention_id"],
        "expected_version": 1,
        "idempotency_key": "concurrent-response-key-01",
        "action": "submit",
        "raw_value": "one raw answer",
    }
    results: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    def respond() -> None:
        try:
            results.append(service.respond_attention(**params))
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=respond)
    second = threading.Thread(target=respond)
    first.start()
    assert delivery_started.wait(timeout=5)
    second.start()
    release_delivery.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert errors == []
    assert delivered == ["one raw answer"]
    assert sorted(result["replayed"] for result in results) == [False, True]
    assert len({result["mutation_id"] for result in results}) == 1
    assert service.waiters.active_count == 0


def test_attention_teardown_serializes_with_claim_delivery_and_finalize(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session, _ = _install_session(tmp_path)
    service = server._work_service_for_session(session)
    delivered: list[object] = []
    attention = service.create_attention_waiter(
        source_session_key="conversation-mobile-session",
        runtime_session_id="mobile-session",
        request_id="teardown-race-request",
        kind="clarify",
        title="Question",
        public_payload={"question": "Continue?"},
        deliver=lambda value: delivered.append(value) or True,
    )
    claim_committed = threading.Event()
    release_claim = threading.Event()
    cancel_identity_loaded = threading.Event()
    original_begin = service.ledger.begin_attention_resolution
    original_get_identity = service.waiters.get_identity

    def paused_begin(*args, **kwargs):
        claim = original_begin(*args, **kwargs)
        claim_committed.set()
        assert release_claim.wait(timeout=5)
        return claim

    def tracked_get_identity(attention_id: str):
        identity = original_get_identity(attention_id)
        if threading.current_thread().name == "attention-teardown":
            cancel_identity_loaded.set()
        return identity

    monkeypatch.setattr(service.ledger, "begin_attention_resolution", paused_begin)
    monkeypatch.setattr(service.waiters, "get_identity", tracked_get_identity)
    response_results: list[dict[str, Any]] = []
    cancel_results: list[dict[str, Any] | None] = []
    response_errors: list[BaseException] = []
    cancel_errors: list[BaseException] = []

    def respond() -> None:
        try:
            response_results.append(
                service.respond_attention(
                    attention_id=attention["attention_id"],
                    expected_version=1,
                    idempotency_key="teardown-race-response-key",
                    action="submit",
                    raw_value="TOP-SECRET-ANSWER",
                )
            )
        except BaseException as exc:
            response_errors.append(exc)

    def cancel() -> None:
        try:
            cancel_results.append(
                service.cancel_attention(
                    attention["attention_id"],
                    terminal_reason="session_closed",
                )
            )
        except BaseException as exc:
            cancel_errors.append(exc)

    responder = threading.Thread(target=respond)
    teardown = threading.Thread(target=cancel, name="attention-teardown")
    responder.start()
    assert claim_committed.wait(timeout=5)
    teardown.start()
    assert cancel_identity_loaded.wait(timeout=5)
    release_claim.set()
    responder.join(timeout=5)
    teardown.join(timeout=5)

    assert not responder.is_alive() and not teardown.is_alive()
    assert response_errors == []
    assert not cancel_errors or all(
        isinstance(error, WaiterUnavailable) for error in cancel_errors
    )
    assert delivered == ["TOP-SECRET-ANSWER"]
    assert response_results[0]["state"] == "resolved"
    assert cancel_results in ([], [None])
    assert service.ledger.get_attention(attention["attention_id"])["state"] == "resolved"
    receipt = service.ledger.get_idempotency(
        operation="attention.respond",
        idempotency_key="teardown-race-response-key",
    )
    assert receipt is not None and receipt["state"] == "finalized"


def test_session_teardown_drains_more_than_one_hundred_waiters(tmp_path: Path) -> None:
    session, _ = _install_session(tmp_path)
    service = server._work_service_for_session(session)
    cancelled: list[str] = []
    for index in range(125):
        service.create_attention_waiter(
            source_session_key="conversation-mobile-session",
            runtime_session_id="mobile-session",
            request_id=f"bulk-teardown-request-{index:03d}",
            kind="clarify",
            title="Question",
            public_payload={"question": "Continue?"},
            deliver=lambda _value: True,
            cancel=lambda item=str(index): cancelled.append(item),
        )

    changed = service.cancel_attention_session(
        "mobile-session",
        terminal_reason="session_closed",
    )

    assert len(changed) == 125
    assert len(cancelled) == 125
    assert service.waiters.active_count == 0
    conn = sqlite3.connect(service.ledger.path)
    try:
        states = dict(
            conn.execute(
                "SELECT state, COUNT(*) FROM attention_items GROUP BY state"
            ).fetchall()
        )
    finally:
        conn.close()
    assert states == {"cancelled": 125}


@pytest.mark.parametrize("kind", ["clarify", "sudo", "secret"])
def test_nonapproval_cancel_rejects_client_value_without_delivery(
    tmp_path: Path,
    kind: str,
) -> None:
    session, _ = _install_session(tmp_path)
    service = server._work_service_for_session(session)
    delivered: list[object] = []
    sentinel = f"DO-NOT-DELIVER-{kind}-VALUE"
    attention = service.create_attention_waiter(
        source_session_key="conversation-mobile-session",
        runtime_session_id="mobile-session",
        request_id=f"cancel-value-{kind}-request",
        kind=kind,
        title="Input required",
        public_payload={"question": "Continue?"},
        deliver=lambda value: delivered.append(value) or True,
        sensitive=kind in {"sudo", "secret"},
    )
    base = {
        "session_id": "mobile-session",
        "attention_id": attention["attention_id"],
        "expected_version": 1,
        "idempotency_key": f"cancel-value-{kind}-key-0001",
        "action": "cancel",
    }

    invalid = _rpc("attention.respond", {**base, "value": sentinel})

    assert invalid["error"]["data"]["code"] == "invalid_params"
    assert delivered == []
    assert service.ledger.get_attention(attention["attention_id"])["state"] == "pending"
    conn = sqlite3.connect(service.ledger.path)
    try:
        assert sentinel not in "\n".join(conn.iterdump())
    finally:
        conn.close()

    accepted = _rpc("attention.respond", base)["result"]
    assert accepted["state"] == "denied"
    assert delivered == [""]


def test_approval_deny_reason_is_ephemeral_and_only_valid_for_deny(
    tmp_path: Path,
) -> None:
    session, _ = _install_session(tmp_path)
    service = server._work_service_for_session(session)
    delivered: list[object] = []
    attention = service.create_attention_waiter(
        source_session_key="conversation-mobile-session",
        runtime_session_id="mobile-session",
        request_id="approval-reason-request",
        kind="approval",
        title="Approval required",
        public_payload={"description": "Review action"},
        deliver=lambda value: delivered.append(value) or True,
    )
    reason = "OPENAI_API_KEY=" + "r" * 48
    base = {
        "session_id": "mobile-session",
        "attention_id": attention["attention_id"],
        "expected_version": 1,
        "idempotency_key": "approval-reason-key-00001",
        "action": "deny",
        "reason": reason,
    }
    first = _rpc("attention.respond", base)["result"]
    replay = _rpc(
        "attention.respond",
        {**base, "reason": "different retry reason"},
    )["result"]

    assert first["state"] == "denied"
    assert replay == {**first, "replayed": True}
    assert delivered == [{"choice": "deny", "reason": reason}]
    conn = sqlite3.connect(service.ledger.path)
    try:
        dump = "\n".join(conn.iterdump())
    finally:
        conn.close()
    assert reason not in dump

    second = service.create_attention_waiter(
        source_session_key="conversation-mobile-session",
        runtime_session_id="mobile-session",
        request_id="approval-invalid-reason-request",
        kind="approval",
        title="Approval required",
        public_payload={},
        deliver=lambda value: delivered.append(value) or True,
    )
    invalid = _rpc(
        "attention.respond",
        {
            "session_id": "mobile-session",
            "attention_id": second["attention_id"],
            "expected_version": 1,
            "idempotency_key": "approval-invalid-reason-key",
            "action": "once",
            "reason": "not meaningful for approval",
        },
    )
    assert invalid["error"]["data"]["code"] == "invalid_params"
    assert service.ledger.get_attention(second["attention_id"])["state"] == "pending"


@pytest.mark.parametrize(
    ("exc", "number", "code"),
    [
        (InvalidPublicData("bad"), -32602, "invalid_params"),
        (WorkNotFound("hidden-id"), -32004, "not_found"),
        (IdempotencyConflict("hidden"), -32041, "idempotency_conflict"),
        (VersionConflict("hidden"), -32042, "version_conflict"),
        (InvalidTransition("hidden"), -32043, "invalid_transition"),
        (LedgerRuntimeOwnerMismatch("hidden"), -32044, "runtime_owner_mismatch"),
        (RuntimeOwnerMismatch("hidden"), -32044, "runtime_owner_mismatch"),
        (AttentionNotActionable("hidden"), -32045, "attention_not_actionable"),
        (WaiterUnavailable("hidden"), -32046, "waiter_unavailable"),
        (DeliveryOutcomeUnknown("hidden"), -32046, "waiter_unavailable"),
        (CursorExpired("hidden"), -32047, "cursor_expired"),
        (WorkStoreReplacedError("hidden"), -32047, "cursor_expired"),
        (WorkStoreRebound("hidden"), -32047, "cursor_expired"),
        (WorkStoreUnavailable("hidden"), -32048, "work_store_unavailable"),
        (WorkCapacityExceeded("hidden"), -32049, "work_capacity_exceeded"),
        (WorkOperationInProgress("hidden"), -32050, "work_operation_in_progress"),
    ],
)
def test_work_error_mapping_is_stable_and_sanitized(
    exc: BaseException, number: int, code: str
) -> None:
    response = server._work_err("error", exc)
    assert response["error"]["code"] == number
    assert response["error"]["data"]["code"] == code
    assert "hidden" not in repr(response)


def test_replaced_work_store_requires_bootstrap_without_leaking_identity(
    tmp_path: Path,
) -> None:
    session, _ = _install_session(tmp_path)
    service = server._work_service_for_session(session)
    replacement = "ledger_" + "f" * 32
    conn = sqlite3.connect(service.ledger.path)
    try:
        conn.execute(
            "UPDATE work_meta SET value=? WHERE key='ledger_id'",
            (replacement,),
        )
        conn.commit()
    finally:
        conn.close()

    response = _rpc("job.list", {"session_id": "mobile-session"})

    assert response["error"] == {
        "code": -32047,
        "message": "Work cursor expired; bootstrap again",
        "data": {"code": "cursor_expired", "bootstrap": True},
    }
    assert replacement not in repr(response)


def test_work_methods_remain_unadvertised(tmp_path: Path) -> None:
    _install_session(tmp_path)
    capabilities = _rpc("gateway.capabilities", {})["result"]
    assert not {
        "job.create",
        "job.sync",
        "job.get",
        "job.list",
        "job.events",
        "job.cancel",
        "attention.get",
        "attention.list",
        "attention.respond",
    }.intersection(capabilities["methods"])
    assert "durable_work" not in capabilities["features"]


@pytest.mark.parametrize(
    ("method", "params"),
    [
        (
            "job.create",
            {
                "kind": "background_prompt",
                "text": "x",
                "idempotency_key": "allowlist-create-key-001",
            },
        ),
        ("job.get", {"job_id": "job_" + "1" * 32}),
        ("job.list", {}),
        ("job.events", {"after": 0}),
        ("job.sync", {}),
        (
            "job.cancel",
            {
                "job_id": "job_" + "1" * 32,
                "expected_version": 1,
                "idempotency_key": "allowlist-cancel-key-001",
            },
        ),
        ("attention.get", {"attention_id": "attn_" + "1" * 32}),
        ("attention.list", {}),
        (
            "attention.respond",
            {
                "attention_id": "attn_" + "1" * 32,
                "expected_version": 1,
                "idempotency_key": "allowlist-attention-key-1",
                "action": "submit",
                "value": "answer",
            },
        ),
    ],
)
def test_every_work_rpc_rejects_unknown_client_scope_fields(
    tmp_path: Path, method: str, params: dict[str, Any]
) -> None:
    _install_session(tmp_path)
    response = _rpc(
        method,
        {"session_id": "mobile-session", **params, "profile": "forged-profile"},
    )
    assert response["error"]["code"] == -32602
    assert response["error"]["data"] == {"code": "invalid_params"}


def test_work_list_empty_filters_return_empty_pages(tmp_path: Path) -> None:
    _install_session(tmp_path)

    jobs = _rpc(
        "job.list",
        {"session_id": "mobile-session", "statuses": []},
    )["result"]
    attention = _rpc(
        "attention.list",
        {"session_id": "mobile-session", "states": []},
    )["result"]

    assert jobs["jobs"] == [] and jobs["next_before"] is None
    assert attention["attention"] == [] and attention["next_before"] is None


def test_job_read_collection_and_delta_rpc_shapes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _session, _ = _install_session(tmp_path)
    release = threading.Event()
    monkeypatch.setattr(
        server,
        "_run_durable_background_agent",
        lambda _spec, _control: (release.wait(timeout=5), {"final_response": "ok"})[1],
    )
    receipt = _rpc(
        "job.create",
        {
            "session_id": "mobile-session",
            "kind": "background_prompt",
            "text": "inspect",
            "title": "Inspectable",
            "idempotency_key": "read-shapes-create-key-01",
        },
    )["result"]
    job_id = receipt["job"]["job_id"]
    detail = _rpc("job.get", {"session_id": "mobile-session", "job_id": job_id})[
        "result"
    ]
    listing = _rpc(
        "job.list",
        {"session_id": "mobile-session", "statuses": [detail["status"]], "limit": 10},
    )["result"]
    events = _rpc(
        "job.events",
        {"session_id": "mobile-session", "job_id": job_id, "after": 0},
    )["result"]
    delta = _rpc(
        "job.sync",
        {
            "session_id": "mobile-session",
            "ledger_id": server._work_service_for_session(_session).ledger_id,
            "after": 0,
            "limit": 100,
        },
    )["result"]

    assert detail["job_id"] == job_id
    assert [job["job_id"] for job in listing["jobs"]] == [job_id]
    assert events["events"][0]["event_type"] == "job.created"
    assert delta["mode"] == "delta"
    assert delta["events"][0]["subject_id"] == job_id
    release.set()


def test_job_and_attention_list_tokens_preserve_submillisecond_order(
    tmp_path: Path,
) -> None:
    session, _ = _install_session(tmp_path)
    service = server._work_service_for_session(session)
    jobs: list[dict[str, Any]] = []
    for index, timestamp in enumerate((1000.0008, 1000.0009)):
        jobs.append(
            service.ledger.create_job(
                kind="background_prompt",
                title=f"Job {index}",
                source="mobile",
                owner=service.owner,
                source_session_key="conversation-mobile-session",
                runtime_session_id="mobile-session",
                runtime_summary={"kind": "in_process_agent"},
                run_runtime={"kind": "in_process_agent"},
                idempotency_key=f"same-ms-job-key-{index:04d}",
                now=timestamp,
            )["job"]
        )
    attention: list[dict[str, Any]] = []
    for index, timestamp in enumerate((2000.0008, 2000.0009)):
        attention.append(
            service.ledger.create_attention(
                source_session_key="conversation-mobile-session",
                runtime_session_id="mobile-session",
                request_id=f"same-ms-attention-{index:04d}",
                kind="clarify",
                title="Question",
                public_payload={"question": "Continue?"},
                owner=service.owner,
                waiter_generation=f"same-ms-waiter-{index}",
                now=timestamp,
            )
        )

    first_jobs = _rpc("job.list", {"session_id": "mobile-session", "limit": 1})[
        "result"
    ]
    second_jobs = _rpc(
        "job.list",
        {
            "session_id": "mobile-session",
            "limit": 1,
            "before": first_jobs["next_before"],
        },
    )["result"]
    assert first_jobs["jobs"][0]["job_id"] == jobs[1]["job_id"]
    assert second_jobs["jobs"][0]["job_id"] == jobs[0]["job_id"]
    assert first_jobs["jobs"][0]["updated_at"] == second_jobs["jobs"][0]["updated_at"]

    first_attention = _rpc(
        "attention.list",
        {"session_id": "mobile-session", "limit": 1},
    )["result"]
    second_attention = _rpc(
        "attention.list",
        {
            "session_id": "mobile-session",
            "limit": 1,
            "before": first_attention["next_before"],
        },
    )["result"]
    assert first_attention["attention"][0]["attention_id"] == attention[1]["attention_id"]
    assert second_attention["attention"][0]["attention_id"] == attention[0]["attention_id"]
    assert (
        first_attention["attention"][0]["created_at"]
        == second_attention["attention"][0]["created_at"]
    )


def test_attention_get_and_list_rpc_shapes(tmp_path: Path) -> None:
    session, _ = _install_session(tmp_path)
    service = server._work_service_for_session(session)
    attention = service.create_attention_waiter(
        source_session_key="conversation-mobile-session",
        runtime_session_id="mobile-session",
        request_id="attention-read-request",
        kind="approval",
        title="Review action",
        public_payload={"description": "reviewed"},
        deliver=lambda _value: True,
    )

    detail = _rpc(
        "attention.get",
        {"session_id": "mobile-session", "attention_id": attention["attention_id"]},
    )["result"]
    listing = _rpc(
        "attention.list",
        {"session_id": "mobile-session", "states": ["pending"], "limit": 10},
    )["result"]

    assert detail["attention_id"] == attention["attention_id"]
    assert [item["attention_id"] for item in listing["attention"]] == [
        attention["attention_id"]
    ]


def test_unsupported_job_kind_has_stable_typed_error(tmp_path: Path) -> None:
    _install_session(tmp_path)
    response = _rpc(
        "job.create",
        {
            "session_id": "mobile-session",
            "kind": "unknown_kind",
            "text": "x",
            "idempotency_key": "unsupported-kind-key-0001",
        },
    )
    assert response["error"] == {
        "code": -32040,
        "message": "Unsupported job kind",
        "data": {"code": "unsupported_job_kind"},
    }
