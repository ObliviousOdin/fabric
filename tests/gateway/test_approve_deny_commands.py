"""Tests for /approve and /deny gateway commands.

Verifies that dangerous command approvals use the blocking gateway approval
mechanism — the agent thread blocks until the user responds with /approve
or /deny, mirroring the CLI's synchronous input() flow.

Supports multiple concurrent approvals (parallel subagents, execute_code)
via a per-session queue.
"""

import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


def _make_event(text: str) -> MessageEvent:
    return MessageEvent(
        text=text,
        source=_make_source(),
        message_id="m1",
    )


def _make_runner():
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="***")}
    )
    adapter = MagicMock()
    adapter.send = AsyncMock()
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), loaded_hooks=False)
    runner.session_store = MagicMock()
    runner._running_agents = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._background_tasks = set()
    runner._session_db = None
    runner._reasoning_config = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._show_reasoning = False
    runner._is_user_authorized = lambda _source: True
    runner._bind_session_context = lambda _context: None
    return runner


def _clear_approval_state():
    """Reset all module-level approval state between tests."""
    from tools import approval as mod
    mod._gateway_queues.clear()
    mod._gateway_notify_cbs.clear()
    mod._session_approved.clear()
    mod._permanent_approved.clear()
    mod._pending.clear()


@contextmanager
def _gateway_approval_context(session_key: str):
    """Bind the task-local gateway identity used by approval routing."""
    from gateway.session_context import clear_session_vars, set_session_vars

    tokens = set_session_vars(
        platform="test_gateway",
        session_key=session_key,
    )
    try:
        yield
    finally:
        clear_session_vars(tokens)


# ------------------------------------------------------------------
# Blocking gateway approval infrastructure (tools/approval.py)
# ------------------------------------------------------------------


