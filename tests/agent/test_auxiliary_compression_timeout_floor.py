"""Regression tests for honest auxiliary compression timeout semantics."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.auxiliary_client import (
    _effective_aux_timeout,
    async_call_llm,
    call_llm,
)
from fabric_cli.config import DEFAULT_CONFIG


def _ok_response():
    return {"ok": True}


def _client_sync():
    client = MagicMock()
    client.base_url = "https://api.openai.com/v1"
    client.chat.completions.create.return_value = _ok_response()
    return client


def _client_async():
    client = MagicMock()
    client.base_url = "https://api.openai.com/v1"
    client.chat.completions.create = AsyncMock(return_value=_ok_response())
    return client


def _patches(client, *, task_timeout):
    return (
        patch(
            "agent.auxiliary_client._resolve_task_provider_model",
            return_value=("openai-codex", "gpt-5.5", None, None, None),
        ),
        patch(
            "agent.auxiliary_client._get_cached_client",
            return_value=(client, "gpt-5.5"),
        ),
        patch(
            "agent.auxiliary_client._validate_llm_response",
            side_effect=lambda response, _task: response,
        ),
        patch(
            "agent.auxiliary_client._get_task_timeout",
            return_value=task_timeout,
        ),
    )


@pytest.mark.parametrize("configured", [60.0, 90.0, 120.0, 600.0])
def test_sync_configured_compression_timeout_reaches_client_unchanged(configured):
    client = _client_sync()
    patches = _patches(client, task_timeout=configured)
    with patches[0], patches[1], patches[2], patches[3]:
        call_llm(
            task="compression",
            messages=[{"role": "user", "content": "summarize this"}],
        )

    assert client.chat.completions.create.call_args.kwargs["timeout"] == configured


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [60.0, 90.0, 120.0, 600.0])
async def test_async_configured_compression_timeout_reaches_client_unchanged(
    configured,
):
    client = _client_async()
    patches = _patches(client, task_timeout=configured)
    with patches[0], patches[1], patches[2], patches[3]:
        await async_call_llm(
            task="compression",
            messages=[{"role": "user", "content": "summarize this"}],
        )

    assert client.chat.completions.create.call_args.kwargs["timeout"] == configured


def test_explicit_call_timeout_wins():
    client = _client_sync()
    patches = _patches(client, task_timeout=300.0)
    with patches[0], patches[1], patches[2], patches[3]:
        call_llm(
            task="compression",
            messages=[{"role": "user", "content": "x"}],
            timeout=45.0,
        )

    assert client.chat.completions.create.call_args.kwargs["timeout"] == 45.0


@pytest.mark.parametrize("invalid", [0, -1, float("nan"), float("inf"), "invalid"])
def test_invalid_explicit_timeout_falls_back_safely(invalid):
    with patch("agent.auxiliary_client._get_task_timeout", return_value=300.0):
        assert _effective_aux_timeout("compression", invalid) == 300.0


def test_default_compression_timeout_is_the_configured_bounded_budget():
    configured_default = DEFAULT_CONFIG["auxiliary"]["compression"]["timeout"]
    with patch(
        "agent.auxiliary_client._get_task_timeout",
        return_value=float(configured_default),
    ):
        assert _effective_aux_timeout("compression", None) == configured_default
