from __future__ import annotations

import multiprocessing
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from agent.memory_scope import (
    MAX_MEMORY_TIMESTAMP,
    MemoryIdentityAuthority,
    MemoryScopeConflict,
    MemoryScopeEffectState,
    MemoryScopeTransition,
    MemoryScopeUnavailable,
    derive_memory_scope,
    transition_operation_id,
    transition_scope,
)
from fabric_state import SessionDB


def _process_transition_worker(
    db_path: str,
    source,
    target,
    target_session: str,
    transition_id: str,
    ready,
    start,
    outcomes,
) -> None:
    database = SessionDB(Path(db_path))
    try:
        ready.put(target_session)
        if not start.wait(timeout=10):
            outcomes.put((target_session, "start_timeout"))
            return
        try:
            database.commit_memory_scope_transition(
                source_session_id="source",
                source_scope=source,
                expected_revision=1,
                target_session_id=target_session,
                target_scope=target,
                transition_id=transition_id,
                reason=MemoryScopeTransition.BRANCH,
            )
        except MemoryScopeConflict:
            outcome = "conflict"
        except BaseException as exc:
            outcome = f"unexpected:{type(exc).__name__}"
        else:
            outcome = "committed"
        outcomes.put((target_session, outcome))
    finally:
        database.close()


def _identity(marker: str = "1") -> MemoryIdentityAuthority:
    return MemoryIdentityAuthority(
        tenant_id="ten_" + (marker * 32),
        profile_id="pro_" + ("2" * 32),
        principal_id="pri_" + ("3" * 32),
        audience_id="aud_" + ("4" * 32),
        surface="cli",
    )


def _scope(session_id: str, *, marker: str = "1"):
    return derive_memory_scope(_identity(marker), session_id=session_id)


def _transition_id(
    source,
    target,
    reason: MemoryScopeTransition,
    *,
    source_session_id: str,
    target_session_id: str,
    source_revision: int,
    durable_revision: int | None = None,
) -> str:
    return transition_operation_id(
        source,
        target,
        reason,
        source_session_id=source_session_id,
        target_session_id=target_session_id,
        source_revision=source_revision,
        durable_revision=durable_revision,
    )


def _commit_branch_transition(
    database: SessionDB,
    *,
    source_session_id: str = "source",
    target_session_id: str = "target",
    marker: str = "1",
):
    for session_id in (source_session_id, target_session_id):
        database.create_session(session_id, "cli")
    source = _scope(source_session_id, marker=marker)
    target = transition_scope(
        source,
        reason=MemoryScopeTransition.BRANCH,
        new_session_id=target_session_id,
    )
    database.bind_memory_scope(source_session_id, source)
    transition_id = _transition_id(
        source,
        target,
        MemoryScopeTransition.BRANCH,
        source_session_id=source_session_id,
        target_session_id=target_session_id,
        source_revision=1,
    )
    outcome = database.commit_memory_scope_transition(
        source_session_id=source_session_id,
        source_scope=source,
        expected_revision=1,
        target_session_id=target_session_id,
        target_scope=target,
        transition_id=transition_id,
        reason=MemoryScopeTransition.BRANCH,
    )
    assert outcome.transition is not None
    return source, target, transition_id, outcome


def _replace_memory_tables_with_constraintless_copies(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        for table in ("memory_scope_transitions", "memory_scope_bindings"):
            old_table = f"old_{table}"
            connection.execute(f'ALTER TABLE "{table}" RENAME TO "{old_table}"')
            connection.execute(f'CREATE TABLE "{table}" AS SELECT * FROM "{old_table}"')
            connection.execute(f'DROP TABLE "{old_table}"')
        connection.commit()
    finally:
        connection.close()


def _replace_transition_table_ddl(
    path: Path,
    transform,
    *,
    transform_rows=None,
) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        ddl = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'memory_scope_transitions'"
        ).fetchone()[0]
        connection.execute(
            "ALTER TABLE memory_scope_transitions "
            "RENAME TO old_memory_scope_transitions"
        )
        connection.execute(transform(ddl))
        rows = connection.execute(
            "SELECT * FROM old_memory_scope_transitions"
        ).fetchall()
        for row in rows:
            values = list(row)
            if transform_rows is not None:
                values = transform_rows(values)
            connection.execute(
                "INSERT INTO memory_scope_transitions VALUES ("
                + ",".join("?" for _ in values)
                + ")",
                values,
            )
        connection.execute("DROP TABLE old_memory_scope_transitions")
        connection.commit()
    finally:
        connection.close()


@pytest.fixture
def db(tmp_path: Path):
    database = SessionDB(tmp_path / "state.db")
    try:
        yield database
    finally:
        database.close()


def test_bind_requires_real_session_and_is_exactly_idempotent(db: SessionDB):
    scope = _scope("session")

    assert db.load_memory_scope("session") is None
    with pytest.raises(MemoryScopeUnavailable) as missing:
        db.bind_memory_scope("session", scope)
    assert missing.value.code == "scope_session_missing"

    db.create_session("session", "cli")
    first = db.bind_memory_scope("session", scope)
    retry = db.bind_memory_scope("session", scope)

    assert first == retry
    assert first.session_id == "session"
    assert first.scope == scope
    assert first.revision == 1
    assert "session" not in repr(first)
    assert scope.conversation_id not in repr(first)


@pytest.mark.parametrize("invalid_session_id", [" session", "session ", "session\n"])
def test_db_memory_session_ids_are_strict_and_never_trimmed(
    db: SessionDB,
    invalid_session_id: str,
):
    db.create_session("session", "cli")
    scope = _scope("session")

    with pytest.raises(MemoryScopeUnavailable) as loaded:
        db.load_memory_scope(invalid_session_id)
    with pytest.raises(MemoryScopeUnavailable) as bound:
        db.bind_memory_scope(invalid_session_id, scope)

    assert loaded.value.code == "conversation_id_unavailable"
    assert bound.value.code == "conversation_id_unavailable"
    assert db.load_memory_scope("session") is None


def test_bind_rejects_conflicting_existing_scope(db: SessionDB):
    db.create_session("session", "cli")
    original = _scope("session")
    conflicting = replace(original, surface="tui")
    db.bind_memory_scope("session", original)

    with pytest.raises(MemoryScopeConflict) as caught:
        db.bind_memory_scope("session", conflicting)

    assert caught.value.code == "memory_scope_binding_conflict"
    assert db.load_memory_scope("session").scope == original


def test_bind_rejects_scope_derived_for_a_different_session(db: SessionDB):
    db.create_session("real-session", "cli")
    wrong = _scope("different-session")

    with pytest.raises(MemoryScopeUnavailable) as caught:
        db.bind_memory_scope("real-session", wrong)

    assert caught.value.code == "scope_session_mismatch"
    assert db.load_memory_scope("real-session") is None


def test_initial_bind_rejects_nonroot_lineage(db: SessionDB):
    db.create_session("session", "cli")
    root = _scope("session")
    rewound = transition_scope(
        root,
        reason=MemoryScopeTransition.REWIND,
        new_session_id="session",
        durable_revision=1,
    )

    with pytest.raises(MemoryScopeUnavailable) as caught:
        db.bind_memory_scope("session", rewound)

    assert caught.value.code == "scope_initial_lineage_invalid"
    assert db.load_memory_scope("session") is None


