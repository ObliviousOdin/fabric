"""Non-blocking, reconnecting publisher for dashboard Chat metadata/events.

The primary stdio transport always runs first (see :class:`TeeTransport`).
This secondary only queues bounded semantic frames; a daemon worker owns all
connect/send work so model and TUI output never wait on the dashboard socket.
"""

from __future__ import annotations

import json
import logging
import math
import queue
import re
import threading
from itertools import islice
from typing import Optional

try:
    from websockets.sync.client import connect as ws_connect
except ImportError:  # pragma: no cover - websockets is a required install path
    ws_connect = None  # type: ignore[assignment]

_log = logging.getLogger(__name__)

_DRAIN_STOP = object()
_QUEUE_MAX = 256
_MAX_FRAME_BYTES = 32 * 1024
_MAX_LIST_ITEMS = 20
_MAX_INPUT_LIST_SCAN = 128
_MAX_ARTIFACT_SCAN_NODES = 128
_MAX_FIELD_CHARS = 8 * 1024
_MAX_EVENT_TYPE_CHARS = 128
_MAX_SESSION_ID_CHARS = 512
_STREAM_ONLY_EVENT_TYPES = frozenset({
    "message.delta",
    "reasoning.delta",
    "thinking.delta",
})
_SESSION_INFO_KEYS = frozenset({
    "credential_warning",
    "cwd",
    "model",
    "provider",
    "running",
    "session_id",
    "title",
})
_EVENT_PAYLOAD_KEYS = {
    "dashboard.new_session_requested": frozenset({"reason"}),
    "error": frozenset({"message"}),
    "session.info": _SESSION_INFO_KEYS,
    "session.title": frozenset({"session_id", "title"}),
    "status.update": frozenset({"kind", "text"}),
    "subagent.complete": frozenset(
        {
            "child_session_id",
            "depth",
            "duration_seconds",
            "error",
            "files_written",
            "parent_id",
            "status",
            "subagent_id",
            "summary",
            "task_count",
            "task_index",
            "tool_name",
        }
    ),
    "tool.start": frozenset({"context", "name", "tool_id", "todos"}),
    "tool.complete": frozenset(
        {
            "duration_s",
            "error",
            "files_written",
            "name",
            "summary",
            "tool_id",
            "todos",
        }
    ),
}
_ACCEPTED_EVENT_TYPES = frozenset(
    {
        "approval.request",
        "dashboard.new_session_requested",
        "error",
        "message.complete",
        "message.start",
        "session.info",
        "session.title",
        "status.update",
        "subagent.complete",
        "tool.complete",
        "tool.start",
    }
)
_ARTIFACT_KEY_RE = re.compile(
    r"(?:^|[._-])(artifact|download|file|image|output|path|target|url)(?:s|$|[._-])",
    re.IGNORECASE,
)
_ARTIFACT_EXT_RE = re.compile(
    r"\.(?:bmp|csv|gif|gz|jpe?g|json|md|mov|mp3|mp4|pdf|png|svg|tar|txt|wav|webp|zip)"
    r"(?:[?#].*)?$",
    re.IGNORECASE,
)


class _OversizedSidecarField(ValueError):
    pass


def _compact_todos(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    compact: list[dict] = []
    for item in islice(value, _MAX_INPUT_LIST_SCAN):
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str):
            continue
        if len(content) > _MAX_FIELD_CHARS:
            raise _OversizedSidecarField("todo content exceeds sidecar field cap")
        if not content.strip():
            continue
        todo = {"content": content}
        for key in ("id", "status"):
            field = item.get(key)
            if isinstance(field, str):
                if len(field) > _MAX_FIELD_CHARS:
                    raise _OversizedSidecarField(
                        f"todo {key} exceeds sidecar field cap"
                    )
                todo[key] = field
        compact.append(todo)
        if len(compact) >= _MAX_LIST_ITEMS:
            break
    return compact


