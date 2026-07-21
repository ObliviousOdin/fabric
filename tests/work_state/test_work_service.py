from __future__ import annotations

import inspect
import logging
import queue
import sqlite3
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, Callable

import pytest

from fabric_cli.work_ledger import (
    RuntimeOwnerMismatch as LedgerRuntimeOwnerMismatch,
    VersionConflict,
    WorkLedger,
)
from tui_gateway import work_service as work_service_module
from tui_gateway.work_service import (
    BackgroundRunSpec,
    CapacityReservation,
    DeliveryOutcomeUnknown,
    GlobalWorkScheduler,
    OwnerClassification,
    OwnerProof,
    OwnerProofUnavailable,
    RuntimeOwnerMismatch,
    RuntimeRegistry,
    SchedulerLimits,
    WaiterAlreadyConsumed,
    WaiterRegistry,
    WaiterUnavailable,
    WorkCapacityExceeded,
    WorkSchedulerClosed,
    WorkService,
    WorkServiceCache,
    WorkServiceClosed,
    WorkStoreRebound,
    classify_owner,
    classify_owner_group,
    create_process_owner_proof,
    get_global_work_scheduler,
)


class FakeLedger:
    def __init__(self, ledger_id: str = "ledger_test") -> None:
        self.ledger_id = ledger_id
        self.closed = False
        self.identity_checks = 0
        self.candidates: list[dict[str, Any]] = []
        self.reconciled: list[tuple[object, str]] = []
        self.retention_calls: list[dict[str, int]] = []
        self.retention_error: Exception | None = None
        self.retention_result: dict[str, int] = {
            "events_deleted": 0,
            "idempotency_deleted": 0,
            "jobs_deleted": 0,
            "attention_deleted": 0,
            "event_floor": 1,
        }

    def close(self) -> None:
        self.closed = True

    def assert_store_identity(self) -> None:
        self.identity_checks += 1

    def list_nonterminal_owners(self) -> list[dict[str, Any]]:
        return list(self.candidates)

    def reconcile_owner(self, *, owner: object, classification: str) -> None:
        self.reconciled.append((owner, classification))

    def run_retention(
        self,
        *,
        event_batch_size: int = 1_000,
        idempotency_batch_size: int = 1_000,
        subject_batch_size: int = 100,
    ) -> dict[str, int]:
        self.retention_calls.append(
            {
                "event_batch_size": event_batch_size,
                "idempotency_batch_size": idempotency_batch_size,
                "subject_batch_size": subject_batch_size,
            }
        )
        if self.retention_error is not None:
            raise self.retention_error
        return dict(self.retention_result)


class ManualClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, amount: float) -> None:
        self.value += amount


class LockContentionProbe:
    """RLock wrapper that deterministically records a named thread's contention."""

    def __init__(self, target_thread_name: str) -> None:
        self._lock = threading.RLock()
        self._target_thread_name = target_thread_name
        self.classified = threading.Event()
        self.blocked = threading.Event()
        self.acquired_without_blocking = threading.Event()

    def __enter__(self) -> LockContentionProbe:
        if threading.current_thread().name != self._target_thread_name:
            self._lock.acquire()
            return self

        acquired = self._lock.acquire(blocking=False)
        if acquired:
            self.acquired_without_blocking.set()
        else:
            self.blocked.set()
        self.classified.set()
        if not acquired:
            self._lock.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._lock.release()


@pytest.fixture
def runtime_owner() -> OwnerProof:
    return OwnerProof(
        boot_token="instantiation:test-boot",
        pid=4242,
        start_token="100",
        generation="gen_test",
    )


def _spec(
    profile_home: Path,
    owner: OwnerProof,
    number: int,
    *,
    prompt: str | None = None,
) -> BackgroundRunSpec:
    return BackgroundRunSpec.create(
        job_id=f"job_{number:032x}",
        run_id=f"run_{number:032x}",
        profile_home=profile_home,
        runtime_session_id=f"runtime-{number}",
        source_session_key=f"session-{number}",
        prompt=prompt or f"prompt {number}",
        owner=owner,
        agent_inputs={"model": "test", "nested": {"number": number}},
    )


def _create_service_background(
    service: WorkService,
    *,
    suffix: str,
    runner: Callable[[BackgroundRunSpec, Any], Any],
    agent_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return service.create_background_job(
        runtime_session_id=f"runtime-{suffix}",
        source_session_key=f"session-{suffix}",
        text=f"prompt {suffix}",
        title=f"Background {suffix}",
        idempotency_key=f"service-background-{suffix}-key",
        agent_inputs=agent_inputs or {"model": "test"},
        runner=runner,
        source="test",
    )


def test_global_scheduler_limit_warning_formats_without_logging_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 1))
    monkeypatch.setattr(work_service_module, "_global_scheduler", scheduler)

    with caplog.at_level(logging.WARNING, logger="tui_gateway.work_service"):
        selected = get_global_work_scheduler(limits=SchedulerLimits(2, 3))

    assert selected is scheduler
    assert caplog.messages == [
        "Ignoring per-caller work scheduler limits SchedulerLimits("
        "max_concurrent_jobs=2, max_queued_jobs=3); process-global limits are "
        "SchedulerLimits(max_concurrent_jobs=1, max_queued_jobs=1)"
    ]
    scheduler.shutdown()


def test_process_owner_proof_requires_every_field() -> None:
    proof = create_process_owner_proof(
        pid=44,
        generation="gen-fixed",
        boot_token_provider=lambda: "instantiation:boot",
        start_token_provider=lambda pid: f"start-{pid}",
    )
    assert proof == OwnerProof("instantiation:boot", 44, "start-44", "gen-fixed")

    with pytest.raises(OwnerProofUnavailable):
        create_process_owner_proof(
            pid=44,
            boot_token_provider=lambda: None,
            start_token_provider=lambda _pid: "start",
        )
    with pytest.raises(OwnerProofUnavailable):
        create_process_owner_proof(
            pid=44,
            boot_token_provider=lambda: "boot",
            start_token_provider=lambda _pid: None,
        )
    with pytest.raises(OwnerProofUnavailable):
        OwnerProof("b" * 513, 44, "start", "generation")