@pytest.mark.parametrize(
    ("column", "invalid_value"),
    [
        ("schema_version", 1.5),
        ("revision", 1.5),
        ("updated_at", "not-a-real"),
    ],
)
def test_binding_rows_reject_noncanonical_sqlite_scalar_types(
    db: SessionDB,
    column: str,
    invalid_value: object,
):
    db.create_session("session", "cli")
    db.bind_memory_scope("session", _scope("session"))
    with db._lock:
        db._conn.execute("PRAGMA ignore_check_constraints = ON")
        db._conn.execute(
            f'UPDATE memory_scope_bindings SET "{column}" = ? WHERE session_id = ?',
            (invalid_value, "session"),
        )
        db._conn.execute("PRAGMA ignore_check_constraints = OFF")

    with pytest.raises(MemoryScopeUnavailable) as caught:
        db.load_memory_scope("session")

    assert caught.value.code == "scope_record_invalid"


@pytest.mark.parametrize(
    ("column", "invalid_value"),
    [
        ("source_revision", 1.5),
        ("target_schema_version", 1.5),
        ("target_binding_revision", 1.5),
        ("created_at", "not-a-real"),
    ],
)
def test_transition_rows_reject_noncanonical_sqlite_scalar_types(
    db: SessionDB,
    column: str,
    invalid_value: object,
):
    _, _, transition_id, _ = _commit_branch_transition(db)
    with db._lock:
        db._conn.execute("PRAGMA ignore_check_constraints = ON")
        db._conn.execute(
            f'UPDATE memory_scope_transitions SET "{column}" = ? '
            "WHERE transition_id = ?",
            (invalid_value, transition_id),
        )
        db._conn.execute("PRAGMA ignore_check_constraints = OFF")

    with pytest.raises(MemoryScopeUnavailable) as caught:
        db.load_memory_scope_transition(transition_id)

    assert caught.value.code == "scope_record_invalid"


def test_transition_snapshot_timestamp_precedes_or_equals_ledger_creation(
    db: SessionDB,
):
    _, _, transition_id, outcome = _commit_branch_transition(db)
    created_at = outcome.transition.created_at
    older_target_timestamp = created_at - 1.0
    with db._lock:
        db._conn.execute(
            "UPDATE memory_scope_transitions SET target_binding_updated_at = ? "
            "WHERE transition_id = ?",
            (older_target_timestamp, transition_id),
        )

    loaded = db.load_memory_scope_transition(transition_id)
    assert loaded.target.updated_at == older_target_timestamp
    assert loaded.target.updated_at < loaded.created_at

    with db._lock:
        db._conn.execute(
            "UPDATE memory_scope_transitions SET target_binding_updated_at = ? "
            "WHERE transition_id = ?",
            (created_at + 1.0, transition_id),
        )
    with pytest.raises(MemoryScopeUnavailable) as caught:
        db.load_memory_scope_transition(transition_id)
    assert caught.value.code == "scope_record_invalid"


def test_transition_commits_source_target_and_ledger_atomically(db: SessionDB):
    db.create_session("source", "cli")
    db.create_session("target", "cli")
    source = _scope("source")
    target = transition_scope(
        source,
        reason=MemoryScopeTransition.BRANCH,
        new_session_id="target",
    )
    db.bind_memory_scope("source", source)
    transition_id = _transition_id(
        source,
        target,
        MemoryScopeTransition.BRANCH,
        source_session_id="source",
        target_session_id="target",
        source_revision=1,
    )

    result = db.commit_memory_scope_transition(
        source_session_id="source",
        source_scope=source,
        expected_revision=1,
        target_session_id="target",
        target_scope=target,
        transition_id=transition_id,
        reason=MemoryScopeTransition.BRANCH,
    )

    assert db.load_memory_scope("source").revision == 2
    assert db.load_memory_scope("source").scope == source
    assert db.load_memory_scope("target") == result.target
    assert result.target.scope == target
    assert result.target.revision == 1
    assert result.target.updated_at == result.transition.created_at
    assert result.changed is True
    with pytest.raises(TypeError, match=r"use \.changed"):
        bool(result)
    assert result.transition.effect_state is MemoryScopeEffectState.PREPARED
    assert db.load_memory_scope_transition(transition_id) == result.transition
    assert db.list_prepared_memory_scope_transitions() == [result.transition]


def test_exact_transition_retry_returns_original_snapshot_after_target_advances(
    db: SessionDB,
):
    for session in ("source", "target"):
        db.create_session(session, "cli")
    source = _scope("source")
    target = transition_scope(
        source,
        reason=MemoryScopeTransition.BRANCH,
        new_session_id="target",
    )
    db.bind_memory_scope("source", source)
    first_id = _transition_id(
        source,
        target,
        MemoryScopeTransition.BRANCH,
        source_session_id="source",
        target_session_id="target",
        source_revision=1,
    )
    first = db.commit_memory_scope_transition(
        source_session_id="source",
        source_scope=source,
        expected_revision=1,
        target_session_id="target",
        target_scope=target,
        transition_id=first_id,
        reason=MemoryScopeTransition.BRANCH,
    )

    rewound = transition_scope(
        target,
        reason=MemoryScopeTransition.REWIND,
        new_session_id="target",
        durable_revision=1,
    )
    rewind_id = _transition_id(
        target,
        rewound,
        MemoryScopeTransition.REWIND,
        source_session_id="target",
        target_session_id="target",
        source_revision=1,
        durable_revision=1,
    )
    db.commit_memory_scope_transition(
        source_session_id="target",
        source_scope=target,
        expected_revision=1,
        target_session_id="target",
        target_scope=rewound,
        transition_id=rewind_id,
        reason=MemoryScopeTransition.REWIND,
        durable_revision=1,
    )
    assert db.load_memory_scope("target").scope == rewound
    assert db.load_memory_scope("target").revision == 2

    retry = db.commit_memory_scope_transition(
        source_session_id="source",
        source_scope=source,
        expected_revision=1,
        target_session_id="target",
        target_scope=target,
        transition_id=first_id,
        reason=MemoryScopeTransition.BRANCH,
    )

    assert retry == first
    assert retry.target.scope == target
    assert retry.target.revision == 1


def test_transition_rejects_reason_specific_target_forgery(db: SessionDB):
    for session in ("source", "target"):
        db.create_session(session, "cli")
    source = _scope("source")
    db.bind_memory_scope("source", source)
    forged_reset = replace(
        source,
        branch_id=None,
        parent_conversation_id=None,
    )

    with pytest.raises(MemoryScopeUnavailable) as caught:
        transition_operation_id(
            source,
            forged_reset,
            MemoryScopeTransition.RESET,
            source_session_id="source",
            target_session_id="target",
            source_revision=1,
        )

    assert caught.value.code == "scope_transition_target_invalid"
    assert db.load_memory_scope("source").revision == 1
    assert db.load_memory_scope("target") is None


def test_in_place_compression_is_explicit_unchanged_noop(db: SessionDB):
    db.create_session("session", "cli")
    scope = _scope("session")
    binding = db.bind_memory_scope("session", scope)
    compressed = transition_scope(
        scope,
        reason=MemoryScopeTransition.COMPRESSION,
        new_session_id="session",
    )

    outcome = db.commit_memory_scope_transition(
        source_session_id="session",
        source_scope=scope,
        expected_revision=1,
        target_session_id="session",
        target_scope=compressed,
        transition_id=None,
        reason=MemoryScopeTransition.COMPRESSION,
    )

    assert outcome.changed is False
    with pytest.raises(TypeError, match=r"use \.changed"):
        bool(outcome)
    assert outcome.transition is None
    assert outcome.target == binding
    assert db.load_memory_scope("session") == binding
    with db._lock:
        count = db._conn.execute(
            "SELECT COUNT(*) FROM memory_scope_transitions"
        ).fetchone()[0]
    assert count == 0


