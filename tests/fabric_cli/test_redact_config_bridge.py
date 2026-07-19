"""Process-level initialization for ``security.redact_secrets``.

The CLI configures the redactor directly before logging starts. The setting is
behavioral configuration with no environment-variable alias.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _probe_redaction_state(fabric_home: Path) -> subprocess.CompletedProcess[str]:
    probe = textwrap.dedent(
        f"""\
        import sys
        sys.path.insert(0, {str(REPO_ROOT)!r})
        import fabric_cli.main
        import agent.redact
        print(f"REDACT_ENABLED={{agent.redact._REDACT_ENABLED}}")
        """
    )
    env = dict(os.environ)
    env["FABRIC_HOME"] = str(fabric_home)
    return subprocess.run(
        [sys.executable, "-c", probe],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )


@pytest.mark.parametrize("configured", [False, True])
def test_redaction_setting_is_applied_directly(tmp_path, configured):
    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    (fabric_home / "config.yaml").write_text(
        "security:\n  redact_secrets: " + str(configured).lower() + "\n",
        encoding="utf-8",
    )

    result = _probe_redaction_state(fabric_home)

    assert result.returncode == 0, f"probe failed: {result.stderr}"
    assert f"REDACT_ENABLED={configured}" in result.stdout


def test_redaction_defaults_to_enabled(tmp_path):
    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    (fabric_home / "config.yaml").write_text("{}\n", encoding="utf-8")

    result = _probe_redaction_state(fabric_home)

    assert result.returncode == 0, f"probe failed: {result.stderr}"
    assert "REDACT_ENABLED=True" in result.stdout
