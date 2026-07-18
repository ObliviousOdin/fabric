"""Unit tests for the shared host-stats collector.

Covers the always-present contract, psutil-gated enrichment, and the
network-throughput rate computation (which relies on process-local state
between successive samples). GPU assertions stay tolerant — CI hosts have no
NVIDIA GPU, so ``gpus`` is expected to be absent there.
"""

from __future__ import annotations

import time

import pytest

from fabric_cli import system_stats
from fabric_cli.system_stats import collect_dynamic_stats

try:
    import psutil  # type: ignore  # noqa: F401

    _HAVE_PSUTIL = True
except Exception:  # pragma: no cover - depends on the environment
    _HAVE_PSUTIL = False


@pytest.fixture(autouse=True)
def _reset_net_state():
    """Each test starts from a clean net-rate baseline (no prior sample)."""
    system_stats._last_net = None
    yield
    system_stats._last_net = None


def test_always_reports_psutil_flag():
    stats = collect_dynamic_stats()
    assert isinstance(stats, dict)
    assert isinstance(stats["psutil"], bool)


def test_gpus_absent_or_well_formed():
    stats = collect_dynamic_stats()
    # Absent on GPU-less hosts; when present every entry is well-formed.
    for gpu in stats.get("gpus") or []:
        assert {"name", "util_percent", "mem_used", "mem_total", "mem_percent"} <= set(gpu)
        assert 0 <= gpu["util_percent"] <= 100


@pytest.mark.skipif(not _HAVE_PSUTIL, reason="psutil not installed")
def test_psutil_metrics_populated():
    stats = collect_dynamic_stats()
    assert stats["psutil"] is True
    assert isinstance(stats["memory"]["percent"], (int, float))
    assert isinstance(stats["cpu_percent"], (int, float))
    assert stats["per_cpu_percent"] and all(
        0 <= v <= 100 for v in stats["per_cpu_percent"]
    )
    # cpu_percent is the mean of the per-core samples.
    per = stats["per_cpu_percent"]
    assert stats["cpu_percent"] == pytest.approx(sum(per) / len(per), abs=0.6)


@pytest.mark.skipif(not _HAVE_PSUTIL, reason="psutil not installed")
def test_net_rate_is_null_first_then_numeric():
    # First sample has no predecessor → rates are null.
    first = collect_dynamic_stats()
    assert first["net"]["sent_per_sec"] is None
    assert first["net"]["recv_per_sec"] is None

    time.sleep(0.05)

    # Second sample computes a non-negative rate from the delta.
    second = collect_dynamic_stats()
    assert second["net"]["sent_per_sec"] is not None
    assert second["net"]["recv_per_sec"] is not None
    assert second["net"]["sent_per_sec"] >= 0
    assert second["net"]["recv_per_sec"] >= 0
    # Cumulative counters never go backwards between two reads.
    assert second["net"]["bytes_sent"] >= first["net"]["bytes_sent"]