def test_cross_session_transition_rejects_prebound_target(db: SessionDB):
    for session in ("source", "target"):
        db.create_session(session, "cli")
    source = _scope("source")
    target = transition_scope(
        source,
        reason=MemoryScopeTransition.RESET,
        new_session_id="target",
    )
    db.bind_memory_scope("source", source)
    db.bind_memory_scope("target", target)
    transition_id = _transition_id(
        source,
        target,
        MemoryScopeTransition.RESET,
        source_session_id="source",
        target_session_id="target",
        source_revision=1,
    )

    with pytest.raises(MemoryScopeConflict) as caught:
        db.commit_memory_scope_transition(
            source_session_id="source",
            source_scope=source,
            expected_revision=1,
            target_session_id="target",
            target_scope=target,
            transition_id=transition_id,
            reason=MemoryScopeTransition.RESET,
        )

    assert caught.value.code == "memory_scope_target_binding_conflict"
    assert db.load_memory_scope("source").revision == 1


def test_two_sources_cannot_converge_on_one_reset_target(db: SessionDB):
    for session in ("source-a", "source-b", "target"):
        db.create_session(session, "cli")
    source_a = _scope("source-a")
    source_b = _scope("source-b")
    target_a = transition_scope(
        source_a,
        reason=MemoryScopeTransition.RESET,
        new_session_id="target",
    )
    target_b = transition_scope(
        source_b,
        reason=MemoryScopeTransition.RESET,
        new_session_id="target",
    )
    assert target_a == target_b
    db.bind_memory_scope("source-a", source_a)
    db.bind_memory_scope("source-b", source_b)

    first_id = _transition_id(
        source_a,
        target_a,
        MemoryScopeTransition.RESET,
        source_session_id="source-a",
        target_session_id="target",
        source_revision=1,
    )
    second_id = _transition_id(
        source_b,
        target_b,
        MemoryScopeTransition.RESET,
        source_session_id="source-b",
        target_session_id="target",
        source_revision=1,
    )
    db.commit_memory_scope_transition(
        source_session_id="source-a",
        source_scope=source_a,
        expected_revision=1,
        target_session_id="target",
        target_scope=target_a,
        transition_id=first_id,
        reason=MemoryScopeTransition.RESET,
    )

    with pytest.raises(MemoryScopeConflict) as caught:
        db.commit_memory_scope_transition(
            source_session_id="source-b",
            source_scope=source_b,
            expected_revision=1,
            target_session_id="target",
            target_scope=target_b,
            transition_id=second_id,
            reason=MemoryScopeTransition.RESET,
        )

    assert caught.value.code == "memory_scope_target_binding_conflict"
    assert db.load_memory_scope("source-a").revision == 2
    assert db.load_memory_scope("source-b").revision == 1
    with db._lock:
        count = db._conn.execute(
            "SELECT COUNT(*) FROM memory_scope_transitions "
            "WHERE target_session_id = 'target'"
        ).fetchone()[0]
    assert count == 1