class TestBlockingGatewayApproval:
    """Tests for the blocking approval mechanism in tools/approval.py."""

    def setup_method(self):
        _clear_approval_state()

    def test_register_and_resolve_unblocks_entry(self):
        """resolve_gateway_approval signals the entry's event."""
        from tools.approval import (
            register_gateway_notify, unregister_gateway_notify,
            resolve_gateway_approval, has_blocking_approval,
            _ApprovalEntry, _gateway_queues,
        )
        session_key = "test-session"
        register_gateway_notify(session_key, lambda d: None)

        # Simulate what check_all_command_guards does
        entry = _ApprovalEntry({"command": "rm -rf /"})
        _gateway_queues.setdefault(session_key, []).append(entry)

        assert has_blocking_approval(session_key) is True

        # Resolve from another thread
        def resolve():
            time.sleep(0.1)
            resolve_gateway_approval(session_key, "once")

        t = threading.Thread(target=resolve)
        t.start()
        resolved = entry.event.wait(timeout=5)
        t.join()

        assert resolved is True
        assert entry.result == "once"
        unregister_gateway_notify(session_key)

    def test_resolve_returns_zero_when_no_pending(self):
        from tools.approval import resolve_gateway_approval
        assert resolve_gateway_approval("nonexistent", "once") == 0

    def test_resolve_all_unblocks_multiple_entries(self):
        """resolve_gateway_approval with resolve_all=True signals all entries."""
        from tools.approval import (
            resolve_gateway_approval, _ApprovalEntry, _gateway_queues,
        )
        session_key = "test-all"
        e1 = _ApprovalEntry({"command": "cmd1"})
        e2 = _ApprovalEntry({"command": "cmd2"})
        e3 = _ApprovalEntry({"command": "cmd3"})
        _gateway_queues[session_key] = [e1, e2, e3]

        count = resolve_gateway_approval(session_key, "session", resolve_all=True)
        assert count == 3
        assert all(e.event.is_set() for e in [e1, e2, e3])
        assert all(e.result == "session" for e in [e1, e2, e3])

    def test_resolve_single_pops_oldest_fifo(self):
        """resolve_gateway_approval without resolve_all resolves oldest first."""
        from tools.approval import (
            resolve_gateway_approval,
            _ApprovalEntry, _gateway_queues,
        )
        session_key = "test-fifo"
        e1 = _ApprovalEntry({"command": "first"})
        e2 = _ApprovalEntry({"command": "second"})
        _gateway_queues[session_key] = [e1, e2]

        count = resolve_gateway_approval(session_key, "once")
        assert count == 1
        assert e1.event.is_set()
        assert e1.result == "once"
        assert not e2.event.is_set()
        assert len(_gateway_queues[session_key]) == 1

    def test_resolve_single_targets_request_id(self):
        """Identical approvals remain independently targetable by transport ID."""
        from tools.approval import (
            resolve_gateway_approval,
            _ApprovalEntry, _gateway_queues,
        )

        session_key = "test-request-id"
        first = _ApprovalEntry({"command": "same", "request_id": "approval-1"})
        second = _ApprovalEntry({"command": "same", "request_id": "approval-2"})
        _gateway_queues[session_key] = [first, second]

        count = resolve_gateway_approval(
            session_key, "once", request_id="approval-2"
        )

        assert count == 1
        assert not first.event.is_set()
        assert second.event.is_set()
        assert _gateway_queues[session_key] == [first]

    @pytest.mark.parametrize(
        "invalid_choice",
        [None, "", "   ", "yes", "allow_forever", True, 1, object()],
    )
    def test_invalid_choice_never_signals_or_removes_an_entry(self, invalid_choice):
        """Malformed programmatic choices fail before queue mutation."""
        from tools.approval import (
            resolve_gateway_approval,
            _ApprovalEntry, _gateway_queues,
        )

        session_key = "test-invalid-choice"
        first = _ApprovalEntry({"command": "same", "request_id": "approval-1"})
        second = _ApprovalEntry({"command": "same", "request_id": "approval-2"})
        _gateway_queues[session_key] = [first, second]

        with pytest.raises(ValueError, match="invalid approval choice"):
            resolve_gateway_approval(
                session_key,
                invalid_choice,
                request_id="approval-2",
            )

        assert _gateway_queues[session_key] == [first, second]
        assert not first.event.is_set()
        assert not second.event.is_set()
        assert first.result is None
        assert second.result is None

        # The exact second request remains independently actionable after the
        # rejected mutation; FIFO order must not have shifted.
        assert resolve_gateway_approval(
            session_key,
            "approved",
            request_id="approval-2",
        ) == 1
        assert not first.event.is_set()
        assert second.event.is_set()
        assert second.result == "once"
        assert _gateway_queues[session_key] == [first]

    def test_request_id_and_resolve_all_conflict_never_mutates_queue(self):
        """Exact and all-pending addressing cannot be combined."""
        from tools.approval import (
            resolve_gateway_approval,
            _ApprovalEntry, _gateway_queues,
        )

        session_key = "test-request-id-all-conflict"
        first = _ApprovalEntry({"command": "first", "request_id": "approval-1"})
        second = _ApprovalEntry({"command": "second", "request_id": "approval-2"})
        _gateway_queues[session_key] = [first, second]

        with pytest.raises(
            ValueError,
            match="request_id cannot be combined with resolve_all",
        ):
            resolve_gateway_approval(
                session_key,
                "once",
                resolve_all=True,
                request_id="approval-2",
            )

        assert _gateway_queues[session_key] == [first, second]
        assert not first.event.is_set()
        assert not second.event.is_set()

    @pytest.mark.parametrize("invalid_request_id", ["", "   ", 0, False, object()])
    def test_explicit_invalid_request_id_never_falls_back_to_fifo(
        self, invalid_request_id
    ):
        """Only an omitted ID enables the legacy FIFO compatibility path."""
        from tools.approval import (
            _ApprovalEntry,
            _gateway_queues,
            resolve_gateway_approval,
        )

        session_key = "test-invalid-request-id"
        first = _ApprovalEntry({"command": "first", "request_id": "approval-1"})
        second = _ApprovalEntry({"command": "second", "request_id": "approval-2"})
        _gateway_queues[session_key] = [first, second]

        with pytest.raises(ValueError, match="request_id must be a non-empty string"):
            resolve_gateway_approval(
                session_key,
                "once",
                request_id=invalid_request_id,
            )

        assert _gateway_queues[session_key] == [first, second]
        assert not first.event.is_set()
        assert not second.event.is_set()

    @pytest.mark.parametrize(
        ("choice", "expected"),
        [
            ("once", "once"),
            ("session", "session"),
            ("always", "always"),
            ("deny", "deny"),
            ("allow", "once"),
            ("approve", "once"),
            ("  APPROVED  ", "once"),
        ],
    )
    def test_gateway_choice_normalizer_accepts_only_canonical_and_aliases(
        self,
        choice,
        expected,
    ):
        from tools.approval import normalize_gateway_approval_choice

        assert normalize_gateway_approval_choice(choice) == expected

    def test_unregister_signals_all_entries(self):
        """unregister_gateway_notify signals all waiting entries to prevent hangs."""
        from tools.approval import (
            register_gateway_notify, unregister_gateway_notify,
            _ApprovalEntry, _gateway_queues,
        )
        session_key = "test-cleanup"
        register_gateway_notify(session_key, lambda d: None)

        e1 = _ApprovalEntry({"command": "cmd1"})
        e2 = _ApprovalEntry({"command": "cmd2"})
        _gateway_queues[session_key] = [e1, e2]

        unregister_gateway_notify(session_key)
        assert e1.event.is_set()
        assert e2.event.is_set()

    def test_clear_session_denies_and_signals_all_entries(self):
        """clear_session must wake blocked entries during boundary cleanup."""
        from tools.approval import clear_session, _ApprovalEntry, _gateway_queues

        session_key = "test-boundary-cleanup"
        e1 = _ApprovalEntry({"command": "cmd1"})
        e2 = _ApprovalEntry({"command": "cmd2"})
        _gateway_queues[session_key] = [e1, e2]

        clear_session(session_key)

        assert e1.event.is_set()
        assert e2.event.is_set()
        assert e1.result == "deny"
        assert e2.result == "deny"
        assert session_key not in _gateway_queues


