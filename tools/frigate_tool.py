"""Frigate NVR tool for querying camera events, reviews, snapshots and clips.

Registers five LLM-callable tools:
- ``frigate_events``   -- search tracked-object events (camera/label/zone/time filters)
- ``frigate_reviews``  -- list review items (the curated alert/detection queue)
- ``frigate_snapshot`` -- download an event snapshot or a camera's latest frame
- ``frigate_clip``     -- download an event clip for video analysis
- ``frigate_status``   -- service stats and per-camera health

Configuration via env:
- ``FRIGATE_URL`` -- base URL of the Frigate instance. Port 5000 serves
  Frigate's internal, unauthenticated API (docker-network integrations);
  port 8971 serves the authenticated UI/API.
- ``FRIGATE_TOKEN`` -- optional JWT (from POST /api/login on the 8971 port),
  sent as a Bearer token. Frigate has no API-key header; JWT is the only
  native credential.

Media downloads land under ``$HERMES_HOME/cache/frigate/`` — inside the
media-cache confinement roots — so ``vision_analyze`` / ``video_analyze``
can read them even when the terminal sandbox is non-local.
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _get_config():
    """Return (frigate_url, frigate_token) from env vars at call time."""
    return (
        os.getenv("FRIGATE_URL", "").rstrip("/"),
        os.getenv("FRIGATE_TOKEN", ""),
    )


def _get_headers(token: str = "") -> Dict[str, str]:
    """Return request headers, adding Authorization only when a JWT is set."""
    headers = {"Accept": "application/json"}
    if not token:
        _, token = _get_config()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# Frigate event IDs look like "1718987128.947436-g92ztx". Both the event id
# and the camera name are interpolated into URL paths
# (/api/events/{id}/snapshot.jpg, /api/{camera}/latest.jpg), so they must be
# strictly validated to prevent path traversal against the Frigate host.
_EVENT_ID_RE = re.compile(r"^[0-9]+\.[0-9]+-[A-Za-z0-9]+$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# Review filters accept comma-separated lists ("front,back").
_NAME_LIST_RE = re.compile(r"^[A-Za-z0-9_-]+(,[A-Za-z0-9_-]+)*$")

_SEVERITIES = frozenset({"alert", "detection"})

# Download caps. The clip cap matches video_analyze's 50MB base64 ceiling —
# a bigger file could be fetched but never analyzed, so fail early instead.
_MAX_SNAPSHOT_BYTES = 10 * 1024 * 1024
_MAX_CLIP_BYTES = 50 * 1024 * 1024

_API_TIMEOUT = 15
_MEDIA_TIMEOUT = 60


def _media_dir():
    """Directory for downloaded snapshots/clips, inside the vision-readable
    media cache roots (see tools/image_source.py confinement)."""
    from fabric_constants import get_hermes_dir

    path = get_hermes_dir("cache/frigate", "frigate_cache")
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Response summarizers (pure functions -- unit tested)
# ---------------------------------------------------------------------------


def _summarize_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Compact one event for context efficiency.

    The raw payload carries a base64 ``thumbnail`` per event that would blow
    up the model context — strip it and keep the queryable fields.
    """
    data = event.get("data") or {}
    summary = {
        "id": event.get("id", ""),
        "camera": event.get("camera", ""),
        "label": event.get("label", ""),
        "sub_label": event.get("sub_label"),
        "start_time": event.get("start_time"),
        "end_time": event.get("end_time"),
        "zones": event.get("zones", []),
        "has_clip": event.get("has_clip", False),
        "has_snapshot": event.get("has_snapshot", False),
    }
    score = data.get("top_score", event.get("top_score"))
    if score is not None:
        summary["top_score"] = score
    if data.get("recognized_license_plate"):
        summary["recognized_license_plate"] = data["recognized_license_plate"]
    return summary


