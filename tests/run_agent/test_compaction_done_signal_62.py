"""#62: the _compress_context wrapper must always pair the compaction start
status with a completion signal.

The desktop shows "Summarizing thread" while a status.update kind="compacting"
is active and cleared it only on the broad message.complete cleanup, so a long
turn that kept running model/tool work AFTER compaction finished still showed
the indicator for minutes. compress_context() emits the start; the wrapper now
emits the paired completion in a finally so it fires on success, no-op, AND
failure — never leaving the indicator stranded.
"""

import types

import pytest

from run_agent import AIAgent
import agent.conversation_compression as cc


def _fake_agent():
    # A minimal stand-in; _compress_context only touches `self` by handing it to
    # the (patched) module functions, so a bare namespace is enough.
    return types.SimpleNamespace()


def test_wrapper_emits_done_on_success(monkeypatch):
    done_calls: list[object] = []
    monkeypatch.setattr(cc, "compress_context", lambda *a, **k: (["compacted"], "sys"))
    monkeypatch.setattr(cc, "emit_compaction_done", lambda agent: done_calls.append(agent))

    agent = _fake_agent()
    result = AIAgent._compress_context(agent, ["m"], "sys")

    assert result == (["compacted"], "sys")
    assert done_calls == [agent]  # completion fired exactly once


def test_wrapper_emits_done_on_failure(monkeypatch):
    done_calls: list[object] = []

    def _boom(*a, **k):
        raise RuntimeError("summary model exploded")

    monkeypatch.setattr(cc, "compress_context", _boom)
    monkeypatch.setattr(cc, "emit_compaction_done", lambda agent: done_calls.append(agent))

    agent = _fake_agent()
    with pytest.raises(RuntimeError, match="summary model exploded"):
        AIAgent._compress_context(agent, ["m"], "sys")

    # Even when compaction raises, the indicator is cleared — criterion:
    # "Failure and cancellation clear the indicator."
    assert done_calls == [agent]