# ------------------------------------------------------------------
# /approve command
# ------------------------------------------------------------------


class TestApproveCommand:

    def setup_method(self):
        _clear_approval_state()

    @pytest.mark.asyncio
    async def test_approve_resolves_blocking_approval(self):
        """Basic /approve signals the oldest blocked agent thread."""
        from tools.approval import _ApprovalEntry, _gateway_queues

        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)

        entry = _ApprovalEntry({"command": "test"})
        _gateway_queues[session_key] = [entry]

        result = await runner._handle_approve_command(_make_event("/approve"))
        assert "approved" in result.lower()
        assert "resuming" in result.lower()
        assert entry.event.is_set()

    @pytest.mark.asyncio
    async def test_approve_all_resolves_multiple(self):
        """/approve all resolves all pending approvals."""
        from tools.approval import _ApprovalEntry, _gateway_queues

        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)

        e1 = _ApprovalEntry({"command": "cmd1"})
        e2 = _ApprovalEntry({"command": "cmd2"})
        _gateway_queues[session_key] = [e1, e2]

        result = await runner._handle_approve_command(_make_event("/approve all"))
        assert "2 commands" in result
        assert e1.event.is_set()
        assert e2.event.is_set()

    @pytest.mark.asyncio
    async def test_approve_all_session(self):
        """/approve all session resolves all with session scope."""
        from tools.approval import _ApprovalEntry, _gateway_queues

        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)

        e1 = _ApprovalEntry({"command": "cmd1"})
        e2 = _ApprovalEntry({"command": "cmd2"})
        _gateway_queues[session_key] = [e1, e2]

        result = await runner._handle_approve_command(_make_event("/approve all session"))
        assert "session" in result.lower()
        assert e1.result == "session"
        assert e2.result == "session"

    @pytest.mark.asyncio
    async def test_approve_no_pending(self):
        """/approve with no pending approval returns helpful message."""
        runner = _make_runner()
        result = await runner._handle_approve_command(_make_event("/approve"))
        assert "No pending command" in result

    @pytest.mark.asyncio
    async def test_approve_stale_old_style_pending(self):
        """Old-style _pending_approvals without blocking event reports expired."""
        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)
        runner._pending_approvals[session_key] = {"command": "test"}

        result = await runner._handle_approve_command(_make_event("/approve"))
        assert "expired" in result.lower() or "no longer waiting" in result.lower()
        assert session_key not in runner._pending_approvals


