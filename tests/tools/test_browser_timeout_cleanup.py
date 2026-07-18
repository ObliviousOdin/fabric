"""Regression coverage for timed-out agent-browser session cleanup.

The agent-browser CLI is only an IPC client.  Its browser daemon is detached,
so killing a hung CLI must also reap the task-specific daemon/Chromium tree.
Cleanup may also be triggered concurrently by inactivity and turn shutdown;
those lifecycle operations must serialize per session without serializing
independent subagent sessions.
"""

import os
import stat
import threading
import time
from contextlib import contextmanager
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_browser_state():
    from tools import browser_tool as bt

    active = bt._active_sessions.copy()
    activity = bt._session_last_activity.copy()
    recordings = bt._recording_sessions.copy()
    last_active = bt._last_active_session_key.copy()
    live_view_admissions = bt._browser_live_view_last_capture.copy()
    yield
    bt._active_sessions.clear()
    bt._active_sessions.update(active)
    bt._session_last_activity.clear()
    bt._session_last_activity.update(activity)
    bt._recording_sessions.clear()
    bt._recording_sessions.update(recordings)
    bt._last_active_session_key.clear()
    bt._last_active_session_key.update(last_active)
    bt._browser_live_view_last_capture.clear()
    bt._browser_live_view_last_capture.update(live_view_admissions)


