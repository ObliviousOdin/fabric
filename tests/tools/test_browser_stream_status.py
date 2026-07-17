"""Tests for the bounded out-of-band Desktop Browser Live View path."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading
import time
from unittest.mock import patch

import pytest


class _FakeSupervisor:
    def __init__(self, *, active=True, capture=None):
        self._active = active
        self._capture = capture or (
            lambda **_kwargs: {"ok": True, "data": "jpeg", "mime_type": "image/jpeg"}
        )
        self.capture_calls = []

    def snapshot(self):
        return SimpleNamespace(active=self._active)

    def capture_viewport_jpeg(self, **kwargs):
        self.capture_calls.append(kwargs)
        return self._capture(**kwargs)


@pytest.fixture(autouse=True)
def _isolate_browser_sessions(monkeypatch):
    from tools import browser_tool as bt
    from tools import browser_supervisor as bs

    active = bt._active_sessions.copy()
    last_active = bt._last_active_session_key.copy()
    last_capture = bt._browser_live_view_last_capture.copy()
    supervisor_capture_gate = bs._LIVE_VIEW_CAPTURE_LAST_BY_TASK.copy()
    bt._active_sessions.clear()
    bt._last_active_session_key.clear()
    bt._browser_live_view_last_capture.clear()
    bs._LIVE_VIEW_CAPTURE_LAST_BY_TASK.clear()
    monkeypatch.setattr(bt, "_is_camofox_mode", lambda: False)
    monkeypatch.setattr(bt, "_using_lightpanda_engine", lambda: False)
    monkeypatch.setattr(bt, "_existing_browser_daemon_is_live", lambda _info: True)
    yield bt
    bt._active_sessions.clear()
    bt._active_sessions.update(active)
    bt._last_active_session_key.clear()
    bt._last_active_session_key.update(last_active)
    bt._browser_live_view_last_capture.clear()
    bt._browser_live_view_last_capture.update(last_capture)
    bs._LIVE_VIEW_CAPTURE_LAST_BY_TASK.clear()
    bs._LIVE_VIEW_CAPTURE_LAST_BY_TASK.update(supervisor_capture_gate)


def _set_active(bt, *, cdp_url=None):
    bt._active_sessions["durable-key"] = {
        "session_name": "h_existing",
        "cdp_url": cdp_url,
    }


def _patch_registry(monkeypatch, *, existing=None, started=None):
    from tools import browser_supervisor as bs

    monkeypatch.setattr(bs.SUPERVISOR_REGISTRY, "get", lambda _key: existing)
    monkeypatch.setattr(
        bs.SUPERVISOR_REGISTRY,
        "get_or_start",
        lambda **_kwargs: started if started is not None else existing,
    )


def test_no_active_session_never_runs_browser_command(_isolate_browser_sessions):
    bt = _isolate_browser_sessions
    with patch.object(
        bt,
        "_run_browser_command_serialized",
        side_effect=AssertionError("status probe must not create a session"),
    ):
        result = bt.get_browser_stream_status("durable-key")

    assert result == {"available": False, "reason": "no_active_browser_session"}
    assert bt._active_sessions == {}


def test_busy_browser_session_returns_immediately_without_queueing_probe(
    _isolate_browser_sessions, monkeypatch
):
    bt = _isolate_browser_sessions
    _set_active(bt)
    monkeypatch.setattr(
        bt,
        "_run_browser_command_serialized",
        lambda *args, **kwargs: pytest.fail("UI status must not queue behind model work"),
    )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with bt._browser_session_guard("durable-key"):
            result = pool.submit(
                bt.get_browser_stream_status, "durable-key"
            ).result(timeout=0.5)

    assert result == {"available": False, "reason": "browser_session_busy"}


@pytest.mark.parametrize(
    "probe_name",
    ["status", "frame"],
)
def test_slow_liveness_inspection_never_holds_model_action_lock(
    _isolate_browser_sessions, monkeypatch, probe_name
):
    bt = _isolate_browser_sessions
    _set_active(bt, cdp_url="ws://127.0.0.1:9222/devtools/browser/id")
    liveness_entered = threading.Event()
    release_liveness = threading.Event()
    model_entered = threading.Event()
    _patch_registry(monkeypatch, existing=_FakeSupervisor())

    def liveness(_session_info):
        liveness_entered.set()
        assert release_liveness.wait(timeout=2)
        return True

    def model_command(*_args, **_kwargs):
        model_entered.set()
        return {"success": True, "data": {}}

    monkeypatch.setattr(bt, "_existing_browser_daemon_is_live", liveness)
    monkeypatch.setattr(bt, "_run_browser_command_serialized", model_command)
    probe = (
        bt.get_browser_stream_status
        if probe_name == "status"
        else bt.get_browser_stream_frame
    )
    probe_thread = threading.Thread(target=lambda: probe("durable-key"))
    model_thread = threading.Thread(
        target=lambda: bt._run_browser_command("durable-key", "snapshot")
    )

    probe_thread.start()
    assert liveness_entered.wait(timeout=0.5)
    model_thread.start()
    try:
        assert model_entered.wait(timeout=0.5)
    finally:
        release_liveness.set()

    probe_thread.join(timeout=1)
    model_thread.join(timeout=1)
    assert not probe_thread.is_alive()
    assert not model_thread.is_alive()


def test_running_status_probe_does_not_delay_following_model_action(
    _isolate_browser_sessions, monkeypatch
):
    bt = _isolate_browser_sessions
    _set_active(bt)
    status_entered = threading.Event()
    release_status = threading.Event()
    model_action_entered = threading.Event()
    supervisor = _FakeSupervisor()
    _patch_registry(monkeypatch, existing=None, started=supervisor)

    def discover(_session_info):
        status_entered.set()
        assert release_status.wait(timeout=2)
        return "ws://127.0.0.1:9222/devtools/browser/id"

    def command(task_id, command_name, args=None, *rest, **kwargs):
        assert task_id == "durable-key"
        model_action_entered.set()
        return {"success": True, "data": {}}

    monkeypatch.setattr(bt, "_discover_local_browser_cdp_url", discover)
    monkeypatch.setattr(bt, "_run_browser_command_serialized", command)
    status_result = []
    model_result = []
    status_thread = threading.Thread(
        target=lambda: status_result.append(bt.get_browser_stream_status("durable-key"))
    )
    model_thread = threading.Thread(
        target=lambda: model_result.append(bt._run_browser_command("durable-key", "snapshot"))
    )

    status_thread.start()
    assert status_entered.wait(timeout=0.5)
    model_thread.start()
    try:
        assert model_action_entered.wait(timeout=0.5)
    finally:
        release_status.set()

    status_thread.join(timeout=1)
    model_thread.join(timeout=1)
    assert model_result[0]["success"] is True
    assert status_result[0] == {
        "available": True,
        "transport": "gateway_pull",
        "min_interval_ms": 500,
    }


@pytest.mark.parametrize(
    ("backend", "reason"),
    [
        ("camofox", "camofox_stream_unavailable"),
        ("lightpanda", "lightpanda_stream_unavailable"),
    ],
)
def test_non_streaming_backends_are_explicitly_unavailable(
    _isolate_browser_sessions, monkeypatch, backend, reason
):
    bt = _isolate_browser_sessions
    if backend == "lightpanda":
        _set_active(bt)
    monkeypatch.setattr(bt, "_is_camofox_mode", lambda: backend == "camofox")
    monkeypatch.setattr(bt, "_using_lightpanda_engine", lambda: backend == "lightpanda")

    assert bt.get_browser_stream_status("durable-key") == {
        "available": False,
        "reason": reason,
    }


def test_existing_supervisor_returns_private_gateway_pull_descriptor(
    _isolate_browser_sessions, monkeypatch
):
    bt = _isolate_browser_sessions
    _set_active(bt, cdp_url="wss://provider.example/devtools/browser/secret-token")
    supervisor = _FakeSupervisor()
    _patch_registry(monkeypatch, existing=supervisor)
    monkeypatch.setattr(
        bt,
        "_run_browser_command_serialized",
        lambda *args, **kwargs: pytest.fail("existing supervisor should be reused"),
    )

    result = bt.get_browser_stream_status("durable-key")

    assert result == {
        "available": True,
        "transport": "gateway_pull",
        "min_interval_ms": 500,
    }
    assert "secret-token" not in str(result)


def test_configured_lightpanda_does_not_hide_explicit_cdp_session(
    _isolate_browser_sessions, monkeypatch
):
    bt = _isolate_browser_sessions
    _set_active(bt, cdp_url="ws://127.0.0.1:9222/devtools/browser/id")
    monkeypatch.setattr(bt, "_using_lightpanda_engine", lambda: True)
    _patch_registry(monkeypatch, existing=_FakeSupervisor())

    assert bt.get_browser_stream_status("durable-key")["available"] is True


def test_local_status_resolves_cdp_out_of_band_without_agent_browser_ipc(
    _isolate_browser_sessions, monkeypatch
):
    bt = _isolate_browser_sessions
    _set_active(bt)
    supervisor = _FakeSupervisor()
    discovery_calls = []
    started = []

    def discover(session_info):
        discovery_calls.append(session_info)
        return "ws://127.0.0.1:9222/devtools/browser/id"

    monkeypatch.setattr(bt, "_discover_local_browser_cdp_url", discover)
    monkeypatch.setattr(
        bt,
        "_run_browser_command_serialized",
        lambda *args, **kwargs: pytest.fail(
            "status must not enter agent-browser's serialized IPC queue"
        ),
    )
    from tools import browser_supervisor as bs

    monkeypatch.setattr(bs.SUPERVISOR_REGISTRY, "get", lambda _key: None)

    def get_or_start(**kwargs):
        started.append(kwargs)
        return supervisor

    monkeypatch.setattr(bs.SUPERVISOR_REGISTRY, "get_or_start", get_or_start)

    assert bt.get_browser_stream_status("durable-key", timeout=99)["available"] is True
    assert discovery_calls == [bt._active_sessions["durable-key"]]
    assert started[0]["cdp_url"] == "ws://127.0.0.1:9222/devtools/browser/id"


def test_unavailable_local_cdp_uses_controlled_reason_code(
    _isolate_browser_sessions, monkeypatch
):
    bt = _isolate_browser_sessions
    _set_active(bt)
    _patch_registry(monkeypatch, existing=None)
    monkeypatch.setattr(bt, "_discover_local_browser_cdp_url", lambda _info: None)

    assert bt.get_browser_stream_status("durable-key") == {
        "available": False,
        "reason": "cdp_status_unavailable",
    }


def test_local_cdp_discovery_reads_only_verified_daemon_descendant(
    _isolate_browser_sessions, monkeypatch, tmp_path
):
    bt = _isolate_browser_sessions
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    (profile / "DevToolsActivePort").write_text(
        "45678\n/devtools/browser/abc-123\n", encoding="ascii"
    )

    child = SimpleNamespace(
        cmdline=lambda: [
            "/Applications/Chromium",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
        ],
        cwd=lambda: str(tmp_path),
    )
    daemon = SimpleNamespace(children=lambda recursive: [child])
    import psutil

    monkeypatch.setattr(psutil, "Process", lambda pid: daemon)
    monkeypatch.setattr(
        bt, "_read_browser_daemon_identity", lambda *_args: (321, "h_existing")
    )
    monkeypatch.setattr("gateway.status._pid_exists", lambda pid: pid == 321)
    monkeypatch.setattr(bt, "_verify_reapable_browser_daemon", lambda *args: True)

    result = bt._discover_local_browser_cdp_url(
        {"session_name": "h_existing", "cdp_url": None}
    )

    assert result == "ws://127.0.0.1:45678/devtools/browser/abc-123"


def test_local_cdp_discovery_rejects_unverified_or_non_descendant_processes(
    _isolate_browser_sessions, monkeypatch, tmp_path
):
    bt = _isolate_browser_sessions
    profile = tmp_path / "unrelated-profile"
    profile.mkdir()
    (profile / "DevToolsActivePort").write_text(
        "45678\n/devtools/browser/unrelated\n", encoding="ascii"
    )
    import psutil

    daemon = SimpleNamespace(children=lambda recursive: pytest.fail("must fail before scan"))
    monkeypatch.setattr(psutil, "Process", lambda pid: daemon)
    monkeypatch.setattr(
        bt, "_read_browser_daemon_identity", lambda *_args: (321, "h_existing")
    )
    monkeypatch.setattr("gateway.status._pid_exists", lambda _pid: True)
    monkeypatch.setattr(bt, "_verify_reapable_browser_daemon", lambda *args: False)

    assert (
        bt._discover_local_browser_cdp_url(
            {"session_name": "h_existing", "cdp_url": None}
        )
        is None
    )

    # Even a valid-looking profile elsewhere on the host is irrelevant unless
    # its Chrome process is a descendant of this verified daemon.
    monkeypatch.setattr(bt, "_verify_reapable_browser_daemon", lambda *args: True)
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda _pid: SimpleNamespace(children=lambda recursive: []),
    )
    assert (
        bt._discover_local_browser_cdp_url(
            {"session_name": "h_existing", "cdp_url": None}
        )
        is None
    )


@pytest.mark.parametrize(
    "contents",
    [
        b"not-a-port\n/devtools/browser/id\n",
        b"70000\n/devtools/browser/id\n",
        b"45678\n/devtools/page/not-browser\n",
        b"45678\n/devtools/browser/id?token=secret\n",
        b"x" * 1025,
    ],
)
def test_local_cdp_discovery_rejects_malformed_or_oversized_port_file(
    _isolate_browser_sessions, monkeypatch, tmp_path, contents
):
    bt = _isolate_browser_sessions
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    (profile / "DevToolsActivePort").write_bytes(contents)
    child = SimpleNamespace(
        cmdline=lambda: [
            "chromium",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
        ],
        cwd=lambda: str(tmp_path),
    )
    import psutil

    monkeypatch.setattr(
        psutil,
        "Process",
        lambda _pid: SimpleNamespace(children=lambda recursive: [child]),
    )
    monkeypatch.setattr(
        bt, "_read_browser_daemon_identity", lambda *_args: (321, "h_existing")
    )
    monkeypatch.setattr("gateway.status._pid_exists", lambda _pid: True)
    monkeypatch.setattr(bt, "_verify_reapable_browser_daemon", lambda *args: True)

    assert (
        bt._discover_local_browser_cdp_url(
            {"session_name": "h_existing", "cdp_url": None}
        )
        is None
    )


def test_local_cdp_discovery_rejects_symlinked_port_file(
    _isolate_browser_sessions, monkeypatch, tmp_path
):
    bt = _isolate_browser_sessions
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    target = tmp_path / "outside-port"
    target.write_text("45678\n/devtools/browser/id\n", encoding="ascii")
    try:
        (profile / "DevToolsActivePort").symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    child = SimpleNamespace(
        cmdline=lambda: [
            "chromium",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
        ],
        cwd=lambda: str(tmp_path),
    )
    import psutil

    monkeypatch.setattr(
        psutil,
        "Process",
        lambda _pid: SimpleNamespace(children=lambda recursive: [child]),
    )
    monkeypatch.setattr(
        bt, "_read_browser_daemon_identity", lambda *_args: (321, "h_existing")
    )
    monkeypatch.setattr("gateway.status._pid_exists", lambda _pid: True)
    monkeypatch.setattr(bt, "_verify_reapable_browser_daemon", lambda *args: True)

    assert (
        bt._discover_local_browser_cdp_url(
            {"session_name": "h_existing", "cdp_url": None}
        )
        is None
    )


def test_frame_server_enforces_two_fps_before_upstream_capture(
    _isolate_browser_sessions, monkeypatch
):
    bt = _isolate_browser_sessions
    _set_active(bt, cdp_url="ws://127.0.0.1:9222/devtools/browser/id")
    supervisor = _FakeSupervisor()
    _patch_registry(monkeypatch, existing=supervisor)
    times = iter([100.0, 100.1, 100.5])
    monkeypatch.setattr(bt.time, "monotonic", lambda: next(times))

    first = bt.get_browser_stream_frame("durable-key")
    second = bt.get_browser_stream_frame("durable-key")
    third = bt.get_browser_stream_frame("durable-key")

    assert first["available"] is True
    assert second["available"] is False
    assert second["reason"] == "frame_throttled"
    assert 400 <= second["retry_after_ms"] <= 401
    assert third["available"] is True
    assert len(supervisor.capture_calls) == 2


def test_busy_model_session_rejects_frame_without_upstream_capture(
    _isolate_browser_sessions, monkeypatch
):
    bt = _isolate_browser_sessions
    _set_active(bt, cdp_url="ws://127.0.0.1:9222/devtools/browser/id")
    supervisor = _FakeSupervisor()
    _patch_registry(monkeypatch, existing=supervisor)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with bt._browser_session_guard("durable-key"):
            result = pool.submit(
                bt.get_browser_stream_frame, "durable-key"
            ).result(timeout=0.5)

    assert result == {"available": False, "reason": "browser_session_busy"}
    assert supervisor.capture_calls == []


def test_running_frame_capture_does_not_delay_following_model_action(
    _isolate_browser_sessions, monkeypatch
):
    bt = _isolate_browser_sessions
    _set_active(bt, cdp_url="ws://127.0.0.1:9222/devtools/browser/id")
    frame_entered = threading.Event()
    release_frame = threading.Event()
    model_entered = threading.Event()

    def capture(**_kwargs):
        frame_entered.set()
        assert release_frame.wait(timeout=2)
        return {"ok": True, "data": "jpeg", "mime_type": "image/jpeg"}

    supervisor = _FakeSupervisor(capture=capture)
    _patch_registry(monkeypatch, existing=supervisor)

    def model_command(*_args, **_kwargs):
        model_entered.set()
        return {"success": True, "data": {}}

    monkeypatch.setattr(bt, "_run_browser_command_serialized", model_command)
    frame_result = []
    model_result = []
    frame_thread = threading.Thread(
        target=lambda: frame_result.append(bt.get_browser_stream_frame("durable-key"))
    )
    model_thread = threading.Thread(
        target=lambda: model_result.append(bt._run_browser_command("durable-key", "snapshot"))
    )

    frame_thread.start()
    assert frame_entered.wait(timeout=0.5)
    model_thread.start()
    try:
        assert model_entered.wait(timeout=0.5)
    finally:
        release_frame.set()

    frame_thread.join(timeout=1)
    model_thread.join(timeout=1)
    assert frame_result[0]["available"] is True
    assert model_result[0]["success"] is True


def _running_supervisor(task_id="test"):
    from tools.browser_supervisor import CDPSupervisor

    supervisor = CDPSupervisor(
        task_id=task_id,
        cdp_url="ws://127.0.0.1:9222/devtools/browser/id",
    )
    supervisor._active = True
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def runner():
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    assert ready.wait(timeout=1)
    supervisor._loop = loop
    supervisor._thread = thread
    return supervisor, loop, thread


def _stop_running_supervisor(loop, thread):
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=1)
    loop.close()


def test_capture_switches_to_visible_tab_and_uses_one_screenshot_call():
    supervisor, loop, thread = _running_supervisor()
    supervisor._page_session_id = "session-1"
    supervisor._page_target_id = "target-1"
    supervisor._page_sessions = {"target-1": "session-1"}
    calls = []

    async def cdp(method, params=None, *, session_id=None, timeout=10.0):
        calls.append((method, params, session_id, timeout))
        if method == "Runtime.evaluate":
            visibility = "hidden" if session_id == "session-1" else "visible"
            return {"result": {"result": {"type": "string", "value": visibility}}}
        if method == "Target.getTargets":
            return {
                "result": {
                    "targetInfos": [
                        {"targetId": "target-1", "type": "page"},
                        {"targetId": "target-2", "type": "page"},
                    ]
                }
            }
        if method == "Target.attachToTarget":
            assert params == {"targetId": "target-2", "flatten": True}
            return {"result": {"sessionId": "session-2"}}
        if method == "Page.captureScreenshot":
            return {"result": {"data": "visible-tab-jpeg"}}
        raise AssertionError(f"unexpected CDP method {method}")

    supervisor._cdp = cdp
    try:
        result = supervisor.capture_viewport_jpeg(timeout=1)
    finally:
        _stop_running_supervisor(loop, thread)

    assert result == {
        "ok": True,
        "data": "visible-tab-jpeg",
        "mime_type": "image/jpeg",
    }
    screenshots = [call for call in calls if call[0] == "Page.captureScreenshot"]
    assert len(screenshots) == 1
    assert screenshots[0][2] == "session-2"
    assert all(call[0] != "Page.startScreencast" for call in calls)


def test_actual_capture_gate_survives_supervisor_recreation():
    first, first_loop, first_thread = _running_supervisor("same-task")
    second, second_loop, second_thread = _running_supervisor("same-task")
    screenshot_calls = []

    def configure(supervisor, label):
        supervisor._page_session_id = f"session-{label}"
        supervisor._page_target_id = f"target-{label}"
        supervisor._page_sessions = {
            f"target-{label}": f"session-{label}"
        }

        async def cdp(method, params=None, *, session_id=None, timeout=10.0):
            if method == "Runtime.evaluate":
                return {
                    "result": {
                        "result": {"type": "string", "value": "visible"}
                    }
                }
            if method == "Page.captureScreenshot":
                screenshot_calls.append((label, session_id))
                return {"result": {"data": f"jpeg-{label}"}}
            raise AssertionError(f"unexpected CDP method {method}")

        supervisor._cdp = cdp

    configure(first, "one")
    configure(second, "two")
    try:
        first_result = first.capture_viewport_jpeg(timeout=0.5)
        second_result = second.capture_viewport_jpeg(timeout=0.5)
    finally:
        _stop_running_supervisor(first_loop, first_thread)
        _stop_running_supervisor(second_loop, second_thread)

    assert first_result["ok"] is True
    assert second_result["ok"] is False
    assert second_result["reason"] == "frame_throttled"
    assert screenshot_calls == [("one", "session-one")]


def test_delayed_tab_discovery_cannot_bunch_actual_screenshot_starts():
    supervisor, loop, thread = _running_supervisor("delayed-task")
    supervisor._page_session_id = "session-1"
    supervisor._page_target_id = "target-1"
    supervisor._page_sessions = {"target-1": "session-1"}
    visibility_calls = 0
    screenshot_starts = []

    async def cdp(method, params=None, *, session_id=None, timeout=10.0):
        nonlocal visibility_calls
        if method == "Runtime.evaluate":
            visibility_calls += 1
            if visibility_calls == 1:
                await asyncio.sleep(0.15)
            return {
                "result": {
                    "result": {"type": "string", "value": "visible"}
                }
            }
        if method == "Page.captureScreenshot":
            screenshot_starts.append(time.monotonic())
            return {"result": {"data": "jpeg"}}
        raise AssertionError(f"unexpected CDP method {method}")

    supervisor._cdp = cdp
    try:
        first = supervisor.capture_viewport_jpeg(timeout=0.5)
        throttled = supervisor.capture_viewport_jpeg(timeout=0.5)
        assert throttled["reason"] == "frame_throttled"
        time.sleep((throttled["retry_after_ms"] + 20) / 1000)
        third = supervisor.capture_viewport_jpeg(timeout=0.5)
    finally:
        _stop_running_supervisor(loop, thread)

    assert first["ok"] is True
    assert third["ok"] is True
    assert len(screenshot_starts) == 2
    assert screenshot_starts[1] - screenshot_starts[0] >= 0.49


def test_capture_deadline_finishes_before_next_pull_can_start():
    supervisor, loop, thread = _running_supervisor()
    supervisor._page_session_id = "session-1"
    supervisor._page_target_id = "target-1"
    supervisor._page_sessions = {"target-1": "session-1"}
    attempts = 0
    in_flight = 0
    max_in_flight = 0

    async def cdp(method, params=None, *, session_id=None, timeout=10.0):
        nonlocal attempts, in_flight, max_in_flight
        if method == "Runtime.evaluate":
            attempts += 1
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            try:
                if attempts == 1:
                    await asyncio.wait_for(asyncio.Event().wait(), timeout=timeout)
                return {
                    "result": {
                        "result": {"type": "string", "value": "visible"}
                    }
                }
            finally:
                in_flight -= 1
        if method == "Page.captureScreenshot":
            return {"result": {"data": "jpeg"}}
        raise AssertionError(f"unexpected CDP method {method}")

    supervisor._cdp = cdp
    try:
        first = supervisor.capture_viewport_jpeg(timeout=0.1)
        second = supervisor.capture_viewport_jpeg(timeout=0.5)
    finally:
        _stop_running_supervisor(loop, thread)

    assert first["ok"] is False
    assert second["ok"] is True
    assert max_in_flight == 1


def test_outer_capture_timeout_explicitly_cancels_scheduled_future(monkeypatch):
    supervisor, loop, thread = _running_supervisor()
    cancelled = []

    class TimedOutFuture:
        def result(self, *, timeout):
            raise TimeoutError("outer bridge timeout")

        def done(self):
            return False

        def cancel(self):
            cancelled.append(True)
            return True

    def schedule(coro, _loop):
        coro.close()
        return TimedOutFuture()

    monkeypatch.setattr("agent.async_utils.safe_schedule_threadsafe", schedule)
    try:
        result = supervisor.capture_viewport_jpeg(timeout=0.1)
    finally:
        _stop_running_supervisor(loop, thread)

    assert result["ok"] is False
    assert cancelled == [True]


def test_live_view_helpers_are_not_registered_model_tools(_isolate_browser_sessions):
    bt = _isolate_browser_sessions
    registered = {schema["name"] for schema in bt.BROWSER_TOOL_SCHEMAS}

    assert "visual.status" not in registered
    assert "visual.frame" not in registered
    assert "get_browser_stream_status" not in registered
    assert "get_browser_stream_frame" not in registered
