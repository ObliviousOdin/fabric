"""Shared local publication seam for Fabric Remote Control.

The model-facing agent remains untouched. TUI gateway events and classic CLI
callbacks normalize into the same JSON-RPC event DTO, which a
``SessionEventHub`` can fan out without replacing the session's ``AIAgent`` or
changing model history.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tui_gateway.session_event_hub import SessionEventHub


def publication_event(
    event_type: str,
    session_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the transport-neutral event contract shared by local surfaces."""
    if not event_type:
        raise ValueError("event_type is required")
    if not session_id:
        raise ValueError("session_id is required")
    params: dict[str, Any] = {
        "type": event_type,
        "session_id": session_id,
    }
    if payload is not None:
        params["payload"] = payload
    return {"jsonrpc": "2.0", "method": "event", "params": params}


def compose_stream_delta_callback(
    *,
    session_id: str,
    event_hub: SessionEventHub,
    local_callback: Callable[[str | None], None] | None,
) -> Callable[[str | None], None]:
    """Preserve classic CLI rendering while publishing matching deltas.

    ``None`` is the existing classic callback's local turn-boundary sentinel;
    it is forwarded locally but is not a content event.
    """

    def callback(text: str | None) -> None:
        if local_callback is not None:
            local_callback(text)
        if text:
            event_hub.emit(
                publication_event(
                    "message.delta",
                    session_id,
                    {"text": text},
                )
            )

    return callback
