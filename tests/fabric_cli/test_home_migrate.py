"""Tests for safe ~/.hermes → ~/.fabric migration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from fabric_cli.home_migrate import (
    HomeMigrationError,
    _read_live_gateway_pid,
    _verify_copy,
    migrate_home,
)
from fabric_cli.migrate import cmd_migrate_home


def _seed_legacy_home(path: Path) -> None:
    path.mkdir(mode=0o700)
    (path / "config.yaml").write_text("model:\n  default: test/model\n", encoding="utf-8")
    (path / ".env").write_text("TEST_SECRET=redacted\n", encoding="utf-8")
    (path / ".env").chmod(0o600)
    (path / "state.db").write_bytes(b"sqlite-like-state")
    (path / "SOUL.md").write_text("# My custom agent\nNever overwrite me.\n", encoding="utf-8")
    (path / "sessions").mkdir()
    (path / "sessions" / "one.json").write_text("{}\n", encoding="utf-8")
    (path / "profiles" / "ops").mkdir(parents=True)
    (path / "profiles" / "ops" / "config.yaml").write_text("agent: {}\n", encoding="utf-8")
    (path / "cron").mkdir()
    (path / "cron" / "jobs.json").write_text("[]\n", encoding="utf-8")
    (path / "cron" / ".tick.lock").write_text("stale\n", encoding="utf-8")
    (path / "gateway.pid").write_text("99999999\n", encoding="utf-8")
    (path / "gateway.lock").write_text("stale\n", encoding="utf-8")
    (path / "hermes-agent").mkdir()
    (path / "hermes-agent" / "pyproject.toml").write_text("[project]\n", encoding="utf-8")


def test_migrate_home_preserves_data_archives_source_and_excludes_old_runtime(tmp_path: Path):
    source = tmp_path / ".hermes"
    target = tmp_path / ".fabric"
    _seed_legacy_home(source)

    result = migrate_home(source, target)

    assert not source.exists()
    assert result.backup is not None
    backup = Path(result.backup)
    assert backup.is_dir()
    assert (backup / "hermes-agent" / "pyproject.toml").is_file()

    assert target.is_dir()
    assert (target / "config.yaml").read_text() == "model:\n  default: test/model\n"
    assert (target / ".env").read_text() == "TEST_SECRET=redacted\n"
    assert (target / "state.db").read_bytes() == b"sqlite-like-state"
    assert (target / "SOUL.md").read_text() == "# My custom agent\nNever overwrite me.\n"
    assert (target / "sessions" / "one.json").is_file()
    assert (target / "profiles" / "ops" / "config.yaml").is_file()
    assert (target / "cron" / "jobs.json").is_file()

    assert not (target / "hermes-agent").exists()
    assert not (target / "gateway.pid").exists()
    assert not (target / "gateway.lock").exists()
    assert not (target / "cron" / ".tick.lock").exists()

    receipt = json.loads((target / "migration-hermes-to-fabric.json").read_text())
    assert receipt["source"] == str(source.resolve())
    assert receipt["target"] == str(target.resolve())
    assert receipt["old_engine_excluded"] is True
    assert receipt["souls_migrated"] == 0
    assert result.skipped_old_engine is True


def test_migrate_home_keep_source(tmp_path: Path):
    source = tmp_path / ".hermes"
    target = tmp_path / ".fabric"
    _seed_legacy_home(source)

    result = migrate_home(source, target, archive_source=False)

    assert source.is_dir()
    assert target.is_dir()
    assert result.backup is None


def test_dry_run_recommends_merge_for_installer_seeded_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    source = tmp_path / ".hermes"
    target = tmp_path / ".fabric"
    source.mkdir()
    target.mkdir()
    (target / "skills").mkdir()

    rc = cmd_migrate_home(
        SimpleNamespace(
            source=str(source),
            target=str(target),
            apply=False,
            include_old_engine=False,
            merge_existing=False,
        )
    )

    assert rc == 0
    assert "fabric migrate home --apply --merge-existing" in capsys.readouterr().out


def test_migrate_home_refuses_nonempty_target(tmp_path: Path):
    source = tmp_path / ".hermes"
    target = tmp_path / ".fabric"
    _seed_legacy_home(source)
    target.mkdir()
    (target / "existing").write_text("do not merge\n")

    with pytest.raises(HomeMigrationError, match="not empty"):
        migrate_home(source, target)

    assert source.is_dir()
    assert (target / "existing").read_text() == "do not merge\n"


def test_migrate_home_explicitly_merges_installer_scaffold(tmp_path: Path):
    source = tmp_path / ".hermes"
    target = tmp_path / ".fabric"
    _seed_legacy_home(source)
    target.mkdir()
    (target / "config.yaml").write_text("display:\n  skin: fabric\n", encoding="utf-8")
    (target / "skins").mkdir()
    (target / "skins" / "fabric.yaml").write_text("name: Fabric\n", encoding="utf-8")
    (target / "skills" / "new-bundled").mkdir(parents=True)
    (target / "skills" / "new-bundled" / "SKILL.md").write_text("new\n", encoding="utf-8")

    result = migrate_home(source, target, merge_existing=True)

    # Legacy customer data wins conflicts.
    assert (target / "config.yaml").read_text() == "model:\n  default: test/model\n"
    # Installer-only files absent from the legacy home survive.
    assert (target / "skins" / "fabric.yaml").read_text() == "name: Fabric\n"
    assert (target / "skills" / "new-bundled" / "SKILL.md").read_text() == "new\n"
    assert result.previous_target_backup is not None
    previous = Path(result.previous_target_backup)
    assert previous.is_dir()
    assert (previous / "config.yaml").read_text() == "display:\n  skin: fabric\n"


def test_migrate_home_refuses_live_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / ".hermes"
    target = tmp_path / ".fabric"
    _seed_legacy_home(source)
    monkeypatch.setattr("fabric_cli.home_migrate._read_live_gateway_pid", lambda _source: 4242)

    with pytest.raises(HomeMigrationError, match="4242.*still running"):
        migrate_home(source, target)

    assert source.is_dir()
    assert not target.exists()


def test_process_table_fallback_detects_legacy_gateway_without_pid_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / ".hermes"
    source.mkdir()

    class _Process:
        info = {
            "pid": 4321,
            "cmdline": [
                str(source / "hermes-agent" / "venv" / "bin" / "python"),
                "-m",
                "hermes_cli.main",
                "gateway",
                "run",
                "--replace",
            ],
        }

    monkeypatch.setattr("fabric_cli.home_migrate.psutil.process_iter", lambda _attrs: [_Process()])

    assert _read_live_gateway_pid(source) == 4321


def test_migrate_home_can_include_old_engine(tmp_path: Path):
    source = tmp_path / ".hermes"
    target = tmp_path / ".fabric"
    _seed_legacy_home(source)

    result = migrate_home(source, target, include_old_engine=True)

    assert (target / "hermes-agent" / "pyproject.toml").is_file()
    assert result.skipped_old_engine is False


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only")
def test_migrate_home_preserves_profile_exact_account_state_and_private_modes(
    tmp_path: Path,
):
    from fabric_cli import provider_accounts as accounts

    source = tmp_path / ".hermes"
    target = tmp_path / ".fabric"
    _seed_legacy_home(source)
    named_home = source / "profiles" / "ops"

    before = {}
    for profile_home, repair_value in (
        (source, "default-repair"),
        (named_home, "ops-repair"),
    ):
        managed = accounts.create_managed_request(
            home=profile_home,
            provider_id="openai-codex",
            device_label=f"Migrated {profile_home.name}",
            expected_revision=0,
        )
        started = accounts.capture_personal_oauth_start(
            home=profile_home,
            provider_id="openai-codex",
            expected_revision=managed.snapshot.revision,
        )
        leased = accounts.acquire_oauth_lease(
            home=profile_home,
            provider_id="openai-codex",
            captured_intent=started.intent,
        )
        state = profile_home / "provider-accounts.json"
        before[profile_home.relative_to(source)] = (
            leased.snapshot.revision,
            managed.request.request_id,
            json.loads(state.read_text())["store_instance_id"],
        )
        state.chmod(0o644)
        (profile_home / "provider-accounts.lock").write_text("runtime-lock")
        (profile_home / ".provider-accounts.json.tmp.1234.abcdef").write_text(
            "temporary-full-state"
        )
        repair = profile_home / ".provider-account-repair"
        repair.mkdir(mode=0o755)
        copy = repair / "provider-accounts.invalid.json"
        copy.write_text(repair_value)
        copy.chmod(0o644)

    migrate_home(source, target, archive_source=False)

    for relative, expected_repair in (
        (Path("."), "default-repair"),
        (Path("profiles/ops"), "ops-repair"),
    ):
        profile_home = target / relative
        revision, request_id, source_instance = before[relative]
        restored = accounts.get_account_snapshot(
            home=profile_home,
            provider_id="openai-codex",
        )
        restored_instance = json.loads(
            (profile_home / accounts.STATE_FILENAME).read_text()
        )["store_instance_id"]
        assert restored_instance != source_instance
        assert restored.revision == revision + 1
        assert restored.active_request_id == request_id
        assert restored.oauth_lease is None
        assert restored.oauth_completion is None
        assert (
            profile_home / ".provider-account-repair/provider-accounts.invalid.json"
        ).read_text() == expected_repair
        assert (
            profile_home / accounts.STATE_FILENAME
        ).stat().st_mode & 0o777 == 0o600
        assert (
            profile_home / ".provider-account-repair/provider-accounts.invalid.json"
        ).stat().st_mode & 0o777 == 0o600
    for relative in (
        ".provider-account-repair",
        "profiles/ops/.provider-account-repair",
    ):
        assert (target / relative).stat().st_mode & 0o777 == 0o700
    assert (target / "provider-accounts.lock").read_text() != "runtime-lock"
    assert (
        target / "profiles/ops/provider-accounts.lock"
    ).read_text() != "runtime-lock"
    assert not (target / ".provider-accounts.json.tmp.1234.abcdef").exists()
    assert not (
        target / "profiles/ops/.provider-accounts.json.tmp.1234.abcdef"
    ).exists()


def test_home_migration_verifies_account_state_and_repair_bytes(tmp_path: Path):
    source = tmp_path / "source"
    staging = tmp_path / "staging"
    source.mkdir()
    staging.mkdir()
    (source / "provider-accounts.json").write_text("source-state")
    (staging / "provider-accounts.json").write_text("changed-state")
    source_repair = source / ".provider-account-repair"
    staging_repair = staging / ".provider-account-repair"
    source_repair.mkdir()
    staging_repair.mkdir()
    (source_repair / "invalid.json").write_text("source-repair")
    (staging_repair / "invalid.json").write_text("source-repair")

    with pytest.raises(HomeMigrationError, match="provider-accounts.json"):
        _verify_copy(source, staging, include_old_engine=False)
