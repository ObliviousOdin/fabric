"""Fabric Link adapter for an exact classic CLI publication."""

from __future__ import annotations

import secrets
import time
from typing import Any

from fabric_cli.classic_remote_control import ClassicRemoteControlHost

from .application import LinkApplicationDispatchRejected
from .gateway_bridge import LinkGatewayBridge
from .protocol import LinkRequest
from .store import LinkDevice, MachineIdentity

_CLASSIC_SESSION_METHODS = frozenset(
    {
        "approval.respond",
        "clarify.respond",
        "session.attach",
        "session.detach",
        "session.input.submit",
        "session.remote_status",
    }
)


class ClassicLinkGatewayBridge:
    """Route the exact classic session locally and all other RPCs normally."""

    def __init__(
        self,
        *,
        host: ClassicRemoteControlHost,
        machine_identity: MachineIdentity,
    ) -> None:
        self._host = host
        self._gateway = LinkGatewayBridge(machine_identity=machine_identity)

    @property
    def registered_methods(self) -> frozenset[str]:
        return self._gateway.registered_methods

    def dispatch(
        self,
        device: LinkDevice,
        request: LinkRequest,
        params: dict[str, Any],
    ) -> Any:
        if request.method == "session.active_list":
            generic = self._gateway.dispatch(device, request, params)
            rows = list(generic.get("sessions") or []) if isinstance(generic, dict) else []
            rows = [row for row in rows if row.get("title") != "Fabric Link Dispatch"]
            rows.insert(0, self._active_item())
            return {"sessions": rows}
        if (
            request.method in _CLASSIC_SESSION_METHODS
            and str(params.get("session_id") or "") == self._host.session_id
        ):
            transport = self._gateway.transport_for_device(device)
            response = self._host.dispatch_authenticated(
                {
                    "id": f"link_{secrets.token_hex(16)}",
                    "jsonrpc": "2.0",
                    "method": request.method,
                    "params": params,
                },
                transport=transport,
            )
            if "error" in response:
                raise LinkApplicationDispatchRejected("rpc_rejected")
            if "result" not in response:
                raise LinkApplicationDispatchRejected("rpc_rejected")
            return response["result"]
        return self._gateway.dispatch(device, request, params)

    def close(self) -> None:
        self._gateway.close()

    def revoke_device(self, device_id: str) -> None:
        self._gateway.revoke_device(device_id)

    def _active_item(self) -> dict[str, Any]:
        snapshot = self._host.snapshot()
        messages = list(snapshot.get("messages") or [])
        preview = ""
        for message in reversed(messages):
            text = str(message.get("text") or "").strip()
            if text:
                preview = " ".join(text.split())[:160]
                break
        return {
            "current": True,
            "id": self._host.session_id,
            "last_active": time.time(),
            "message_count": len(messages),
            "model": "",
            "preview": preview,
            "session_key": str(
                snapshot.get("session_key") or self._host.session_id
            ),
            "started_at": time.time(),
            "status": str(snapshot.get("status") or "idle"),
            "title": "Live terminal",
        }
