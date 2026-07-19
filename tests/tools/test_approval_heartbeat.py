"""Tests for the activity-heartbeat behavior of the blocking gateway approval wait.

Regression test for false gateway inactivity timeouts firing while the agent
is legitimately blocked waiting for a user to respond to a dangerous-command
approval prompt.  Before the fix, ``entry.event.wait(timeout=...)`` blocked
silently — no ``_touch_activity()`` calls — and the gateway's inactivity
watchdog (``agent.gateway_timeout``, default 1800s) would kill the agent
while the user was still choosing whether to approve.

The fix polls the event in short slices and fires ``touch_activity_if_due``
between slices, mirroring ``_wait_for_process`` in ``tools/environments/base.py``.
"""

def _clear_approval_state():
    """Reset all module-level approval state between tests."""
    from tools import approval as mod
    mod._gateway_queues.clear()
    mod._gateway_notify_cbs.clear()
    mod._session_approved.clear()
    mod._permanent_approved.clear()
    mod._pending.clear()


class TestApprovalHeartbeat:
    """The blocking gateway approval wait must fire activity heartbeats.

    Without heartbeats, the gateway's inactivity watchdog kills the agent
    thread while it's legitimately waiting for a slow user to respond to
    an approval prompt (observed in real user logs: MRB, April 2026).
    """

    SESSION_KEY = "heartbeat-test-session"

    def setup_method(self):
        _clear_approval_state()
        from tools import approval as mod

        self._session_token = mod.set_current_session_key(self.SESSION_KEY)

    def teardown_method(self):
        from tools import approval as mod

        mod.reset_current_session_key(self._session_token)
        _clear_approval_state()