def test_competing_transitions_from_two_handles_have_one_winner(tmp_path: Path):
    path = tmp_path / "state.db"
    first_db = SessionDB(path)
    second_db = SessionDB(path)
    try:
        for session in ("source", "target-a", "target-b"):
            first_db.create_session(session, "cli")
        source = _scope("source")
        first_db.bind_memory_scope("source", source)
        targets = {
            "target-a": transition_scope(
                source,
                reason=MemoryScopeTransition.BRANCH,
                new_session_id="target-a",
            ),
            "target-b": transition_scope(
                source,
                reason=MemoryScopeTransition.BRANCH,
                new_session_id="target-b",
            ),
        }
        barrier = threading.Barrier(2)
        outcomes: list[tuple[str, str]] = []
        outcomes_lock = threading.Lock()

        def run(database: SessionDB, target_session: str) -> None:
            target = targets[target_session]
            transition_id = _transition_id(
                source,
                target,
                MemoryScopeTransition.BRANCH,
                source_session_id="source",
                target_session_id=target_session,
                source_revision=1,
            )
            barrier.wait()
            try:
                database.commit_memory_scope_transition(
                    source_session_id="source",
                    source_scope=source,
                    expected_revision=1,
                    target_session_id=target_session,
                    target_scope=target,
                    transition_id=transition_id,
                    reason=MemoryScopeTransition.BRANCH,
                )
            except MemoryScopeConflict:
                outcome = "conflict"
            else:
                outcome = "committed"
            with outcomes_lock:
                outcomes.append((target_session, outcome))

        threads = [
            threading.Thread(target=run, args=(first_db, "target-a")),
            threading.Thread(target=run, args=(second_db, "target-b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert not any(thread.is_alive() for thread in threads)
        assert sorted(outcome for _, outcome in outcomes) == [
            "committed",
            "conflict",
        ]
        winner = next(name for name, outcome in outcomes if outcome == "committed")
        loser = next(name for name, outcome in outcomes if outcome == "conflict")
        assert first_db.load_memory_scope("source").revision == 2
        assert first_db.load_memory_scope(winner) is not None
        assert first_db.load_memory_scope(loser) is None
    finally:
        second_db.close()
        first_db.close()


def test_competing_transitions_from_two_processes_have_one_winner(tmp_path: Path):
    path = tmp_path / "state.db"
    database = SessionDB(path)
    try:
        for session in ("source", "target-a", "target-b"):
            database.create_session(session, "cli")
        source = _scope("source")
        database.bind_memory_scope("source", source)
        targets = {
            name: transition_scope(
                source,
                reason=MemoryScopeTransition.BRANCH,
                new_session_id=name,
            )
            for name in ("target-a", "target-b")
        }
        transition_ids = {
            name: _transition_id(
                source,
                target,
                MemoryScopeTransition.BRANCH,
                source_session_id="source",
                target_session_id=name,
                source_revision=1,
            )
            for name, target in targets.items()
        }
        context = multiprocessing.get_context("spawn")
        ready = context.Queue()
        start = context.Event()
        outcomes = context.Queue()
        processes = [
            context.Process(
                target=_process_transition_worker,
                args=(
                    str(path),
                    source,
                    targets[name],
                    name,
                    transition_ids[name],
                    ready,
                    start,
                    outcomes,
                ),
            )
            for name in ("target-a", "target-b")
        ]
        for process in processes:
            process.start()
        assert {ready.get(timeout=15), ready.get(timeout=15)} == {
            "target-a",
            "target-b",
        }
        start.set()
        results = [outcomes.get(timeout=15), outcomes.get(timeout=15)]
        for process in processes:
            process.join(timeout=15)

        assert all(process.exitcode == 0 for process in processes)
        assert sorted(outcome for _, outcome in results) == [
            "committed",
            "conflict",
        ]
        winner = next(name for name, outcome in results if outcome == "committed")
        loser = next(name for name, outcome in results if outcome == "conflict")
        assert database.load_memory_scope("source").revision == 2
        assert database.load_memory_scope(winner) is not None
        assert database.load_memory_scope(loser) is None
    finally:
        database.close()


def test_failed_ledger_insert_rolls_back_source_and_target(db: SessionDB):
    for session in ("source", "target"):
        db.create_session(session, "cli")
    source = _scope("source")
    target = transition_scope(
        source,
        reason=MemoryScopeTransition.BRANCH,
        new_session_id="target",
    )
    db.bind_memory_scope("source", source)
    transition_id = _transition_id(
        source,
        target,
        MemoryScopeTransition.BRANCH,
        source_session_id="source",
        target_session_id="target",
        source_revision=1,
    )
    with db._lock:
        db._conn.execute(
            """CREATE TRIGGER reject_memory_transition
               BEFORE INSERT ON memory_scope_transitions
               BEGIN
                   SELECT RAISE(ABORT, 'injected transition failure');
               END"""
        )

    with pytest.raises(MemoryScopeConflict):
        db.commit_memory_scope_transition(
            source_session_id="source",
            source_scope=source,
            expected_revision=1,
            target_session_id="target",
            target_scope=target,
            transition_id=transition_id,
            reason=MemoryScopeTransition.BRANCH,
        )

    assert db.load_memory_scope("source").revision == 1
    assert db.load_memory_scope("target") is None
    assert db.load_memory_scope_transition(transition_id) is None


def test_base_exception_before_commit_rolls_back_every_transition_write(
    db: SessionDB, monkeypatch
):
    for session in ("source", "target"):
        db.create_session(session, "cli")
    source = _scope("source")
    target = transition_scope(
        source,
        reason=MemoryScopeTransition.BRANCH,
        new_session_id="target",
    )
    db.bind_memory_scope("source", source)
    transition_id = _transition_id(
        source,
        target,
        MemoryScopeTransition.BRANCH,
        source_session_id="source",
        target_session_id="target",
        source_revision=1,
    )
    original = db._memory_transition_from_row

    def interrupt_after_ledger_insert(row):
        if "transition_id" in row.keys():
            raise KeyboardInterrupt
        return original(row)

    with monkeypatch.context() as patcher:
        patcher.setattr(
            db,
            "_memory_transition_from_row",
            interrupt_after_ledger_insert,
        )
        with pytest.raises(KeyboardInterrupt):
            db.commit_memory_scope_transition(
                source_session_id="source",
                source_scope=source,
                expected_revision=1,
                target_session_id="target",
                target_scope=target,
                transition_id=transition_id,
                reason=MemoryScopeTransition.BRANCH,
            )

    assert db.load_memory_scope("source").revision == 1
    assert db.load_memory_scope("target") is None
    assert db.load_memory_scope_transition(transition_id) is None


def test_transition_rejects_authority_mismatch_without_mutation(db: SessionDB):
    for session in ("source", "target"):
        db.create_session(session, "cli")
    source = _scope("source", marker="1")
    target = _scope("target", marker="a")
    db.bind_memory_scope("source", source)

    with pytest.raises(MemoryScopeUnavailable) as invalid_id:
        transition_id = _transition_id(
            source,
            target,
            MemoryScopeTransition.BRANCH,
            source_session_id="source",
            target_session_id="target",
            source_revision=1,
        )
        db.commit_memory_scope_transition(
            source_session_id="source",
            source_scope=source,
            expected_revision=1,
            target_session_id="target",
            target_scope=target,
            transition_id=transition_id,
            reason=MemoryScopeTransition.BRANCH,
        )

    assert invalid_id.value.code == "scope_authority_mismatch"
    assert db.load_memory_scope("source").revision == 1
    assert db.load_memory_scope("target") is None


def test_effect_claim_completion_and_idempotent_final_record(db: SessionDB):
    for session in ("source", "target"):
        db.create_session(session, "cli")
    source = _scope("source")
    target = transition_scope(
        source,
        reason=MemoryScopeTransition.BRANCH,
        new_session_id="target",
    )
    db.bind_memory_scope("source", source)
    transition_id = _transition_id(
        source,
        target,
        MemoryScopeTransition.BRANCH,
        source_session_id="source",
        target_session_id="target",
        source_revision=1,
    )
    db.commit_memory_scope_transition(
        source_session_id="source",
        source_scope=source,
        expected_revision=1,
        target_session_id="target",
        target_scope=target,
        transition_id=transition_id,
        reason=MemoryScopeTransition.BRANCH,
    )

    claimed = db.claim_memory_scope_transition_effect(transition_id, "manager-a")
    assert claimed.effect_state is MemoryScopeEffectState.RUNNING
    assert db.claim_memory_scope_transition_effect(transition_id, "manager-b") is None
    with pytest.raises(MemoryScopeConflict):
        db.record_memory_scope_transition_effect(
            transition_id,
            "manager-b",
            MemoryScopeEffectState.APPLIED,
        )

    applied = db.record_memory_scope_transition_effect(
        transition_id,
        "manager-a",
        MemoryScopeEffectState.APPLIED,
    )
    retry = db.record_memory_scope_transition_effect(
        transition_id,
        "manager-a",
        MemoryScopeEffectState.APPLIED,
    )
    with pytest.raises(MemoryScopeConflict) as wrong_owner_retry:
        db.record_memory_scope_transition_effect(
            transition_id,
            "manager-b",
            MemoryScopeEffectState.APPLIED,
        )
    assert applied == retry
    assert applied.effect_state is MemoryScopeEffectState.APPLIED
    assert wrong_owner_retry.value.code == "memory_scope_effect_claim_conflict"
    assert db.list_prepared_memory_scope_transitions() == []


def test_failed_and_uncertain_effects_require_stable_error_codes(db: SessionDB):
    for state in (MemoryScopeEffectState.FAILED, MemoryScopeEffectState.UNCERTAIN):
        with pytest.raises(MemoryScopeUnavailable) as caught:
            db.record_memory_scope_transition_effect(
                "mtr_" + ("a" * 32),
                "manager-a",
                state,
            )
        assert caught.value.code == "scope_effect_error_invalid"


def test_stale_running_effect_becomes_uncertain_and_cannot_be_reclaimed(db: SessionDB):
    for session in ("source", "target"):
        db.create_session(session, "cli")
    source = _scope("source")
    target = transition_scope(
        source,
        reason=MemoryScopeTransition.BRANCH,
        new_session_id="target",
    )
    db.bind_memory_scope("source", source)
    transition_id = _transition_id(
        source,
        target,
        MemoryScopeTransition.BRANCH,
        source_session_id="source",
        target_session_id="target",
        source_revision=1,
    )
    db.commit_memory_scope_transition(
        source_session_id="source",
        source_scope=source,
        expected_revision=1,
        target_session_id="target",
        target_scope=target,
        transition_id=transition_id,
        reason=MemoryScopeTransition.BRANCH,
    )
    db.claim_memory_scope_transition_effect(transition_id, "manager-a")

    assert (
        db.mark_stale_memory_scope_effects_uncertain(
            started_before=time.time() + 1,
        )
        == 1
    )
    result = db.load_memory_scope_transition(transition_id)
    assert result.effect_state is MemoryScopeEffectState.UNCERTAIN
    assert result.effect_error_code == "stale_running"
    assert db.claim_memory_scope_transition_effect(transition_id, "manager-b") is None


@pytest.mark.parametrize(
    "corruption",
    [
        "owner_null",
        "owner_empty",
        "owner_whitespace",
        "owner_control",
        "owner_oversize",
        "owner_type",
        "error_present",
        "start_null",
        "start_text",
        "start_nan",
        "start_infinite",
        "start_negative",
        "start_out_of_range",
        "start_before_created",
        "start_after_updated",
        "updated_text",
        "updated_infinite",
        "updated_out_of_range",
        "updated_before_created",
    ],
)
def test_every_malformed_running_effect_repairs_to_nonreplayable_uncertainty(
    db: SessionDB,
    corruption: str,
):
    _, _, transition_id, _ = _commit_branch_transition(db)
    claimed = db.claim_memory_scope_transition_effect(transition_id, "manager-a")
    assert claimed is not None
    with db._lock:
        original = db._conn.execute(
            "SELECT created_at, updated_at FROM memory_scope_transitions "
            "WHERE transition_id = ?",
            (transition_id,),
        ).fetchone()
        created_at = original["created_at"]
        original_updated_at = original["updated_at"]
        corruptions = {
            "owner_null": ("effect_owner_id", None),
            "owner_empty": ("effect_owner_id", ""),
            "owner_whitespace": ("effect_owner_id", " manager-a"),
            "owner_control": ("effect_owner_id", "manager\na"),
            "owner_oversize": ("effect_owner_id", "x" * 257),
            "owner_type": ("effect_owner_id", sqlite3.Binary(b"manager-a")),
            "error_present": ("effect_error_code", "unexpected_error"),
            "start_null": ("effect_started_at", None),
            "start_text": ("effect_started_at", "not-a-real"),
            "start_nan": ("effect_started_at", float("nan")),
            "start_infinite": ("effect_started_at", float("inf")),
            "start_negative": ("effect_started_at", -1.0),
            "start_out_of_range": (
                "effect_started_at",
                MAX_MEMORY_TIMESTAMP + 1.0,
            ),
            "start_before_created": ("effect_started_at", created_at - 1.0),
            "start_after_updated": (
                "effect_started_at",
                original_updated_at + 1.0,
            ),
            "updated_text": ("updated_at", "not-a-real"),
            "updated_infinite": ("updated_at", float("inf")),
            "updated_out_of_range": ("updated_at", MAX_MEMORY_TIMESTAMP + 1.0),
            "updated_before_created": ("updated_at", created_at - 1.0),
        }
        column, invalid_value = corruptions[corruption]
        db._conn.execute("PRAGMA ignore_check_constraints = ON")
        db._conn.execute(
            f'UPDATE memory_scope_transitions SET "{column}" = ? '
            "WHERE transition_id = ?",
            (invalid_value, transition_id),
        )
        db._conn.execute("PRAGMA ignore_check_constraints = OFF")

    with pytest.raises(MemoryScopeUnavailable) as invalid:
        db.load_memory_scope_transition(transition_id)
    assert invalid.value.code == "scope_record_invalid"
    assert (
        db.mark_stale_memory_scope_effects_uncertain(
            started_before=0.0,
        )
        == 1
    )
    repaired = db.load_memory_scope_transition(transition_id)
    assert repaired.effect_state is MemoryScopeEffectState.UNCERTAIN
    assert repaired.effect_error_code == "invalid_running_metadata"
    with db._lock:
        raw = db._conn.execute(
            "SELECT effect_owner_id, effect_started_at, created_at, updated_at "
            "FROM memory_scope_transitions WHERE transition_id = ?",
            (transition_id,),
        ).fetchone()
    assert raw["effect_owner_id"] == "scope_recovery"
    assert raw["effect_started_at"] == raw["created_at"]
    assert raw["updated_at"] >= original_updated_at
    assert db.claim_memory_scope_transition_effect(transition_id, "manager-b") is None
    assert db.mark_stale_memory_scope_effects_uncertain(started_before=0.0) == 0


def test_malformed_running_repair_count_excludes_valid_fresh_rows(db: SessionDB):
    transition_ids = []
    for index, marker in enumerate(("5", "6", "7")):
        _, _, transition_id, _ = _commit_branch_transition(
            db,
            source_session_id=f"source-{index}",
            target_session_id=f"target-{index}",
            marker=marker,
        )
        db.claim_memory_scope_transition_effect(transition_id, f"manager-{index}")
        transition_ids.append(transition_id)

    with db._lock:
        db._conn.execute("PRAGMA ignore_check_constraints = ON")
        db._conn.execute(
            "UPDATE memory_scope_transitions SET effect_owner_id = '' "
            "WHERE transition_id = ?",
            (transition_ids[0],),
        )
        db._conn.execute(
            "UPDATE memory_scope_transitions SET effect_started_at = 'not-a-real' "
            "WHERE transition_id = ?",
            (transition_ids[1],),
        )
        db._conn.execute("PRAGMA ignore_check_constraints = OFF")

    assert db.mark_stale_memory_scope_effects_uncertain(started_before=0.0) == 2
    assert {
        db.load_memory_scope_transition(transition_id).effect_state
        for transition_id in transition_ids[:2]
    } == {MemoryScopeEffectState.UNCERTAIN}
    assert (
        db.load_memory_scope_transition(transition_ids[2]).effect_state
        is MemoryScopeEffectState.RUNNING
    )


def test_malformed_running_repairs_roll_back_as_one_transaction(db: SessionDB):
    transition_ids = []
    for index, marker in enumerate(("8", "9")):
        _, _, transition_id, _ = _commit_branch_transition(
            db,
            source_session_id=f"source-{index}",
            target_session_id=f"target-{index}",
            marker=marker,
        )
        db.claim_memory_scope_transition_effect(transition_id, f"manager-{index}")
        transition_ids.append(transition_id)

    with db._lock:
        db._conn.execute("PRAGMA ignore_check_constraints = ON")
        db._conn.execute(
            "UPDATE memory_scope_transitions SET effect_owner_id = '' "
            "WHERE transition_id IN (?, ?)",
            tuple(transition_ids),
        )
        db._conn.execute("PRAGMA ignore_check_constraints = OFF")
        db._conn.execute(
            f"""CREATE TRIGGER fail_second_memory_repair
                BEFORE UPDATE OF effect_state ON memory_scope_transitions
                WHEN OLD.transition_id = '{transition_ids[1]}'
                  AND NEW.effect_state = 'uncertain'
                BEGIN SELECT RAISE(ABORT, 'forced repair failure'); END"""
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced repair failure"):
        db.mark_stale_memory_scope_effects_uncertain(started_before=0.0)
    with db._lock:
        states = db._conn.execute(
            "SELECT effect_state FROM memory_scope_transitions "
            "WHERE transition_id IN (?, ?) ORDER BY transition_id",
            tuple(transition_ids),
        ).fetchall()
        db._conn.execute("DROP TRIGGER fail_second_memory_repair")
    assert [row["effect_state"] for row in states] == ["running", "running"]
    assert db.mark_stale_memory_scope_effects_uncertain(started_before=0.0) == 2


def test_transition_queries_and_stale_cutoffs_validate_strictly(db: SessionDB):
    with pytest.raises(MemoryScopeUnavailable) as invalid_id:
        db.load_memory_scope_transition("mtr_not-hex")
    with pytest.raises(MemoryScopeUnavailable) as invalid_time:
        db.mark_stale_memory_scope_effects_uncertain(started_before=float("nan"))

    assert invalid_id.value.code == "scope_transition_id_invalid"
    assert invalid_time.value.code == "scope_timestamp_invalid"


def test_read_only_legacy_db_without_memory_tables_degrades_to_unbound(
    tmp_path: Path,
):
    path = tmp_path / "legacy.db"
    database = SessionDB(path)
    database.close()
    connection = sqlite3.connect(path)
    connection.execute("DROP TABLE memory_scope_transitions")
    connection.execute("DROP TABLE memory_scope_bindings")
    connection.commit()
    connection.close()

    read_only = SessionDB(path, read_only=True)
    try:
        assert read_only.load_memory_scope("legacy") is None
        assert read_only.load_memory_scope_transition("mtr_" + ("a" * 32)) is None
        assert read_only.list_prepared_memory_scope_transitions() == []
    finally:
        read_only.close()


def test_empty_partial_memory_schema_is_recreated_before_indexes(tmp_path: Path):
    path = tmp_path / "partial.db"
    database = SessionDB(path)
    database.close()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("DROP TABLE memory_scope_transitions")
    connection.execute("DROP TABLE memory_scope_bindings")
    connection.execute(
        "CREATE TABLE memory_scope_bindings (session_id TEXT PRIMARY KEY)"
    )
    connection.commit()
    connection.close()

    recovered = SessionDB(path)
    try:
        with recovered._lock:
            columns = {
                row[1]
                for row in recovered._conn.execute(
                    "PRAGMA table_info(memory_scope_bindings)"
                ).fetchall()
            }
            indexes = {
                row[0]
                for row in recovered._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                ).fetchall()
            }
        assert {"conversation_id", "branch_id", "revision"} <= columns
        assert "idx_memory_scope_conversation" in indexes
        assert "idx_memory_scope_effect_state" in indexes
    finally:
        recovered.close()


def test_populated_unknown_partial_memory_schema_fails_closed(tmp_path: Path):
    path = tmp_path / "partial-populated.db"
    database = SessionDB(path)
    database.close()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("DROP TABLE memory_scope_transitions")
    connection.execute("DROP TABLE memory_scope_bindings")
    connection.execute(
        "CREATE TABLE memory_scope_bindings (session_id TEXT PRIMARY KEY)"
    )
    connection.execute("INSERT INTO memory_scope_bindings VALUES ('sentinel')")
    connection.commit()
    connection.close()

    with pytest.raises(sqlite3.DatabaseError, match="memory_scope_schema_incompatible"):
        SessionDB(path)


def test_memory_schema_ddl_normalization_preserves_quoted_literals_and_escaping():
    canonical = (
        "CREATE TABLE IF NOT EXISTS sample (state TEXT CHECK "
        "(state = 'prepared' OR state = 'it''s PREPARED'))"
    )
    uppercase_literal = canonical.replace("'prepared'", "'PREPARED'")

    normalized = SessionDB._normalized_memory_schema_ddl(canonical)

    assert normalized.startswith("create table sample")
    assert "'prepared'" in normalized
    assert "'it''s PREPARED'" in normalized
    assert normalized != SessionDB._normalized_memory_schema_ddl(uppercase_literal)


def test_empty_schema_with_uppercase_prepared_check_literal_is_rebuilt(
    tmp_path: Path,
):
    path = tmp_path / "uppercase-check-empty.db"
    database = SessionDB(path)
    database.close()
    _replace_transition_table_ddl(
        path,
        lambda ddl: ddl.replace("'prepared'", "'PREPARED'"),
    )

    recovered = SessionDB(path)
    try:
        with recovered._lock:
            ddl = recovered._conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' "
                "AND name = 'memory_scope_transitions'"
            ).fetchone()[0]
        assert "'prepared'" in ddl
        assert "'PREPARED'" not in ddl
    finally:
        recovered.close()


def test_populated_schema_with_uppercase_prepared_literal_fails_without_loss(
    tmp_path: Path,
):
    path = tmp_path / "uppercase-check-populated.db"
    database = SessionDB(path)
    _, _, transition_id, _ = _commit_branch_transition(database)
    database.close()

    def _uppercase_prepared_row(values):
        values[16] = "PREPARED"
        return values

    _replace_transition_table_ddl(
        path,
        lambda ddl: ddl.replace("'prepared'", "'PREPARED'"),
        transform_rows=_uppercase_prepared_row,
    )

    with pytest.raises(sqlite3.DatabaseError, match="memory_scope_schema_incompatible"):
        SessionDB(path)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT transition_id, effect_state FROM memory_scope_transitions"
        ).fetchall() == [(transition_id, "PREPARED")]
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("name", "ddl"),
    [
        (
            "extra_memory_plain",
            "CREATE INDEX extra_memory_plain ON memory_scope_bindings(surface)",
        ),
        (
            "extra_memory_unique",
            "CREATE UNIQUE INDEX extra_memory_unique ON memory_scope_bindings(surface)",
        ),
        (
            "extra_memory_expression",
            "CREATE INDEX extra_memory_expression "
            "ON memory_scope_bindings(lower(surface))",
        ),
        (
            "extra_memory_partial",
            "CREATE INDEX extra_memory_partial ON memory_scope_bindings(surface) "
            "WHERE branch_id IS NOT NULL",
        ),
    ],
)
def test_empty_extra_memory_indexes_are_removed_transactionally(
    tmp_path: Path,
    name: str,
    ddl: str,
):
    path = tmp_path / f"empty-{name}.db"
    database = SessionDB(path)
    database.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute(ddl)
        connection.commit()
    finally:
        connection.close()

    recovered = SessionDB(path)
    try:
        with recovered._lock:
            assert (
                recovered._conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?",
                    (name,),
                ).fetchone()
                is None
            )
            _, expected_indexes = recovered._expected_memory_scope_schema()
            assert recovered._memory_index_signatures(recovered._conn) == (
                expected_indexes
            )
    finally:
        recovered.close()


