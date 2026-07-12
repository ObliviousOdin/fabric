"""Cross-process evidence for the shared Ollama target lease."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from fabric_cli.ollama_pull import OllamaPullBusyError, _pull_lease


def test_target_lease_is_shared_across_processes(tmp_path: Path) -> None:
    root = tmp_path / "fabric-root"
    target_hash = "a" * 64
    repository = Path(__file__).resolve().parents[2]
    child_code = "\n".join(
        (
            "import sys",
            "from pathlib import Path",
            "from fabric_cli.ollama_pull import _pull_lease",
            "with _pull_lease(Path(sys.argv[1]), sys.argv[2]):",
            "    print('READY', flush=True)",
            "    sys.stdin.readline()",
        )
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repository)
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(root), target_hash],
        cwd=repository,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "READY"

        with pytest.raises(OllamaPullBusyError):
            with _pull_lease(root, target_hash):
                pass
    finally:
        if child.poll() is None:
            try:
                child.communicate(input="\n", timeout=5)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.communicate(timeout=5)

    assert child.returncode == 0
    with _pull_lease(root, target_hash):
        pass