@pytest.mark.parametrize(
    ("current_boot", "alive", "current_start", "expected"),
    [
        ("other-boot", True, "100", OwnerClassification.DIFFERENT_BOOT),
        ("instantiation:test-boot", False, None, OwnerClassification.DEAD),
        ("instantiation:test-boot", True, "101", OwnerClassification.PID_REUSED),
        ("instantiation:test-boot", True, None, OwnerClassification.UNVERIFIABLE),
        (None, None, None, OwnerClassification.UNVERIFIABLE),
        ("instantiation:test-boot", True, "100", OwnerClassification.LIVE),
    ],
)
def test_owner_classification_uses_only_positive_evidence(
    runtime_owner: OwnerProof,
    current_boot: str | None,
    alive: bool | None,
    current_start: str | None,
    expected: OwnerClassification,
) -> None:
    classification = classify_owner(
        runtime_owner,
        current_boot_token=current_boot,
        pid_exists=lambda _pid: alive,
        start_token_probe=lambda _pid: current_start,
    )
    assert classification is expected
    assert classification.recoverable is (
        expected
        in {
            OwnerClassification.DIFFERENT_BOOT,
            OwnerClassification.DEAD,
            OwnerClassification.PID_REUSED,
        }
    )


def test_owner_probe_failures_are_unverifiable_not_dead(runtime_owner: OwnerProof) -> None:
    def broken_probe(_pid: int) -> bool:
        raise PermissionError("not observable")

    assert (
        classify_owner(
            runtime_owner,
            current_boot_token=runtime_owner.boot_token,
            pid_exists=broken_probe,
        )
        is OwnerClassification.UNVERIFIABLE
    )


def test_owner_group_probes_one_os_identity_once(runtime_owner: OwnerProof) -> None:
    second_generation = replace(runtime_owner, generation="gen_second")
    calls = {"alive": 0, "start": 0}

    def alive(_pid: int) -> bool:
        calls["alive"] += 1
        return True

    def start(_pid: int) -> str:
        calls["start"] += 1
        return "100"

    result = classify_owner_group(
        [runtime_owner, second_generation],
        current_boot_token=runtime_owner.boot_token,
        pid_exists=alive,
        start_token_probe=start,
    )

    assert result == {
        runtime_owner: OwnerClassification.LIVE,
        second_generation: OwnerClassification.LIVE,
    }
    assert calls == {"alive": 1, "start": 1}


def test_background_run_spec_is_immutable_snapshot_without_parent_agent(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    inputs = {"nested": {"values": [1, 2]}}
    spec = BackgroundRunSpec.create(
        job_id="job_" + "1" * 32,
        run_id="run_" + "2" * 32,
        profile_home=tmp_path / "profile" / ".." / "profile",
        runtime_session_id="runtime",
        source_session_key="session",
        prompt="raw prompt",
        owner=runtime_owner,
        agent_inputs=inputs,
    )
    inputs["nested"]["values"].append(3)

    assert spec.agent_inputs() == {"nested": {"values": [1, 2]}}
    assert spec.interaction_key == "work:run_" + "2" * 32
    assert "parent_agent" not in inspect.signature(BackgroundRunSpec).parameters
    with pytest.raises(FrozenInstanceError):
        spec.prompt = "changed"  # type: ignore[misc]


def test_background_run_spec_bounds_raw_prompt_and_agent_inputs(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    common = {
        "job_id": "job_" + "1" * 32,
        "run_id": "run_" + "2" * 32,
        "profile_home": tmp_path,
        "runtime_session_id": "runtime",
        "source_session_key": "session",
        "owner": runtime_owner,
    }
    with pytest.raises(ValueError, match="prompt exceeds"):
        BackgroundRunSpec.create(**common, prompt="x" * 200_001)
    with pytest.raises(ValueError, match="construction inputs exceed"):
        BackgroundRunSpec.create(
            **common,
            prompt="work",
            agent_inputs={"large": "x" * (32 * 1024)},
        )
    with pytest.raises(ValueError, match="JSON-safe"):
        BackgroundRunSpec.create(
            **common,
            prompt="work",
            agent_inputs={"not_finite": float("nan")},
        )


def test_background_job_prevalidation_failure_creates_no_durable_state(
    tmp_path: Path,
    runtime_owner: OwnerProof,
) -> None:
    profile = tmp_path / "profile"
    ledger = WorkLedger(profile)
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    service = WorkService(
        profile,
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )
    key = "service-background-oversize-key"

    try:
        with pytest.raises(ValueError, match="construction inputs exceed"):
            service.create_background_job(
                runtime_session_id="runtime-oversize",
                source_session_key="session-oversize",
                text="must never become queued",
                title="Oversize inputs",
                idempotency_key=key,
                agent_inputs={"large": "x" * (33 * 1024)},
                runner=lambda _spec, _control: None,
                source="test",
            )

        assert ledger.list_jobs() == []
        assert ledger.get_idempotency(
            operation="job.create",
            idempotency_key=key,
        ) is None
        assert scheduler.owner_load(service.cache_key) == 0
        assert service.runtimes.active_count == 0
    finally:
        service.shutdown()
        scheduler.shutdown(wait=True, timeout=5)


def test_background_runtime_setup_failure_durably_interrupts_created_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runtime_owner: OwnerProof,
) -> None:
    profile = tmp_path / "profile"
    ledger = WorkLedger(profile)
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    service = WorkService(
        profile,
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )

    def fail_register(**_kwargs: Any) -> None:
        raise RuntimeError("injected runtime registration failure")

    monkeypatch.setattr(service.runtimes, "register", fail_register)
    try:
        with pytest.raises(RuntimeError, match="injected runtime registration failure"):
            _create_service_background(
                service,
                suffix="setup-failure",
                runner=lambda _spec, _control: None,
            )

        jobs = ledger.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["status"] == "interrupted"
        assert jobs[0]["error"]["code"] == "runtime_setup_failed"
        assert scheduler.owner_load(service.cache_key) == 0
        assert service.runtimes.active_count == 0
        assert service._job_controls == {}
        assert service._job_futures == {}
    finally:
        service.shutdown()
        scheduler.shutdown(wait=True, timeout=5)


def test_successful_background_future_cleans_runtime_and_control_state(
    tmp_path: Path,
    runtime_owner: OwnerProof,
) -> None:
    profile = tmp_path / "profile"
    ledger = WorkLedger(profile)
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    service = WorkService(
        profile,
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )
    started = threading.Event()
    release = threading.Event()

    def runner(_spec: BackgroundRunSpec, _control: Any) -> str:
        started.set()
        assert release.wait(timeout=5)
        return "finished"

    try:
        receipt = _create_service_background(
            service,
            suffix="success-cleanup",
            runner=runner,
        )
        job_id = receipt["job"]["job_id"]
        assert started.wait(timeout=5)
        future = service._job_futures[job_id]
        release.set()

        assert future.result(timeout=5) == "finished"
        assert ledger.get_job(job_id)["status"] == "succeeded"
        assert service.runtimes.active_count == 0
        assert job_id not in service._job_controls
        assert job_id not in service._job_futures
        assert scheduler.owner_load(service.cache_key) == 0
    finally:
        release.set()
        service.shutdown()
        scheduler.shutdown(wait=True, timeout=5)


def test_scheduler_abandonment_terminalizes_and_cleans_queued_runtime(
    tmp_path: Path,
    runtime_owner: OwnerProof,
) -> None:
    profile = tmp_path / "profile"
    ledger = WorkLedger(profile)
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 1))
    service = WorkService(
        profile,
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )
    started = threading.Event()
    release = threading.Event()

    def blocking(_spec: BackgroundRunSpec, _control: Any) -> str:
        started.set()
        assert release.wait(timeout=5)
        return "first finished"

    try:
        first = _create_service_background(
            service,
            suffix="abandon-running",
            runner=blocking,
        )
        assert started.wait(timeout=5)
        second = _create_service_background(
            service,
            suffix="abandon-queued",
            runner=lambda _spec, _control: "must not run",
        )
        first_id = first["job"]["job_id"]
        second_id = second["job"]["job_id"]
        first_future = service._job_futures[first_id]
        second_future = service._job_futures[second_id]

        scheduler.shutdown(wait=False)

        with pytest.raises(WorkSchedulerClosed):
            second_future.result(timeout=5)
        terminal = ledger.get_job(second_id)
        assert terminal["status"] == "interrupted"
        assert terminal["error"]["code"] == "runner_never_started"
        assert second_id not in service._job_controls
        assert second_id not in service._job_futures
        assert service.runtimes.active_count == 1

        release.set()
        assert first_future.result(timeout=5) == "first finished"
        assert ledger.get_job(first_id)["status"] == "succeeded"
        assert service.runtimes.active_count == 0
    finally:
        release.set()
        service.shutdown()
        scheduler.shutdown(wait=True, timeout=5)


