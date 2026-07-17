"""Tests for the Frigate gateway platform adapter.

Tests real logic: review-item selection (severity filter, escalation,
camera watch/ignore lists), cooldown behavior, message formatting,
MQTT connect kwargs, env enablement, and requirement gating.
"""

import time
from unittest.mock import patch

import pytest

from gateway.config import Platform, PlatformConfig
from plugins.platforms.frigate.adapter import (
    DEFAULT_REPLY_TOPIC,
    FrigateAdapter,
    _env_enablement,
    _mqtt_connect_kwargs,
    check_frigate_requirements,
)


def make_adapter(**extra) -> FrigateAdapter:
    config = PlatformConfig(enabled=True, extra=extra)
    return FrigateAdapter(config)


REVIEW_AFTER = {
    "id": "1718987129.308396-fqk5ka",
    "camera": "front_cam",
    "severity": "alert",
    "start_time": 1718987129.3,
    "end_time": None,
    "data": {
        "detections": ["1718987128.947436-g92ztx"],
        "objects": ["person"],
        "sub_labels": [],
        "zones": ["front_yard"],
        "audio": [],
    },
}


def payload(msg_type="new", after=None, before=None):
    return {"type": msg_type, "after": after or dict(REVIEW_AFTER), "before": before or {}}


# ---------------------------------------------------------------------------
# check_frigate_requirements
# ---------------------------------------------------------------------------


class TestCheckRequirements:
    def test_false_without_broker_host(self, monkeypatch):
        monkeypatch.delenv("FRIGATE_MQTT_HOST", raising=False)
        assert check_frigate_requirements() is False

    @patch("plugins.platforms.frigate.adapter.AIOMQTT_AVAILABLE", True)
    def test_true_with_host_and_lib(self, monkeypatch):
        monkeypatch.setenv("FRIGATE_MQTT_HOST", "127.0.0.1")
        assert check_frigate_requirements() is True


# ---------------------------------------------------------------------------
# _select_review — filtering pipeline
# ---------------------------------------------------------------------------


class TestSelectReview:
    def test_new_alert_passes(self):
        adapter = make_adapter()
        assert adapter._select_review(payload("new")) is not None

    def test_new_detection_dropped_by_default(self):
        after = dict(REVIEW_AFTER, severity="detection")
        adapter = make_adapter()
        assert adapter._select_review(payload("new", after)) is None

    def test_new_detection_passes_in_detection_mode(self):
        after = dict(REVIEW_AFTER, severity="detection")
        adapter = make_adapter(watch_severity="detection")
        assert adapter._select_review(payload("new", after)) is not None

    def test_update_escalation_passes(self):
        before = dict(REVIEW_AFTER, severity="detection")
        adapter = make_adapter()
        assert adapter._select_review(payload("update", before=before)) is not None

    def test_update_without_escalation_dropped(self):
        before = dict(REVIEW_AFTER, severity="alert")
        adapter = make_adapter()
        assert adapter._select_review(payload("update", before=before)) is None

    def test_end_dropped(self):
        adapter = make_adapter()
        assert adapter._select_review(payload("end")) is None

    def test_ignored_camera_dropped(self):
        adapter = make_adapter(ignore_cameras=["front_cam"])
        assert adapter._select_review(payload("new")) is None

    def test_watch_list_excludes_other_cameras(self):
        adapter = make_adapter(watch_cameras=["back_yard"])
        assert adapter._select_review(payload("new")) is None

    def test_watch_list_includes_listed_camera(self):
        adapter = make_adapter(watch_cameras=["front_cam"])
        assert adapter._select_review(payload("new")) is not None

    def test_empty_after_dropped(self):
        adapter = make_adapter()
        assert adapter._select_review({"type": "new", "after": {}}) is None

    def test_non_dict_payload_dropped(self):
        adapter = make_adapter()
        assert adapter._select_review("garbage") is None


# ---------------------------------------------------------------------------
# _format_review
# ---------------------------------------------------------------------------


