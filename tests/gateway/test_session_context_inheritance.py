"""Handler-entry reset prevents inherited task-local session identity."""

import asyncio

import pytest

from gateway.session_context import (
    async_delivery_supported,
    get_session_context,
    reset_session_vars,
    set_session_vars,
)


MINE = dict(
    session_key="mine-key",
    platform="discord",
    chat_id="mine-chat",
    thread_id="mine-thread",
    user_id="mine-user",
)
FOREIGN = dict(
    session_key="foreign-key",
    platform="discord",
    chat_id="foreign-chat",
    thread_id="foreign-thread",
    user_id="foreign-user",
)


@pytest.fixture(autouse=True)
def _reset_context():
    reset_session_vars()
    yield
    reset_session_vars()


async def _child_turn(reset_first: bool):
    captured = {}

    async def body():
        if reset_first:
            reset_session_vars()
        captured["window"] = get_session_context()
        set_session_vars(**FOREIGN)
        captured["bound"] = get_session_context()

    await asyncio.create_task(body())
    return captured


def test_child_task_inherits_parent_context_without_entry_reset():
    set_session_vars(**MINE)
    captured = asyncio.run(_child_turn(reset_first=False))
    assert captured["window"].session_key == "mine-key"


def test_entry_reset_closes_inheritance_window():
    set_session_vars(**MINE)
    captured = asyncio.run(_child_turn(reset_first=True))

    assert captured["window"].session_key == ""
    assert captured["window"].chat_id == ""
    assert captured["bound"].session_key == "foreign-key"
    assert captured["bound"].chat_id == "foreign-chat"


async def _child_async_delivery(reset_first: bool) -> bool:
    async def body() -> bool:
        if reset_first:
            reset_session_vars()
        return async_delivery_supported()

    return await asyncio.create_task(body())


def test_child_task_inherits_async_delivery_capability_without_reset():
    set_session_vars(**FOREIGN, async_delivery=False)
    assert asyncio.run(_child_async_delivery(reset_first=False)) is False


def test_entry_reset_restores_default_async_delivery_capability():
    set_session_vars(**FOREIGN, async_delivery=False)
    assert asyncio.run(_child_async_delivery(reset_first=True)) is True


def test_reset_restores_empty_typed_snapshot():
    set_session_vars(**MINE)
    reset_session_vars()
    assert get_session_context().session_key == ""
    assert get_session_context().platform == ""
    assert async_delivery_supported() is True
