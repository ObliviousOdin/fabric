"""Host SOUL.md migration tests (byte-identical defaults only)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fabric_cli.default_soul import DEFAULT_SOUL_MD
from fabric_cli.fabric_brand import FABRIC_SOUL_MD
from fabric_cli.fabric_soul_migrate import (
    LEGACY_IDENTITY_HASHES,
    migrate_fabric_home_souls,
    migrate_soul_file,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_legacy_default_soul_hash_is_allowlisted():
    # The native Fabric default is already current and must not be rewritten.
    assert _sha(DEFAULT_SOUL_MD) not in LEGACY_IDENTITY_HASHES
    # Preserve the known pre-Fabric default hash for upgrade compatibility.
    assert "2765a846e1bb371d78d3b93b403dfb0f8d1ba1a9895edb5f608367abfe81194d" in LEGACY_IDENTITY_HASHES


def test_migrates_byte_identical_default_soul(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FABRIC_BRAND", "1")
    soul = tmp_path / "SOUL.md"
    legacy = "legacy-default-for-test"
    monkeypatch.setattr(
        "fabric_cli.fabric_soul_migrate.LEGACY_IDENTITY_HASHES",
        frozenset({_sha(legacy)}),
    )
    soul.write_text(legacy, encoding="utf-8")

    assert migrate_soul_file(soul) is True
    assert soul.read_text(encoding="utf-8") == FABRIC_SOUL_MD


def test_does_not_touch_custom_soul(tmp_path: Path):
    soul = tmp_path / "SOUL.md"
    custom = "You are a warehouse ops copilot for Acme."
    soul.write_text(custom, encoding="utf-8")

    assert migrate_soul_file(soul) is False
    assert soul.read_text(encoding="utf-8") == custom


def test_migrate_home_covers_profiles(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FABRIC_BRAND", "1")
    home = tmp_path / "home"
    (home / "profiles" / "ops").mkdir(parents=True)
    root_soul = home / "SOUL.md"
    profile_soul = home / "profiles" / "ops" / "SOUL.md"
    legacy = "legacy-default-for-test"
    monkeypatch.setattr(
        "fabric_cli.fabric_soul_migrate.LEGACY_IDENTITY_HASHES",
        frozenset({_sha(legacy)}),
    )
    root_soul.write_text(legacy, encoding="utf-8")
    profile_soul.write_text(legacy, encoding="utf-8")

    changed = migrate_fabric_home_souls(home)
    assert changed == 2
    assert root_soul.read_text(encoding="utf-8") == FABRIC_SOUL_MD
    assert profile_soul.read_text(encoding="utf-8") == FABRIC_SOUL_MD


def test_migrate_is_idempotent(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FABRIC_BRAND", "1")
    soul = tmp_path / "SOUL.md"
    legacy = "legacy-default-for-test"
    monkeypatch.setattr(
        "fabric_cli.fabric_soul_migrate.LEGACY_IDENTITY_HASHES",
        frozenset({_sha(legacy)}),
    )
    soul.write_text(legacy, encoding="utf-8")

    assert migrate_soul_file(soul) is True
    assert migrate_soul_file(soul) is False
