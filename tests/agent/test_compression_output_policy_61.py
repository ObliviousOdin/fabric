"""Issue #61 regressions for compression latency and output policy."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.auxiliary_client import (
    _client_cache_key,
    _resolve_auto,
    call_llm,
    resolve_provider_client,
)
from agent.context_compressor import (
    HISTORICAL_TASK_HEADING,
    ContextCompressor,
    SUMMARY_PREFIX,
)
from agent.model_metadata import get_model_context_length


def _online_policy():
    # _resolve_auto only identity-checks this against EgressMode.LOCAL_AI.
    return SimpleNamespace(mode=object())


def test_auto_compression_uses_same_provider_fast_model():
    client = MagicMock()

    def _resolve(provider, model, **_kwargs):
        return client, model

    with patch(
        "agent.auxiliary_client.resolve_provider_client",
        side_effect=_resolve,
    ) as resolve:
        resolved_client, resolved_model = _resolve_auto(
            main_runtime={
                "provider": "openai-codex",
                "model": "gpt-5.6-sol",
                "base_url": "https://chatgpt.com/backend-api/codex",
                "api_key": "oauth-placeholder",
                "api_mode": "codex_responses",
                "compression_threshold_tokens": int(272_000 * 0.85),
            },
            task="compression",
            policy=_online_policy(),
            route_config={},
        )

    assert resolved_client is client
    assert resolved_model == "gpt-5.4-mini"
    assert resolve.call_args.args[:2] == ("openai-codex", "gpt-5.4-mini")
    assert (
        resolve.call_args.kwargs["explicit_base_url"]
        == "https://chatgpt.com/backend-api/codex"
    )


def test_automatic_fast_model_can_fit_the_configured_compression_threshold():
    configured_context = 272_000
    configured_threshold = int(configured_context * 0.85)
    assert get_model_context_length("gpt-5.4-mini") >= configured_threshold


def test_auto_compression_keeps_main_model_when_fast_context_is_too_small():
    client = MagicMock()
    with (
        patch(
            "agent.auxiliary_client._candidate_context_window",
            return_value=128_000,
        ),
        patch(
            "agent.auxiliary_client.resolve_provider_client",
            return_value=(client, "gpt-5.6-sol"),
        ) as resolve,
    ):
        _, resolved_model = _resolve_auto(
            main_runtime={
                "provider": "openai-codex",
                "model": "gpt-5.6-sol",
                "compression_threshold_tokens": 231_200,
            },
            task="compression",
            policy=_online_policy(),
            route_config={},
        )

    assert resolved_model == "gpt-5.6-sol"
    assert resolve.call_args.args[:2] == ("openai-codex", "gpt-5.6-sol")


def test_auto_compression_keeps_main_model_without_live_threshold():
    client = MagicMock()
    with patch(
        "agent.auxiliary_client.resolve_provider_client",
        return_value=(client, "gpt-5.6-sol"),
    ) as resolve:
        _, resolved_model = _resolve_auto(
            main_runtime={
                "provider": "openai-codex",
                "model": "gpt-5.6-sol",
            },
            task="compression",
            policy=_online_policy(),
            route_config={},
        )

    assert resolved_model == "gpt-5.6-sol"
    assert resolve.call_args.args[:2] == ("openai-codex", "gpt-5.6-sol")


def test_compression_threshold_participates_in_auto_client_cache_key():
    common = {
        "provider": "openai-codex",
        "model": "gpt-5.6-sol",
    }
    lower = _client_cache_key(
        "auto",
        async_mode=False,
        main_runtime={**common, "compression_threshold_tokens": 200_000},
        task="compression",
    )
    higher = _client_cache_key(
        "auto",
        async_mode=False,
        main_runtime={**common, "compression_threshold_tokens": 260_000},
        task="compression",
    )

    assert lower != higher


def test_auto_compression_does_not_reuse_generic_auxiliary_default():
    client = MagicMock()
    with patch(
        "agent.auxiliary_client.resolve_provider_client",
        return_value=(client, "claude-opus-4-8"),
    ) as resolve:
        _, resolved_model = _resolve_auto(
            main_runtime={
                "provider": "anthropic",
                "model": "claude-opus-4-8",
                "compression_threshold_tokens": 850_000,
            },
            task="compression",
            policy=_online_policy(),
            route_config={},
        )

    assert resolved_model == "claude-opus-4-8"
    assert resolve.call_args.args[:2] == ("anthropic", "claude-opus-4-8")


def test_non_compression_auto_task_keeps_main_model():
    client = MagicMock()

    def _resolve(provider, model, **_kwargs):
        return client, model

    with patch(
        "agent.auxiliary_client.resolve_provider_client",
        side_effect=_resolve,
    ) as resolve:
        _, resolved_model = _resolve_auto(
            main_runtime={
                "provider": "openai-codex",
                "model": "gpt-5.6-sol",
                "base_url": "https://chatgpt.com/backend-api/codex",
                "api_key": "oauth-placeholder",
                "api_mode": "codex_responses",
            },
            task="title_generation",
            policy=_online_policy(),
            route_config={},
        )

    assert resolved_model == "gpt-5.6-sol"
    assert resolve.call_args.args[:2] == ("openai-codex", "gpt-5.6-sol")


def test_explicit_compression_model_overrides_automatic_fast_model():
    client = MagicMock()
    with patch(
        "agent.auxiliary_client._resolve_auto",
        return_value=(client, "gpt-5.4-mini"),
    ):
        resolved_client, resolved_model = resolve_provider_client(
            "auto",
            model="explicit-compression-model",
            main_runtime={
                "provider": "openai-codex",
                "model": "gpt-5.6-sol",
            },
            task="compression",
        )

    assert resolved_client is client
    assert resolved_model == "explicit-compression-model"


def test_call_llm_forwards_compression_task_to_automatic_router():
    client = MagicMock()
    client.base_url = "https://chatgpt.com/backend-api/codex"
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
    )
    client.chat.completions.create.return_value = response

    with (
        patch(
            "agent.auxiliary_client._resolve_task_provider_model",
            return_value=("auto", None, None, None, None),
        ),
        patch(
            "agent.auxiliary_client._get_cached_client",
            return_value=(client, "gpt-5.4-mini"),
        ) as cached,
        patch(
            "agent.auxiliary_client._validate_llm_response",
            side_effect=lambda result, _task: result,
        ),
    ):
        call_llm(
            task="compression",
            messages=[{"role": "user", "content": "summarize"}],
            timeout=60,
        )

    assert cached.call_args.kwargs["task"] == "compression"


def test_generated_summary_is_bounded_after_reasoning_completes():
    with patch(
        "agent.context_compressor.get_model_context_length",
        return_value=272_000,
    ):
        compressor = ContextCompressor(
            model="gpt-5.6-sol",
            provider="openai-codex",
            threshold_percent=0.75,
            quiet_mode=True,
        )

    oversized = (
        "## Goal\nPreserve continuity.\n\n"
        + ("x" * 5_000)
        + f"\n\n{HISTORICAL_TASK_HEADING}\nHISTORICAL_TASK_MUST_SURVIVE\n"
        + ("y" * 5_000)
        + "\n\n## Critical Context\nCRITICAL_CONTEXT_MUST_SURVIVE\n"
        + ("z" * 5_000)
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=oversized))]
    )
    turns = [{"role": "user", "content": "summarize this turn"}]
    expected_budget = compressor._compute_summary_budget(turns)

    with patch(
        "agent.context_compressor.call_llm",
        return_value=response,
    ) as call:
        summary = compressor._generate_summary(turns)

    assert summary is not None
    assert summary.startswith(SUMMARY_PREFIX)
    retained = compressor._strip_summary_prefix(summary)
    assert len(retained.encode("utf-8")) <= expected_budget * 4
    assert HISTORICAL_TASK_HEADING in retained
    assert "HISTORICAL_TASK_MUST_SURVIVE" in retained
    assert "## Critical Context" in retained
    assert "CRITICAL_CONTEXT_MUST_SURVIVE" in retained
    assert retained.endswith("[Summary truncated to compression output budget.]")
    assert compressor._previous_summary == retained
    assert call.call_args.kwargs["task"] == "compression"
    assert (
        call.call_args.kwargs["main_runtime"]["compression_threshold_tokens"]
        == compressor.threshold_tokens
    )
    # A provider-side cap can be spent on hidden reasoning before any useful
    # handoff is emitted; the completed text is bounded locally instead.
    assert "max_tokens" not in call.call_args.kwargs


def test_summary_output_policy_leaves_under_budget_text_byte_identical():
    summary = f"{HISTORICAL_TASK_HEADING}\nKeep this unchanged — 完全保留."
    assert ContextCompressor._cap_summary_output(summary, 100) == summary


def test_summary_output_policy_is_utf8_byte_bounded():
    summary = (
        "开" * 2_000
        + f"\n\n{HISTORICAL_TASK_HEADING}\n保留当前任务"
        + "界" * 2_000
        + "\n\n## Critical Context\n保留关键上下文"
        + "终" * 2_000
    )
    bounded = ContextCompressor._cap_summary_output(summary, 1_024)

    assert len(bounded.encode("utf-8")) <= 4_096
    assert HISTORICAL_TASK_HEADING in bounded
    assert "## Critical Context" in bounded
    assert bounded.endswith("[Summary truncated to compression output budget.]")
