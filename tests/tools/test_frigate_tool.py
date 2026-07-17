"""Tests for the Frigate NVR tool module.

Tests real logic: query-param building, response summarization, handler
validation (path-traversal guards on event_id/camera), and availability
gating.
"""

import json
from unittest.mock import patch

import pytest

from tools.frigate_tool import (
    _EVENT_ID_RE,
    _NAME_LIST_RE,
    _NAME_RE,
    _build_event_params,
    _build_review_params,
    _check_frigate_available,
    _get_headers,
    _handle_clip,
    _handle_snapshot,
    _summarize_events,
    _summarize_reviews,
    _summarize_stats,
)


# ---------------------------------------------------------------------------
# Sample payloads (match real Frigate /api/events, /api/review, /api/stats)
# ---------------------------------------------------------------------------

SAMPLE_EVENTS = [
    {
        "id": "1718987128.947436-g92ztx",
        "camera": "front_door",
        "label": "person",
        "sub_label": None,
        "start_time": 1718987128.9,
        "end_time": 1718987158.2,
        "zones": ["porch"],
        "has_clip": True,
        "has_snapshot": True,
        "thumbnail": "iVBORw0KGgo" * 500,  # base64 blob that must be stripped
        "data": {"top_score": 0.87},
    },
    {
        "id": "1718987222.123456-ab12cd",
        "camera": "driveway",
        "label": "car",
        "start_time": 1718987222.1,
        "end_time": None,
        "zones": [],
        "has_clip": False,
        "has_snapshot": True,
        "data": {"top_score": 0.71, "recognized_license_plate": "ABC123"},
    },
]

SAMPLE_REVIEWS = [
    {
        "id": "1718987129.308396-fqk5ka",
        "camera": "front_cam",
        "start_time": 1718987129.3,
        "end_time": 1718987174.9,
        "severity": "alert",
        "has_been_reviewed": False,
        "thumb_path": "/media/frigate/clips/review/thumb-front_cam.webp",
        "data": {
            "detections": ["1718987128.947436-g92ztx"],
            "objects": ["person", "car"],
            "sub_labels": ["Bob"],
            "zones": ["front_yard"],
            "audio": [],
        },
    },
]

SAMPLE_STATS = {
    "service": {"version": "0.16.1", "uptime": 123456},
    "cameras": {
        "front_door": {
            "camera_fps": 5.1,
            "detection_fps": 5.0,
            "process_fps": 5.1,
            "skipped_fps": 0.0,
            "pid": 123,
        },
    },
    "detectors": {"coral": {"inference_speed": 9.2, "detection_start": 0.0}},
}


# ---------------------------------------------------------------------------
# Validation regexes
# ---------------------------------------------------------------------------


class TestValidationPatterns:
    def test_event_id_valid(self):
        assert _EVENT_ID_RE.match("1718987128.947436-g92ztx")

    def test_event_id_rejects_traversal(self):
        assert not _EVENT_ID_RE.match("../../config")
        assert not _EVENT_ID_RE.match("1718987128.947436-g92ztx/../x")
        assert not _EVENT_ID_RE.match("")

    def test_name_valid(self):
        assert _NAME_RE.match("front_door")
        assert _NAME_RE.match("cam-2")

    def test_name_rejects_separators(self):
        assert not _NAME_RE.match("front/door")
        assert not _NAME_RE.match("a b")
        assert not _NAME_RE.match("a.b")

    def test_name_list(self):
        assert _NAME_LIST_RE.match("front,back")
        assert _NAME_LIST_RE.match("front")
        assert not _NAME_LIST_RE.match("front,,back")
        assert not _NAME_LIST_RE.match(",front")
        assert not _NAME_LIST_RE.match("front/back")


# ---------------------------------------------------------------------------
# Param builders
# ---------------------------------------------------------------------------


class TestBuildEventParams:
    def test_defaults(self):
        assert _build_event_params({}) == {"limit": 20}

    def test_full(self):
        params = _build_event_params(
            {
                "camera": "front_door",
                "label": "person",
                "zone": "porch",
                "after": 1718987000,
                "before": "1718988000",
                "has_clip": True,
                "has_snapshot": "false",
                "in_progress": "true",
                "limit": 5,
            }
        )
        assert params == {
            "limit": 5,
            "camera": "front_door",
            "label": "person",
            "zone": "porch",
            "after": 1718987000.0,
            "before": 1718988000.0,
            "has_clip": 1,
            "has_snapshot": 0,
            "in_progress": 1,
        }

    def test_invalid_camera_raises(self):
        with pytest.raises(ValueError):
            _build_event_params({"camera": "../evil"})

    def test_invalid_label_raises(self):
        with pytest.raises(ValueError):
            _build_event_params({"label": "person car"})

    def test_bad_timestamp_raises(self):
        with pytest.raises(ValueError):
            _build_event_params({"after": "yesterday"})