@pytest.mark.parametrize(
    ("name", "ddl"),
    [
        (
            "extra_memory_plain",
            "CREATE INDEX extra_memory_plain ON memory_scope_bindings(surface)",
        ),
        (
            "extra_memory_unique",
            "CREATE UNIQUE INDEX extra_memory_unique ON memory_scope_bindings(surface)",
        ),
        (
            "extra_memory_expression",
            "CREATE INDEX extra_memory_expression "
            "ON memory_scope_bindings(lower(surface))",
        ),
        (
            "extra_memory_partial",
            "CREATE INDEX extra_memory_partial ON memory_scope_bindings(surface) "
            "WHERE branch_id IS NOT NULL",
        ),
    ],
)
def test_populated_extra_memory_indexes_fail_without_data_or_index_loss(
    tmp_path: Path,
    name: str,
    ddl: str,
):
    path = tmp_path / f"populated-{name}.db"
    database = SessionDB(path)
    database.create_session("sentinel-session", "cli")
    database.bind_memory_scope("sentinel-session", _scope("sentinel-session"))
    database.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute(ddl)
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(sqlite3.DatabaseError, match="memory_scope_schema_incompatible"):
        SessionDB(path)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT session_id FROM memory_scope_bindings"
        ).fetchall() == [("sentinel-session",)]
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?",
            (name,),
        ).fetchone() == (1,)
    finally:
        connection.close()