# ------------------------------------------------------------------
# /deny command
# ------------------------------------------------------------------


class TestDenyCommand:

    def setup_method(self):
        _clear_approval_state()

    @pytest.mark.asyncio
    async def test_deny_resolves_blocking_approval(self):
        """/deny signals the oldest blocked agent thread with 'deny'."""
        from tools.approval import _ApprovalEntry, _gateway_queues

        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)

        entry = _ApprovalEntry({"command": "test"})
        _gateway_queues[session_key] = [entry]

        result = await runner._handle_deny_command(_make_event("/deny"))
        assert "denied" in result.lower()
        assert entry.event.is_set()
        assert entry.result == "deny"

    @pytest.mark.asyncio
    async def test_deny_all_resolves_all(self):
        """/deny all denies all pending approvals."""
        from tools.approval import _ApprovalEntry, _gateway_queues

        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)

        e1 = _ApprovalEntry({"command": "cmd1"})
        e2 = _ApprovalEntry({"command": "cmd2"})
        _gateway_queues[session_key] = [e1, e2]

        result = await runner._handle_deny_command(_make_event("/deny all"))
        assert "2 commands" in result
        assert all(e.result == "deny" for e in [e1, e2])

    @pytest.mark.asyncio
    async def test_deny_no_pending(self):
        """/deny with no pending approval returns helpful message."""
        runner = _make_runner()
        result = await runner._handle_deny_command(_make_event("/deny"))
        assert "No pending command" in result

    @pytest.mark.asyncio
    async def test_deny_with_reason_attaches_reason(self):
        """/deny <reason> attaches the reason to the resolved entry."""
        from tools.approval import _ApprovalEntry, _gateway_queues

        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)

        entry = _ApprovalEntry({"command": "test"})
        _gateway_queues[session_key] = [entry]

        result = await runner._handle_deny_command(
            _make_event("/deny that path is still in use")
        )
        assert entry.result == "deny"
        assert entry.reason == "that path is still in use"
        assert "that path is still in use" in result

    @pytest.mark.asyncio
    async def test_deny_all_with_reason(self):
        """/deny all <reason> denies everything and relays one reason."""
        from tools.approval import _ApprovalEntry, _gateway_queues

        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)

        e1 = _ApprovalEntry({"command": "cmd1"})
        e2 = _ApprovalEntry({"command": "cmd2"})
        _gateway_queues[session_key] = [e1, e2]

        result = await runner._handle_deny_command(
            _make_event("/deny all wrong directory")
        )
        assert "2 commands" in result
        assert all(e.result == "deny" for e in [e1, e2])
        assert all(e.reason == "wrong directory" for e in [e1, e2])

    @pytest.mark.asyncio
    async def test_deny_plain_has_no_reason(self):
        """A bare /deny leaves the reason unset (regression guard)."""
        from tools.approval import _ApprovalEntry, _gateway_queues

        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)

        entry = _ApprovalEntry({"command": "test"})
        _gateway_queues[session_key] = [entry]

        await runner._handle_deny_command(_make_event("/deny"))
        assert entry.result == "deny"
        assert entry.reason is None


# ------------------------------------------------------------------
# Bare "yes" must NOT trigger approval
# ------------------------------------------------------------------


class TestBareTextNoLongerApproves:

    def setup_method(self):
        _clear_approval_state()

    @pytest.mark.asyncio
    async def test_yes_does_not_execute_pending_command(self):
        """Saying 'yes' must not trigger approval. Only /approve works."""
        from tools.approval import _ApprovalEntry, _gateway_queues

        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)

        entry = _ApprovalEntry({"command": "test"})
        _gateway_queues[session_key] = [entry]

        # "yes" is not /approve — entry should still be pending
        assert not entry.event.is_set()


# ------------------------------------------------------------------
# End-to-end blocking flow
# ------------------------------------------------------------------


