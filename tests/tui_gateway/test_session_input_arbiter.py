from __future__ import annotations

import threading

from tui_gateway.session_input_arbiter import SessionInputArbiter


def test_serializes_inputs_and_promotes_in_ordinal_order() -> None:
    arbiter = SessionInputArbiter()

    first = arbiter.submit(
        controller_id="local-owner",
        request_id="local-1",
        payload="first",
    )
    second = arbiter.submit(
        controller_id="phone",
        request_id="phone-1",
        payload="second",
    )
    third = arbiter.submit(
        controller_id="desktop",
        request_id="desktop-1",
        payload="third",
    )

    assert (first.state, first.ordinal) == ("accepted", 1)
    assert (second.state, second.ordinal) == ("queued", 2)
    assert (third.state, third.ordinal) == ("queued", 3)
    assert arbiter.active == first
    assert arbiter.queued == (second, third)

    promoted = arbiter.complete(
        controller_id="local-owner",
        request_id="local-1",
    )
    assert promoted is not None
    assert (promoted.state, promoted.ordinal) == ("accepted", 2)
    assert arbiter.receipt(
        controller_id="local-owner",
        request_id="local-1",
    ).state == "completed"

    promoted = arbiter.complete(controller_id="phone", request_id="phone-1")
    assert promoted is not None
    assert (promoted.state, promoted.ordinal) == ("accepted", 3)
    assert arbiter.complete(
        controller_id="desktop",
        request_id="desktop-1",
    ) is None
    assert arbiter.active is None


def test_duplicate_request_returns_original_decision_without_new_ordinal() -> None:
    arbiter = SessionInputArbiter()
    original = arbiter.submit(
        controller_id="phone",
        request_id="request-1",
        payload="hello",
    )
    duplicate = arbiter.submit(
        controller_id="phone",
        request_id="request-1",
        payload="hello",
    )
    conflict = arbiter.submit(
        controller_id="phone",
        request_id="request-1",
        payload="different",
    )

    assert original.state == "accepted"
    assert duplicate.state == "duplicate"
    assert duplicate.original_state == "accepted"
    assert duplicate.ordinal == original.ordinal
    assert conflict.state == "rejected"
    assert conflict.reason == "request_id_conflict"
    assert conflict.ordinal == original.ordinal
    assert arbiter.queued == ()


def test_request_ids_are_scoped_to_controller_identity() -> None:
    arbiter = SessionInputArbiter()

    phone = arbiter.submit(
        controller_id="phone",
        request_id="same-id",
        payload="phone text",
    )
    desktop = arbiter.submit(
        controller_id="desktop",
        request_id="same-id",
        payload="desktop text",
    )

    assert phone.state == "accepted"
    assert desktop.state == "queued"
    assert phone.ordinal != desktop.ordinal


def test_queue_full_rejection_is_idempotent() -> None:
    arbiter = SessionInputArbiter(max_queue=1)
    arbiter.submit(controller_id="local", request_id="1", payload="one")
    arbiter.submit(controller_id="phone", request_id="2", payload="two")

    rejected = arbiter.submit(
        controller_id="desktop",
        request_id="3",
        payload="three",
    )
    duplicate = arbiter.submit(
        controller_id="desktop",
        request_id="3",
        payload="three",
    )

    assert rejected.state == "rejected"
    assert rejected.reason == "queue_full"
    assert duplicate.state == "duplicate"
    assert duplicate.original_state == "rejected"
    assert duplicate.ordinal == rejected.ordinal


def test_concurrent_duplicate_submission_claims_one_mutation() -> None:
    arbiter = SessionInputArbiter()
    barrier = threading.Barrier(12)
    receipts = []
    receipt_lock = threading.Lock()

    def submit() -> None:
        barrier.wait()
        receipt = arbiter.submit(
            controller_id="phone",
            request_id="same-request",
            payload="one mutation",
        )
        with receipt_lock:
            receipts.append(receipt)

    threads = [threading.Thread(target=submit) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert [receipt.state for receipt in receipts].count("accepted") == 1
    assert [receipt.state for receipt in receipts].count("duplicate") == 11
    assert {receipt.ordinal for receipt in receipts} == {1}
    assert arbiter.queued == ()


def test_concurrent_distinct_inputs_receive_one_total_order() -> None:
    count = 20
    arbiter = SessionInputArbiter(max_queue=count - 1)
    barrier = threading.Barrier(count)
    receipts = []
    receipt_lock = threading.Lock()

    def submit(index: int) -> None:
        barrier.wait()
        receipt = arbiter.submit(
            controller_id=f"controller-{index}",
            request_id=f"request-{index}",
            payload=f"payload-{index}",
        )
        with receipt_lock:
            receipts.append(receipt)

    threads = [threading.Thread(target=submit, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    ordered = sorted(receipts, key=lambda receipt: receipt.ordinal or 0)
    assert [receipt.ordinal for receipt in ordered] == list(range(1, count + 1))
    assert ordered[0].state == "accepted"
    assert {receipt.state for receipt in ordered[1:]} == {"queued"}

    for position, receipt in enumerate(ordered):
        promoted = arbiter.complete(
            controller_id=receipt.controller_id,
            request_id=receipt.request_id,
        )
        if position + 1 < len(ordered):
            assert promoted is not None
            assert promoted.ordinal == ordered[position + 1].ordinal
        else:
            assert promoted is None

    assert arbiter.active is None
    assert arbiter.queued == ()
