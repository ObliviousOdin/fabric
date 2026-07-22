"""Issue #61 regressions for provider-calibrated preflight pressure."""

from unittest.mock import patch

from agent.context_compressor import ContextCompressor
from agent.model_metadata import estimate_request_tokens_rough


def _compressor() -> ContextCompressor:
    with patch(
        "agent.context_compressor.get_model_context_length",
        return_value=272_000,
    ):
        return ContextCompressor(
            model="test/model",
            threshold_percent=0.75,
            quiet_mode=True,
        )


def _opaque_replay_messages() -> list[dict]:
    # Codex replay rows can contain a large opaque reasoning payload whose
    # chars/4 pressure estimate is much larger than provider prompt usage.
    return [
        {"role": "user", "content": "continue"},
        {
            "role": "assistant",
            "content": "working",
            "reasoning": {
                "type": "reasoning",
                "encrypted_content": "r" * 820_000,
            },
        },
    ]


def test_stable_opaque_replay_does_not_repeat_false_rough_growth():
    compressor = _compressor()
    messages = _opaque_replay_messages()
    rough_pressure = estimate_request_tokens_rough(messages)
    assert rough_pressure >= compressor.threshold_tokens

    # The provider proves this exact request fits comfortably below threshold.
    compressor.update_from_response({
        "prompt_tokens": 150_000,
        "completion_tokens": 1_000,
        "total_tokens": 151_000,
        "rough_context_pressure": rough_pressure,
    })

    assert compressor.should_defer_preflight_to_real_usage(rough_pressure) is True
    assert compressor.last_calibrated_context_pressure == 150_000

    # Replaying the same opaque blob on the next turn is not new context.
    compressor.update_from_response({
        "prompt_tokens": 150_500,
        "completion_tokens": 1_000,
        "total_tokens": 151_500,
        "rough_context_pressure": rough_pressure,
    })
    assert compressor.should_defer_preflight_to_real_usage(rough_pressure) is True
    assert compressor.last_calibrated_context_pressure == 150_500


def test_genuinely_large_new_tool_result_still_triggers_preflight():
    compressor = _compressor()
    messages = _opaque_replay_messages()
    baseline_pressure = estimate_request_tokens_rough(messages)
    compressor.update_from_response({
        "prompt_tokens": 150_000,
        "completion_tokens": 1_000,
        "total_tokens": 151_000,
        "rough_context_pressure": baseline_pressure,
    })

    messages.extend([
        {"role": "user", "content": "read the large artifact"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "new-result " + ("x" * 240_000),
        },
    ])
    grown_pressure = estimate_request_tokens_rough(messages)

    assert grown_pressure - baseline_pressure >= 60_000
    assert compressor.should_defer_preflight_to_real_usage(grown_pressure) is False
    assert compressor.last_calibrated_context_pressure >= compressor.threshold_tokens