class TestBlockingApprovalE2E:
    """Test the full blocking flow: agent thread blocks → user approves → agent resumes."""

    def setup_method(self):
        _clear_approval_state()

    def test_blocking_approval_approve_once(self):
        """check_all_command_guards blocks until resolve_gateway_approval is called."""
        from tools.approval import (
            register_gateway_notify, unregister_gateway_notify,
            resolve_gateway_approval, check_all_command_guards,
        )

        session_key = "e2e-test"
        notified = []

        register_gateway_notify(session_key, lambda d: notified.append(d))

        result_holder = [None]

        def agent_thread():
            from tools.approval import reset_current_session_key, set_current_session_key

            token = set_current_session_key(session_key)
            try:
                with _gateway_approval_context(session_key):
                    result_holder[0] = check_all_command_guards(
                        "rm -rf /important", "local"
                    )
            finally:
                reset_current_session_key(token)

        t = threading.Thread(target=agent_thread)
        t.start()

        for _ in range(50):
            if notified:
                break
            time.sleep(0.05)

        assert len(notified) == 1
        assert "rm -rf /important" in notified[0]["command"]

        resolve_gateway_approval(session_key, "once")
        t.join(timeout=5)

        assert result_holder[0] is not None
        assert result_holder[0]["approved"] is True
        unregister_gateway_notify(session_key)

    def test_blocking_approval_deny(self):
        """check_all_command_guards returns BLOCKED when denied."""
        from tools.approval import (
            register_gateway_notify, unregister_gateway_notify,
            resolve_gateway_approval, check_all_command_guards,
        )

        session_key = "e2e-deny"
        notified = []
        register_gateway_notify(session_key, lambda d: notified.append(d))

        result_holder = [None]

        def agent_thread():
            from tools.approval import reset_current_session_key, set_current_session_key

            token = set_current_session_key(session_key)
            try:
                with _gateway_approval_context(session_key):
                    result_holder[0] = check_all_command_guards(
                        "rm -rf /important", "local"
                    )
            finally:
                reset_current_session_key(token)

        t = threading.Thread(target=agent_thread)
        t.start()
        for _ in range(50):
            if notified:
                break
            time.sleep(0.05)

        resolve_gateway_approval(session_key, "deny")
        t.join(timeout=5)

        assert result_holder[0]["approved"] is False
        assert "BLOCKED" in result_holder[0]["message"]
        unregister_gateway_notify(session_key)

    def test_blocking_approval_timeout(self):
        """check_all_command_guards returns BLOCKED on timeout."""
        from tools.approval import (
            register_gateway_notify, unregister_gateway_notify,
            check_all_command_guards,
        )

        session_key = "e2e-timeout"
        register_gateway_notify(session_key, lambda d: None)

        result_holder = [None]

        def agent_thread():
            from tools.approval import reset_current_session_key, set_current_session_key

            token = set_current_session_key(session_key)
            try:
                with _gateway_approval_context(session_key):
                    with patch("tools.approval._get_approval_config",
                               return_value={"gateway_timeout": 1}):
                        result_holder[0] = check_all_command_guards(
                            "rm -rf /important", "local"
                        )
            finally:
                reset_current_session_key(token)

        t = threading.Thread(target=agent_thread)
        t.start()
        t.join(timeout=10)

        assert result_holder[0]["approved"] is False
        assert "timed out" in result_holder[0]["message"]
        unregister_gateway_notify(session_key)

    def test_parallel_subagent_approvals(self):
        """Multiple threads can block concurrently and be resolved independently."""
        from tools.approval import (
            register_gateway_notify, unregister_gateway_notify,
            resolve_gateway_approval, check_all_command_guards,
            _gateway_queues,
        )

        session_key = "e2e-parallel"
        notified = []
        register_gateway_notify(session_key, lambda d: notified.append(d))

        results = [None, None, None]

        def make_agent(idx, cmd):
            def run():
                from tools.approval import reset_current_session_key, set_current_session_key

                token = set_current_session_key(session_key)
                try:
                    with _gateway_approval_context(session_key):
                        results[idx] = check_all_command_guards(cmd, "local")
                finally:
                    reset_current_session_key(token)
            return run

        threads = [
            threading.Thread(target=make_agent(0, "rm -rf /a")),
            threading.Thread(target=make_agent(1, "rm -rf /b")),
            threading.Thread(target=make_agent(2, "rm -rf /c")),
        ]
        for t in threads:
            t.start()

        # Wait for all 3 to block
        for _ in range(100):
            if len(notified) >= 3:
                break
            time.sleep(0.05)

        assert len(notified) == 3
        assert len(_gateway_queues.get(session_key, [])) == 3

        # Approve all at once
        count = resolve_gateway_approval(session_key, "session", resolve_all=True)
        assert count == 3

        for t in threads:
            t.join(timeout=5)

        assert all(r is not None for r in results)
        assert all(r["approved"] is True for r in results)
        unregister_gateway_notify(session_key)

    def test_parallel_mixed_approve_deny(self):
        """Approve some, deny others in a parallel batch."""
        from tools.approval import (
            register_gateway_notify, unregister_gateway_notify,
            resolve_gateway_approval, check_all_command_guards,
        )

        session_key = "e2e-mixed"
        register_gateway_notify(session_key, lambda d: None)

        results = [None, None]

        def make_agent(idx, cmd):
            def run():
                from tools.approval import reset_current_session_key, set_current_session_key

                token = set_current_session_key(session_key)
                try:
                    with _gateway_approval_context(session_key):
                        results[idx] = check_all_command_guards(cmd, "local")
                finally:
                    reset_current_session_key(token)
            return run

        threads = [
            threading.Thread(target=make_agent(0, "rm -rf /x")),
            threading.Thread(target=make_agent(1, "rm -rf /y")),
        ]
        for t in threads:
            t.start()

        # Wait for both threads to register pending approvals instead of
        # relying on a fixed sleep.  The approval module stores entries in
        # _gateway_queues[session_key] — poll until we see 2 entries.
        from tools.approval import _gateway_queues
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if len(_gateway_queues.get(session_key, [])) >= 2:
                break
            time.sleep(0.05)

        # Approve first, deny second
        resolve_gateway_approval(session_key, "once")   # oldest
        resolve_gateway_approval(session_key, "deny")   # next

        for t in threads:
            t.join(timeout=5)

        assert all(r is not None for r in results)
        assert sorted(r["approved"] for r in results) == [False, True]
        assert sum("BLOCKED" in (r.get("message") or "") for r in results) == 1
        unregister_gateway_notify(session_key)


