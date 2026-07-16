"""Secret-safe, bounded DTO builders for Desktop Live View events."""

from __future__ import annotations

import json
import re


_LIVE_VIEW_TEXT_MAX_CHARS = 1_024
_LIVE_VIEW_URL_MAX_CHARS = 2_048
_LIVE_VIEW_RESULT_PARSE_MAX_CHARS = 64_000
_LIVE_VIEW_IMAGE_MAX_CHARS = 2_000_000
_LIVE_VIEW_IMAGE_ENVELOPE_MAX_CHARS = 256_000
_LIVE_VIEW_IMAGE_PREFIXES = (
    "data:image/jpeg;base64,",
    "data:image/png;base64,",
)


def _live_view_bounded_text(value: object, *, max_chars: int) -> str | None:
    """Return a force-redacted, bounded display string."""
    if not isinstance(value, str):
        return None
    # Bound before redaction so a malformed tool cannot make this event path
    # scan/copy an unbounded title or URL.
    text = value[:max_chars].strip()
    if not text:
        return None
    try:
        from agent.redact import redact_sensitive_text

        text = redact_sensitive_text(text, force=True)
    except Exception:
        return None
    return text[:max_chars] or None


def _live_view_result_record(result: object) -> dict | None:
    """Parse only bounded JSON results; large browser snapshots stay opaque."""
    if isinstance(result, dict):
        return result
    if not isinstance(result, str) or len(result) > _LIVE_VIEW_RESULT_PARSE_MAX_CHARS:
        return None
    try:
        parsed = json.loads(result)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _live_view_result_records(record: dict | None) -> list[dict]:
    """Return the few known structured result envelopes, without deep walking."""
    if record is None:
        return []
    records = [record]
    for key in ("data", "result", "meta", "structuredContent"):
        nested = record.get(key)
        if isinstance(nested, dict):
            records.append(nested)
    return records


def _live_view_json_string_from_prefix(
    result: object,
    keys: tuple[str, ...],
    *,
    max_chars: int,
) -> str | None:
    """Read a short JSON string field from a bounded large-result prefix.

    Browser navigate results put title/url before their potentially large
    accessibility snapshot. This preserves those fields without materialising
    the full JSON object or serialising the snapshot into a websocket event.
    """
    if not isinstance(result, str):
        return None
    prefix = result[:_LIVE_VIEW_RESULT_PARSE_MAX_CHARS]
    for key in keys:
        match = re.search(
            rf'"{re.escape(key)}"\s*:\s*("(?:\\.|[^"\\])*")',
            prefix,
        )
        if match is None or len(match.group(1)) > max_chars * 6:
            continue
        try:
            value = json.loads(match.group(1))
        except Exception:
            continue
        bounded = _live_view_bounded_text(value, max_chars=max_chars)
        if bounded:
            return bounded
    return None


def _live_view_first_record_string(
    records: list[dict],
    keys: tuple[str, ...],
    *,
    max_chars: int,
) -> str | None:
    for record in records:
        for key in keys:
            bounded = _live_view_bounded_text(record.get(key), max_chars=max_chars)
            if bounded:
                return bounded
    return None


def _live_view_result_status(result: object, records: list[dict]) -> str:
    for record in records:
        raw_status = record.get("status")
        status = (
            raw_status[:64].strip().lower() if isinstance(raw_status, str) else ""
        )
        if record.get("success") is False or record.get("isError") is True:
            return "error"
        if record.get("error") not in (None, False, "", {}, []):
            return "error"
        if status in {"cancelled", "error", "failed", "failure"}:
            return "error"

    if isinstance(result, str):
        prefix = result[:_LIVE_VIEW_RESULT_PARSE_MAX_CHARS]
        if re.search(r'"success"\s*:\s*false\b', prefix, re.IGNORECASE):
            return "error"
        if re.search(
            r'"status"\s*:\s*"(?:cancelled|error|failed|failure)"',
            prefix,
            re.IGNORECASE,
        ):
            return "error"
    return "complete"


