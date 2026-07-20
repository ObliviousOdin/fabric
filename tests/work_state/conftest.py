from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import pytest

from fabric_cli.work_ledger import RuntimeOwner, WorkLedger


@pytest.fixture
def owner() -> RuntimeOwner:
    return RuntimeOwner(
        boot_token="test-boot-token",
        pid=max(1, os.getpid()),
        start_token="test-start-token",
        generation="test-process-generation",
    )


@pytest.fixture
def ledger(tmp_path: Path) -> WorkLedger:
    return WorkLedger(tmp_path / "profile")


@pytest.fixture
def create_job(
    ledger: WorkLedger, owner: RuntimeOwner
) -> Callable[..., dict]:
    counter = 0

    def create(**overrides):
        nonlocal counter
        counter += 1
        params = {
            "kind": "background_prompt",
            "title": f"Background job {counter}",
            "source": "mobile",
            "owner": owner,
            "idempotency_key": f"work-test-key-{counter:08d}",
            "runtime_summary": {"kind": "in_process_agent"},
            "run_runtime": {"kind": "in_process_agent"},
            "source_session_key": "session-key",
            "runtime_session_id": "runtime-session",
        }
        params.update(overrides)
        return ledger.create_job(**params)

    return create