class TestFormatReview:
    def test_includes_camera_severity_objects(self):
        msg = FrigateAdapter._format_review(REVIEW_AFTER)
        assert "ALERT" in msg
        assert "front_cam" in msg
        assert "person" in msg
        assert "front_yard" in msg

    def test_includes_event_ids_and_tool_hint(self):
        msg = FrigateAdapter._format_review(REVIEW_AFTER)
        assert "1718987128.947436-g92ztx" in msg
        assert "frigate_snapshot" in msg

    def test_recognized_sub_labels(self):
        review = dict(REVIEW_AFTER)
        review["data"] = dict(REVIEW_AFTER["data"], sub_labels=["Bob"])
        msg = FrigateAdapter._format_review(review)
        assert "Bob" in msg

    def test_handles_missing_data(self):
        msg = FrigateAdapter._format_review({"camera": "x", "severity": "alert"})
        assert "x" in msg


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------


class TestCooldown:
    @pytest.mark.asyncio
    async def test_second_event_within_cooldown_dropped(self):
        adapter = make_adapter(cooldown_seconds=300)
        forwarded = []

        async def fake_handle(event):
            forwarded.append(event)

        adapter.handle_message = fake_handle

        class Msg:
            payload = __import__("json").dumps(payload("new")).encode()

        await adapter._handle_mqtt_message(Msg())
        await adapter._handle_mqtt_message(Msg())
        assert len(forwarded) == 1

    @pytest.mark.asyncio
    async def test_cooldown_expiry_allows_next(self):
        adapter = make_adapter(cooldown_seconds=300)
        forwarded = []

        async def fake_handle(event):
            forwarded.append(event)

        adapter.handle_message = fake_handle

        class Msg:
            payload = __import__("json").dumps(payload("new")).encode()

        await adapter._handle_mqtt_message(Msg())
        adapter._last_event_time["front_cam"] = time.time() - 301
        await adapter._handle_mqtt_message(Msg())
        assert len(forwarded) == 2


# ---------------------------------------------------------------------------
# Config plumbing
# ---------------------------------------------------------------------------


class TestConfig:
    def test_mqtt_kwargs_from_extra(self):
        kwargs = _mqtt_connect_kwargs(
            {"mqtt_host": "broker", "mqtt_port": 1884, "mqtt_username": "u", "mqtt_password": "p"}
        )
        assert kwargs == {"hostname": "broker", "port": 1884, "username": "u", "password": "p"}

    def test_mqtt_kwargs_env_fallback(self, monkeypatch):
        monkeypatch.setenv("FRIGATE_MQTT_HOST", "envbroker")
        monkeypatch.delenv("FRIGATE_MQTT_PORT", raising=False)
        monkeypatch.delenv("FRIGATE_MQTT_USERNAME", raising=False)
        kwargs = _mqtt_connect_kwargs({})
        assert kwargs == {"hostname": "envbroker", "port": 1883}

    def test_platform_enum_accepts_frigate(self):
        assert Platform("frigate") is Platform("frigate")

    def test_adapter_defaults(self):
        adapter = make_adapter()
        assert adapter._topic_prefix == "frigate"
        assert adapter._reply_topic == DEFAULT_REPLY_TOPIC
        assert adapter._watch_severity == "alert"
        assert adapter._cooldown_seconds == 60

    def test_topic_prefix_override(self, monkeypatch):
        monkeypatch.delenv("FRIGATE_MQTT_TOPIC_PREFIX", raising=False)
        adapter = make_adapter(topic_prefix="cctv")
        assert adapter._topic_prefix == "cctv"

    def test_env_enablement_none_without_host(self, monkeypatch):
        monkeypatch.delenv("FRIGATE_MQTT_HOST", raising=False)
        assert _env_enablement() is None

    def test_env_enablement_seed(self, monkeypatch):
        monkeypatch.setenv("FRIGATE_MQTT_HOST", "10.0.0.5")
        monkeypatch.setenv("FRIGATE_MQTT_PORT", "1884")
        monkeypatch.setenv("FRIGATE_MQTT_TOPIC_PREFIX", "cctv")
        seed = _env_enablement()
        assert seed == {"mqtt_host": "10.0.0.5", "mqtt_port": "1884", "topic_prefix": "cctv"}