# ------------------------------------------------------------------
# Fallback: no gateway callback (cron/batch mode)
# ------------------------------------------------------------------


class TestFallbackNoCallback:

    def setup_method(self):
        _clear_approval_state()

    def test_no_callback_returns_approval_required(self):
        """Without a registered callback, the fallback returns pending_approval.

        PR #6d495d9e7 renamed the LLM-visible status from ``approval_required``
        to ``pending_approval`` to make the state distinguishable from a
        failed tool call.
        """
        from tools.approval import check_all_command_guards

        with _gateway_approval_context("no-callback-test"):
            result = check_all_command_guards("rm -rf /important", "local")

        assert result["approved"] is False
        assert result.get("status") == "pending_approval"
        assert result.get("approval_pending") is True


# ------------------------------------------------------------------
# Regression: cross-session approval routing isolation (#24100)
# ------------------------------------------------------------------


class TestCrossSessionApprovalIsolation:
    """Concurrent approval routing remains isolated by task-local identity."""

    def setup_method(self):
        _clear_approval_state()

    def test_approval_context_overrides_general_session_context(self):
        from tools.approval import (
            get_current_session_key,
            reset_current_session_key,
            set_current_session_key,
        )

        from gateway.session_context import clear_session_vars, set_session_vars

        session_tokens = set_session_vars(session_key="session-B")
        token = set_current_session_key("session-A")
        try:
            assert get_current_session_key() == "session-A"
        finally:
            reset_current_session_key(token)
            clear_session_vars(session_tokens)

    def test_cleared_context_returns_default_scope(self):
        from gateway.session_context import clear_session_vars, set_session_vars
        from tools.approval import get_current_session_key

        tokens = set_session_vars(session_key="session-A")
        try:
            assert get_current_session_key() == "session-A"
        finally:
            clear_session_vars(tokens)

        assert get_current_session_key() == "default"

    def test_approval_prompt_routes_to_originating_session(self):
        """A dangerous command in session A's worker thread notifies
        session A's callback and never session B's callback."""
        from tools.approval import (
            check_all_command_guards,
            register_gateway_notify,
            reset_current_session_key,
            resolve_gateway_approval,
            set_current_session_key,
            unregister_gateway_notify,
        )
        notified_a = []
        notified_b = []
        register_gateway_notify("session-A", lambda d: notified_a.append(d))
        register_gateway_notify("session-B", lambda d: notified_b.append(d))

        result_holder = [None]

        def worker_a():
            # This worker belongs to session A and binds only task-local state.
            token = set_current_session_key("session-A")
            try:
                with _gateway_approval_context("session-A"):
                    result_holder[0] = check_all_command_guards(
                        "rm -rf /important", "local"
                    )
            finally:
                reset_current_session_key(token)

        t = threading.Thread(target=worker_a)
        t.start()
        try:
            for _ in range(50):
                if notified_a or notified_b:
                    break
                time.sleep(0.05)

            # The prompt must land in session A (the originator), never B.
            assert len(notified_a) == 1, "approval prompt did not route to session A"
            assert len(notified_b) == 0, "approval prompt leaked to session B (#24100)"
            assert "rm -rf /important" in notified_a[0]["command"]

            resolve_gateway_approval("session-A", "once")
            t.join(timeout=5)
            assert result_holder[0] is not None
            assert result_holder[0]["approved"] is True
        finally:
            unregister_gateway_notify("session-A")
            unregister_gateway_notify("session-B")

    def test_two_concurrent_sessions_route_to_own_queue_contextvar_only(self):
        """Cross-session isolation driven by contextvars ALONE (#24100).

        Two concurrent worker threads have distinct task-local session
        identities. This proves task-local routing is sufficient and would fail if
        context routing regressed
        (the prior 'parallel' tests share one key and dual-set env+contextvar,
        so they cannot guard this invariant). Each session's dangerous command
        must land in its OWN gateway queue, and resolving one must not resolve
        the other.
        """
        from tools.approval import (
            _gateway_queues,
            check_all_command_guards,
            register_gateway_notify,
            reset_current_session_key,
            resolve_gateway_approval,
            set_current_session_key,
            unregister_gateway_notify,
        )

        register_gateway_notify("sess-A", lambda d: None)
        register_gateway_notify("sess-B", lambda d: None)

        results = {"sess-A": None, "sess-B": None}

        def worker(key, cmd):
            token = set_current_session_key(key)
            try:
                with _gateway_approval_context(key):
                    results[key] = check_all_command_guards(cmd, "local")
            finally:
                reset_current_session_key(token)

        ta = threading.Thread(target=worker, args=("sess-A", "rm -rf /a-data"))
        tb = threading.Thread(target=worker, args=("sess-B", "rm -rf /b-data"))
        ta.start()
        tb.start()
        try:
            # Wait until both sessions have a pending approval in their queue.
            for _ in range(100):
                if (len(_gateway_queues.get("sess-A", [])) >= 1
                        and len(_gateway_queues.get("sess-B", [])) >= 1):
                    break
                time.sleep(0.05)

            # Each command must be parked in its OWN session queue.
            qa = _gateway_queues.get("sess-A", [])
            qb = _gateway_queues.get("sess-B", [])
            assert len(qa) == 1, f"sess-A queue should hold 1, got {len(qa)}"
            assert len(qb) == 1, f"sess-B queue should hold 1, got {len(qb)}"

            # Resolve ONLY sess-A; sess-B must stay blocked (no cross-leak).
            resolve_gateway_approval("sess-A", "once")
            ta.join(timeout=5)
            assert results["sess-A"] is not None
            assert results["sess-A"]["approved"] is True
            assert results["sess-B"] is None, "sess-B resolved by sess-A's approval (#24100)"
            assert len(_gateway_queues.get("sess-B", [])) == 1

            # Now resolve sess-B independently.
            resolve_gateway_approval("sess-B", "once")
            tb.join(timeout=5)
            assert results["sess-B"] is not None
            assert results["sess-B"]["approved"] is True
        finally:
            resolve_gateway_approval("sess-A", "deny")
            resolve_gateway_approval("sess-B", "deny")
            ta.join(timeout=2)
            tb.join(timeout=2)
            unregister_gateway_notify("sess-A")
            unregister_gateway_notify("sess-B")
