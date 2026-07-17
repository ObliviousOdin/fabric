"""Packaging contracts for first-party pet assets."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_bundled_pet_assets_ship_in_both_wheel_and_sdist():
    pet_dir = REPO_ROOT / "agent" / "pet" / "assets" / "fabric-mascot"
    assert (pet_dir / "pet.json").is_file()
    assert (pet_dir / "spritesheet.webp").is_file()

    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    agent_pkg_data = data["tool"]["setuptools"]["package-data"].get("agent", [])
    assert any(pattern.startswith("pet/assets/") for pattern in agent_pkg_data), (
        "pyproject package-data 'agent' must ship bundled pet assets in wheels"
    )

    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "recursive-include agent/pet/assets" in manifest, (
        "MANIFEST.in must ship bundled pet assets in source distributions"
    )
