"""Session identity remains in-process when local child environments are built."""

import pytest

from gateway.session_context import reset_session_vars, set_session_vars
from tools.environments.local import (
    _make_run_env,
    _sanitize_subprocess_env,
    fabric_subprocess_env,
)


@pytest.fixture(autouse=True)
def _reset_context():
    reset_session_vars()
    yield
    reset_session_vars()


def _bind_unique_context() -> set[str]:
    values = {
        "routing-platform-sentinel",
        "routing-chat-sentinel",
        "routing-thread-sentinel",
        "routing-user-sentinel",
        "routing-key-sentinel",
        "routing-durable-sentinel",
    }
    set_session_vars(
        platform="routing-platform-sentinel",
        chat_id="routing-chat-sentinel",
        thread_id="routing-thread-sentinel",
        user_id="routing-user-sentinel",
        session_key="routing-key-sentinel",
        session_id="routing-durable-sentinel",
    )
    return values


def _assert_context_not_exported(env: dict, context_values: set[str]) -> None:
    exported_values = {str(value) for value in env.values()}
    assert context_values.isdisjoint(exported_values)


def test_foreground_environment_does_not_export_session_identity():
    values = _bind_unique_context()
    _assert_context_not_exported(_make_run_env({}), values)


def test_background_environment_does_not_export_session_identity():
    values = _bind_unique_context()
    _assert_context_not_exported(_sanitize_subprocess_env({"PATH": "/bin"}), values)


def test_general_subprocess_environment_does_not_export_session_identity():
    values = _bind_unique_context()
    _assert_context_not_exported(fabric_subprocess_env(), values)
