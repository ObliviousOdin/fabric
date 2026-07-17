"""
Frigate NVR platform adapter.

Connects to the MQTT broker Frigate publishes to and subscribes to the
``<prefix>/reviews`` topic — Frigate's curated review queue, where each item
groups one or more tracked-object events with a severity of ``alert`` or
``detection``.  Matching review items are converted to MessageEvent objects
and forwarded to the agent, which can then pull media with the ``frigate``
toolset (frigate_snapshot / frigate_clip) and analyze it with vision tools.

The raw ``<prefix>/events`` topic (per-object lifecycle) is intentionally
NOT subscribed by default: it fires on every tracked-object update and would
flood the agent. Set ``watch_severity: detection`` in the platform config
extra to also receive routine detections; alerts-only is the default.

Requires:
- aiomqtt (lazy-installed via tools.lazy_deps on first use)
- FRIGATE_MQTT_HOST env var (broker host)
- Optional: FRIGATE_MQTT_PORT / FRIGATE_MQTT_USERNAME / FRIGATE_MQTT_PASSWORD /
  FRIGATE_MQTT_TOPIC_PREFIX
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Set

try:
    import aiomqtt

    AIOMQTT_AVAILABLE = True
except ImportError:
    AIOMQTT_AVAILABLE = False
    aiomqtt = None  # type: ignore[assignment]

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
)

logger = logging.getLogger(__name__)

DEFAULT_PORT = 1883
DEFAULT_TOPIC_PREFIX = "frigate"
DEFAULT_REPLY_TOPIC = "fabric/frigate/notifications"
DEFAULT_COOLDOWN_SECONDS = 60
MAX_MESSAGE_LENGTH = 4096

# Review payloads are small JSON; anything huge is not a review message.
_MAX_PAYLOAD_BYTES = 256 * 1024


def check_frigate_requirements() -> bool:
    """Check if MQTT dependencies are available and the broker is configured.

    Lazy-installs aiomqtt via ``tools.lazy_deps.ensure("platform.frigate")``
    on first call if not present. After a successful install, re-binds the
    module global so ``AIOMQTT_AVAILABLE`` becomes True.
    """
    global AIOMQTT_AVAILABLE, aiomqtt
    if not os.getenv("FRIGATE_MQTT_HOST"):
        return False
    if AIOMQTT_AVAILABLE:
        return True
    try:
        from tools.lazy_deps import ensure as _lazy_ensure

        _lazy_ensure("platform.frigate", prompt=False)
    except Exception:
        return False
    try:
        import aiomqtt as _aiomqtt
    except ImportError:
        return False
    aiomqtt = _aiomqtt
    AIOMQTT_AVAILABLE = True
    return True


def _mqtt_connect_kwargs(extra: Dict[str, Any]) -> Dict[str, Any]:
    """Build aiomqtt.Client kwargs from config extra + env fallbacks."""
    host = extra.get("mqtt_host") or os.getenv("FRIGATE_MQTT_HOST", "")
    port = int(extra.get("mqtt_port") or os.getenv("FRIGATE_MQTT_PORT", DEFAULT_PORT))
    username = extra.get("mqtt_username") or os.getenv("FRIGATE_MQTT_USERNAME", "")
    password = extra.get("mqtt_password") or os.getenv("FRIGATE_MQTT_PASSWORD", "")
    kwargs: Dict[str, Any] = {"hostname": host, "port": port}
    if username:
        kwargs["username"] = username
        kwargs["password"] = password or None
    return kwargs


class FrigateAdapter(BasePlatformAdapter):
    """
    Frigate MQTT review-queue adapter.

    Subscribes to ``<prefix>/reviews`` and forwards review items as
    MessageEvent objects. Supports severity filtering, camera watch/ignore
    lists, and per-camera cooldowns.
    """

    MAX_MESSAGE_LENGTH = MAX_MESSAGE_LENGTH

    # Reconnection backoff schedule (seconds)
    _BACKOFF_STEPS = [5, 10, 30, 60]

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform("frigate"))

        self._listen_task: Optional[asyncio.Task] = None

        extra = config.extra or {}
        self._extra: Dict[str, Any] = dict(extra)
        self._topic_prefix: str = (
            extra.get("topic_prefix")
            or os.getenv("FRIGATE_MQTT_TOPIC_PREFIX", DEFAULT_TOPIC_PREFIX)
        ).strip("/")
        self._reply_topic: str = extra.get("reply_topic") or DEFAULT_REPLY_TOPIC

        # Event filtering.
        # watch_severity: "alert" (default) forwards alerts only;
        # "detection" forwards both alerts and routine detections.
        self._watch_severity: str = str(extra.get("watch_severity", "alert")).lower()
        self._watch_cameras: Set[str] = set(extra.get("watch_cameras", []))
        self._ignore_cameras: Set[str] = set(extra.get("ignore_cameras", []))
        self._cooldown_seconds: int = int(
            extra.get("cooldown_seconds", DEFAULT_COOLDOWN_SECONDS)
        )

        # Cooldown tracking: camera -> last_forwarded_timestamp
        self._last_event_time: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        """Start the MQTT listener loop."""
        if not check_frigate_requirements():
            logger.warning(
                "[%s] aiomqtt not installed or FRIGATE_MQTT_HOST not set. "
                "Run: pip install aiomqtt",
                self.name,
            )
            return False

        self._running = True
        self._listen_task = asyncio.create_task(self._listen_loop())
        logger.info(
            "[%s] Listening for %s/reviews on %s",
            self.name,
            self._topic_prefix,
            _mqtt_connect_kwargs(self._extra).get("hostname"),
        )
        return True

    async def disconnect(self) -> None:
        """Stop the MQTT listener."""
        self._running = False
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None
        logger.info("[%s] Disconnected", self.name)

    # ------------------------------------------------------------------
    # Event listener
    # ------------------------------------------------------------------

    async def _listen_loop(self) -> None:
        """Main MQTT loop with automatic reconnection."""
        backoff_idx = 0
        topic = f"{self._topic_prefix}/reviews"

        while self._running:
            try:
                async with aiomqtt.Client(**_mqtt_connect_kwargs(self._extra)) as client:
                    await client.subscribe(topic)
                    backoff_idx = 0
                    logger.info("[%s] Subscribed to %s", self.name, topic)
                    async for message in client.messages:
                        if not self._running:
                            return
                        await self._handle_mqtt_message(message)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("[%s] MQTT error: %s", self.name, e)

            if not self._running:
                return

            delay = self._BACKOFF_STEPS[min(backoff_idx, len(self._BACKOFF_STEPS) - 1)]
            logger.info("[%s] Reconnecting in %ds...", self.name, delay)
            await asyncio.sleep(delay)
            backoff_idx += 1

    async def _handle_mqtt_message(self, message) -> None:
        """Parse one MQTT message and forward it if it passes the filters."""
        try:
            raw = message.payload
            if raw is None or len(raw) > _MAX_PAYLOAD_BYTES:
                return
            payload = json.loads(raw)
        except (ValueError, TypeError):
            logger.debug("[%s] Non-JSON MQTT payload dropped", self.name)
            return

        review = self._select_review(payload)
        if review is None:
            return

        camera = review.get("camera", "")

        # Cooldown per camera
        now = time.time()
        if (now - self._last_event_time.get(camera, 0)) < self._cooldown_seconds:
            return
        self._last_event_time[camera] = now

        text = self._format_review(review)
        source = self.build_source(
            chat_id="frigate_events",
            chat_name="Frigate Camera Events",
            chat_type="channel",
            user_id="frigate",
            user_name="Frigate",
        )
        msg_event = MessageEvent(
            text=text,
            message_type=MessageType.TEXT,
            source=source,
            message_id=f"frigate_{review.get('id', uuid.uuid4().hex[:8])}",
            timestamp=datetime.now(),
        )
        await self.handle_message(msg_event)

    # ------------------------------------------------------------------
    # Filtering / formatting (pure logic — unit tested)
    # ------------------------------------------------------------------

    def _select_review(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return the review dict to forward, or None to drop the message.

        Forwards:
        - ``type: new`` items whose severity passes the severity filter
        - ``type: update`` items that escalated detection -> alert
        Drops ``type: end`` (the item is over) and everything filtered out.
        """
        if not isinstance(payload, dict):
            return None
        msg_type = payload.get("type")
        after = payload.get("after") or {}
        before = payload.get("before") or {}
        if not isinstance(after, dict) or not after:
            return None

        camera = after.get("camera", "")
        if camera in self._ignore_cameras:
            return None
        if self._watch_cameras and camera not in self._watch_cameras:
            return None

        severity = after.get("severity", "")
        if msg_type == "new":
            if severity == "alert":
                return after
            if severity == "detection" and self._watch_severity == "detection":
                return after
            return None
        if msg_type == "update":
            # Severity escalation is the one update worth waking the agent for.
            if before.get("severity") == "detection" and severity == "alert":
                return after
            return None
        return None

    @staticmethod
    def _format_review(review: Dict[str, Any]) -> str:
        """Convert a review item into an agent-readable event description."""
        camera = review.get("camera", "unknown")
        severity = review.get("severity", "unknown")
        data = review.get("data") or {}
        objects = ", ".join(data.get("objects", [])) or "activity"
        zones = ", ".join(data.get("zones", []))
        sub_labels = ", ".join(data.get("sub_labels", []))
        detections = data.get("detections", [])

        lines = [
            f"[Frigate] {severity.upper()}: {objects} on camera '{camera}'"
            + (f" in zones: {zones}" if zones else "")
        ]
        if sub_labels:
            lines.append(f"Recognized: {sub_labels}")
        if detections:
            lines.append(f"Event IDs: {', '.join(detections[:5])}")
            lines.append(
                "Use frigate_snapshot(event_id=...) then vision_analyze to "
                "inspect, or frigate_clip(event_id=...) for the recording."
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Outbound messaging
    # ------------------------------------------------------------------

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Publish a reply to the MQTT reply topic.

        Home Assistant automations (or anything else on the broker) can
        subscribe to ``fabric/frigate/notifications`` to consume agent
        output — e.g. to forward it as a phone notification.
        """
        if not AIOMQTT_AVAILABLE:
            return SendResult(success=False, error="aiomqtt not installed")
        payload = json.dumps(
            {
                "message": content[: self.MAX_MESSAGE_LENGTH],
                "chat_id": chat_id,
                "ts": time.time(),
            }
        )
        try:
            async with aiomqtt.Client(**_mqtt_connect_kwargs(self._extra)) as client:
                await client.publish(self._reply_topic, payload)
            return SendResult(success=True, message_id=uuid.uuid4().hex[:12])
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        """No typing indicator for MQTT."""

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """Return basic info about the Frigate event channel."""
        return {
            "name": "Frigate Camera Events",
            "type": "channel",
            "topic_prefix": self._topic_prefix,
        }


# ---------------------------------------------------------------------------
# Standalone (out-of-process) sender — used by cron deliver=frigate
# ---------------------------------------------------------------------------


async def _standalone_send(
    pconfig,
    chat_id: str,
    message: str,
    *,
    thread_id: Optional[str] = None,
    media_files: Optional[list] = None,
    force_document: bool = False,
) -> Dict[str, Any]:
    """Publish a message to the MQTT reply topic without a live adapter.

    Used by ``tools/send_message_tool._send_via_adapter`` when the gateway
    runner is not in this process (typical for cron jobs). ``thread_id``,
    ``media_files`` and ``force_document`` are accepted for signature parity
    with other standalone senders; MQTT has no threading or attachments.
    """
    if not check_frigate_requirements():
        return {"error": "aiomqtt not installed or FRIGATE_MQTT_HOST not set"}

    extra = getattr(pconfig, "extra", {}) or {}
    reply_topic = extra.get("reply_topic") or DEFAULT_REPLY_TOPIC
    payload = json.dumps(
        {"message": message[:MAX_MESSAGE_LENGTH], "chat_id": chat_id, "ts": time.time()}
    )
    try:
        async with aiomqtt.Client(**_mqtt_connect_kwargs(extra)) as client:
            await client.publish(reply_topic, payload)
        return {"success": True, "platform": "frigate", "chat_id": chat_id}
    except Exception as e:
        return {"error": f"Frigate MQTT send failed: {e}"}


# ---------------------------------------------------------------------------
# Env enablement / is_connected probes
# ---------------------------------------------------------------------------


def _env_enablement() -> Optional[dict]:
    """Seed ``PlatformConfig.extra`` from env vars during gateway config load.

    Returns None when the broker host isn't configured; the caller then
    skips auto-enabling the platform.
    """
    host = os.getenv("FRIGATE_MQTT_HOST", "").strip()
    if not host:
        return None
    seed: dict = {"mqtt_host": host}
    port = os.getenv("FRIGATE_MQTT_PORT", "").strip()
    if port:
        seed["mqtt_port"] = port
    prefix = os.getenv("FRIGATE_MQTT_TOPIC_PREFIX", "").strip()
    if prefix:
        seed["topic_prefix"] = prefix
    return seed


def _is_connected(config) -> bool:
    """Frigate is considered configured when FRIGATE_MQTT_HOST is set."""
    import fabric_cli.gateway as gateway_mod

    return bool((gateway_mod.get_env_value("FRIGATE_MQTT_HOST") or "").strip())


# ---------------------------------------------------------------------------
# Plugin registration entry point
# ---------------------------------------------------------------------------


def _build_adapter(config):
    """Factory wrapper that constructs FrigateAdapter from a PlatformConfig."""
    return FrigateAdapter(config)


def register(ctx) -> None:
    """Plugin entry point — called by the Hermes plugin system."""
    ctx.register_platform(
        name="frigate",
        label="Frigate",
        adapter_factory=_build_adapter,
        check_fn=check_frigate_requirements,
        is_connected=_is_connected,
        required_env=["FRIGATE_MQTT_HOST"],
        install_hint="pip install aiomqtt",
        env_enablement_fn=_env_enablement,
        # Out-of-process cron delivery via MQTT publish. Without this hook,
        # deliver=frigate cron jobs would fail with "No live adapter" when
        # cron runs separately from the gateway.
        standalone_sender_fn=_standalone_send,
        max_message_length=FrigateAdapter.MAX_MESSAGE_LENGTH,
        emoji="📹",
        platform_hint=(
            "You are receiving Frigate NVR camera events over MQTT. Each "
            "message describes a review item with event IDs. Use the frigate "
            "toolset (frigate_snapshot, frigate_clip, frigate_events) to pull "
            "media and vision_analyze/video_analyze to inspect it. Replies "
            "are published to an MQTT topic consumed by home automations — "
            "keep them concise and factual."
        ),
        allow_update_command=True,
    )