class TestBuildReviewParams:
    def test_defaults(self):
        assert _build_review_params({}) == {"limit": 20}

    def test_full(self):
        params = _build_review_params(
            {
                "severity": "alert",
                "cameras": "front,back",
                "labels": "person",
                "zones": "yard",
                "reviewed": True,
                "after": 1.0,
                "limit": 3,
            }
        )
        assert params == {
            "limit": 3,
            "severity": "alert",
            "cameras": "front,back",
            "labels": "person",
            "zones": "yard",
            "reviewed": 1,
            "after": 1.0,
        }

    def test_invalid_severity_raises(self):
        with pytest.raises(ValueError):
            _build_review_params({"severity": "urgent"})

    def test_invalid_camera_list_raises(self):
        with pytest.raises(ValueError):
            _build_review_params({"cameras": "front;back"})


# ---------------------------------------------------------------------------
# Summarizers
# ---------------------------------------------------------------------------


class TestSummarizeEvents:
    def test_strips_thumbnail(self):
        result = _summarize_events(SAMPLE_EVENTS)
        assert result["count"] == 2
        for e in result["events"]:
            assert "thumbnail" not in e

    def test_keeps_key_fields(self):
        result = _summarize_events(SAMPLE_EVENTS)
        first = result["events"][0]
        assert first["id"] == "1718987128.947436-g92ztx"
        assert first["camera"] == "front_door"
        assert first["label"] == "person"
        assert first["zones"] == ["porch"]
        assert first["has_clip"] is True
        assert first["top_score"] == 0.87

    def test_license_plate_surfaced(self):
        result = _summarize_events(SAMPLE_EVENTS)
        assert result["events"][1]["recognized_license_plate"] == "ABC123"

    def test_empty(self):
        assert _summarize_events([]) == {"count": 0, "events": []}


class TestSummarizeReviews:
    def test_fields(self):
        result = _summarize_reviews(SAMPLE_REVIEWS)
        assert result["count"] == 1
        item = result["reviews"][0]
        assert item["severity"] == "alert"
        assert item["objects"] == ["person", "car"]
        assert item["detections"] == ["1718987128.947436-g92ztx"]
        assert item["sub_labels"] == ["Bob"]
        # thumb_path is a server-side path, not useful to the model
        assert "thumb_path" not in item


class TestSummarizeStats:
    def test_fields(self):
        result = _summarize_stats(SAMPLE_STATS)
        assert result["version"] == "0.16.1"
        assert result["cameras"]["front_door"]["camera_fps"] == 5.1
        assert result["detectors"]["coral"]["inference_speed"] == 9.2
        # pid and other noise dropped
        assert "pid" not in result["cameras"]["front_door"]

    def test_empty(self):
        result = _summarize_stats({})
        assert result["cameras"] == {}
        assert result["detectors"] == {}


# ---------------------------------------------------------------------------
# Headers / auth
# ---------------------------------------------------------------------------


class TestHeaders:
    def test_no_token_no_auth_header(self):
        with patch.dict("os.environ", {"FRIGATE_URL": "http://f:5000"}, clear=False):
            with patch.dict("os.environ", {"FRIGATE_TOKEN": ""}, clear=False):
                headers = _get_headers()
        assert "Authorization" not in headers

    def test_token_sets_bearer(self):
        headers = _get_headers("jwt123")
        assert headers["Authorization"] == "Bearer jwt123"


# ---------------------------------------------------------------------------
# Handler validation (no network)
# ---------------------------------------------------------------------------


class TestHandlerValidation:
    def test_snapshot_requires_exactly_one_target(self):
        result = json.loads(_handle_snapshot({}))
        assert "error" in result
        result = json.loads(
            _handle_snapshot({"event_id": "1.2-abc", "camera": "front"})
        )
        assert "error" in result

    def test_snapshot_rejects_bad_event_id(self):
        result = json.loads(_handle_snapshot({"event_id": "../../etc/passwd"}))
        assert "error" in result

    def test_snapshot_rejects_bad_camera(self):
        result = json.loads(_handle_snapshot({"camera": "front/../admin"}))
        assert "error" in result

    def test_clip_requires_event_id(self):
        result = json.loads(_handle_clip({}))
        assert "error" in result

    def test_clip_rejects_bad_event_id(self):
        result = json.loads(_handle_clip({"event_id": "abc"}))
        assert "error" in result


# ---------------------------------------------------------------------------
# Availability gating
# ---------------------------------------------------------------------------


class TestAvailability:
    def test_unavailable_without_url(self):
        with patch.dict("os.environ", {}, clear=True):
            assert _check_frigate_available() is False

    def test_available_with_url(self):
        with patch.dict(
            "os.environ", {"FRIGATE_URL": "http://frigate.local:5000"}, clear=True
        ):
            assert _check_frigate_available() is True
