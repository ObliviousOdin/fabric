"""Privacy contract for full Fabric backup archives."""

from __future__ import annotations

import os
import stat
import struct
import zipfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest


_PRIVATE_BACKUP_COMMENT = b"fabric-private-full-backup-v1"


def _write_zip(
    path: Path,
    members: dict[str, bytes | str],
    *,
    comment: bytes = b"",
) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
        archive.comment = comment


def _is_private(path: Path, fabric_home: Path) -> bool:
    from fabric_cli.provider_account_privacy import is_private_provider_account_path

    return is_private_provider_account_path(
        path,
        active_home=fabric_home,
        fabric_root=fabric_home,
    )


def _empty_eocd(*, central_offset: int = 0) -> bytes:
    return struct.pack(
        "<4s4H2LH",
        b"PK\x05\x06",
        0,
        0,
        0,
        0,
        0,
        central_offset,
        0,
    )


def _seed_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    (fabric_home / "config.yaml").write_text("model: local\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(fabric_home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return fabric_home


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only")
def test_custom_full_backup_is_marked_private_and_owner_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli.backup import run_backup
    from fabric_cli.provider_account_privacy import is_private_provider_account_path

    fabric_home = _seed_home(tmp_path, monkeypatch)
    archive = tmp_path / "exports" / "customer-copy.zip"

    run_backup(Namespace(output=str(archive)))

    with zipfile.ZipFile(archive, "r") as backup_zip:
        assert backup_zip.comment == _PRIVATE_BACKUP_COMMENT
    assert archive.stat().st_mode & 0o777 == 0o600
    assert is_private_provider_account_path(
        archive,
        active_home=fabric_home,
        fabric_root=fabric_home,
    )


def test_private_marker_survives_an_arbitrary_archive_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli.backup import run_backup
    from fabric_cli.provider_account_privacy import is_private_provider_account_path

    fabric_home = _seed_home(tmp_path, monkeypatch)
    original = tmp_path / "customer-copy.zip"
    renamed = tmp_path / "unrelated-name.payload"
    run_backup(Namespace(output=str(original)))
    original.rename(renamed)

    assert is_private_provider_account_path(
        renamed,
        active_home=fabric_home,
        fabric_root=fabric_home,
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only")
def test_success_replaces_broad_existing_output_with_private_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli.backup import run_backup

    _seed_home(tmp_path, monkeypatch)
    archive = tmp_path / "customer-copy.zip"
    archive.write_bytes(b"old public archive")
    archive.chmod(0o644)

    run_backup(Namespace(output=str(archive)))

    assert archive.stat().st_mode & 0o777 == 0o600
    with zipfile.ZipFile(archive, "r") as backup_zip:
        assert backup_zip.comment == _PRIVATE_BACKUP_COMMENT


def test_unmarked_unmanaged_zip_is_not_misclassified(
    tmp_path: Path,
) -> None:
    from fabric_cli.provider_account_privacy import is_private_provider_account_path

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    archive = tmp_path / "ordinary-project.zip"
    with zipfile.ZipFile(archive, "w") as ordinary_zip:
        ordinary_zip.writestr("config.yaml", "not a Fabric backup marker\n")

    assert not is_private_provider_account_path(
        archive,
        active_home=fabric_home,
        fabric_root=fabric_home,
    )


def test_inflight_private_archive_is_blocked_and_excluded_from_nested_backup(
    tmp_path: Path,
) -> None:
    from fabric_cli.backup import _should_exclude
    from fabric_cli.provider_account_privacy import is_private_provider_account_path

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    staging_name = ".fabric-private-backup-1234-deadbeef.zip"
    staging_archive = tmp_path / staging_name
    staging_archive.write_bytes(b"incomplete private backup")

    assert is_private_provider_account_path(
        staging_archive,
        active_home=fabric_home,
        fabric_root=fabric_home,
    )
    assert _should_exclude(Path(staging_name))


def test_marked_custom_backup_is_blocked_from_model_and_gateway_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent.file_safety import get_read_block_error
    from fabric_cli.backup import run_backup
    from gateway.platforms.base import BasePlatformAdapter

    fabric_home = _seed_home(tmp_path, monkeypatch)
    created_archive = tmp_path / "allowed-media" / "customer-copy.zip"
    archive = created_archive.with_suffix(".payload")
    run_backup(Namespace(output=str(created_archive)))
    created_archive.rename(archive)

    with (
        patch("agent.file_safety._hermes_home_path", return_value=fabric_home),
        patch("agent.file_safety._hermes_root_path", return_value=fabric_home),
    ):
        assert get_read_block_error(str(archive)) is not None

    # Private classification must beat even an explicit gateway media allowlist.
    monkeypatch.setattr("gateway.platforms.base._HERMES_HOME", fabric_home)
    monkeypatch.setattr("gateway.platforms.base._HERMES_ROOT", fabric_home)
    monkeypatch.setattr(
        "gateway.platforms.base.MEDIA_DELIVERY_SAFE_ROOTS",
        (archive.parent,),
    )
    monkeypatch.setenv("HERMES_MEDIA_DELIVERY_STRICT", "1")
    monkeypatch.setenv("HERMES_MEDIA_TRUST_RECENT_FILES", "0")
    assert BasePlatformAdapter.validate_media_delivery_path(str(archive)) is None


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only")
def test_full_zip_helper_marks_and_hardens_arbitrary_output(
    tmp_path: Path,
) -> None:
    from fabric_cli.backup import _write_full_zip_backup
    from fabric_cli.provider_account_privacy import is_private_provider_account_path

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    (fabric_home / "config.yaml").write_text("model: local\n", encoding="utf-8")
    archive = tmp_path / "exports" / "migration-safety-copy"
    archive.parent.mkdir()

    result = _write_full_zip_backup(archive, fabric_home)

    assert result == archive
    assert archive.stat().st_mode & 0o777 == 0o600
    assert is_private_provider_account_path(
        archive,
        active_home=fabric_home,
        fabric_root=fabric_home,
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX hardening path only")
def test_run_backup_fails_closed_when_private_hardening_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fabric_cli.backup as backup_module

    _seed_home(tmp_path, monkeypatch)
    archive = tmp_path / "customer-copy.zip"

    def fail_chmod(_fd: int, _mode: int) -> None:
        raise PermissionError("private mode unavailable")

    monkeypatch.setattr(backup_module.os, "fchmod", fail_chmod)

    with pytest.raises(PermissionError, match="private mode unavailable"):
        backup_module.run_backup(Namespace(output=str(archive)))

    assert not archive.exists()
    assert list(tmp_path.glob(".fabric-private-backup-*.zip")) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX hardening path only")
def test_full_zip_helper_returns_none_when_private_hardening_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fabric_cli.backup as backup_module

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    (fabric_home / "config.yaml").write_text("model: local\n", encoding="utf-8")
    archive = tmp_path / "customer-copy.zip"
    archive.write_bytes(b"prior-good-backup")

    def fail_hardening(_path: Path, *, parent_fd: int | None) -> int:
        del parent_fd
        raise PermissionError("private mode unavailable")

    monkeypatch.setattr(
        backup_module,
        "_open_private_staging_file",
        fail_hardening,
    )

    assert backup_module._write_full_zip_backup(archive, fabric_home) is None
    assert archive.read_bytes() == b"prior-good-backup"
    assert list(tmp_path.glob(".fabric-private-backup-*.zip")) == []


@pytest.mark.parametrize(
    "member",
    [
        ".env",
        "auth.json",
        "provider-accounts.json",
        ".provider-account-repair/invalid.json",
        "profiles/ops/provider-accounts.json",
    ],
)
def test_sensitive_archive_members_are_private_without_marker_or_comment(
    tmp_path: Path,
    member: str,
) -> None:
    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    archive = tmp_path / "renamed.payload"
    _write_zip(archive, {member: b"private bytes"})

    assert _is_private(archive, fabric_home)


def test_full_backup_shape_remains_private_after_marker_metadata_is_removed(
    tmp_path: Path,
) -> None:
    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    archive = tmp_path / "unlabelled.data"
    _write_zip(
        archive,
        {
            "config.yaml": "model: local\n",
            "sessions/one.json": "{}",
            "skills/custom/SKILL.md": "# Custom\n",
        },
    )

    assert _is_private(archive, fabric_home)


def test_registry_keeps_same_archive_identity_private_after_metadata_scrub_and_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli.backup import run_backup

    fabric_home = _seed_home(tmp_path, monkeypatch)
    archive = tmp_path / "registered.zip"
    renamed = tmp_path / "ordinary-looking.data"
    run_backup(Namespace(output=str(archive)))

    # write_bytes truncates the same inode: archive metadata and ZIP structure
    # are gone, but the protected publication identity must still classify it.
    archive.write_bytes(b"metadata deliberately stripped")
    archive.rename(renamed)

    assert _is_private(renamed, fabric_home)


def test_appended_trailing_bytes_fail_closed(tmp_path: Path) -> None:
    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    archive = tmp_path / "ordinary.payload"
    _write_zip(archive, {"README.md": "safe"})
    with archive.open("ab") as handle:
        handle.write(b"unreferenced trailing payload")

    assert _is_private(archive, fabric_home)


def test_prepended_stub_and_extension_rename_fail_closed(tmp_path: Path) -> None:
    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    archive = tmp_path / "ordinary.payload"
    staged = tmp_path / "private.zip"
    _write_zip(staged, {"auth.json": "private"})
    archive.write_bytes(b"self-extracting-stub\n" + staged.read_bytes())

    assert _is_private(archive, fabric_home)


def test_multiple_eocd_records_fail_closed(tmp_path: Path) -> None:
    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    archive = tmp_path / "ordinary.payload"
    _write_zip(archive, {"README.md": "safe"})
    with archive.open("ab") as handle:
        handle.write(_empty_eocd())

    assert _is_private(archive, fabric_home)


def test_alternate_eocd_beyond_standard_search_window_fails_closed(
    tmp_path: Path,
) -> None:
    from fabric_cli.provider_account_privacy import _ZIP_MAX_EOCD_SIZE

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    archive = tmp_path / "ordinary.payload"
    _write_zip(archive, {"auth.json": "private"})
    padding = b"x" * (_ZIP_MAX_EOCD_SIZE + 257)
    eocd_offset = archive.stat().st_size + len(padding)
    with archive.open("ab") as handle:
        handle.write(padding)
        handle.write(_empty_eocd(central_offset=eocd_offset))

    assert _is_private(archive, fabric_home)


@pytest.mark.skipif(os.name == "nt", reason="avoid allocating a 5 GiB NTFS test file")
def test_huge_sparse_archive_classification_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import provider_account_privacy as privacy

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    archive = tmp_path / "sparse.payload"
    with archive.open("wb") as handle:
        handle.write(b"PK\x03\x04")
        handle.truncate(5 * 1024 * 1024 * 1024)

    requested: list[int] = []
    original_read_at = privacy.PinnedFileCapability.read_at

    def tracked_read_at(self, offset: int, size: int) -> bytes:
        requested.append(size)
        return original_read_at(self, offset, size)

    monkeypatch.setattr(privacy.PinnedFileCapability, "read_at", tracked_read_at)

    assert _is_private(archive, fabric_home)
    assert sum(requested) <= privacy._ZIP_MAX_EOCD_SIZE + 4


def test_similarly_named_non_archive_is_not_private(tmp_path: Path) -> None:
    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    ordinary = tmp_path / "hermes-backup-project-notes.payload"
    ordinary.write_text("This is a normal project report, not an archive.\n")

    assert not _is_private(ordinary, fabric_home)


def test_similarly_named_valid_project_zip_is_not_private(tmp_path: Path) -> None:
    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    ordinary = tmp_path / "hermes-backup-project.zip"
    _write_zip(ordinary, {"config.yaml": "project-local: true\n"})

    assert not _is_private(ordinary, fabric_home)


def test_nested_private_archive_is_excluded_but_similar_project_zip_is_kept(
    tmp_path: Path,
) -> None:
    from fabric_cli.backup import _write_full_zip_backup

    fabric_home = tmp_path / ".fabric"
    nested = fabric_home / "exports"
    nested.mkdir(parents=True)
    private_archive = nested / "renamed.data"
    project_archive = nested / "hermes-backup-project.zip"
    _write_zip(
        private_archive,
        {"sessions/one.json": "{}", "skills/custom/SKILL.md": "# skill"},
    )
    _write_zip(project_archive, {"config.yaml": "project: true\n"})
    (fabric_home / "config.yaml").write_text("model: local\n")
    output = tmp_path / "outer.zip"

    assert _write_full_zip_backup(output, fabric_home) == output
    with zipfile.ZipFile(output) as backup_zip:
        names = set(backup_zip.namelist())
    assert "exports/renamed.data" not in names
    assert "exports/hermes-backup-project.zip" in names


def test_pinned_capability_rejects_path_replacement_and_in_place_mutation(
    tmp_path: Path,
) -> None:
    from fabric_cli.provider_account_privacy import (
        PinnedFileCapability,
        PinnedPathError,
    )

    path = tmp_path / "report.txt"
    path.write_text("safe")
    with PinnedFileCapability.open(path) as capability:
        original = tmp_path / "original.txt"
        path.rename(original)
        path.write_text("replacement secret")
        with pytest.raises(PinnedPathError, match="path_changed"):
            capability.read_bytes()

    path.write_text("safe again")
    with PinnedFileCapability.open(path) as capability:
        path.write_text("mutated")
        with pytest.raises(PinnedPathError, match="path_changed"):
            capability.read_bytes()


def test_model_read_rejects_replacement_between_policy_check_and_consumption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from fabric_cli import provider_account_privacy as privacy
    from tools.file_tools import clear_file_ops_cache, read_file_tool

    path = tmp_path / "report.txt"
    path.write_text("safe payload\n")
    original_classify = privacy.classify_pinned_provider_account_path
    swapped = False

    def classify_then_swap(capability, *, active_home: Path, fabric_root: Path):
        nonlocal swapped
        result = original_classify(
            capability,
            active_home=active_home,
            fabric_root=fabric_root,
        )
        if not swapped:
            swapped = True
            path.rename(tmp_path / "original.txt")
            path.write_text("replacement secret\n")
        return result

    monkeypatch.setattr(
        privacy,
        "classify_pinned_provider_account_path",
        classify_then_swap,
    )
    clear_file_ops_cache("backup-privacy-read")

    result = json.loads(read_file_tool(str(path), task_id="backup-privacy-read"))

    assert "error" in result
    assert "path_changed" in result["error"]
    assert "replacement secret" not in result["error"]


def test_model_read_rejects_replacement_during_policy_evaluation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent.file_safety import pinned_model_read
    from fabric_cli import provider_account_privacy as privacy

    path = tmp_path / "report.txt"
    path.write_text("safe payload\n")
    original_classify = privacy.classify_pinned_provider_account_path

    def swap_then_classify(capability, *, active_home: Path, fabric_root: Path):
        path.rename(tmp_path / "original.txt")
        path.write_text("replacement secret\n")
        return original_classify(
            capability,
            active_home=active_home,
            fabric_root=fabric_root,
        )

    monkeypatch.setattr(
        privacy,
        "classify_pinned_provider_account_path",
        swap_then_classify,
    )

    with pinned_model_read(str(path)) as (capability, error):
        assert capability is None
        assert error is not None
        assert "changed" in error


def test_gateway_materialization_consumes_the_pinned_source_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli.provider_account_privacy import PinnedFileCapability
    from gateway.platforms import base

    source = tmp_path / "report.txt"
    source.write_text("safe payload")
    cache = tmp_path / "cache"
    monkeypatch.setattr(base, "get_document_cache_dir", lambda: cache)
    monkeypatch.setattr(base, "MEDIA_DELIVERY_SAFE_ROOTS", (tmp_path,))
    original_copy = PinnedFileCapability.copy_to_private_directory

    def replace_before_copy(self, directory: Path) -> Path:
        moved = source.with_suffix(".original")
        source.rename(moved)
        source.write_text("replacement secret")
        return original_copy(self, directory)

    monkeypatch.setattr(
        PinnedFileCapability,
        "copy_to_private_directory",
        replace_before_copy,
    )

    assert base.materialize_media_delivery_path(str(source)) is None
    assert not any(path.is_file() for path in cache.rglob("*"))
    assert not any(path.name.startswith("validated-") for path in cache.rglob("*"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory-fd swap barrier")
def test_gateway_materialization_rejects_snapshot_root_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from fabric_cli.provider_account_privacy import PinnedFileCapability
    from gateway.platforms import base

    source = tmp_path / "report.txt"
    source.write_text("safe payload")
    cache = tmp_path / "cache"
    snapshot_root = cache / ".validated-delivery"
    moved_root = cache / ".validated-delivery-original"
    monkeypatch.setattr(base, "get_document_cache_dir", lambda: cache)
    monkeypatch.setattr(base, "MEDIA_DELIVERY_SAFE_ROOTS", (tmp_path,))
    original_reader = PinnedFileCapability.open_reader

    @contextmanager
    def swap_snapshot_root(self):
        snapshot_root.rename(moved_root)
        snapshot_root.mkdir(mode=0o700)
        with original_reader(self) as reader:
            yield reader

    monkeypatch.setattr(PinnedFileCapability, "open_reader", swap_snapshot_root)

    assert base.materialize_media_delivery_path(str(source)) is None
    assert not any(path.is_file() for path in moved_root.rglob("*"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink swap semantics")
def test_gateway_registration_rejects_snapshot_swap_after_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli.provider_account_privacy import PinnedFileCapability
    from gateway.platforms import base

    source = tmp_path / "report.txt"
    source.write_text("safe payload")
    secret = tmp_path / "secret.txt"
    secret.write_text("must not be registered")
    cache = tmp_path / "cache"
    monkeypatch.setattr(base, "get_document_cache_dir", lambda: cache)
    monkeypatch.setattr(base, "MEDIA_DELIVERY_SAFE_ROOTS", (tmp_path,))
    original_copy = PinnedFileCapability.copy_to_private_directory

    def swap_after_copy(self, directory: Path) -> Path:
        snapshot = original_copy(self, directory)
        snapshot.rename(snapshot.with_name("original-snapshot"))
        snapshot.symlink_to(secret)
        return snapshot

    monkeypatch.setattr(
        PinnedFileCapability,
        "copy_to_private_directory",
        swap_after_copy,
    )

    assert base.materialize_media_delivery_path(str(source)) is None
    assert secret.read_text() == "must not be registered"
    assert not any(path.is_symlink() for path in cache.rglob("*"))


def test_gateway_inline_read_consumes_the_pinned_source_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli.provider_account_privacy import PinnedFileCapability
    from gateway.platforms import base

    source = tmp_path / "image.png"
    source.write_bytes(b"safe image")
    monkeypatch.setattr(base, "MEDIA_DELIVERY_SAFE_ROOTS", (tmp_path,))
    original_read = PinnedFileCapability.read_bytes

    def replace_before_read(self, *, max_bytes: int | None = None) -> bytes:
        source.rename(tmp_path / "original.png")
        source.write_bytes(b"replacement secret")
        return original_read(self, max_bytes=max_bytes)

    monkeypatch.setattr(PinnedFileCapability, "read_bytes", replace_before_read)

    assert base.read_media_delivery_bytes(str(source), max_bytes=1024) is None


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink swap semantics")
async def test_gateway_revalidates_materialized_snapshot_at_adapter_send_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gateway.platforms import base

    source = tmp_path / "report.txt"
    source.write_text("safe payload")
    secret = tmp_path / "source-secret.txt"
    secret.write_text("must never be uploaded")
    cache = tmp_path / "cache"
    monkeypatch.setattr(base, "get_document_cache_dir", lambda: cache)
    monkeypatch.setattr(base, "MEDIA_DELIVERY_SAFE_ROOTS", (tmp_path,))

    class BoundaryProbeAdapter(base.BasePlatformAdapter):
        name = "boundary-probe"

        def __init__(self):
            self.observed: bytes | None = None

        async def connect(self, *, is_reconnect: bool = False) -> bool:
            return True

        async def disconnect(self) -> None:
            return None

        async def send(self, chat_id, content, reply_to=None, metadata=None):
            return base.SendResult(success=True)

        async def get_chat_info(self, chat_id):
            return {"name": "probe", "type": "dm"}

        async def send_document(self, chat_id, file_path, **kwargs):
            self.observed = Path(file_path).read_bytes()
            return base.SendResult(success=True)

    snapshot_text = base.materialize_media_delivery_path(str(source))
    assert snapshot_text is not None
    snapshot = Path(snapshot_text)
    original_snapshot = snapshot.with_name("original-snapshot")
    snapshot.rename(original_snapshot)
    snapshot.symlink_to(secret)

    adapter = BoundaryProbeAdapter()
    result = await adapter.send_document("chat", snapshot_text)

    assert not result.success
    assert adapter.observed is None


@pytest.mark.skipif(os.name != "posix", reason="POSIX publication transaction")
def test_publication_reports_rolled_back_before_replace_and_preserves_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import backup

    root = tmp_path / ".fabric"
    root.mkdir()
    target = tmp_path / "backup.zip"
    target.write_bytes(b"prior-good")

    def fail_replace(*_args, **_kwargs) -> None:
        raise OSError("replace did not happen")

    monkeypatch.setattr(backup, "_replace_private_backup", fail_replace)
    transaction = None
    with pytest.raises(OSError, match="replace did not happen"):
        with backup._private_backup_zip(target, registry_root=root) as transaction:
            transaction.writestr("config.yaml", "model: local\n")

    assert transaction is not None
    assert transaction.result is not None
    assert transaction.result.state is backup.BackupPublicationState.ROLLED_BACK
    assert target.read_bytes() == b"prior-good"
    assert not list(tmp_path.glob(".fabric-private-backup-*.zip"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX file fsync contract")
def test_archive_file_fsync_failure_rolls_back_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import backup

    root = tmp_path / ".fabric"
    root.mkdir()
    target = tmp_path / "backup.zip"
    target.write_bytes(b"prior-good")

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("archive fsync failed")

    monkeypatch.setattr(backup.os, "fsync", fail_fsync)
    transaction = None
    with pytest.raises(OSError, match="archive fsync failed"):
        with backup._private_backup_zip(target, registry_root=root) as transaction:
            transaction.writestr("config.yaml", "model: local\n")

    assert transaction is not None
    assert transaction.result is not None
    assert transaction.result.state is backup.BackupPublicationState.ROLLED_BACK
    assert target.read_bytes() == b"prior-good"


@pytest.mark.skipif(os.name != "posix", reason="POSIX publication transaction")
def test_post_effect_baseexception_is_reconciled_as_committed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import backup

    root = tmp_path / ".fabric"
    root.mkdir()
    target = tmp_path / "backup.zip"
    original_replace = backup._replace_private_backup

    def replace_then_interrupt(*args, **kwargs) -> None:
        original_replace(*args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(backup, "_replace_private_backup", replace_then_interrupt)
    with backup._private_backup_zip(target, registry_root=root) as transaction:
        transaction.writestr("config.yaml", "model: local\n")

    assert transaction.result is not None
    assert transaction.result.state is backup.BackupPublicationState.COMMITTED
    assert zipfile.is_zipfile(target)


@pytest.mark.skipif(os.name != "posix", reason="POSIX publication transaction")
def test_post_replace_fsync_failure_is_uncertain_and_reconciles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import backup

    root = tmp_path / ".fabric"
    root.mkdir()
    target = tmp_path / "backup.zip"
    original_fsync = backup._fsync_output_parent

    def fail_parent_fsync(_parent: Path, _parent_fd: int | None) -> None:
        raise OSError("parent fsync failed")

    monkeypatch.setattr(backup, "_fsync_output_parent", fail_parent_fsync)
    with pytest.raises(backup.BackupPublicationUncertain) as caught:
        with backup._private_backup_zip(target, registry_root=root) as transaction:
            transaction.writestr("config.yaml", "model: local\n")

    assert caught.value.result.state is backup.BackupPublicationState.UNCERTAIN
    assert transaction.result == caught.value.result
    assert zipfile.is_zipfile(target)
    journal = backup._publication_journal_path(root, target)
    assert journal.exists()

    monkeypatch.setattr(backup, "_fsync_output_parent", original_fsync)
    reconciled = backup._reconcile_publication(out_path=target, registry_root=root)
    assert reconciled is not None
    assert reconciled.state is backup.BackupPublicationState.COMMITTED
    assert not journal.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX replacement timing")
def test_target_replacement_during_registration_is_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import backup

    root = tmp_path / ".fabric"
    root.mkdir()
    target = tmp_path / "backup.zip"
    original_register = backup.register_private_backup

    def register_then_replace(path: Path, *, fabric_root: Path) -> Path:
        record = original_register(path, fabric_root=fabric_root)
        path.rename(tmp_path / "published-but-replaced.zip")
        path.write_bytes(b"replacement")
        return record

    monkeypatch.setattr(backup, "register_private_backup", register_then_replace)

    with pytest.raises(backup.BackupPublicationUncertain) as caught:
        with backup._private_backup_zip(target, registry_root=root) as transaction:
            transaction.writestr("config.yaml", "model: local\n")

    assert caught.value.result.state is backup.BackupPublicationState.UNCERTAIN
    assert transaction.result == caught.value.result
    assert target.read_bytes() == b"replacement"


def test_forged_recovery_journal_cannot_delete_an_unrelated_file(
    tmp_path: Path,
) -> None:
    import json

    from fabric_cli import backup

    root = tmp_path / ".fabric"
    root.mkdir()
    target = tmp_path / "backup.zip"
    victim = tmp_path / "unrelated.txt"
    victim.write_text("must survive")
    victim_stat = victim.stat()
    journal = backup._publication_journal_path(root, target)
    journal.parent.mkdir(parents=True)
    journal.write_text(
        json.dumps({
            "version": 1,
            "operation_id": "a" * 32,
            "target": os.fspath(target),
            "temporary": os.fspath(victim),
            "staged_device": victim_stat.st_dev,
            "staged_inode": victim_stat.st_ino,
            "staged_size": victim_stat.st_size,
            "phase": "prepared",
        })
    )

    with pytest.raises(backup.BackupPublicationUncertain) as caught:
        backup._reconcile_publication(out_path=target, registry_root=root)

    assert caught.value.result.state is backup.BackupPublicationState.UNCERTAIN
    assert victim.read_text() == "must survive"


def test_publication_lock_serializes_same_target(
    tmp_path: Path,
) -> None:
    import threading

    from fabric_cli import backup

    root = tmp_path / ".fabric"
    root.mkdir()
    target = tmp_path / "backup.zip"
    started = threading.Event()
    acquired = threading.Event()
    errors: list[BaseException] = []

    def contender() -> None:
        started.set()
        try:
            with backup._publication_lock(root, target):
                acquired.set()
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    with backup._publication_lock(root, target):
        thread = threading.Thread(target=contender)
        thread.start()
        assert started.wait(1)
        assert not acquired.wait(0.05)

    assert acquired.wait(2)
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert errors == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX publication transaction")
def test_baseexception_during_archive_build_is_rolled_back(
    tmp_path: Path,
) -> None:
    from fabric_cli import backup

    root = tmp_path / ".fabric"
    root.mkdir()
    target = tmp_path / "backup.zip"
    target.write_bytes(b"prior-good")
    transaction = None

    with pytest.raises(KeyboardInterrupt):
        with backup._private_backup_zip(target, registry_root=root) as transaction:
            transaction.writestr("config.yaml", "model: local\n")
            raise KeyboardInterrupt

    assert transaction is not None
    assert transaction.result is not None
    assert transaction.result.state is backup.BackupPublicationState.ROLLED_BACK
    assert target.read_bytes() == b"prior-good"


@pytest.mark.skipif(os.name != "posix", reason="POSIX path-swap barrier")
def test_publication_rejects_parent_directory_swap_before_replace(
    tmp_path: Path,
) -> None:
    from fabric_cli import backup

    root = tmp_path / ".fabric"
    root.mkdir()
    parent = tmp_path / "exports"
    parent.mkdir()
    target = parent / "backup.zip"
    moved_parent = tmp_path / "exports-original"

    with pytest.raises(OSError, match="output parent changed"):
        with backup._private_backup_zip(target, registry_root=root) as transaction:
            transaction.writestr("config.yaml", "model: local\n")
            parent.rename(moved_parent)
            parent.mkdir()

    assert not target.exists()
    assert not (moved_parent / "backup.zip").exists()
    assert not list(moved_parent.glob(".fabric-private-backup-*.zip"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink semantics")
def test_run_backup_replaces_output_symlink_without_touching_its_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli.backup import run_backup

    _seed_home(tmp_path, monkeypatch)
    victim = tmp_path / "victim.zip"
    victim.write_bytes(b"do not overwrite")
    output = tmp_path / "requested.zip"
    output.symlink_to(victim)

    run_backup(Namespace(output=str(output)))

    assert victim.read_bytes() == b"do not overwrite"
    assert not output.is_symlink()
    assert zipfile.is_zipfile(output)


@pytest.mark.skipif(os.name != "nt", reason="native Windows DACL workflow")
def test_windows_full_backup_is_private_before_and_after_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import provider_accounts
    from fabric_cli.backup import _private_backup_zip

    root = tmp_path / ".fabric"
    root.mkdir()
    target = tmp_path / "backup.zip"
    original_private_open = provider_accounts._windows_open_private_file
    private_before_write: list[Path] = []
    delete_shared_staging: list[Path] = []

    def checked_private_open(
        path: Path,
        *,
        create_new: bool,
        share_delete: bool = False,
        share_write: bool = True,
        open_existing: bool = False,
    ) -> int:
        descriptor = original_private_open(
            path,
            create_new=create_new,
            share_delete=share_delete,
            share_write=share_write,
            open_existing=open_existing,
        )
        assert provider_accounts._windows_private_fd(descriptor, apply=False)
        if create_new:
            assert os.fstat(descriptor).st_size == 0
            if share_delete:
                delete_shared_staging.append(path)
        private_before_write.append(path)
        return descriptor

    monkeypatch.setattr(
        provider_accounts,
        "_windows_open_private_file",
        checked_private_open,
    )
    with _private_backup_zip(target, registry_root=root) as transaction:
        transaction.writestr("config.yaml", "model: local\n")

    assert private_before_write
    assert any(
        path.name.startswith(".fabric-private-backup-")
        for path in delete_shared_staging
    )
    fd = os.open(target, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        assert provider_accounts._windows_private_fd(fd, apply=False)
    finally:
        os.close(fd)


def test_concatenated_private_zip_with_large_prefix_is_detected_with_bounded_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import provider_account_privacy as privacy

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    inner = tmp_path / "inner.zip"
    archive = tmp_path / "renamed.payload"
    _write_zip(inner, {"auth.json": "private"})
    archive.write_bytes((b"self-extracting-stub\n" * 8192) + inner.read_bytes())
    assert archive.stat().st_size - inner.stat().st_size > 64 * 1024
    with zipfile.ZipFile(archive) as stdlib_zip:
        assert stdlib_zip.namelist() == ["auth.json"]

    requested: list[int] = []
    original_read_at = privacy.PinnedFileCapability.read_at

    def tracked_read_at(self, offset: int, size: int) -> bytes:
        requested.append(size)
        return original_read_at(self, offset, size)

    monkeypatch.setattr(privacy.PinnedFileCapability, "read_at", tracked_read_at)

    assert _is_private(archive, fabric_home)
    assert sum(requested) <= (
        privacy._ZIP_MAX_EOCD_SIZE
        + privacy._ZIP_MAX_CENTRAL_BYTES
        + 128 * privacy._ZIP_MAX_ENTRIES
    )


def test_nul_truncated_member_alias_matches_stdlib_and_is_private(
    tmp_path: Path,
) -> None:
    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    archive = tmp_path / "renamed.payload"
    placeholder = "x" * len("auth.json\x00.txt")
    _write_zip(archive, {placeholder: "private"})
    payload = archive.read_bytes().replace(
        placeholder.encode("ascii"),
        b"auth.json\x00.txt",
    )
    archive.write_bytes(payload)

    with zipfile.ZipFile(archive) as stdlib_zip:
        assert stdlib_zip.namelist() == ["auth.json"]
    assert _is_private(archive, fabric_home)


def test_full_backup_shape_under_one_common_wrapper_is_private(
    tmp_path: Path,
) -> None:
    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    archive = tmp_path / "wrapped.payload"
    _write_zip(
        archive,
        {
            "customer-export/config.yaml": "model: local\n",
            "customer-export/sessions/one.json": "{}",
            "customer-export/skills/custom/SKILL.md": "# Custom\n",
        },
    )

    assert _is_private(archive, fabric_home)


def test_ordinary_directory_is_not_private_and_directory_search_is_not_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent import file_safety

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    project = tmp_path / "ordinary-project"
    project.mkdir()
    (project / "notes.txt").write_text("searchable\n")
    monkeypatch.setattr(file_safety, "_hermes_home_path", lambda: fabric_home)
    monkeypatch.setattr(file_safety, "_hermes_root_path", lambda: fabric_home)

    assert not _is_private(project, fabric_home)
    assert file_safety.get_read_block_error(str(project)) is None


def test_nested_archive_replacement_after_classification_cannot_enter_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import backup
    from fabric_cli import provider_account_privacy as privacy

    fabric_home = tmp_path / ".fabric"
    nested = fabric_home / "exports"
    nested.mkdir(parents=True)
    candidate = nested / "candidate.payload"
    private_replacement = tmp_path / "private-replacement.zip"
    _write_zip(candidate, {"README.md": "safe"})
    _write_zip(private_replacement, {"auth.json": "must not enter outer backup"})
    (fabric_home / "config.yaml").write_text("model: local\n")
    output = tmp_path / "outer.zip"
    original_disposition = privacy._zip_archive_disposition
    replaced = False

    def classify_then_replace(capability):
        nonlocal replaced
        result = original_disposition(capability)
        if capability.requested_path == candidate.resolve() and not replaced:
            replaced = True
            candidate.rename(tmp_path / "original-candidate.zip")
            candidate.write_bytes(private_replacement.read_bytes())
        return result

    monkeypatch.setattr(
        privacy,
        "_zip_archive_disposition",
        classify_then_replace,
    )

    assert backup._write_full_zip_backup(output, fabric_home) == output
    assert replaced
    with zipfile.ZipFile(output) as outer:
        assert "exports/candidate.payload" not in outer.namelist()


@pytest.mark.skipif(os.name != "posix", reason="POSIX staged-inode semantics")
def test_staged_path_replacement_cannot_commit_different_hardlinked_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import backup

    root = tmp_path / ".fabric"
    root.mkdir()
    target = tmp_path / "backup.zip"
    attacker = tmp_path / "attacker.zip"
    _write_zip(attacker, {"auth.json": "different bytes"})
    original_commit = backup._commit_private_backup

    def replace_then_commit(**kwargs):
        temporary = kwargs["temporary"]
        temporary.rename(tmp_path / "actual-staged.zip")
        os.link(attacker, temporary)
        return original_commit(**kwargs)

    monkeypatch.setattr(backup, "_commit_private_backup", replace_then_commit)

    transaction = None
    with pytest.raises((OSError, backup.BackupPublicationUncertain)):
        with backup._private_backup_zip(target, registry_root=root) as transaction:
            transaction.writestr("config.yaml", "model: local\n")

    assert transaction is not None
    assert transaction.result is not None
    assert transaction.result.state is not backup.BackupPublicationState.COMMITTED
    assert not target.exists()
    assert attacker.stat().st_nlink == 2


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-lock semantics")
def test_publication_lock_survives_lock_leaf_rename_and_replacement(
    tmp_path: Path,
) -> None:
    import subprocess
    import sys
    import time

    from fabric_cli import backup

    root = tmp_path / ".fabric"
    root.mkdir()
    target = tmp_path / "backup.zip"
    journal = backup._publication_journal_path(root, target)
    lock_path = journal.with_suffix(".lock")
    ready = tmp_path / "contender-ready"
    acquired = tmp_path / "contender-acquired"
    script = """
import sys
from pathlib import Path
from fabric_cli import backup
root, target, ready, acquired = map(Path, sys.argv[1:])
ready.write_text("ready")
with backup._publication_lock(root, target):
    acquired.write_text("acquired")
"""

    with backup._publication_lock(root, target):
        moved = lock_path.with_suffix(".moved")
        lock_path.rename(moved)
        lock_path.write_bytes(b"replacement")
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                os.fspath(root),
                os.fspath(target),
                os.fspath(ready),
                os.fspath(acquired),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 2
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        time.sleep(0.1)
        assert not acquired.exists()

    stdout, stderr = process.communicate(timeout=2)
    assert process.returncode == 0, (stdout, stderr)
    assert acquired.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner-only mode contract")
def test_quick_snapshot_tree_is_owner_only_with_umask_zero(
    tmp_path: Path,
) -> None:
    from fabric_cli.backup import create_quick_snapshot

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir(mode=0o700)
    (fabric_home / "config.yaml").write_text("model: local\n")
    previous_umask = os.umask(0)
    try:
        snapshot_id = create_quick_snapshot(hermes_home=fabric_home)
    finally:
        os.umask(previous_umask)

    assert snapshot_id is not None
    root = fabric_home / "state-snapshots"
    snapshot = root / snapshot_id
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o700
    for directory in (path for path in snapshot.rglob("*") if path.is_dir()):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for file_path in (path for path in snapshot.rglob("*") if path.is_file()):
        assert stat.S_IMODE(file_path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX pre-byte mode contract")
def test_quick_snapshot_regular_file_is_private_before_first_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import backup

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir(mode=0o700)
    (fabric_home / "config.yaml").write_text("model: local\n")
    original_copy = backup._copy_to_private_descriptor
    observed: list[Path] = []

    def checked_copy(path: Path, descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        assert metadata.st_size == 0
        assert stat.S_IMODE(metadata.st_mode) == 0o600
        observed.append(path)
        original_copy(path, descriptor)

    monkeypatch.setattr(backup, "_copy_to_private_descriptor", checked_copy)

    snapshot_id = backup.create_quick_snapshot(hermes_home=fabric_home)

    assert snapshot_id is not None
    assert any(path.name == "config.yaml" for path in observed)


@pytest.mark.skipif(os.name != "nt", reason="native Windows DACL workflow")
def test_windows_quick_and_db_staging_apply_dacl_before_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import backup, provider_accounts

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    (fabric_home / "config.yaml").write_text("model: local\n")
    database = fabric_home / "state.db"
    import sqlite3

    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE proof (value TEXT)")
    connection.commit()
    connection.close()
    original_open = provider_accounts._windows_open_private_file
    created: list[Path] = []

    def checked_open(
        path: Path,
        *,
        create_new: bool,
        share_delete: bool = False,
        share_write: bool = True,
        open_existing: bool = False,
    ) -> int:
        descriptor = original_open(
            path,
            create_new=create_new,
            share_delete=share_delete,
            share_write=share_write,
            open_existing=open_existing,
        )
        assert provider_accounts._windows_private_fd(descriptor, apply=False)
        if create_new:
            assert os.fstat(descriptor).st_size == 0
            created.append(path)
        return descriptor

    monkeypatch.setattr(
        provider_accounts,
        "_windows_open_private_file",
        checked_open,
    )

    snapshot_id = backup.create_quick_snapshot(hermes_home=fabric_home)
    output = tmp_path / "full.zip"
    assert backup._write_full_zip_backup(output, fabric_home) == output

    assert snapshot_id is not None
    assert any(path.name == "config.yaml" for path in created)
    assert any(path.name.startswith(".fabric-private-db-") for path in created)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor delivery aliases")
@pytest.mark.parametrize(
    "delivery_kind",
    ("document", "image", "video", "voice", "batch"),
)
async def test_gateway_adapter_consumes_registered_object_not_replaced_path(
    delivery_kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from urllib.parse import unquote, urlsplit

    from gateway.platforms import base

    source = tmp_path / "report.txt"
    source.write_bytes(b"registered safe payload")
    secret = tmp_path / "provider-secret.txt"
    secret.write_bytes(b"PROVIDER_PRIVATE_SECRET")
    cache = tmp_path / "cache"
    monkeypatch.setattr(base, "get_document_cache_dir", lambda: cache)
    monkeypatch.setattr(base, "MEDIA_DELIVERY_SAFE_ROOTS", (tmp_path,))

    snapshot_text = base.materialize_media_delivery_path(str(source))
    assert snapshot_text is not None
    snapshot = Path(snapshot_text)
    original_snapshot = snapshot.with_name("registered-original")

    class ExactObjectProbe(base.BasePlatformAdapter):
        name = "exact-object-probe"

        def __init__(self) -> None:
            self.observed: list[bytes] = []

        async def connect(self, *, is_reconnect: bool = False) -> bool:
            return True

        async def disconnect(self) -> None:
            return None

        async def send(self, chat_id, content, reply_to=None, metadata=None):
            return base.SendResult(success=True)

        async def get_chat_info(self, chat_id):
            return {"name": "probe", "type": "dm"}

        def _replace_registered_path(self) -> None:
            if snapshot.exists() and not snapshot.is_symlink():
                snapshot.rename(original_snapshot)
                snapshot.symlink_to(secret)

        def _consume(self, value) -> None:
            self._replace_registered_path()
            self.observed.append(Path(os.fspath(value)).read_bytes())

        async def send_document(self, chat_id, file_path, **kwargs):
            self._consume(file_path)
            return base.SendResult(success=True)

        async def send_image_file(self, chat_id, image_path, **kwargs):
            self._consume(image_path)
            return base.SendResult(success=True)

        async def send_video(self, chat_id, video_path, **kwargs):
            self._consume(video_path)
            return base.SendResult(success=True)

        async def send_voice(self, chat_id, audio_path, **kwargs):
            self._consume(audio_path)
            return base.SendResult(success=True)

        async def send_multiple_images(self, chat_id, images, **kwargs):
            for url, _caption in images:
                parsed = urlsplit(url)
                self._consume(unquote(parsed.path))
            return [base.SendResult(success=True)]

    adapter = ExactObjectProbe()
    if delivery_kind == "document":
        await adapter.send_document("chat", snapshot_text)
    elif delivery_kind == "image":
        await adapter.send_image_file("chat", snapshot_text)
    elif delivery_kind == "video":
        await adapter.send_video("chat", snapshot_text)
    elif delivery_kind == "voice":
        await adapter.send_voice("chat", snapshot_text)
    else:
        await adapter.send_multiple_images(
            "chat",
            [(snapshot.as_uri(), "caption")],
        )

    assert adapter.observed == [b"registered safe payload"]
    assert b"PROVIDER_PRIVATE_SECRET" not in adapter.observed


def test_local_content_search_pins_and_classifies_before_match_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent import file_safety
    from fabric_cli import provider_account_privacy as privacy
    from tools import file_tools
    from tools.file_operations import SearchMatch, SearchResult

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    report = project / "report.txt"
    report.write_text("ordinary report\n")
    private_state = fabric_home / "provider-accounts.json"
    private_state.write_text("SEARCH_PROVIDER_PRIVATE_SECRET\n")
    saved_report = project / "saved-report.txt"
    swapped = False

    class RacingFileOps:
        def search(self, **_kwargs):
            report.rename(saved_report)
            private_state.rename(report)
            observed = report.read_text()
            report.rename(private_state)
            saved_report.rename(report)
            return SearchResult(
                matches=[SearchMatch(str(report), 1, observed.rstrip())],
                total_count=1,
            )

        def list_content_search_candidates(self, **_kwargs):
            return [str(report)]

    original_classify = privacy.classify_pinned_provider_account_path

    def classify_then_replace(capability, **kwargs):
        nonlocal swapped
        result = original_classify(capability, **kwargs)
        if capability.requested_path == report.resolve() and not swapped:
            report.rename(saved_report)
            private_state.rename(report)
            swapped = True
        return result

    monkeypatch.setattr(file_safety, "_hermes_home_path", lambda: fabric_home)
    monkeypatch.setattr(file_safety, "_hermes_root_path", lambda: fabric_home)
    monkeypatch.setattr(
        privacy,
        "classify_pinned_provider_account_path",
        classify_then_replace,
    )
    monkeypatch.setattr(file_tools, "_get_file_ops", lambda _task_id: RacingFileOps())
    monkeypatch.setattr(file_tools, "_terminal_env_type_for_task", lambda _task_id: "local")
    monkeypatch.setattr(
        file_tools,
        "_resolve_path_for_task",
        lambda path, _task_id: Path(path).resolve(),
    )

    try:
        result = file_tools.search_tool(
            "SEARCH_PROVIDER_PRIVATE_SECRET",
            path=str(project),
            task_id="search-race",
        )
    finally:
        if swapped:
            report.rename(private_state)
            saved_report.rename(report)

    assert "SEARCH_PROVIDER_PRIVATE_SECRET" not in result


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-lock semantics")
def test_publication_lock_survives_transaction_directory_replacement(
    tmp_path: Path,
) -> None:
    import subprocess
    import sys
    import time

    from fabric_cli import backup

    root = tmp_path / ".fabric"
    root.mkdir()
    target = tmp_path / "backup.zip"
    journal = backup._publication_journal_path(root, target)
    transaction_dir = journal.parent
    ready = tmp_path / "parent-contender-ready"
    acquired = tmp_path / "parent-contender-acquired"
    script = """
import sys
from pathlib import Path
from fabric_cli import backup
root, target, ready, acquired = map(Path, sys.argv[1:])
ready.write_text("ready")
with backup._publication_lock(root, target):
    acquired.write_text("acquired")
"""

    with backup._publication_lock(root, target):
        moved = transaction_dir.with_name(f"{transaction_dir.name}.moved")
        transaction_dir.rename(moved)
        transaction_dir.mkdir(mode=0o700)
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                os.fspath(root),
                os.fspath(target),
                os.fspath(ready),
                os.fspath(acquired),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 2
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        time.sleep(0.1)
        assert not acquired.exists()

    stdout, stderr = process.communicate(timeout=2)
    assert process.returncode == 0, (stdout, stderr)
    assert acquired.exists()


def test_sqlite_snapshot_writes_only_the_exact_private_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sqlite3

    from fabric_cli import backup

    source = tmp_path / "source.db"
    destination = tmp_path / "snapshot.db"
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"VICTIM_MUST_REMAIN_UNCHANGED")
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE proof (value TEXT)")
    connection.execute("INSERT INTO proof VALUES ('DB_PRIVATE_SECRET')")
    connection.commit()
    connection.close()
    original_connect = backup.sqlite3.connect
    swapped = False

    def connect_then_redirect(database, *args, **kwargs):
        nonlocal swapped
        result = original_connect(database, *args, **kwargs)
        if not swapped and str(database).startswith(f"file:{source}"):
            destination.rename(tmp_path / "exact-private-destination.db")
            destination.symlink_to(victim)
            swapped = True
        return result

    monkeypatch.setattr(backup.sqlite3, "connect", connect_then_redirect)

    assert backup._safe_copy_db(source, destination) is False
    assert victim.read_bytes() == b"VICTIM_MUST_REMAIN_UNCHANGED"


def test_failed_quick_snapshot_cannot_delete_prior_same_timestamp_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime as real_datetime
    from datetime import timezone as real_timezone

    from fabric_cli import backup

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    config = fabric_home / "config.yaml"
    config.write_text("model: first\n")
    fixed = real_datetime(2026, 7, 11, 12, 0, 0, tzinfo=real_timezone.utc)

    class FrozenDateTime:
        @classmethod
        def now(cls, _timezone):
            return fixed

    monkeypatch.setattr(backup, "datetime", FrozenDateTime)
    first_id = backup.create_quick_snapshot(hermes_home=fabric_home)
    assert first_id is not None
    first_snapshot = fabric_home / "state-snapshots" / first_id
    assert (first_snapshot / "config.yaml").read_text() == "model: first\n"

    def fail_copy(_source: Path, _descriptor: int) -> None:
        raise PermissionError("deterministic failed attempt")

    monkeypatch.setattr(backup, "_copy_to_private_descriptor", fail_copy)
    assert backup.create_quick_snapshot(hermes_home=fabric_home) is None

    assert first_snapshot.is_dir()
    assert (first_snapshot / "config.yaml").read_text() == "model: first\n"


def test_quick_snapshot_label_is_metadata_only_and_id_is_direct_child(
    tmp_path: Path,
) -> None:
    import json

    from fabric_cli import backup

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    (fabric_home / "config.yaml").write_text("model: local\n")
    victim = fabric_home / "victim"
    victim.mkdir()
    sentinel = victim / "sentinel.txt"
    sentinel.write_text("unchanged")
    label = "x/../../victim"

    snapshot_id = backup.create_quick_snapshot(
        label=label,
        hermes_home=fabric_home,
    )

    assert snapshot_id is not None
    assert "/" not in snapshot_id
    assert "\\" not in snapshot_id
    assert ".." not in snapshot_id
    root = fabric_home / "state-snapshots"
    snapshot = root / snapshot_id
    assert snapshot.parent == root
    assert snapshot.is_dir()
    assert sentinel.read_text() == "unchanged"
    assert not (victim / "config.yaml").exists()
    manifest = json.loads((snapshot / "manifest.json").read_text())
    assert manifest["label"] == label
