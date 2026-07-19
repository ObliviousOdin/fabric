"""Behavioral coverage for task-local gateway session context."""

import asyncio

import pytest

from gateway.config import Platform
from gateway.run import GatewayRunner
from gateway.session import SessionContext, SessionSource
from gateway.session_context import (
    clear_session_vars,
    get_current_session_id,
    get_session_context,
    reset_session_vars,
    set_session_vars,
)


@pytest.fixture(autouse=True)
def _reset_context():
    reset_session_vars()
    yield
    reset_session_vars()


def _telegram_context(*, optional_fields: bool = True) -> SessionContext:
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-1001",
        chat_name="Group" if optional_fields else None,
        chat_type="group",
        user_id="123456",
        user_name="alice",
        thread_id="17585" if optional_fields else None,
    )
    return SessionContext(
        source=source,
        connected_platforms=[],
        home_channels={},
        session_key="tg:-1001:17585",
    )


def test_gateway_runner_binds_typed_context():
    runner = object.__new__(GatewayRunner)
    tokens = runner._bind_session_context(_telegram_context())
    try:
        assert get_session_context() == get_session_context().__class__(
            platform="telegram",
            chat_id="-1001",
            chat_name="Group",
            thread_id="17585",
            user_id="123456",
            user_name="alice",
            session_key="tg:-1001:17585",
        )
    finally:
        runner._clear_session_context(tokens)


def test_gateway_runner_normalizes_missing_optional_fields():
    runner = object.__new__(GatewayRunner)
    tokens = runner._bind_session_context(_telegram_context(optional_fields=False))
    try:
        context = get_session_context()
        assert context.platform == "telegram"
        assert context.chat_id == "-1001"
        assert context.chat_name == ""
        assert context.thread_id == ""
    finally:
        runner._clear_session_context(tokens)


def test_clear_removes_bound_identity():
    tokens = set_session_vars(
        platform="telegram",
        source="tool",
        session_key="session-key",
        session_id="durable-id",
    )
    assert get_session_context().session_key == "session-key"
    assert get_current_session_id() == "durable-id"

    clear_session_vars(tokens)

    assert get_session_context().session_key == ""
    assert get_session_context().platform == ""
    assert get_current_session_id() == ""


def test_snapshot_is_immutable_and_stable():
    tokens = set_session_vars(platform="telegram", session_key="first")
    first = get_session_context()
    set_session_vars(platform="discord", session_key="second")

    assert first.platform == "telegram"
    assert first.session_key == "first"
    with pytest.raises(Exception):
        first.platform = "mutated"  # type: ignore[misc]
    clear_session_vars(tokens)


def test_concurrent_tasks_keep_distinct_identity():
    results = {}

    async def handler(key: str, delay: float):
        tokens = set_session_vars(session_key=key)
        try:
            await asyncio.sleep(delay)
            results[key] = get_session_context().session_key
        finally:
            clear_session_vars(tokens)

    async def run():
        task_a = asyncio.create_task(handler("session-A", 0.05))
        await asyncio.sleep(0.01)
        task_b = asyncio.create_task(handler("session-B", 0.01))
        await asyncio.gather(task_a, task_b)

    asyncio.run(run())
    assert results == {"session-A": "session-A", "session-B": "session-B"}


@pytest.mark.asyncio
async def test_gateway_executor_preserves_typed_context():
    runner = object.__new__(GatewayRunner)
    tokens = runner._bind_session_context(_telegram_context())
    try:
        result = await runner._run_in_executor_with_context(
            lambda: {
                "platform": get_session_context().platform,
                "chat_id": get_session_context().chat_id,
                "user_id": get_session_context().user_id,
                "session_key": get_session_context().session_key,
            }
        )
    finally:
        runner._clear_session_context(tokens)
        runner._shutdown_executor()

    assert result == {
        "platform": "telegram",
        "chat_id": "-1001",
        "user_id": "123456",
        "session_key": "tg:-1001:17585",
    }


@pytest.mark.asyncio
async def test_run_in_executor_with_context_forwards_args():
    runner = object.__new__(GatewayRunner)
    try:
        result = await runner._run_in_executor_with_context(lambda a, b: a + b, 3, 7)
    finally:
        runner._shutdown_executor()
    assert result == 10


@pytest.mark.asyncio
async def test_run_in_executor_with_context_propagates_exceptions():
    runner = object.__new__(GatewayRunner)

    def blow_up():
        raise ValueError("boom")

    try:
        with pytest.raises(ValueError, match="boom"):
            await runner._run_in_executor_with_context(blow_up)
    finally:
        runner._shutdown_executor()


@pytest.mark.asyncio
async def test_run_in_executor_with_context_survives_default_executor_shutdown():
    runner = object.__new__(GatewayRunner)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: None)
    await loop.shutdown_default_executor()

    try:
        result = await runner._run_in_executor_with_context(lambda: "ok")
    finally:
        runner._shutdown_executor()
    assert result == "ok"


@pytest.mark.asyncio
async def test_gateway_executor_refuses_resurrection_after_shutdown():
    runner = object.__new__(GatewayRunner)
    try:
        assert await runner._run_in_executor_with_context(lambda: "first") == "first"
        runner._shutdown_executor()
        with pytest.raises(RuntimeError, match="shutting down"):
            await runner._run_in_executor_with_context(lambda: "second")
    finally:
        runner._shutdown_executor()
