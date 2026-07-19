"""Tests for task-local AIAgent session identity."""

import sys

import pytest

from run_agent import AIAgent


@pytest.fixture(autouse=True)
def _cleanup_session_context():
    from gateway.session_context import _SESSION_ID, _UNSET

    token = _SESSION_ID.set(_UNSET)
    yield
    _SESSION_ID.reset(token)


def test_generated_session_id_is_bound_task_locally():
    agent = AIAgent(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    from gateway.session_context import get_current_session_id

    assert get_current_session_id() == agent.session_id
    assert len(agent.session_id) > 0


def test_explicit_session_id_is_bound_task_locally():
    custom_id = "20260511_120000_abc12345"
    agent = AIAgent(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        session_id=custom_id,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    from gateway.session_context import get_current_session_id

    assert get_current_session_id() == custom_id
    assert agent.session_id == custom_id


def test_session_id_is_not_exported_in_process_environment():
    """Concurrent agents must not publish their identity process-wide."""
    custom_id = "20260511_130000_def67890"
    AIAgent(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        session_id=custom_id,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    import os

    assert custom_id not in os.environ.values()
