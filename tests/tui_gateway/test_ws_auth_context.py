from __future__ import annotations

import asyncio

from fabric_cli import mcp_startup
from tui_gateway import server
from tui_gateway import ws as ws_mod
from tui_gateway.auth_context import make_authenticated_ws_context


def test_ws_refreshes_context_correlation_for_each_accepted_request(monkeypatch) -> None:
    received = 0
    contexts = []

    monkeypatch.setattr(
        mcp_startup,
        "start_background_mcp_discovery",
        lambda **_kwargs: None,
    )

    def dispatch(req, transport=None, auth_context=None):
        del transport
        contexts.append(auth_context)
        return {"jsonrpc": "2.0", "id": req["id"], "result": {"ok": True}}

    monkeypatch.setattr(server, "dispatch", dispatch)

    class FakeWS:
        async def accept(self):
            return None

        async def send_text(self, line):
            return None

        async def receive_text(self):
            nonlocal received
            received += 1
            if received <= 2:
                return f'{{"jsonrpc":"2.0","id":"{received}","method":"connection.context"}}'
            raise ws_mod._WebSocketDisconnect()

        async def close(self):
            return None

    connection_context = make_authenticated_ws_context(
        auth_kind="provider_cookie",
        gateway_identity="dashboard:test",
        principal_identity="stub:user-42",
    )

    server._sessions.clear()
    try:
        asyncio.run(ws_mod.handle_ws(FakeWS(), auth_context=connection_context))
    finally:
        server._sessions.clear()

    assert len(contexts) == 2
    assert all(context is not None for context in contexts)
    assert [context.principal_id for context in contexts] == [
        connection_context.principal_id,
        connection_context.principal_id,
    ]
    assert contexts[0].correlation_id != contexts[1].correlation_id
    assert contexts[0].correlation_id != connection_context.correlation_id
