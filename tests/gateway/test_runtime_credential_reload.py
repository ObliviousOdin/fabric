"""Gateway per-turn credential reload contract."""

from __future__ import annotations

import os
from pathlib import Path

from gateway import run as gateway_run


def test_reload_runtime_credentials_refreshes_dotenv_secret(
    tmp_path: Path, monkeypatch
) -> None:
    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    (fabric_home / ".env").write_text(
        "OPENROUTER_API_KEY=fresh-key\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(gateway_run, "_fabric_home", fabric_home)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    gateway_run._reload_runtime_credentials()

    assert os.environ["OPENROUTER_API_KEY"] == "fresh-key"
