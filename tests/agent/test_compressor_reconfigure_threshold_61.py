"""Regression tests for #61 — hot-applying a changed ``compression.threshold``.

A long-lived agent (the desktop session that is not rebuilt between turns)
bakes ``compression.threshold`` into ``threshold_percent`` / ``threshold_tokens``
at construction. When the user edits the setting mid-session the live compressor
kept compacting at the stale trigger — the reported case was a 272K session
configured to 85% that kept firing at the old 204,000-token (75%) trigger
instead of 231,200 (85%).

``ContextCompressor.reconfigure_threshold`` is the supported hot-apply surface;
the desktop wires it in at turn start (see ``tui_gateway/server.py``).
"""

import pytest
from unittest.mock import patch

from agent.context_compressor import ContextCompressor


def _make(context_length: int, threshold_percent: float, **kw) -> ContextCompressor:
    with patch(
        "agent.context_compressor.get_model_context_length",
        return_value=context_length,
    ):
        return ContextCompressor(
            model="test/model",
            threshold_percent=threshold_percent,
            quiet_mode=True,
            **kw,
        )


class TestReconfigureThreshold:
    def test_272k_75_to_85_updates_effective_threshold(self):
        """The headline acceptance criterion from #61.

        A live 272K compressor at 75% (204,000 tokens) reconfigured to 85%
        must report 231,200 tokens before the next decision.
        """
        c = _make(272_000, 0.75)
        assert c.threshold_tokens == 204_000
        assert c.threshold_percent == pytest.approx(0.75)

        changed = c.reconfigure_threshold(0.85)

        assert changed is True
        assert c.threshold_percent == pytest.approx(0.85)
        assert c.threshold_tokens == 231_200
        # The configured percent is what a later small<->large model switch
        # restores from, so it must track the new value too.
        assert c._configured_threshold_percent == pytest.approx(0.85)

    def test_should_compress_uses_new_threshold(self):
        """The next decision (not just the reported number) honors the change."""
        c = _make(272_000, 0.75)
        # 210,000 prompt tokens: above the old 204,000 trigger, below the new
        # 231,200 trigger. Behavior must flip after reconfigure.
        assert c.should_compress(prompt_tokens=210_000) is True
        c.reconfigure_threshold(0.85)
        assert c.should_compress(prompt_tokens=210_000) is False
        assert c.should_compress(prompt_tokens=240_000) is True

    def test_noop_when_unchanged(self):
        c = _make(272_000, 0.85)
        assert c.reconfigure_threshold(0.85) is False
        assert c.threshold_tokens == 231_200

    def test_lowering_threshold_reapplies(self):
        c = _make(272_000, 0.85)
        assert c.threshold_tokens == 231_200
        assert c.reconfigure_threshold(0.75) is True
        assert c.threshold_tokens == 204_000
        assert c.threshold_percent == pytest.approx(0.75)

    def test_small_context_floor_still_applies(self):
        """Below 512K the 75% small-context floor still raises a low config.

        Lowering the configured percent below the floor keeps the effective
        trigger at the 75% floor. Because the effective trigger does not move,
        ``reconfigure_threshold`` reports no change — but it still records the
        newly-configured percent so a later switch to a >512K window re-derives
        from what the user actually set.
        """
        c = _make(128_000, 0.75)
        assert c.reconfigure_threshold(0.50) is False
        assert c._configured_threshold_percent == pytest.approx(0.50)
        assert c.threshold_percent == pytest.approx(0.75)
        assert c.threshold_tokens == 96_000  # int(128000 * 0.75)

    def test_subfloor_edit_recorded_then_applied_on_large_switch(self):
        """A sub-floor edit is masked now but takes effect after a big-window
        switch — the reason we still persist the configured percent."""
        c = _make(128_000, 0.75)
        c.reconfigure_threshold(0.50)  # masked by the 75% floor at 128K
        assert c.threshold_percent == pytest.approx(0.75)
        # Switch to a >512K window: no floor, so the recorded 50% now governs.
        c.update_model(model="big/model", context_length=1_000_000)
        assert c.threshold_percent == pytest.approx(0.50)
        assert c.threshold_tokens == 500_000  # int(1_000_000 * 0.50)

    def test_tail_budget_recomputed(self):
        c = _make(272_000, 0.75, summary_target_ratio=0.20)
        assert c.tail_token_budget == int(204_000 * 0.20)
        c.reconfigure_threshold(0.85)
        assert c.tail_token_budget == int(231_200 * 0.20)

    def test_preserves_calibration_state(self):
        """Unlike update_model, a threshold change must NOT reset the
        provider-usage calibration captured under the same model."""
        c = _make(272_000, 0.75)
        c.last_real_prompt_tokens = 137_466
        c.last_provider_prompt_tokens_at_calibration = 137_466
        c.last_rough_tokens_when_real_prompt_fit = 204_307
        c.awaiting_real_usage_after_compression = True
        c.reconfigure_threshold(0.85)
        assert c.last_real_prompt_tokens == 137_466
        assert c.last_provider_prompt_tokens_at_calibration == 137_466
        assert c.last_rough_tokens_when_real_prompt_fit == 204_307
        assert c.awaiting_real_usage_after_compression is True

    def test_invalid_values_are_noops(self):
        c = _make(272_000, 0.75)
        for bad in (0, -0.3, "nope", None):
            assert c.reconfigure_threshold(bad) is False
        assert c.threshold_tokens == 204_000