def _summarize_events(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    items = [_summarize_event(e) for e in events if isinstance(e, dict)]
    return {"count": len(items), "events": items}


def _summarize_review(item: Dict[str, Any]) -> Dict[str, Any]:
    """Compact one review item (frigate/reviews shape, see MQTT docs)."""
    data = item.get("data") or {}
    return {
        "id": item.get("id", ""),
        "camera": item.get("camera", ""),
        "severity": item.get("severity", ""),
        "start_time": item.get("start_time"),
        "end_time": item.get("end_time"),
        "has_been_reviewed": item.get("has_been_reviewed", False),
        "objects": data.get("objects", []),
        "sub_labels": data.get("sub_labels", []),
        "zones": data.get("zones", []),
        # Event IDs usable with frigate_events / frigate_snapshot / frigate_clip
        "detections": data.get("detections", []),
    }


def _summarize_reviews(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    summaries = [_summarize_review(i) for i in items if isinstance(i, dict)]
    return {"count": len(summaries), "reviews": summaries}


def _summarize_stats(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Compact /api/stats into service + per-camera health."""
    service = stats.get("service") or {}
    cameras = {}
    for name, cam in (stats.get("cameras") or {}).items():
        if isinstance(cam, dict):
            cameras[name] = {
                "camera_fps": cam.get("camera_fps"),
                "detection_fps": cam.get("detection_fps"),
                "process_fps": cam.get("process_fps"),
                "skipped_fps": cam.get("skipped_fps"),
            }
    detectors = {}
    for name, det in (stats.get("detectors") or {}).items():
        if isinstance(det, dict):
            detectors[name] = {"inference_speed": det.get("inference_speed")}
    return {
        "version": service.get("version"),
        "uptime_seconds": service.get("uptime"),
        "cameras": cameras,
        "detectors": detectors,
    }


# ---------------------------------------------------------------------------
# Async HTTP helpers
# ---------------------------------------------------------------------------


async def _async_get_json(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """GET a Frigate API path and return parsed JSON."""
    import aiohttp

    frigate_url, token = _get_config()
    url = f"{frigate_url}{path}"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            headers=_get_headers(token),
            params=params or {},
            timeout=aiohttp.ClientTimeout(total=_API_TIMEOUT),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


async def _async_download(path: str, dest_name: str, max_bytes: int) -> Dict[str, Any]:
    """Stream a media file to the frigate cache dir with a hard size cap."""
    import aiohttp

    frigate_url, token = _get_config()
    url = f"{frigate_url}{path}"
    dest = _media_dir() / dest_name

    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            headers=_get_headers(token),
            timeout=aiohttp.ClientTimeout(total=_MEDIA_TIMEOUT),
        ) as resp:
            resp.raise_for_status()
            length = resp.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                raise ValueError(
                    f"Media is {int(length)} bytes, exceeding the "
                    f"{max_bytes} byte limit"
                )
            written = 0
            with open(dest, "wb") as fh:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        fh.close()
                        dest.unlink(missing_ok=True)
                        raise ValueError(
                            f"Media exceeded the {max_bytes} byte limit mid-download"
                        )
                    fh.write(chunk)

    return {"path": str(dest), "bytes": written}


def _run_async(coro):
    """Run an async coroutine from a sync handler."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already inside an event loop -- run in a fresh thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=_MEDIA_TIMEOUT + 15)
    else:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Param builders (pure functions -- unit tested)
# ---------------------------------------------------------------------------


def _build_event_params(args: dict) -> Dict[str, Any]:
    """Translate tool args into /api/events query params, validating names."""
    params: Dict[str, Any] = {"limit": int(args.get("limit") or 20)}
    for key in ("camera", "label", "zone"):
        value = args.get(key)
        if value:
            if not _NAME_RE.match(str(value)):
                raise ValueError(f"Invalid {key} format: {value!r}")
            params[key] = value
    for key in ("after", "before"):
        value = args.get(key)
        if value is not None and value != "":
            params[key] = float(value)
    for key in ("has_clip", "has_snapshot", "in_progress"):
        value = args.get(key)
        if value is not None and value != "":
            params[key] = 1 if str(value).lower() in {"1", "true", "yes"} else 0
    return params


def _build_review_params(args: dict) -> Dict[str, Any]:
    """Translate tool args into /api/review query params, validating names."""
    params: Dict[str, Any] = {"limit": int(args.get("limit") or 20)}
    severity = args.get("severity")
    if severity:
        if severity not in _SEVERITIES:
            raise ValueError(
                f"Invalid severity {severity!r} (expected 'alert' or 'detection')"
            )
        params["severity"] = severity
    for key in ("cameras", "labels", "zones"):
        value = args.get(key)
        if value:
            if not _NAME_LIST_RE.match(str(value)):
                raise ValueError(f"Invalid {key} format: {value!r}")
            params[key] = value
    reviewed = args.get("reviewed")
    if reviewed is not None and reviewed != "":
        params["reviewed"] = 1 if str(reviewed).lower() in {"1", "true", "yes"} else 0
    for key in ("after", "before"):
        value = args.get(key)
        if value is not None and value != "":
            params[key] = float(value)
    return params


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_events(args: dict, **kw) -> str:
    """Handler for frigate_events tool."""
    try:
        params = _build_event_params(args)
    except (ValueError, TypeError) as e:
        return tool_error(str(e))
    try:
        events = _run_async(_async_get_json("/api/events", params))
        return json.dumps({"result": _summarize_events(events or [])})
    except Exception as e:
        logger.error("frigate_events error: %s", e)
        return tool_error(f"Failed to list Frigate events: {e}")


def _handle_reviews(args: dict, **kw) -> str:
    """Handler for frigate_reviews tool."""
    try:
        params = _build_review_params(args)
    except (ValueError, TypeError) as e:
        return tool_error(str(e))
    try:
        items = _run_async(_async_get_json("/api/review", params))
        return json.dumps({"result": _summarize_reviews(items or [])})
    except Exception as e:
        logger.error("frigate_reviews error: %s", e)
        return tool_error(f"Failed to list Frigate review items: {e}")


def _handle_snapshot(args: dict, **kw) -> str:
    """Handler for frigate_snapshot tool."""
    event_id = args.get("event_id", "")
    camera = args.get("camera", "")
    if bool(event_id) == bool(camera):
        return tool_error("Provide exactly one of: event_id or camera")

    if event_id:
        if not _EVENT_ID_RE.match(event_id):
            return tool_error(f"Invalid event_id format: {event_id}")
        path = f"/api/events/{event_id}/snapshot.jpg"
        dest_name = f"event_{event_id.replace('.', '_')}.jpg"
    else:
        if not _NAME_RE.match(camera):
            return tool_error(f"Invalid camera format: {camera}")
        path = f"/api/{camera}/latest.jpg"
        dest_name = f"latest_{camera}_{int(time.time())}.jpg"

    try:
        result = _run_async(_async_download(path, dest_name, _MAX_SNAPSHOT_BYTES))
        result["note"] = "Pass this path to vision_analyze to inspect the image."
        return json.dumps({"result": result})
    except Exception as e:
        logger.error("frigate_snapshot error: %s", e)
        return tool_error(f"Failed to fetch snapshot: {e}")


def _handle_clip(args: dict, **kw) -> str:
    """Handler for frigate_clip tool."""
    event_id = args.get("event_id", "")
    if not event_id:
        return tool_error("Missing required parameter: event_id")
    if not _EVENT_ID_RE.match(event_id):
        return tool_error(f"Invalid event_id format: {event_id}")

    dest_name = f"clip_{event_id.replace('.', '_')}.mp4"
    try:
        result = _run_async(
            _async_download(
                f"/api/events/{event_id}/clip.mp4", dest_name, _MAX_CLIP_BYTES
            )
        )
        result["note"] = (
            "Pass this path to video_analyze, or sample frames with ffmpeg "
            "and use vision_analyze per frame."
        )
        return json.dumps({"result": result})
    except Exception as e:
        logger.error("frigate_clip error: %s", e)
        return tool_error(f"Failed to fetch clip: {e}")


def _handle_status(args: dict, **kw) -> str:
    """Handler for frigate_status tool."""
    try:
        stats = _run_async(_async_get_json("/api/stats"))
        return json.dumps({"result": _summarize_stats(stats or {})})
    except Exception as e:
        logger.error("frigate_status error: %s", e)
        return tool_error(f"Failed to fetch Frigate stats: {e}")


# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------


def _check_frigate_available() -> bool:
    """Tools are only available when FRIGATE_URL is set."""
    return bool(os.getenv("FRIGATE_URL"))


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

FRIGATE_EVENTS_SCHEMA = {
    "name": "frigate_events",
    "description": (
        "Search Frigate NVR tracked-object events (person/car/etc. detections). "
        "Filter by camera, label, zone, or a unix-time window. Returns compact "
        "event records whose IDs work with frigate_snapshot and frigate_clip."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "camera": {"type": "string", "description": "Camera name to filter by (e.g. 'front_door')."},
            "label": {"type": "string", "description": "Object label to filter by (e.g. 'person', 'car', 'dog')."},
            "zone": {"type": "string", "description": "Zone name to filter by (e.g. 'driveway')."},
            "after": {"type": "number", "description": "Only events starting after this unix timestamp."},
            "before": {"type": "number", "description": "Only events starting before this unix timestamp."},
            "has_clip": {"type": "boolean", "description": "Only events that have a recorded clip."},
            "has_snapshot": {"type": "boolean", "description": "Only events that have a snapshot."},
            "in_progress": {"type": "boolean", "description": "Only events still in progress."},
            "limit": {"type": "integer", "description": "Max events to return (default 20)."},
        },
        "required": [],
    },
}

FRIGATE_REVIEWS_SCHEMA = {
    "name": "frigate_reviews",
    "description": (
        "List Frigate review items — the curated activity queue. Severity "
        "'alert' items are the important ones; 'detection' items are routine. "
        "Each item groups one or more event IDs (in 'detections') usable with "
        "frigate_events, frigate_snapshot, and frigate_clip."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "severity": {"type": "string", "enum": ["alert", "detection"], "description": "Filter by severity."},
            "cameras": {"type": "string", "description": "Comma-separated camera names (e.g. 'front_door,back_yard')."},
            "labels": {"type": "string", "description": "Comma-separated object labels (e.g. 'person,car')."},
            "zones": {"type": "string", "description": "Comma-separated zone names."},
            "reviewed": {"type": "boolean", "description": "Include already-reviewed items (default false)."},
            "after": {"type": "number", "description": "Only items after this unix timestamp."},
            "before": {"type": "number", "description": "Only items before this unix timestamp."},
            "limit": {"type": "integer", "description": "Max items to return (default 20)."},
        },
        "required": [],
    },
}

FRIGATE_SNAPSHOT_SCHEMA = {
    "name": "frigate_snapshot",
    "description": (
        "Download a Frigate snapshot to a local file: either the best snapshot "
        "of a tracked-object event (by event_id) or the latest frame from a "
        "camera (by camera name). Returns a local path to pass to vision_analyze."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "event_id": {"type": "string", "description": "Event ID from frigate_events/frigate_reviews (e.g. '1718987128.947436-g92ztx')."},
            "camera": {"type": "string", "description": "Camera name for a live latest-frame snapshot instead of an event snapshot."},
        },
        "required": [],
    },
}