def test_cancel_queued_job_evicts_prompt_and_releases_capacity_immediately(
    tmp_path: Path,
    runtime_owner: OwnerProof,
) -> None:
    profile = tmp_path / "profile"
    ledger = WorkLedger(profile)
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 1))
    service = WorkService(
        profile,
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )
    started = threading.Event()
    release = threading.Event()

    def blocking(_spec: BackgroundRunSpec, _control: Any) -> str:
        started.set()
        assert release.wait(timeout=5)
        return "first finished"

    try:
        first = _create_service_background(
            service,
            suffix="cancel-running",
            runner=blocking,
        )
        assert started.wait(timeout=5)
        second = _create_service_background(
            service,
            suffix="cancel-queued",
            runner=lambda _spec, _control: "must not run",
        )
        first_id = first["job"]["job_id"]
        second_id = second["job"]["job_id"]
        first_future = service._job_futures[first_id]
        second_future = service._job_futures[second_id]
        assert scheduler.owner_load(service.cache_key) == 2

        cancel_receipt = service.cancel_background_job(
            job_id=second_id,
            expected_version=1,
            idempotency_key="service-cancel-queued-job-key",
        )

        assert cancel_receipt["job"]["status"] == "cancel_requested"
        assert second_future.cancelled()
        assert scheduler.stats().queued == 0
        assert scheduler.owner_load(service.cache_key) == 1
        terminal = ledger.get_job(second_id)
        assert terminal["status"] == "cancelled"
        assert second_id not in service._job_controls
        assert second_id not in service._job_futures
        assert service.runtimes.active_count == 1
        replacement = scheduler.reserve(owner_key=service.cache_key)
        assert replacement.active is True
        replacement.release()

        release.set()
        assert first_future.result(timeout=5) == "first finished"
        assert ledger.get_job(first_id)["status"] == "succeeded"
    finally:
        release.set()
        service.shutdown()
        scheduler.shutdown(wait=True, timeout=5)


def test_cancel_running_job_returns_receipt_when_agent_interrupt_raises(
    tmp_path: Path,
    runtime_owner: OwnerProof,
) -> None:
    profile = tmp_path / "profile"
    ledger = WorkLedger(profile)
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    service = WorkService(
        profile,
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )
    started = threading.Event()
    release = threading.Event()

    class RaisingAgent:
        def interrupt(self) -> None:
            raise RuntimeError("injected interrupt failure")

    def runner(_spec: BackgroundRunSpec, control: Any) -> str:
        control.attach_agent(RaisingAgent())
        started.set()
        assert release.wait(timeout=5)
        return "late result"

    try:
        created = _create_service_background(
            service,
            suffix="raising-interrupt",
            runner=runner,
        )
        job_id = created["job"]["job_id"]
        assert started.wait(timeout=5)
        running = ledger.get_job(job_id)
        assert running["status"] == "running"
        future = service._job_futures[job_id]

        receipt = service.cancel_background_job(
            job_id=job_id,
            expected_version=running["version"],
            idempotency_key="service-raising-interrupt-cancel",
        )

        assert receipt["job"]["status"] == "cancel_requested"
        release.set()
        assert future.result(timeout=5) == "late result"
        assert ledger.get_job(job_id)["status"] == "cancelled"
        assert any(
            event["event_type"] == "job.run_late_result"
            and event["subject_id"] == job_id
            and event["subject"]["status"] == "cancelled"
            for event in ledger.list_events()
        )
    finally:
        release.set()
        service.shutdown()
        scheduler.shutdown(wait=True, timeout=5)


def test_scheduler_limits_parse_gateway_work_config() -> None:
    assert SchedulerLimits.from_config(None) == SchedulerLimits(2, 32)
    assert SchedulerLimits.from_config(
        {"gateway": {"work": {"max_concurrent_jobs": "3", "max_queued_jobs": 7}}}
    ) == SchedulerLimits(3, 7)
    assert SchedulerLimits.from_config(
        {"gateway": {"work": {"max_concurrent_jobs": 0, "max_queued_jobs": -1}}}
    ) == SchedulerLimits(2, 32)


