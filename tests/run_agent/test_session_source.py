import pytest

from gateway.session_context import clear_session_vars, reset_session_vars, set_session_vars
from run_agent import _session_source_for_agent


@pytest.fixture(autouse=True)
def _reset_contextvars():
    reset_session_vars()
    yield
    reset_session_vars()


def test_session_source_context_overrides_platform():
    tokens = set_session_vars(source="tool")
    try:
        assert _session_source_for_agent("tui") == "tool"
    finally:
        clear_session_vars(tokens)


def test_session_source_falls_back_to_platform():
    assert _session_source_for_agent("tui") == "tui"


def test_session_source_defaults_to_cli_without_context_or_platform():
    assert _session_source_for_agent(None) == "cli"