FRIGATE_CLIP_SCHEMA = {
    "name": "frigate_clip",
    "description": (
        "Download the recorded clip (mp4, max 50MB) of a Frigate event to a "
        "local file. Returns a local path to pass to video_analyze."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "event_id": {"type": "string", "description": "Event ID from frigate_events/frigate_reviews."},
        },
        "required": ["event_id"],
    },
}

FRIGATE_STATUS_SCHEMA = {
    "name": "frigate_status",
    "description": (
        "Get Frigate service status: version, uptime, per-camera FPS health, "
        "and detector inference speeds. Use to diagnose a camera that stopped "
        "detecting or to confirm Frigate is reachable."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

from tools.registry import registry, tool_error

registry.register(
    name="frigate_events",
    toolset="frigate",
    schema=FRIGATE_EVENTS_SCHEMA,
    handler=_handle_events,
    check_fn=_check_frigate_available,
    emoji="📹",
)

registry.register(
    name="frigate_reviews",
    toolset="frigate",
    schema=FRIGATE_REVIEWS_SCHEMA,
    handler=_handle_reviews,
    check_fn=_check_frigate_available,
    emoji="📹",
)

registry.register(
    name="frigate_snapshot",
    toolset="frigate",
    schema=FRIGATE_SNAPSHOT_SCHEMA,
    handler=_handle_snapshot,
    check_fn=_check_frigate_available,
    emoji="📹",
)

registry.register(
    name="frigate_clip",
    toolset="frigate",
    schema=FRIGATE_CLIP_SCHEMA,
    handler=_handle_clip,
    check_fn=_check_frigate_available,
    emoji="📹",
)

registry.register(
    name="frigate_status",
    toolset="frigate",
    schema=FRIGATE_STATUS_SCHEMA,
    handler=_handle_status,
    check_fn=_check_frigate_available,
    emoji="📹",
)