def test_process_global_scheduler_bounds_running_and_queue_across_profiles(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    scheduler = GlobalWorkScheduler(SchedulerLimits(2, 2))
    release = threading.Event()
    started: queue.Queue[str] = queue.Queue()

    def runner(spec: BackgroundRunSpec) -> str:
        started.put(spec.run_id)
        assert release.wait(timeout=5)
        return spec.run_id

    futures = []
    for number in range(4):
        profile = tmp_path / ("alpha" if number % 2 == 0 else "beta")
        reservation = scheduler.reserve(owner_key=str(profile / "work.db"))
        futures.append(scheduler.submit(reservation, _spec(profile, runtime_owner, number + 1), runner))

    started.get(timeout=5)
    started.get(timeout=5)
    stats = scheduler.stats()
    assert (stats.running, stats.queued, stats.reserved) == (2, 2, 0)
    with pytest.raises(WorkCapacityExceeded) as exc:
        scheduler.reserve(owner_key="third-profile")
    assert exc.value.retryable is True

    release.set()
    assert {future.result(timeout=5) for future in futures} == {
        f"run_{number:032x}" for number in range(1, 5)
    }
    assert scheduler.stats().running == 0
    scheduler.shutdown(wait=True, timeout=5)


def test_releasing_failed_admission_reservation_restores_capacity() -> None:
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    reservation = scheduler.reserve(owner_key="profile")
    with pytest.raises(WorkCapacityExceeded):
        scheduler.reserve(owner_key="profile")
    assert reservation.release() is True
    replacement = scheduler.reserve(owner_key="profile")
    assert replacement.active is True
    replacement.release()
    scheduler.shutdown()


def test_scheduler_shutdown_drops_queued_prompt_and_reports_abandonment(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 1))
    release = threading.Event()
    started = threading.Event()
    abandoned: list[tuple[str, str]] = []

    def blocking(spec: BackgroundRunSpec) -> str:
        started.set()
        assert release.wait(timeout=5)
        return spec.run_id

    first = scheduler.reserve(owner_key="profile")
    first_future = scheduler.submit(first, _spec(tmp_path, runtime_owner, 1), blocking)
    assert started.wait(timeout=5)
    second = scheduler.reserve(owner_key="profile")
    second_future = scheduler.submit(
        second,
        _spec(tmp_path, runtime_owner, 2, prompt="sensitive queued prompt"),
        blocking,
        on_abandon=lambda spec, reason: abandoned.append((spec.run_id, reason)),
    )

    scheduler.shutdown(wait=False)
    with pytest.raises(WorkSchedulerClosed):
        second_future.result(timeout=5)
    assert abandoned == [("run_" + f"{2:032x}", "scheduler_shutdown")]
    release.set()
    assert first_future.result(timeout=5) == "run_" + f"{1:032x}"
    scheduler.shutdown(wait=True, timeout=5)


def test_runtime_registry_requires_exact_local_generation_and_cancels_once(
    runtime_owner: OwnerProof,
) -> None:
    registry = RuntimeRegistry(runtime_owner)
    calls: list[str] = []
    registry.register(run_id="run-one", owner=runtime_owner, cancel=lambda: calls.append("cancel"))

    with pytest.raises(RuntimeOwnerMismatch):
        registry.cancel("run-one", owner=replace(runtime_owner, generation="other"))
    assert registry.cancel("run-one", owner=runtime_owner) is True
    assert registry.cancel("run-one", owner=runtime_owner) is False
    assert calls == ["cancel"]
    assert registry.unregister("run-one", owner=runtime_owner) is True
    assert registry.active_count == 0


