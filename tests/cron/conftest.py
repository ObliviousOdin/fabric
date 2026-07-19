"""Cron-test fixtures.

Provides an isolated canonical config with a default model for cron tests that
exercise ``run_job``. Individual tests can replace ``config.yaml`` when
they need to cover model-resolution edge cases.
"""

import pytest


@pytest.fixture(autouse=True)
def _default_cron_test_model(monkeypatch, tmp_path):
    """Give every cron test a profile-local canonical model configuration."""
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "model: test-cron-default-model\n",
        encoding="utf-8",
    )