def test_empty_missing_required_memory_index_is_recreated(tmp_path: Path):
    path = tmp_path / "missing-required-empty.db"
    database = SessionDB(path)
    database.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP INDEX idx_memory_scope_conversation")
        connection.commit()
    finally:
        connection.close()

    recovered = SessionDB(path)
    try:
        with recovered._lock:
            columns = tuple(
                row["name"]
                for row in recovered._conn.execute(
                    'PRAGMA index_info("idx_memory_scope_conversation")'
                )
            )
        assert columns == ("conversation_id", "branch_id")
    finally:
        recovered.close()


def test_populated_missing_required_memory_index_fails_without_loss(
    tmp_path: Path,
):
    path = tmp_path / "missing-required-populated.db"
    database = SessionDB(path)
    database.create_session("sentinel-session", "cli")
    database.bind_memory_scope("sentinel-session", _scope("sentinel-session"))
    database.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP INDEX idx_memory_scope_conversation")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(sqlite3.DatabaseError, match="memory_scope_schema_incompatible"):
        SessionDB(path)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT session_id FROM memory_scope_bindings"
        ).fetchall() == [("sentinel-session",)]
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'index' "
                "AND name = 'idx_memory_scope_conversation'"
            ).fetchone()
            is None
        )
    finally:
        connection.close()