def test_waiter_concurrent_duplicate_delivers_at_most_once(
    runtime_owner: OwnerProof,
) -> None:
    registry = WaiterRegistry(runtime_owner)
    callback_entered = threading.Event()
    callback_release = threading.Event()
    calls: list[object] = []

    def deliver(value: object) -> bool:
        calls.append(value)
        callback_entered.set()
        assert callback_release.wait(timeout=5)
        return True

    identity = registry.register(
        attention_id="attn-one",
        runtime_session_id="session-one",
        owner=runtime_owner,
        deliver=deliver,
        waiter_generation="wait-one",
    )

    kwargs = {
        "attention_id": identity.attention_id,
        "owner": runtime_owner,
        "waiter_generation": identity.waiter_generation,
        "resolution_token": "resolution-one",
        "raw_value": "secret value",
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(registry.deliver_once, **kwargs)
        assert callback_entered.wait(timeout=5)
        second = pool.submit(registry.deliver_once, **kwargs)
        callback_release.set()
        first_result = first.result(timeout=5)
        second_result = second.result(timeout=5)

    assert calls == ["secret value"]
    assert first_result.accepted is True
    assert {first_result.replayed, second_result.replayed} == {False, True}


def test_waiter_wrong_owner_generation_or_token_never_redelivers(
    runtime_owner: OwnerProof,
) -> None:
    registry = WaiterRegistry(runtime_owner)
    calls: list[object] = []
    identity = registry.register(
        attention_id="attn-one",
        runtime_session_id="session-one",
        owner=runtime_owner,
        deliver=lambda value: calls.append(value),
        waiter_generation="wait-one",
    )

    with pytest.raises(RuntimeOwnerMismatch):
        registry.deliver_once(
            attention_id="attn-one",
            owner=replace(runtime_owner, generation="foreign"),
            waiter_generation="wait-one",
            resolution_token="token-one",
            raw_value="never",
        )
    with pytest.raises(WaiterUnavailable):
        registry.deliver_once(
            attention_id="attn-one",
            owner=runtime_owner,
            waiter_generation="wrong-generation",
            resolution_token="token-one",
            raw_value="never",
        )

    registry.deliver_once(
        attention_id="attn-one",
        owner=runtime_owner,
        waiter_generation=identity.waiter_generation,
        resolution_token="token-one",
        raw_value="first",
    )
    with pytest.raises(WaiterAlreadyConsumed):
        registry.deliver_once(
            attention_id="attn-one",
            owner=runtime_owner,
            waiter_generation=identity.waiter_generation,
            resolution_token="token-two",
            raw_value="second",
        )
    assert calls == ["first"]


def test_waiter_callback_exception_is_unknown_and_never_retried(
    runtime_owner: OwnerProof,
) -> None:
    registry = WaiterRegistry(runtime_owner)
    calls = 0

    def broken(_value: object) -> bool:
        nonlocal calls
        calls += 1
        raise RuntimeError("signalled then failed")

    identity = registry.register(
        attention_id="attn-one",
        runtime_session_id="session-one",
        owner=runtime_owner,
        deliver=broken,
        waiter_generation="wait-one",
    )
    for _ in range(2):
        with pytest.raises(DeliveryOutcomeUnknown):
            registry.deliver_once(
                attention_id=identity.attention_id,
                owner=runtime_owner,
                waiter_generation=identity.waiter_generation,
                resolution_token="same-token",
                raw_value="do not persist",
            )
    assert calls == 1


def test_waiter_session_cancel_is_isolated(runtime_owner: OwnerProof) -> None:
    registry = WaiterRegistry(runtime_owner)
    cancelled: list[str] = []
    first = registry.register(
        attention_id="attn-first",
        runtime_session_id="session-first",
        owner=runtime_owner,
        deliver=lambda _value: True,
        cancel=lambda: cancelled.append("first"),
    )
    second = registry.register(
        attention_id="attn-second",
        runtime_session_id="session-second",
        owner=runtime_owner,
        deliver=lambda _value: True,
        cancel=lambda: cancelled.append("second"),
    )

    assert registry.cancel_session("session-first") == 1
    assert cancelled == ["first"]
    with pytest.raises(WaiterUnavailable):
        registry.deliver_once(
            attention_id=first.attention_id,
            owner=runtime_owner,
            waiter_generation=first.waiter_generation,
            resolution_token="token-first",
            raw_value="answer",
        )
    result = registry.deliver_once(
        attention_id=second.attention_id,
        owner=runtime_owner,
        waiter_generation=second.waiter_generation,
        resolution_token="token-second",
        raw_value="answer",
    )
    assert result.accepted is True
    assert cancelled == ["first"]


def test_service_reconciliation_mutates_only_positive_dead_owner_classes(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    ledger = FakeLedger()
    different_boot = replace(runtime_owner, boot_token="instantiation:old", pid=10)
    dead = replace(runtime_owner, pid=11, start_token="dead-start", generation="dead")
    reused = replace(runtime_owner, pid=12, start_token="old-start", generation="reused")
    unverifiable = replace(
        runtime_owner, pid=13, start_token="hidden", generation="unverifiable"
    )
    live = replace(runtime_owner, pid=14, start_token="live-start", generation="live")
    ledger.candidates = [
        {"owner": proof, "run_count": 1, "attention_count": 0}
        for proof in (different_boot, dead, reused, unverifiable, live)
    ]
    alive = {11: False, 12: True, 13: True, 14: True}
    starts = {12: "new-start", 13: None, 14: "live-start"}
    service = WorkService(
        tmp_path,
        ledger=ledger,
        scheduler=GlobalWorkScheduler(SchedulerLimits(1, 1)),
        owner=runtime_owner,
        pid_exists=lambda pid: alive[pid],
        start_token_probe=lambda pid: starts[pid],
        auto_reconcile=False,
    )

    result = service.reconcile_startup()

    assert result[different_boot] is OwnerClassification.DIFFERENT_BOOT
    assert result[dead] is OwnerClassification.DEAD
    assert result[reused] is OwnerClassification.PID_REUSED
    assert result[unverifiable] is OwnerClassification.UNVERIFIABLE
    assert result[live] is OwnerClassification.LIVE
    assert ledger.reconciled == [
        (different_boot, "different_boot"),
        (dead, "dead"),
        (reused, "pid_reused"),
    ]
    service.shutdown()
    service.scheduler.shutdown()


def test_work_service_store_fence_detects_ledger_replacement(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    ledger = FakeLedger("ledger_before")
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 1))
    service = WorkService(
        tmp_path,
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )
    assert service.ledger_id == "ledger_before"
    assert ledger.identity_checks == 1
    ledger.ledger_id = "ledger_after_restore"
    with pytest.raises(WorkStoreRebound):
        service.reserve_background_capacity()
    service.shutdown()
    scheduler.shutdown()


def test_reserve_admission_is_serialized_with_service_shutdown(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    class BlockingReserveScheduler(GlobalWorkScheduler):
        def __init__(self) -> None:
            super().__init__(SchedulerLimits(1, 0))
            self.reserve_entered = threading.Event()
            self.allow_reserve = threading.Event()

        def reserve(self, *, owner_key: str) -> CapacityReservation:
            self.reserve_entered.set()
            assert self.allow_reserve.wait(timeout=5)
            return super().reserve(owner_key=owner_key)

    scheduler = BlockingReserveScheduler()
    service = WorkService(
        tmp_path,
        ledger=FakeLedger(),
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )
    shutdown_thread_name = "work-service-reserve-shutdown"
    lock_probe = LockContentionProbe(shutdown_thread_name)
    service._lock = lock_probe  # type: ignore[assignment]
    reservations: list[Any] = []
    errors: list[BaseException] = []

    def reserve() -> None:
        try:
            reservations.append(service.reserve_background_capacity())
        except BaseException as exc:
            errors.append(exc)

    reserve_thread = threading.Thread(target=reserve, name="work-service-reserve")
    shutdown_thread = threading.Thread(
        target=service.shutdown,
        name=shutdown_thread_name,
    )
    reserve_thread.start()
    assert scheduler.reserve_entered.wait(timeout=5)
    shutdown_thread.start()
    try:
        assert lock_probe.classified.wait(timeout=5)
        assert lock_probe.blocked.is_set()
        assert not lock_probe.acquired_without_blocking.is_set()
    finally:
        scheduler.allow_reserve.set()
        reserve_thread.join(timeout=5)
        shutdown_thread.join(timeout=5)

    try:
        assert not reserve_thread.is_alive()
        assert not shutdown_thread.is_alive()
        assert errors == []
        assert len(reservations) == 1
        assert reservations[0].active is False
        assert scheduler.owner_load(service.cache_key) == 0
    finally:
        service.shutdown()
        scheduler.shutdown()


def test_started_submission_returns_future_before_concurrent_shutdown(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    class PausingSubmitScheduler(GlobalWorkScheduler):
        def __init__(self) -> None:
            super().__init__(SchedulerLimits(1, 0))
            self.submitted_before_return = threading.Event()
            self.allow_submit_return = threading.Event()

        def submit(
            self,
            reservation: CapacityReservation,
            spec: BackgroundRunSpec,
            runner: Callable[[BackgroundRunSpec], Any],
            *,
            on_abandon: Callable[[BackgroundRunSpec, str], None] | None = None,
        ) -> Future[Any]:
            future = super().submit(
                reservation,
                spec,
                runner,
                on_abandon=on_abandon,
            )
            self.submitted_before_return.set()
            assert self.allow_submit_return.wait(timeout=5)
            return future

    scheduler = PausingSubmitScheduler()
    service = WorkService(
        tmp_path,
        ledger=FakeLedger(),
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )
    shutdown_thread_name = "work-service-submit-shutdown"
    lock_probe = LockContentionProbe(shutdown_thread_name)
    service._lock = lock_probe  # type: ignore[assignment]
    reservation = service.reserve_background_capacity()
    started = threading.Event()
    release_run = threading.Event()
    returned_futures: list[Any] = []
    errors: list[BaseException] = []

    def runner(spec: BackgroundRunSpec) -> str:
        started.set()
        assert release_run.wait(timeout=5)
        return spec.run_id

    def submit() -> None:
        try:
            returned_futures.append(
                service.submit_background(
                    reservation,
                    _spec(tmp_path, runtime_owner, 99),
                    runner,
                )
            )
        except BaseException as exc:
            errors.append(exc)

    submit_thread = threading.Thread(target=submit, name="work-service-submit")
    shutdown_thread = threading.Thread(
        target=service.shutdown,
        name=shutdown_thread_name,
    )
    submit_thread.start()
    assert scheduler.submitted_before_return.wait(timeout=5)
    assert started.wait(timeout=5)
    shutdown_thread.start()
    try:
        assert lock_probe.classified.wait(timeout=5)
        assert lock_probe.blocked.is_set()
        assert not lock_probe.acquired_without_blocking.is_set()
    finally:
        scheduler.allow_submit_return.set()
        submit_thread.join(timeout=5)
        shutdown_thread.join(timeout=5)
        release_run.set()

    try:
        assert not submit_thread.is_alive()
        assert not shutdown_thread.is_alive()
        assert errors == []
        assert len(returned_futures) == 1
        assert returned_futures[0].result(timeout=5) == f"run_{99:032x}"
        assert scheduler.owner_load(service.cache_key) == 0
    finally:
        release_run.set()
        service.shutdown()
        scheduler.shutdown(wait=True, timeout=5)


def test_service_owner_is_structurally_accepted_by_real_ledger(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    ledger = WorkLedger(tmp_path / "profile")
    service = WorkService(
        tmp_path / "profile",
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )
    reservation = service.reserve_background_capacity()
    try:
        receipt = ledger.create_job(
            kind="background_prompt",
            title="Structural owner proof",
            source="test",
            owner=service.owner,  # type: ignore[arg-type]
            idempotency_key="work-service-owner-0001",
            runtime_summary={"kind": "in_process_agent"},
            run_runtime={"kind": "in_process_agent"},
        )
    finally:
        reservation.release()

    assert receipt["job"]["status"] == "queued"
    service.shutdown()
    scheduler.shutdown()


def test_completion_first_cancel_receipt_does_not_signal_runtime(
    tmp_path: Path,
    runtime_owner: OwnerProof,
) -> None:
    profile = tmp_path / "profile"
    ledger = WorkLedger(profile)
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    service = WorkService(
        profile,
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )
    receipt = ledger.create_job(
        kind="background_prompt",
        title="Already complete",
        source="test",
        owner=service.owner,  # type: ignore[arg-type]
        idempotency_key="completion-first-create-key",
        runtime_summary={"kind": "in_process_agent"},
        run_runtime={"kind": "in_process_agent"},
    )
    job_id = receipt["job"]["job_id"]
    ledger.transition_job(
        job_id,
        expected_version=1,
        next_status="claimed",
        claim_token="completion-first-claim",
    )
    ledger.transition_job(job_id, expected_version=2, next_status="running")
    ledger.transition_job(job_id, expected_version=3, next_status="succeeded")
    changed: list[object] = []

    try:
        cancelled = service.cancel_background_job(
            job_id=job_id,
            expected_version=3,
            idempotency_key="completion-first-cancel-key",
            on_changed=lambda *_args: changed.append(True),
        )
        assert cancelled["newly_cancelled"] is False
        assert cancelled["job"]["status"] == "succeeded"
        assert changed == []
        assert service.runtimes.active_count == 0
    finally:
        service.shutdown()
        scheduler.shutdown()


def test_foreign_live_service_gets_owner_mismatch_before_waiter_lookup(
    tmp_path: Path,
    runtime_owner: OwnerProof,
) -> None:
    profile = tmp_path / "profile"
    ledger = WorkLedger(profile)
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    creator = WorkService(
        profile,
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )
    foreign = WorkService(
        profile,
        ledger=ledger,
        scheduler=scheduler,
        owner=replace(runtime_owner, generation="gen_foreign"),
        auto_reconcile=False,
    )
    delivered: list[object] = []
    attention = creator.create_attention_waiter(
        source_session_key="creator-session",
        runtime_session_id="creator-runtime",
        request_id="foreign-owner-request",
        kind="clarify",
        title="Question",
        public_payload={"question": "Continue?"},
        deliver=lambda value: delivered.append(value) or True,
    )

    try:
        with pytest.raises(LedgerRuntimeOwnerMismatch):
            foreign.respond_attention(
                attention_id=attention["attention_id"],
                expected_version=1,
                idempotency_key="foreign-owner-response-key",
                action="submit",
                raw_value="must not deliver",
            )
        with pytest.raises(LedgerRuntimeOwnerMismatch):
            foreign.cancel_attention(
                attention["attention_id"],
                terminal_reason="foreign_cancel",
            )
        assert delivered == []
        assert ledger.get_attention(attention["attention_id"])["state"] == "pending"
    finally:
        creator.shutdown()
        foreign.shutdown()
        scheduler.shutdown()


def test_shutdown_durably_closes_waiters_before_same_owner_reopen(
    tmp_path: Path,
    runtime_owner: OwnerProof,
) -> None:
    profile = tmp_path / "profile"
    ledger = WorkLedger(profile)
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    first = WorkService(
        profile,
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )
    cancelled = threading.Event()
    attention = first.create_attention_waiter(
        source_session_key="session",
        runtime_session_id="runtime",
        request_id="shutdown-reopen-request",
        kind="clarify",
        title="Question",
        public_payload={"question": "Continue?"},
        deliver=lambda _value: True,
        cancel=cancelled.set,
    )

    first.shutdown()

    assert cancelled.is_set()
    terminal = ledger.get_attention(attention["attention_id"])
    assert terminal["state"] == "cancelled"
    assert terminal["terminal_reason"] == "profile_service_shutdown"
    reopened = WorkService(
        profile,
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=True,
    )
    try:
        assert ledger.get_attention(attention["attention_id"])["state"] == "cancelled"
        assert reopened.waiters.active_count == 0
    finally:
        reopened.shutdown()
        scheduler.shutdown()


def test_real_ledger_startup_reconciliation_interrupts_only_proven_old_boot(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    ledger = WorkLedger(tmp_path / "profile")
    old_owner = replace(
        runtime_owner,
        boot_token="instantiation:previous-boot",
        generation="gen_previous",
    )
    receipt = ledger.create_job(
        kind="background_prompt",
        title="Interrupted after restart",
        source="test",
        owner=old_owner,  # type: ignore[arg-type]
        idempotency_key="work-service-reconcile-0001",
        runtime_summary={"kind": "in_process_agent"},
        run_runtime={"kind": "in_process_agent"},
    )
    attention = ledger.create_attention(
        source_session_key="session-old",
        request_id="request-old-0001",
        kind="approval",
        title="Old approval",
        public_payload={"command": "echo redacted"},
        owner=old_owner,  # type: ignore[arg-type]
        waiter_generation="wait-old",
    )
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))

    def should_not_probe(_pid: int) -> bool:
        raise AssertionError("different-boot evidence must not require a PID probe")

    service = WorkService(
        tmp_path / "profile",
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        pid_exists=should_not_probe,
        start_token_probe=lambda _pid: None,
    )

    job = ledger.get_job(receipt["job"]["job_id"])
    recovered_attention = ledger.get_attention(attention["attention_id"])
    assert job["status"] == "interrupted"
    assert job["error"]["code"] == "runner_never_started"
    assert recovered_attention["state"] == "orphaned"
    assert recovered_attention["terminal_reason"] == "waiter_lost"
    service.shutdown()
    scheduler.shutdown()


def test_profile_cache_normalizes_paths_honors_references_and_evicts_idle(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 1))
    ledgers: list[FakeLedger] = []
    clock = ManualClock()

    def make_ledger(_home: Path) -> FakeLedger:
        ledger = FakeLedger(f"ledger_{len(ledgers)}")
        ledgers.append(ledger)
        return ledger

    cache = WorkServiceCache(
        scheduler=scheduler,
        ledger_factory=make_ledger,
        owner=runtime_owner,
        idle_ttl=10,
        clock=clock,
    )
    profile = tmp_path / "profile"
    lease = cache.acquire(profile / ".." / "profile")
    assert cache.get(profile) is lease.service
    assert cache.size == 1

    clock.advance(20)
    assert cache.evict_idle() == 0
    lease.close()
    clock.advance(20)
    assert cache.evict_idle() == 1
    assert ledgers[0].closed is True
    assert cache.size == 0
    cache.shutdown_all()
    scheduler.shutdown()


def test_due_retention_is_bounded_hourly_and_keeps_redacted_counters(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    clock = ManualClock()
    ledger = FakeLedger()
    ledger.retention_result = {
        "events_deleted": 3,
        "idempotency_deleted": 2,
        "jobs_deleted": 4,
        "attention_deleted": 5,
        "event_floor": 9,
    }
    service = WorkService(
        tmp_path / "profile",
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        clock=clock,
        auto_reconcile=False,
        maintenance_interval_seconds=60 * 60,
        maintenance_event_batch_size=17,
        maintenance_idempotency_batch_size=19,
        maintenance_subject_batch_size=23,
    )
    try:
        assert service.run_due_maintenance() is True
        assert ledger.retention_calls == [
            {
                "event_batch_size": 17,
                "idempotency_batch_size": 19,
                "subject_batch_size": 23,
            }
        ]
        assert service.maintenance_counters == {
            "runs": 1,
            "failures": 0,
            "events_deleted": 3,
            "idempotency_deleted": 2,
            "jobs_deleted": 4,
            "attention_deleted": 5,
        }

        assert service.run_due_maintenance() is False
        clock.advance(60 * 60 - 1)
        assert service.run_due_maintenance() is False
        clock.advance(1)
        assert service.run_due_maintenance() is True
        assert len(ledger.retention_calls) == 2
    finally:
        service.shutdown()
        scheduler.shutdown()


def test_due_retention_retries_without_logging_exception_content(
    tmp_path: Path, runtime_owner: OwnerProof, caplog: pytest.LogCaptureFixture
) -> None:
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    clock = ManualClock()
    ledger = FakeLedger()
    ledger.retention_error = RuntimeError("never log this secret retention payload")
    service = WorkService(
        tmp_path / "profile",
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        clock=clock,
        auto_reconcile=False,
        maintenance_interval_seconds=60 * 60,
        maintenance_retry_seconds=60,
    )
    try:
        with caplog.at_level(logging.WARNING, logger="tui_gateway.work_service"):
            assert service.run_due_maintenance() is False
        assert "RuntimeError" in caplog.text
        assert "never log this secret retention payload" not in caplog.text
        assert service.maintenance_counters == {
            "runs": 0,
            "failures": 1,
            "events_deleted": 0,
            "idempotency_deleted": 0,
            "jobs_deleted": 0,
            "attention_deleted": 0,
        }

        clock.advance(59)
        assert service.run_due_maintenance() is False
        ledger.retention_error = None
        clock.advance(1)
        assert service.run_due_maintenance() is True
        assert len(ledger.retention_calls) == 2
        assert service.maintenance_counters["runs"] == 1
    finally:
        service.shutdown()
        scheduler.shutdown()


def test_due_retention_catches_up_in_bounded_short_batches(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    clock = ManualClock()
    ledger = FakeLedger()
    ledger.retention_result = {
        "events_deleted": 1,
        "idempotency_deleted": 0,
        "event_floor": 2,
    }
    service = WorkService(
        tmp_path / "profile",
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        clock=clock,
        auto_reconcile=False,
        maintenance_interval_seconds=60 * 60,
        maintenance_event_batch_size=1,
    )
    try:
        for _ in range(work_service_module.MAX_WORK_MAINTENANCE_CATCHUP_BATCHES):
            assert service.run_due_maintenance() is True
            assert service.maintenance_due_at == (
                clock.value + work_service_module.WORK_MAINTENANCE_CATCHUP_DELAY_SECONDS
            )
            clock.advance(work_service_module.WORK_MAINTENANCE_CATCHUP_DELAY_SECONDS)

        # A saturated profile gets a finite burst, then yields until its next
        # hourly maintenance cycle instead of monopolizing the sole daemon.
        assert service.run_due_maintenance() is True
        assert service.maintenance_due_at == clock.value + 60 * 60
        assert len(ledger.retention_calls) == (
            work_service_module.MAX_WORK_MAINTENANCE_CATCHUP_BATCHES + 1
        )
    finally:
        service.shutdown()
        scheduler.shutdown()


def test_profile_cache_schedules_retention_off_the_caller_path(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    class BlockingRetentionLedger(FakeLedger):
        def __init__(self) -> None:
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()

        def run_retention(
            self,
            *,
            event_batch_size: int = 1_000,
            idempotency_batch_size: int = 1_000,
            subject_batch_size: int = 100,
        ) -> dict[str, int]:
            self.entered.set()
            assert self.release.wait(timeout=5)
            return super().run_retention(
                event_batch_size=event_batch_size,
                idempotency_batch_size=idempotency_batch_size,
                subject_batch_size=subject_batch_size,
            )

    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    ledgers: list[FakeLedger] = []

    def make_ledger(_home: Path) -> FakeLedger:
        ledger = BlockingRetentionLedger() if not ledgers else FakeLedger()
        ledgers.append(ledger)
        return ledger

    cache = WorkServiceCache(
        scheduler=scheduler,
        ledger_factory=make_ledger,
        owner=runtime_owner,
        maintenance_enabled=True,
    )
    shutdown_thread: threading.Thread | None = None
    try:
        first = cache.get(tmp_path / "first")
        assert isinstance(ledgers[0], BlockingRetentionLedger)
        assert ledgers[0].entered.wait(timeout=2)
        assert cache.invalidate(tmp_path / "first") is False
        assert cache.peek(tmp_path / "first") is first

        # The cache lock is free while the background maintainer holds the
        # first ledger's SQLite work. A second caller must not wait behind it.
        with ThreadPoolExecutor(max_workers=1) as executor:
            second = executor.submit(cache.get, tmp_path / "second").result(timeout=1)
        assert second is not first

        # Closing the cache cannot leave a retained service writing after its
        # lifecycle is over. It waits for the active bounded batch and then
        # joins its daemon before returning.
        shutdown_done = threading.Event()
        shutdown_thread = threading.Thread(
            target=lambda: (cache.shutdown_all(), shutdown_done.set()),
            name="shutdown-work-cache",
        )
        shutdown_thread.start()
        assert shutdown_done.wait(timeout=0.05) is False
    finally:
        if ledgers and isinstance(ledgers[0], BlockingRetentionLedger):
            ledgers[0].release.set()
        if shutdown_thread is not None:
            shutdown_thread.join(timeout=5)
            assert not shutdown_thread.is_alive()
        else:
            cache.shutdown_all()
        scheduler.shutdown()


def test_work_service_lease_close_is_thread_safe_and_preserves_live_reference(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    clock = ManualClock()
    cache = WorkServiceCache(
        scheduler=scheduler,
        ledger_factory=lambda _home: FakeLedger(),
        owner=runtime_owner,
        idle_ttl=1,
        clock=clock,
    )
    profile = tmp_path / "profile"
    closing_lease = cache.acquire(profile)
    live_lease = cache.acquire(profile)
    worker_count = 16
    start = threading.Barrier(worker_count + 1)

    def close_concurrently() -> None:
        start.wait(timeout=5)
        closing_lease.close()

    try:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(close_concurrently) for _ in range(worker_count)]
            start.wait(timeout=5)
            for future in futures:
                future.result(timeout=5)

        clock.advance(2)
        assert cache.evict_idle() == 0
        assert live_lease.service.closed is False

        live_lease.close()
        clock.advance(2)
        assert cache.evict_idle() == 1
        assert live_lease.service.closed is True
    finally:
        closing_lease.close()
        live_lease.close()
        cache.shutdown_all()
        scheduler.shutdown()


def test_profile_cache_keeps_capacity_reservation_busy_until_release(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 0))
    clock = ManualClock()
    cache = WorkServiceCache(
        scheduler=scheduler,
        ledger_factory=lambda _home: FakeLedger(),
        owner=runtime_owner,
        idle_ttl=1,
        clock=clock,
    )
    service = cache.get(tmp_path)
    reservation = service.reserve_background_capacity()
    clock.advance(2)
    assert cache.evict_idle() == 0
    reservation.release()
    clock.advance(2)
    assert cache.evict_idle() == 1
    cache.shutdown_all()
    scheduler.shutdown()


def test_service_shutdown_cleans_only_its_profile_runtime_waiters_and_queue(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 2))
    ledger_one = FakeLedger("ledger_one")
    ledger_two = FakeLedger("ledger_two")
    service_one = WorkService(
        tmp_path / "one",
        ledger=ledger_one,
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )
    service_two = WorkService(
        tmp_path / "two",
        ledger=ledger_two,
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )
    cancelled: list[str] = []
    service_one.runtimes.register(
        run_id="run-one", owner=runtime_owner, cancel=lambda: cancelled.append("runtime-one")
    )
    service_one.waiters.register(
        attention_id="attn-one",
        runtime_session_id="session-one",
        owner=runtime_owner,
        deliver=lambda _value: True,
        cancel=lambda: cancelled.append("waiter-one"),
    )
    first_reservation = service_one.reserve_background_capacity()
    second_reservation = service_two.reserve_background_capacity()

    service_one.shutdown()

    assert first_reservation.active is False
    assert second_reservation.active is True
    assert cancelled == ["waiter-one", "runtime-one"]
    assert ledger_one.closed is True
    assert ledger_two.closed is False
    with pytest.raises(WorkServiceClosed):
        service_one.reserve_background_capacity()
    second_reservation.release()
    service_two.shutdown()
    scheduler.shutdown()


def test_startup_reconcile_propagates_unexpected_version_conflict(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    """An unexpected ledger invariant conflict must fail service construction."""
    profile = tmp_path / "profile"
    ledger = WorkLedger(profile)
    old_owner = replace(
        runtime_owner,
        boot_token="instantiation:previous-boot",
        generation="gen_previous",
    )
    created = ledger.create_job(
        kind="background_prompt",
        title="Must remain fail closed",
        source="test",
        owner=old_owner,  # type: ignore[arg-type]
        idempotency_key="unexpected-reconcile-conflict-0001",
        runtime_summary={"kind": "in_process_agent"},
        run_runtime={"kind": "in_process_agent"},
    )["job"]
    conn = sqlite3.connect(ledger.path)
    try:
        conn.execute(
            "CREATE TRIGGER force_reconcile_version_conflict "
            "BEFORE UPDATE OF status ON jobs WHEN OLD.status='queued' "
            "BEGIN SELECT RAISE(IGNORE); END"
        )
        conn.commit()
    finally:
        conn.close()

    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 1))
    try:
        with pytest.raises(VersionConflict):
            WorkService(
                profile,
                ledger=ledger,
                scheduler=scheduler,
                owner=runtime_owner,
                auto_reconcile=True,
            )
        assert ledger.get_job(created["job_id"])["status"] == "queued"
        assert ledger.list_nonterminal_owners()
    finally:
        ledger.close()
        scheduler.shutdown()


def test_ledger_race_replay_receipt_reports_no_runtime_started(
    tmp_path: Path, runtime_owner: OwnerProof
) -> None:
    """A create the ledger dedupes as a concurrent duplicate must return the
    same truthful shape as the preflight replay: ``replayed`` True and
    ``runtime_started`` False, so a client never attaches to a Run it did not
    schedule."""

    class ReplayingCreateLedger(FakeLedger):
        def get_idempotency(self, *, operation: str, idempotency_key: str):
            return None

        def create_job(self, **_kwargs):
            return {
                "replayed": True,
                "mutation_id": "mut_ledger_race",
                "job": {
                    "job_id": "job_" + "1" * 32,
                    "current_run": {"run_id": "run_" + "1" * 32},
                },
            }

    ledger = ReplayingCreateLedger()
    scheduler = GlobalWorkScheduler(SchedulerLimits(1, 1))
    service = WorkService(
        tmp_path,
        ledger=ledger,
        scheduler=scheduler,
        owner=runtime_owner,
        auto_reconcile=False,
    )
    ran: list[str] = []
    try:
        receipt = service.create_background_job(
            runtime_session_id="runtime-race",
            source_session_key="session-race",
            text="prompt race",
            title="Background race",
            idempotency_key="ledger-race-key-00000001",
            agent_inputs={"model": "test"},
            runner=lambda spec, control: ran.append(spec.run_id),
        )
    finally:
        service.shutdown()
        scheduler.shutdown()

    assert receipt["replayed"] is True
    assert receipt["runtime_started"] is False
    # The ledger already owned the durable Job, so no second runtime was started.
    assert ran == []
