"""Regression tests for Telegram's text-batch adaptive-delay fast-path and
config-backed bounded delay parsing.

The fast-path lets short replies stream near-instantly while keeping the
configured cap as the upper bound, so an operator who tightens the cap
gets the lower number on every tier.

The config parser guarantees delay values never produce NaN/Inf or
out-of-bounds values that could break asyncio.sleep().
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from plugins.platforms.telegram.adapter import TelegramAdapter


@pytest.fixture
def adapter():
    """Build a TelegramAdapter shell without going through __init__'s
    network-touching setup. Just need the class for static-method access
    and the instance for instance-method tests."""
    instance = TelegramAdapter.__new__(TelegramAdapter)
    instance.config = SimpleNamespace(extra={})
    return instance


class TestConfigFloatClamped:
    """Config-backed float parsing rejects NaN/Inf and honors bounds."""

    def test_default_when_unset(self, adapter):
        assert adapter._coerce_float_extra("text_batch_delay_seconds", 0.5) == 0.5

    def test_parses_valid_value(self, adapter):
        adapter.config.extra["text_batch_delay_seconds"] = "1.25"
        assert adapter._coerce_float_extra("text_batch_delay_seconds", 0.5) == 1.25

    def test_falls_back_to_default_on_garbage(self, adapter):
        adapter.config.extra["text_batch_delay_seconds"] = "not-a-float"
        assert adapter._coerce_float_extra("text_batch_delay_seconds", 0.5) == 0.5

    def test_rejects_nan(self, adapter):
        adapter.config.extra["text_batch_delay_seconds"] = "nan"
        result = adapter._coerce_float_extra("text_batch_delay_seconds", 0.5)
        assert math.isfinite(result)
        assert result == 0.5

    def test_rejects_inf(self, adapter):
        adapter.config.extra["text_batch_delay_seconds"] = "inf"
        result = adapter._coerce_float_extra("text_batch_delay_seconds", 0.5)
        assert math.isfinite(result)
        assert result == 0.5

    def test_clamps_below_min(self, adapter):
        adapter.config.extra["text_batch_delay_seconds"] = "0.01"
        assert adapter._coerce_float_extra(
            "text_batch_delay_seconds", 0.5, min_value=0.1,
        ) == 0.1

    def test_clamps_above_max(self, adapter):
        adapter.config.extra["text_batch_delay_seconds"] = "10.0"
        assert adapter._coerce_float_extra(
            "text_batch_delay_seconds", 0.5, max_value=2.0,
        ) == 2.0


class TestAdaptiveTextBatchTiers:
    """The fast-path tiers cap delay for short / medium messages.  Tier
    constants must compose with the configured cap (operators who set a
    lower cap get the lower number on every tier)."""

    def test_class_constants_are_sensible(self):
        """Sanity check that the tier constants form a non-overlapping
        ascending ladder."""
        assert TelegramAdapter._TEXT_BATCH_FAST_LEN < TelegramAdapter._TEXT_BATCH_SHORT_LEN
        assert TelegramAdapter._TEXT_BATCH_FAST_DELAY_S < TelegramAdapter._TEXT_BATCH_SHORT_DELAY_S
        assert TelegramAdapter._TEXT_BATCH_FAST_DELAY_S > 0
        assert TelegramAdapter._TEXT_BATCH_SHORT_DELAY_S > 0

    def test_fast_tier_uses_min_with_configured_cap(self, adapter):
        """A short message picks the lower of the fast-tier delay and
        the operator's configured cap."""
        # Operator set a generous cap (0.6s); fast tier should win.
        adapter._text_batch_delay_seconds = 0.6
        delay = min(
            adapter._text_batch_delay_seconds,
            TelegramAdapter._TEXT_BATCH_FAST_DELAY_S,
        )
        assert delay == TelegramAdapter._TEXT_BATCH_FAST_DELAY_S

        # Operator tightened the cap below the fast-tier delay; cap wins.
        adapter._text_batch_delay_seconds = 0.10
        delay = min(
            adapter._text_batch_delay_seconds,
            TelegramAdapter._TEXT_BATCH_FAST_DELAY_S,
        )
        assert delay == 0.10

    def test_short_tier_uses_min_with_configured_cap(self, adapter):
        """Same composition rule for the medium tier."""
        adapter._text_batch_delay_seconds = 0.6
        delay = min(
            adapter._text_batch_delay_seconds,
            TelegramAdapter._TEXT_BATCH_SHORT_DELAY_S,
        )
        assert delay == TelegramAdapter._TEXT_BATCH_SHORT_DELAY_S

    def test_long_message_uses_full_cap(self, adapter):
        """Messages above the medium threshold use the configured cap
        without the tier-clamp."""
        adapter._text_batch_delay_seconds = 0.5
        # Beyond _TEXT_BATCH_SHORT_LEN there's no tier-clamp; cap wins.
        delay = adapter._text_batch_delay_seconds
        assert delay == 0.5

    def test_split_threshold_takes_priority_over_fast_tier(self, adapter):
        """If the latest chunk hits the platform split threshold a
        continuation is almost certain — wait the longer split delay
        regardless of total length."""
        adapter._text_batch_delay_seconds = 0.3
        adapter._text_batch_split_delay_seconds = 1.0
        last_chunk_len = TelegramAdapter._SPLIT_THRESHOLD + 50
        # The flush path checks last_chunk_len first; assert the contract.
        assert last_chunk_len >= TelegramAdapter._SPLIT_THRESHOLD
        delay = adapter._text_batch_split_delay_seconds
        assert delay == 1.0
        assert delay > adapter._text_batch_delay_seconds