@pytest.mark.parametrize(
    "wrong_index_ddl",
    [
        "CREATE INDEX idx_memory_scope_conversation "
        "ON memory_scope_bindings(conversation_id COLLATE NOCASE DESC, "
        "branch_id DESC)",
        "CREATE INDEX idx_memory_scope_conversation "
        "ON memory_scope_bindings(lower(conversation_id), branch_id)",
        "CREATE INDEX idx_memory_scope_conversation "
        "ON memory_scope_bindings(conversation_id, branch_id) "
        "WHERE branch_id IS NOT NULL",
    ],
    ids=("desc-nocase", "expression", "partial"),
)
def test_empty_wrong_required_index_semantics_are_repaired(
    tmp_path: Path,
    wrong_index_ddl: str,
):
    path = tmp_path / "wrong-required-empty.db"
    database = SessionDB(path)
    database.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP INDEX idx_memory_scope_conversation")
        connection.execute(wrong_index_ddl)
        connection.commit()
    finally:
        connection.close()

    recovered = SessionDB(path)
    try:
        with recovered._lock:
            xinfo = [
                (row["name"], row["desc"], row["coll"], row["key"])
                for row in recovered._conn.execute(
                    'PRAGMA index_xinfo("idx_memory_scope_conversation")'
                )
            ]
            partial = next(
                row["partial"]
                for row in recovered._conn.execute(
                    "PRAGMA index_list(memory_scope_bindings)"
                )
                if row["name"] == "idx_memory_scope_conversation"
            )
        assert xinfo[:2] == [
            ("conversation_id", 0, "BINARY", 1),
            ("branch_id", 0, "BINARY", 1),
        ]
        assert partial == 0
    finally:
        recovered.close()


def test_memory_schema_attests_columns_constraints_foreign_keys_and_indexes(
    db: SessionDB,
):
    with db._lock:
        binding_columns = {
            row["name"]: (
                row["type"],
                row["notnull"],
                row["dflt_value"],
                row["pk"],
                row["hidden"],
            )
            for row in db._conn.execute("PRAGMA table_xinfo(memory_scope_bindings)")
        }
        transition_columns = {
            row["name"]: (
                row["type"],
                row["notnull"],
                row["dflt_value"],
                row["pk"],
                row["hidden"],
            )
            for row in db._conn.execute("PRAGMA table_xinfo(memory_scope_transitions)")
        }
        binding_foreign_keys = {
            (row["from"], row["table"], row["to"], row["on_delete"])
            for row in db._conn.execute(
                "PRAGMA foreign_key_list(memory_scope_bindings)"
            )
        }
        transition_foreign_keys = {
            (row["from"], row["table"], row["to"], row["on_delete"])
            for row in db._conn.execute(
                "PRAGMA foreign_key_list(memory_scope_transitions)"
            )
        }
        unique_indexes = []
        for row in db._conn.execute("PRAGMA index_list(memory_scope_transitions)"):
            if row["unique"] and row["origin"] == "u":
                unique_indexes.append(
                    tuple(
                        column["name"]
                        for column in db._conn.execute(
                            f'PRAGMA index_info("{row["name"]}")'
                        )
                    )
                )
        named_indexes = {
            name: tuple(
                row["name"] for row in db._conn.execute(f'PRAGMA index_info("{name}")')
            )
            for name in (
                "idx_memory_scope_conversation",
                "idx_memory_scope_effect_state",
            )
        }
        table_ddl = {
            row["name"]: row["sql"].lower()
            for row in db._conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'table' "
                "AND name IN ('memory_scope_bindings', 'memory_scope_transitions')"
            )
        }

    assert binding_columns["session_id"] == ("TEXT", 0, None, 1, 0)
    assert binding_columns["schema_version"] == ("INTEGER", 1, None, 0, 0)
    assert binding_columns["revision"] == ("INTEGER", 1, "1", 0, 0)
    assert transition_columns["source_revision"] == (
        "INTEGER",
        1,
        None,
        0,
        0,
    )
    assert binding_foreign_keys == {("session_id", "sessions", "id", "CASCADE")}
    assert transition_foreign_keys == {
        ("source_session_id", "sessions", "id", "CASCADE"),
        ("target_session_id", "sessions", "id", "CASCADE"),
    }
    assert unique_indexes == [("source_session_id", "source_revision")]
    assert named_indexes == {
        "idx_memory_scope_conversation": ("conversation_id", "branch_id"),
        "idx_memory_scope_effect_state": ("effect_state", "effect_started_at"),
    }
    assert "check (schema_version = 1)" in table_ddl["memory_scope_bindings"]
    assert "check (source_revision > 0)" in table_ddl["memory_scope_transitions"]
    assert (
        "effect_state in ('prepared', 'running', 'applied'"
        in table_ddl["memory_scope_transitions"]
    )


def test_empty_constraintless_full_column_schema_is_rebuilt(tmp_path: Path):
    path = tmp_path / "constraintless-empty.db"
    database = SessionDB(path)
    database.close()
    _replace_memory_tables_with_constraintless_copies(path)

    recovered = SessionDB(path)
    try:
        expected_tables, expected_indexes = recovered._expected_memory_scope_schema()
        with recovered._lock:
            assert {
                table: recovered._memory_table_signature(recovered._conn, table)
                for table in (
                    "memory_scope_bindings",
                    "memory_scope_transitions",
                )
            } == expected_tables
            assert {
                name: recovered._memory_named_index_signature(recovered._conn, name)
                for name in expected_indexes
            } == expected_indexes
        _, _, transition_id, _ = _commit_branch_transition(recovered)
        assert recovered.delete_session("source") is True
        assert recovered.load_memory_scope_transition(transition_id) is None
    finally:
        recovered.close()


def test_stale_empty_observation_cannot_drop_a_later_insert(tmp_path: Path):
    path = tmp_path / "stale-empty-observation.db"
    database = SessionDB(path)
    database.create_session("sentinel-session", "cli")
    database.close()
    _replace_memory_tables_with_constraintless_copies(path)
    scope = _scope("sentinel-session")
    observed_empty = threading.Event()
    inserted = threading.Event()
    outcomes: list[str] = []

    def _stale_initializer() -> None:
        observer = sqlite3.connect(path)
        try:
            assert (
                observer.execute(
                    "SELECT COUNT(*) FROM memory_scope_bindings"
                ).fetchone()[0]
                == 0
            )
            observed_empty.set()
            assert inserted.wait(timeout=10)
        finally:
            observer.close()
        try:
            SessionDB(path)
        except sqlite3.DatabaseError as exc:
            outcomes.append(str(exc))
        else:
            outcomes.append("unexpected_success")

    def _writer() -> None:
        assert observed_empty.wait(timeout=10)
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "INSERT INTO memory_scope_bindings VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "sentinel-session",
                    scope.schema_version,
                    scope.tenant_id,
                    scope.profile_id,
                    scope.principal_id,
                    scope.audience_id,
                    scope.conversation_id,
                    scope.branch_id,
                    scope.parent_conversation_id,
                    scope.surface,
                    1,
                    time.time(),
                ),
            )
            connection.commit()
        finally:
            connection.close()
            inserted.set()

    initializer = threading.Thread(target=_stale_initializer)
    writer = threading.Thread(target=_writer)
    initializer.start()
    writer.start()
    initializer.join(timeout=15)
    writer.join(timeout=15)

    assert not initializer.is_alive()
    assert not writer.is_alive()
    assert outcomes == ["memory_scope_schema_incompatible"]
    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT session_id FROM memory_scope_bindings"
        ).fetchall() == [("sentinel-session",)]
    finally:
        connection.close()