def _accepted_live_view_image(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if len(value) > _LIVE_VIEW_IMAGE_MAX_CHARS:
        return None
    return value if value.startswith(_LIVE_VIEW_IMAGE_PREFIXES) else None


def _live_view_image_from_value(value: object, *, depth: int = 0) -> str | None:
    """Find one accepted image through known in-memory result envelopes."""
    if depth > 4:
        return None
    accepted = _accepted_live_view_image(value)
    if accepted:
        return accepted
    if isinstance(value, list):
        for item in value[:16]:
            found = _live_view_image_from_value(item, depth=depth + 1)
            if found:
                return found
        return None
    if not isinstance(value, dict):
        return None

    direct_url = value.get("url")
    accepted = _accepted_live_view_image(direct_url)
    if accepted:
        return accepted
    for key in ("image_url", "imageUrl", "content", "image", "screenshot"):
        if key not in value:
            continue
        found = _live_view_image_from_value(value[key], depth=depth + 1)
        if found:
            return found
    return None


def _live_view_image_from_result(result: object, record: dict | None) -> str | None:
    """Extract one capped image without parsing a large serialized result."""
    if record is not None:
        found = _live_view_image_from_value(record)
        if found:
            return found
    if not isinstance(result, str):
        return None

    # A serialized multimodal Computer Use result normally exceeds the JSON
    # parse budget because the screenshot itself is hundreds of KB. Base64
    # cannot contain a quote, so locate and slice only the first bounded data
    # URL rather than materialising the surrounding result object.
    scan_end = min(
        len(result),
        _LIVE_VIEW_IMAGE_MAX_CHARS + _LIVE_VIEW_IMAGE_ENVELOPE_MAX_CHARS,
    )
    for prefix in _LIVE_VIEW_IMAGE_PREFIXES:
        start = result.find(prefix, 0, scan_end)
        if start < 0:
            continue
        end = result.find(
            '"', start, min(scan_end, start + _LIVE_VIEW_IMAGE_MAX_CHARS + 1)
        )
        if end < 0:
            continue
        accepted = _accepted_live_view_image(result[start:end])
        if accepted:
            return accepted
    return None


def build_visual_start_payload(tool_call_id: str, name: str, args: dict) -> dict:
    """Build the narrow visual.start DTO without free-form typed input."""
    payload: dict[str, object] = {
        "tool_id": tool_call_id,
        "name": name,
        "status": "running",
    }
    safe_args: dict[str, str] = {}
    if name == "browser_navigate":
        url = _live_view_bounded_text(
            args.get("url") if isinstance(args, dict) else None,
            max_chars=_LIVE_VIEW_URL_MAX_CHARS,
        )
        if url:
            payload["url"] = url
            safe_args["url"] = url
    elif name == "computer_use" and isinstance(args, dict):
        action = str(args.get("action") or "").strip().lower()
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", action):
            safe_args["action"] = action
        for key in ("app", "window"):
            value = _live_view_bounded_text(
                args.get(key), max_chars=_LIVE_VIEW_TEXT_MAX_CHARS
            )
            if value:
                safe_args[key] = value
    if safe_args:
        # Reconstructed from an explicit allow-list; never the raw tool args.
        payload["args"] = safe_args
    return payload


def build_visual_complete_payload(
    tool_call_id: str,
    name: str,
    args: dict,
    result: object,
    duration_s: float | None,
) -> dict:
    """Build the narrow visual.complete DTO from explicit allow-lists only."""
    record = _live_view_result_record(result)
    records = _live_view_result_records(record)
    status = _live_view_result_status(result, records)
    window_title = _live_view_first_record_string(
        records,
        ("window_title", "windowTitle"),
        max_chars=_LIVE_VIEW_TEXT_MAX_CHARS,
    ) or _live_view_json_string_from_prefix(
        result,
        ("window_title", "windowTitle"),
        max_chars=_LIVE_VIEW_TEXT_MAX_CHARS,
    )
    title = _live_view_first_record_string(
        records,
        ("title",),
        max_chars=_LIVE_VIEW_TEXT_MAX_CHARS,
    ) or _live_view_json_string_from_prefix(
        result,
        ("title",),
        max_chars=_LIVE_VIEW_TEXT_MAX_CHARS,
    )
    title = title or window_title
    app = _live_view_first_record_string(
        records,
        ("app",),
        max_chars=_LIVE_VIEW_TEXT_MAX_CHARS,
    ) or _live_view_json_string_from_prefix(
        result,
        ("app",),
        max_chars=_LIVE_VIEW_TEXT_MAX_CHARS,
    )
    url = _live_view_first_record_string(
        records,
        ("url",),
        max_chars=_LIVE_VIEW_URL_MAX_CHARS,
    ) or _live_view_json_string_from_prefix(
        result,
        ("url",),
        max_chars=_LIVE_VIEW_URL_MAX_CHARS,
    )
    if url is None and name == "browser_navigate" and isinstance(args, dict):
        url = _live_view_bounded_text(
            args.get("url"), max_chars=_LIVE_VIEW_URL_MAX_CHARS
        )

    payload: dict[str, object] = {
        "tool_id": tool_call_id,
        "name": name,
        "status": status,
    }
    if duration_s is not None:
        payload["duration_s"] = duration_s
    if title:
        payload["title"] = title
    if app:
        payload["app"] = app
    if window_title:
        payload["window_title"] = window_title
    if url:
        payload["url"] = url

    # Keep the existing renderer contract (`payload.result`) while rebuilding
    # it exclusively from whitelisted scalar fields. Browser screenshots and
    # arbitrary tool output never enter this DTO.
    safe_result: dict[str, object] = {
        "status": status,
        "success": status != "error",
    }
    if title:
        safe_result["title"] = title
    if app:
        safe_result["app"] = app
    if window_title:
        safe_result["window_title"] = window_title
    if url:
        safe_result["url"] = url
    if name == "computer_use":
        image = _live_view_image_from_result(result, record)
        if image:
            safe_result["content"] = [
                {"type": "image_url", "image_url": {"url": image}}
            ]
    payload["result"] = safe_result
    return payload