def test_parallel_task_session_guards_do_not_block_each_other():
    """Different subagent task IDs retain full browser concurrency."""
    from tools.browser_tool import _browser_session_guard

    barrier = threading.Barrier(2)
    errors = []

    def enter(task_id):
        try:
            with _browser_session_guard(task_id):
                barrier.wait(timeout=2)
        except Exception as exc:  # pragma: no cover - assertion reports detail
            errors.append(exc)

    threads = [
        threading.Thread(target=enter, args=("task-a",)),
        threading.Thread(target=enter, args=("task-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)


def test_duplicate_cleanup_is_serialized_and_closes_once():
    """Inactivity and turn-end cleanup cannot race in one socket directory."""
    from tools import browser_tool as bt

    bt._active_sessions["task-1"] = {
        "session_name": "h_cleanup_race",
        "bb_session_id": None,
    }
    bt._session_last_activity["task-1"] = 1.0

    close_entered = threading.Event()
    release_close = threading.Event()
    close_calls = []
    errors = []

    def slow_close(task_id, command, args, timeout):
        close_calls.append((task_id, command, args, timeout))
        close_entered.set()
        assert release_close.wait(timeout=2)
        return {"success": True}

    def cleanup():
        try:
            bt._cleanup_single_browser_session("task-1")
        except Exception as exc:  # pragma: no cover - assertion reports detail
            errors.append(exc)

    with (
        patch("tools.browser_tool._stop_cdp_supervisor"),
        patch("tools.browser_tool._is_camofox_mode", return_value=False),
        patch("tools.browser_tool._maybe_stop_recording"),
        patch("tools.browser_tool._run_browser_command", side_effect=slow_close),
        patch("tools.browser_tool.os.path.exists", return_value=False),
    ):
        first = threading.Thread(target=cleanup)
        second = threading.Thread(target=cleanup)
        first.start()
        assert close_entered.wait(timeout=2)
        second.start()

        # The second cleanup must be waiting on the task's lifecycle guard,
        # not launching another close against the same _stdout_close path.
        time.sleep(0.05)
        assert len(close_calls) == 1
        release_close.set()
        first.join(timeout=3)
        second.join(timeout=3)

    assert not errors
    assert len(close_calls) == 1
    assert "task-1" not in bt._active_sessions
    assert not first.is_alive()
    assert not second.is_alive()


def test_inactivity_reaper_revalidates_activity_after_waiting_for_command():
    """A queued reaper cannot close a session refreshed by browser work."""
    from tools import browser_tool as bt

    task_id = "task-active-while-reaper-waits"
    bt._active_sessions[task_id] = {
        "session_name": "h_activity_race",
        "bb_session_id": None,
    }
    bt._session_last_activity[task_id] = 0.0

    original_guard = bt._browser_session_guard
    reaper_waiting = threading.Event()

    @contextmanager
    def observed_guard(guarded_task_id, **kwargs):
        reaper_waiting.set()
        with original_guard(guarded_task_id, **kwargs) as acquired:
            yield acquired

    cleanup_calls = []

    with (
        patch("tools.browser_tool.BROWSER_SESSION_INACTIVITY_TIMEOUT", 30),
        patch("tools.browser_tool.time.time", return_value=100.0),
        patch("tools.browser_tool._browser_session_guard", observed_guard),
        patch(
            "tools.browser_tool.cleanup_browser",
            side_effect=lambda key: cleanup_calls.append(key),
        ),
    ):
        with original_guard(task_id):
            reaper = threading.Thread(
                target=bt._cleanup_inactive_browser_sessions
            )
            reaper.start()
            assert reaper_waiting.wait(timeout=2)

            # Mirrors `_get_session_info()` refreshing activity while the model
            # command owns the same lifecycle guard.
            bt._session_last_activity[task_id] = 100.0

        reaper.join(timeout=2)

    assert not reaper.is_alive()
    assert cleanup_calls == []
    assert bt._active_sessions[task_id]["session_name"] == "h_activity_race"
    assert bt._session_last_activity[task_id] == 100.0


def test_cdp_timeout_uses_task_isolated_default_pid_file(tmp_path):
    """CDP mode's ``default.pid`` is still cleaned inside its unique socket dir."""
    from tools.browser_tool import _terminate_timed_out_browser_daemon

    socket_dir = tmp_path / "agent-browser-cdp_task"
    socket_dir.mkdir()
    (socket_dir / "default.pid").write_text("999999999", encoding="utf-8")

    with patch("gateway.status._pid_exists", return_value=False):
        cleaned = _terminate_timed_out_browser_daemon(
            {"session_name": "cdp_task", "cdp_url": "ws://127.0.0.1:9222"},
            str(socket_dir),
        )

    assert cleaned is True
    assert not socket_dir.exists()


def test_forgetting_reset_local_session_discards_live_view_supervisor(monkeypatch):
    """A killed local Chrome must not leave its CDP reconnect loop behind."""
    from tools import browser_supervisor as bs
    from tools import browser_tool as bt

    task_id = "task-timeout-supervisor-reset"
    session_info = {
        "session_name": "h_timeout_supervisor_reset",
        "owner_task_id": "owner-task",
        "cdp_url": None,
    }
    bt._active_sessions[task_id] = session_info
    bt._session_last_activity[task_id] = 123.0
    bt._recording_sessions.add(task_id)
    bt._last_active_session_key["owner-task"] = task_id
    bt._browser_live_view_last_capture[task_id] = 456.0

    stop_calls = []
    fake_supervisor = type(
        "FakeSupervisor",
        (),
        {"stop": lambda self: stop_calls.append(task_id)},
    )()
    with bs.SUPERVISOR_REGISTRY._lock:
        previous = bs.SUPERVISOR_REGISTRY._by_task.get(task_id)
        bs.SUPERVISOR_REGISTRY._by_task[task_id] = fake_supervisor

    class TrackingLock:
        held = False

        def __enter__(self):
            self.held = True
            return self

        def __exit__(self, *_exc):
            self.held = False

    tracking_lock = TrackingLock()
    original_stop = bs.SUPERVISOR_REGISTRY.stop

    def checked_stop(key):
        assert tracking_lock.held is False
        return original_stop(key)

    monkeypatch.setattr(bt, "_cleanup_lock", tracking_lock)
    monkeypatch.setattr(bs.SUPERVISOR_REGISTRY, "stop", checked_stop)
    try:
        bt._forget_reset_local_browser_session(task_id, session_info)
    finally:
        with bs.SUPERVISOR_REGISTRY._lock:
            bs.SUPERVISOR_REGISTRY._by_task.pop(task_id, None)
            if previous is not None:
                bs.SUPERVISOR_REGISTRY._by_task[task_id] = previous

    assert stop_calls == [task_id]
    assert task_id not in bt._active_sessions
    assert task_id not in bt._session_last_activity
    assert task_id not in bt._recording_sessions
    assert task_id not in bt._browser_live_view_last_capture
    assert "owner-task" not in bt._last_active_session_key


def test_stale_timeout_does_not_stop_replacement_supervisor(monkeypatch):
    """A late reset result cannot tear down a newer session for the task."""
    from tools import browser_tool as bt

    task_id = "task-timeout-replaced"
    old_session = {"session_name": "h_old", "cdp_url": None}
    replacement = {"session_name": "h_new", "cdp_url": None}
    bt._active_sessions[task_id] = replacement
    stop_calls = []
    monkeypatch.setattr(
        bt, "_stop_cdp_supervisor", lambda key: stop_calls.append(key)
    )

    bt._forget_reset_local_browser_session(task_id, old_session)

    assert bt._active_sessions[task_id] is replacement
    assert stop_calls == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable shim/process semantics")
@pytest.mark.live_system_guard_bypass
def test_live_timeout_reaps_detached_daemon_and_socket_dir(tmp_path):
    """A real detached child cannot survive a timed-out browser command.

    The executable shim mirrors agent-browser's process model: the foreground
    IPC client launches a detached daemon, writes ``<session>.pid``, and then
    wedges.  The test exercises real Popen timeout and process-tree teardown;
    only browser discovery/installation checks are bypassed.
    """
    from gateway.status import _pid_exists
    from tools import browser_tool as bt
    from tools.process_registry import ProcessRegistry

    shim = tmp_path / "agent-browser-timeout-shim"
    daemon_pid_marker = tmp_path / "detached-daemon.pid"
    shim.write_text(
        """#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import sys
import time

session = sys.argv[sys.argv.index("--session") + 1]
socket_dir = Path(os.environ["AGENT_BROWSER_SOCKET_DIR"])
socket_dir.mkdir(parents=True, exist_ok=True)
daemon = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(300)",
     "agent-browser-daemon", str(socket_dir)],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    start_new_session=True,
    env=os.environ.copy(),
)
(socket_dir / f"{session}.pid").write_text(str(daemon.pid))
Path(os.environ["TEST_DAEMON_PID_PATH"]).write_text(str(daemon.pid))
time.sleep(300)
""",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)

    session_info = {
        "session_name": "h_timeout_live",
        "bb_session_id": None,
        "cdp_url": None,
    }
    browser_env = os.environ.copy()
    browser_env["TEST_DAEMON_PID_PATH"] = str(daemon_pid_marker)
    bt._active_sessions["task-timeout"] = session_info
    bt._session_last_activity["task-timeout"] = time.time()

    daemon_pid = None
    try:
        with (
            patch("tools.browser_tool._find_agent_browser", return_value=str(shim)),
            patch("tools.browser_tool._is_local_mode", return_value=True),
            patch("tools.browser_tool._chromium_installed", return_value=True),
            patch("tools.browser_tool._get_browser_engine", return_value="auto"),
            patch("tools.browser_tool._get_session_info", return_value=session_info),
            patch("tools.browser_tool._build_browser_env", return_value=browser_env),
            patch("tools.browser_tool._socket_safe_tmpdir", return_value=str(tmp_path)),
            patch.object(ProcessRegistry, "_daemon_term_grace_seconds", return_value=0.2),
        ):
            result = bt._run_browser_command(
                "task-timeout", "snapshot", ["-c"], timeout=1
            )

        assert result["success"] is False
        assert "local browser session was reset" in result["error"]
        daemon_pid = int(daemon_pid_marker.read_text(encoding="utf-8"))
        assert not _pid_exists(daemon_pid)
        assert not (tmp_path / "agent-browser-h_timeout_live").exists()
        assert "task-timeout" not in bt._active_sessions
        assert "task-timeout" not in bt._session_last_activity
    finally:
        if daemon_pid is None and daemon_pid_marker.exists():
            daemon_pid = int(daemon_pid_marker.read_text(encoding="utf-8"))
        if daemon_pid is not None and _pid_exists(daemon_pid):
            ProcessRegistry._terminate_host_pid(daemon_pid)