def test_concurrent_empty_schema_initializers_serialize(tmp_path: Path):
    path = tmp_path / "concurrent-empty-initializers.db"
    database = SessionDB(path)
    database.close()
    _replace_memory_tables_with_constraintless_copies(path)
    barrier = threading.Barrier(3)
    outcomes: list[str] = []

    def _initialize() -> None:
        barrier.wait(timeout=10)
        try:
            opened = SessionDB(path)
        except BaseException as exc:
            outcomes.append(type(exc).__name__ + ":" + str(exc))
        else:
            opened.close()
            outcomes.append("ok")

    workers = [threading.Thread(target=_initialize) for _ in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait(timeout=10)
    for worker in workers:
        worker.join(timeout=15)

    assert all(not worker.is_alive() for worker in workers)
    assert sorted(outcomes) == ["ok", "ok"]
    recovered = SessionDB(path)
    try:
        expected_tables, expected_indexes = recovered._expected_memory_scope_schema()
        with recovered._lock:
            assert {
                table: recovered._memory_table_signature(recovered._conn, table)
                for table in expected_tables
            } == expected_tables
            assert (
                recovered._memory_index_signatures(recovered._conn) == expected_indexes
            )
    finally:
        recovered.close()


def test_empty_schema_recovery_rolls_back_on_base_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    path = tmp_path / "schema-recovery-rollback.db"
    database = SessionDB(path)
    with database._lock:
        database._conn.execute("DROP TABLE memory_scope_transitions")
        database._conn.execute("DROP TABLE memory_scope_bindings")
        database._conn.execute(
            "CREATE TABLE memory_scope_bindings (session_id TEXT PRIMARY KEY)"
        )

    class InjectedSchemaFailure(BaseException):
        pass

    def _fail_after_first_ddl(cursor, script: str) -> None:
        first_statement = database._memory_ddl_statements(script)[0]
        cursor.execute(first_statement)
        raise InjectedSchemaFailure

    monkeypatch.setattr(database, "_execute_memory_ddl", _fail_after_first_ddl)
    try:
        with pytest.raises(InjectedSchemaFailure):
            database._ensure_memory_scope_schema(database._conn.cursor())
        with database._lock:
            binding_columns = [
                row["name"]
                for row in database._conn.execute(
                    "PRAGMA table_info(memory_scope_bindings)"
                )
            ]
            transition_exists = database._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'memory_scope_transitions'"
            ).fetchone()
        assert binding_columns == ["session_id"]
        assert transition_exists is None
    finally:
        database.close()


def test_populated_constraintless_full_column_schema_fails_without_data_loss(
    tmp_path: Path,
):
    path = tmp_path / "constraintless-populated.db"
    database = SessionDB(path)
    database.create_session("sentinel-session", "cli")
    database.bind_memory_scope("sentinel-session", _scope("sentinel-session"))
    database.close()
    _replace_memory_tables_with_constraintless_copies(path)

    with pytest.raises(sqlite3.DatabaseError, match="memory_scope_schema_incompatible"):
        SessionDB(path)

    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT session_id FROM memory_scope_bindings"
        ).fetchall() == [("sentinel-session",)]
    finally:
        connection.close()


def test_constraintless_duplicate_source_revisions_fail_stable(tmp_path: Path):
    path = tmp_path / "constraintless-duplicates.db"
    database = SessionDB(path)
    _, _, transition_id, _ = _commit_branch_transition(database)
    database.close()
    _replace_memory_tables_with_constraintless_copies(path)

    connection = sqlite3.connect(path)
    try:
        row = list(
            connection.execute(
                "SELECT * FROM memory_scope_transitions WHERE transition_id = ?",
                (transition_id,),
            ).fetchone()
        )
        row[0] = "mtr_" + ("f" * 32)
        connection.execute(
            "INSERT INTO memory_scope_transitions VALUES ("
            + ",".join("?" for _ in row)
            + ")",
            row,
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(sqlite3.DatabaseError, match="memory_scope_schema_incompatible"):
        SessionDB(path)
    connection = sqlite3.connect(path)
    try:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM memory_scope_transitions"
            ).fetchone()[0]
            == 2
        )
    finally:
        connection.close()


def test_valid_schema_enforces_source_revision_uniqueness(db: SessionDB):
    _, _, transition_id, _ = _commit_branch_transition(db)
    with db._lock:
        row = list(
            db._conn.execute(
                "SELECT * FROM memory_scope_transitions WHERE transition_id = ?",
                (transition_id,),
            ).fetchone()
        )
        row[0] = "mtr_" + ("f" * 32)
        with pytest.raises(sqlite3.IntegrityError):
            db._conn.execute(
                "INSERT INTO memory_scope_transitions VALUES ("
                + ",".join("?" for _ in row)
                + ")",
                row,
            )


def test_populated_wrong_secondary_memory_index_fails_without_touching_rows(
    tmp_path: Path,
):
    path = tmp_path / "wrong-secondary-index.db"
    database = SessionDB(path)
    database.create_session("sentinel-session", "cli")
    database.bind_memory_scope("sentinel-session", _scope("sentinel-session"))
    database.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP INDEX idx_memory_scope_conversation")
        connection.execute(
            "CREATE INDEX idx_memory_scope_conversation "
            "ON memory_scope_bindings(surface)"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(sqlite3.DatabaseError, match="memory_scope_schema_incompatible"):
        SessionDB(path)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT session_id FROM memory_scope_bindings"
        ).fetchall() == [("sentinel-session",)]
        columns = tuple(
            row[2]
            for row in connection.execute(
                'PRAGMA index_info("idx_memory_scope_conversation")'
            )
        )
        assert columns == ("surface",)
    finally:
        connection.close()


def test_session_delete_cascades_binding_and_transition_ledger(db: SessionDB):
    for session in ("source", "target"):
        db.create_session(session, "cli")
    source = _scope("source")
    target = transition_scope(
        source,
        reason=MemoryScopeTransition.BRANCH,
        new_session_id="target",
    )
    db.bind_memory_scope("source", source)
    transition_id = _transition_id(
        source,
        target,
        MemoryScopeTransition.BRANCH,
        source_session_id="source",
        target_session_id="target",
        source_revision=1,
    )
    db.commit_memory_scope_transition(
        source_session_id="source",
        source_scope=source,
        expected_revision=1,
        target_session_id="target",
        target_scope=target,
        transition_id=transition_id,
        reason=MemoryScopeTransition.BRANCH,
    )

    assert db.delete_session("source") is True
    assert db.load_memory_scope("source") is None
    assert db.load_memory_scope("target") is not None
    assert db.load_memory_scope_transition(transition_id) is None


def test_target_delete_cascades_ledger_but_preserves_source_binding(db: SessionDB):
    for session in ("source", "target"):
        db.create_session(session, "cli")
    source = _scope("source")
    target = transition_scope(
        source,
        reason=MemoryScopeTransition.BRANCH,
        new_session_id="target",
    )
    db.bind_memory_scope("source", source)
    transition_id = _transition_id(
        source,
        target,
        MemoryScopeTransition.BRANCH,
        source_session_id="source",
        target_session_id="target",
        source_revision=1,
    )
    db.commit_memory_scope_transition(
        source_session_id="source",
        source_scope=source,
        expected_revision=1,
        target_session_id="target",
        target_scope=target,
        transition_id=transition_id,
        reason=MemoryScopeTransition.BRANCH,
    )

    assert db.delete_session("target") is True
    assert db.load_memory_scope("target") is None
    assert db.load_memory_scope_transition(transition_id) is None
    assert db.load_memory_scope("source").revision == 2


def test_empty_session_pruning_cascades_binding(db: SessionDB):
    db.create_session("empty", "cli")
    db.bind_memory_scope("empty", _scope("empty"))

    assert db.delete_session_if_empty("empty") is True
    assert db.load_memory_scope("empty") is None


def test_rewind_returns_atomic_monotonic_revision(db: SessionDB):
    db.create_session("session", "cli")
    first = db.append_message("session", "user", "first")
    db.append_message("session", "assistant", "reply")

    one = db.rewind_to_message("session", first)
    two = db.rewind_to_message("session", first)

    assert one["rewind_revision"] == 1
    assert two["rewind_revision"] == 2
    assert db.get_session("session")["rewind_count"] == 2