def _compact_files(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    compact: list[str] = []
    for item in islice(value, _MAX_INPUT_LIST_SCAN):
        if not isinstance(item, str):
            continue
        if len(item) > 2048:
            raise _OversizedSidecarField("artifact path exceeds sidecar field cap")
        compact.append(item)
        if len(compact) >= _MAX_LIST_ITEMS:
            break
    return compact


def _looks_like_artifact(value: str, key_path: str) -> bool:
    if not value or len(value) > 2048 or value.startswith("data:"):
        return False
    path_like = bool(
        re.match(r"^(?:file://|/|~/|\.\.?/|[A-Za-z]:[\\/])", value)
    )
    if re.match(r"^https?://", value, re.IGNORECASE):
        return bool(_ARTIFACT_EXT_RE.search(value))
    return path_like and bool(
        _ARTIFACT_KEY_RE.search(key_path) or _ARTIFACT_EXT_RE.search(value)
    )


def _compact_artifacts(payload: dict) -> list[str]:
    found = dict.fromkeys(_compact_files(payload.get("files_written")))
    budget = [_MAX_ARTIFACT_SCAN_NODES]

    def visit(value: object, key_path: str, depth: int) -> None:
        if len(found) >= _MAX_LIST_ITEMS or budget[0] <= 0 or depth > 6:
            return
        budget[0] -= 1
        if isinstance(value, str):
            if len(value) > 2048:
                return
            normalized = value.strip().rstrip("),.;")
            if _looks_like_artifact(normalized, key_path):
                found.setdefault(normalized, None)
            return
        if isinstance(value, list):
            for index, child in enumerate(islice(value, budget[0])):
                if budget[0] <= 0 or len(found) >= _MAX_LIST_ITEMS:
                    break
                visit(child, f"{key_path}.{index}", depth + 1)
            return
        if isinstance(value, dict):
            for key, child in islice(value.items(), budget[0]):
                if budget[0] <= 0 or len(found) >= _MAX_LIST_ITEMS:
                    break
                child_path = f"{key_path}.{key}" if key_path else str(key)
                visit(child, child_path, depth + 1)

    visit(payload.get("args"), "args", 0)
    visit(payload.get("result"), "result", 0)
    return list(found)[:_MAX_LIST_ITEMS]


def _payload_keys(event_type: str) -> frozenset[str]:
    return _EVENT_PAYLOAD_KEYS.get(event_type, frozenset())


def _compact_payload(event_type: str, payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    compact: dict = {}
    for key in _payload_keys(event_type):
        value = payload.get(key)
        if key == "todos":
            todos = _compact_todos(value)
            if todos:
                compact[key] = todos
        elif key == "files_written":
            files = (
                _compact_artifacts(payload)
                if event_type == "tool.complete"
                else _compact_files(value)
            )
            if files:
                compact[key] = files
        elif isinstance(value, (str, bool, int)):
            if isinstance(value, str) and len(value) > _MAX_FIELD_CHARS:
                raise _OversizedSidecarField(
                    f"{event_type}.{key} exceeds sidecar field cap"
                )
            compact[key] = value
        elif isinstance(value, float) and math.isfinite(value):
            compact[key] = value
    return compact


def _sidecar_projection(obj: dict) -> Optional[dict]:
    """Return an allowlisted dashboard frame, or ``None`` for token streams."""
    if obj.get("method") != "event":
        return None
    params = obj.get("params")
    if not isinstance(params, dict):
        return None
    event_type = params.get("type")
    if (
        not isinstance(event_type, str)
        or not event_type
        or len(event_type) > _MAX_EVENT_TYPE_CHARS
        or event_type not in _ACCEPTED_EVENT_TYPES
        or event_type in _STREAM_ONLY_EVENT_TYPES
    ):
        return None
    projected_params: dict = {"type": event_type}
    session_id = params.get("session_id")
    if isinstance(session_id, str):
        if len(session_id) > _MAX_SESSION_ID_CHARS:
            raise _OversizedSidecarField("session id exceeds sidecar field cap")
        projected_params["session_id"] = session_id
    payload = _compact_payload(event_type, params.get("payload"))
    if payload:
        projected_params["payload"] = payload
    return {
        "jsonrpc": "2.0",
        "method": "event",
        "params": projected_params,
    }


class WsPublisherTransport:
    __slots__ = (
        "_url",
        "_connect_timeout",
        "_retry_initial",
        "_retry_max",
        "_lock",
        "_ws",
        "_dead",
        "_closed",
        "_q",
        "_queue_lock",
        "_worker",
    )

    def __init__(
        self,
        url: str,
        *,
        connect_timeout: float = 2.0,
        retry_initial: float = 0.1,
        retry_max: float = 3.0,
    ) -> None:
        self._url = url
        self._connect_timeout = connect_timeout
        self._retry_initial = max(0.001, retry_initial)
        self._retry_max = max(self._retry_initial, retry_max)
        # Re-entrant so socket teardown remains safe if a WebSocket
        # implementation raises synchronously from inside ``send``.
        self._lock = threading.RLock()
        self._ws: Optional[object] = None
        self._dead = ws_connect is None
        self._closed = threading.Event()
        self._q: queue.Queue[object] = queue.Queue(maxsize=_QUEUE_MAX)
        self._queue_lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None

        if self._dead:
            return

        # Connection establishment is deliberately off-thread. Installing the
        # sidecar must not add its timeout to TUI/model startup latency.
        self._worker = threading.Thread(
            target=self._drain,
            name="ws-publisher",
            daemon=True,
        )
        self._worker.start()

    def _connect(self) -> bool:
        try:
            ws = ws_connect(  # type: ignore[misc]
                self._url,
                open_timeout=self._connect_timeout,
                max_size=None,
            )
        except Exception as exc:
            _log.debug("event publisher connect failed: %s", exc)
            return False
        discard = False
        with self._lock:
            if self._closed.is_set():
                discard = True
            else:
                self._ws = ws
        if discard:
            try:
                ws.close()
            except Exception:
                pass
            return False
        return True

    def _drop_socket(self) -> None:
        with self._lock:
            ws = self._ws
            self._ws = None
        if ws is not None:
            try:
                ws.close()  # type: ignore[union-attr]
            except Exception:
                pass

    def _drain(self) -> None:
        retry_delay = self._retry_initial
        pending: Optional[str] = None
        while not self._closed.is_set():
            if self._ws is None:
                if not self._connect():
                    self._closed.wait(retry_delay)
                    retry_delay = min(retry_delay * 2, self._retry_max)
                    continue
                retry_delay = self._retry_initial

            if pending is None:
                try:
                    item = self._q.get(timeout=0.25)
                except queue.Empty:
                    continue
                if item is _DRAIN_STOP:
                    return
                if not isinstance(item, str):
                    continue
                pending = item

            try:
                # Never hold the state lock across potentially blocking
                # network I/O. close() must be able to detach/close the socket
                # promptly even if an implementation's send() stalls.
                with self._lock:
                    ws = self._ws
                if ws is None:
                    continue
                ws.send(pending)  # type: ignore[union-attr]
                pending = None
            except Exception as exc:
                _log.debug("event publisher write failed: %s", exc)
                self._drop_socket()

    def write(self, obj: dict) -> bool:
        """Queue one semantic frame without waiting for connect or network I/O."""
        if self._dead or self._worker is None or self._closed.is_set():
            return False
        try:
            projected = _sidecar_projection(obj)
        except _OversizedSidecarField:
            return False
        if projected is None:
            return True
        line = json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
        if len(line.encode("utf-8")) > _MAX_FRAME_BYTES:
            return False
        # The sidecar is a live read model. If the bounded queue fills while
        # disconnected, evict the oldest frame so current session/title/tool
        # state survives instead of permanently preserving stale activity.
        with self._queue_lock:
            try:
                self._q.put_nowait(line)
            except queue.Full:
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    pass
                self._q.put_nowait(line)
        return True

    def close(self) -> None:
        self._dead = True
        self._closed.set()
        worker = self._worker
        if worker is not None and worker.is_alive():
            try:
                self._q.put_nowait(_DRAIN_STOP)
            except queue.Full:
                pass
        self._drop_socket()
        if worker is not None:
            worker.join(timeout=self._connect_timeout + 0.5)
        self._worker = None
