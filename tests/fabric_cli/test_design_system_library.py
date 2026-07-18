from __future__ import annotations

import hashlib
import os
import stat
import struct
import unicodedata
import zipfile
from pathlib import Path

import pytest


def _write_zip(path: Path, entries: dict[str, bytes | str]) -> bytes:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, contents in entries.items():
            archive.writestr(name, contents)
    return path.read_bytes()


def _write_zip_stored(path: Path, entries: dict[str, bytes | str]) -> bytes:
    """Write a ZIP with stored (uncompressed) members for high-entropy fixtures."""

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, contents in entries.items():
            archive.writestr(name, contents)
    return path.read_bytes()


def _write_zip_members(
    path: Path, entries: list[tuple[str | zipfile.ZipInfo, bytes | str]]
) -> bytes:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, contents in entries:
            archive.writestr(name, contents)
    return path.read_bytes()


def _mark_first_entry_encrypted(path: Path) -> None:
    data = bytearray(path.read_bytes())
    local = data.index(b"PK\x03\x04")
    central = data.index(b"PK\x01\x02")
    local_flags = struct.unpack_from("<H", data, local + 6)[0]
    central_flags = struct.unpack_from("<H", data, central + 8)[0]
    struct.pack_into("<H", data, local + 6, local_flags | 0x1)
    struct.pack_into("<H", data, central + 8, central_flags | 0x1)
    path.write_bytes(data)


def test_security_limits_match_the_public_import_contract() -> None:
    from fabric_cli import design_system_library as library

    assert library.MAX_ARCHIVE_BYTES == 50 * 1024 * 1024
    assert library.MAX_ARCHIVE_ENTRIES == 2_000
    assert library.MAX_EXPANDED_BYTES == 250 * 1024 * 1024
    assert library.MAX_ENTRY_BYTES == 25 * 1024 * 1024
    assert library.MAX_COMPRESSION_RATIO == 100
    assert library.MAX_PATH_DEPTH == 32
    assert library.MAX_PATH_LENGTH == 512
    assert library.MAX_PATH_SEGMENT_LENGTH == 255


def test_import_persists_a_profile_scoped_content_addressed_revision(
    tmp_path: Path, monkeypatch
) -> None:
    profile_home = tmp_path / "profiles" / "designer"
    monkeypatch.setenv("FABRIC_HOME", str(profile_home))
    archive_path = tmp_path / "Acme-system.zip"
    archive_bytes = _write_zip(
        archive_path,
        {
            "DESIGN.md": "# Acme\n",
            "tokens/colors.json": '{"brand":"#123456"}',
        },
    )

    from fabric_cli.design_system_library import (
        get_design_system,
        import_design_system,
        list_design_systems,
    )

    imported = import_design_system(archive_path)
    revision = hashlib.sha256(archive_bytes).hexdigest()

    assert imported["revision"] == revision
    assert imported["sha256"] == revision
    assert imported["name"] == "Acme system"
    assert imported["file_count"] == 2
    assert imported["expanded_size"] == len(b"# Acme\n") + len(
        b'{"brand":"#123456"}'
    )
    assert Path(imported["archive_path"]).is_relative_to(profile_home)
    assert Path(imported["files_path"]).is_relative_to(profile_home)
    assert (Path(imported["files_path"]) / "DESIGN.md").read_text() == "# Acme\n"
    assert (
        stat.S_IMODE(
            os.stat(Path(imported["files_path"]) / "DESIGN.md").st_mode
        )
        & 0o111
        == 0
    )
    assert get_design_system(imported["id"]) == imported
    assert list_design_systems() == [imported]


def test_replace_keeps_a_stable_id_and_immutable_revision_history(
    tmp_path: Path, monkeypatch
) -> None:
    profile_home = tmp_path / "profile"
    monkeypatch.setenv("FABRIC_HOME", str(profile_home))
    first_zip = tmp_path / "first.zip"
    second_zip = tmp_path / "second.zip"
    _write_zip(first_zip, {"DESIGN.md": "first"})
    _write_zip(second_zip, {"DESIGN.md": "second"})

    from fabric_cli.design_system_library import (
        delete_design_system,
        get_design_system,
        import_design_system,
        list_design_systems,
        replace_design_system,
    )

    first = import_design_system(first_zip, name="Acme")
    first_files = Path(first["files_path"])
    replaced = replace_design_system(first["id"], second_zip)

    assert replaced["id"] == first["id"]
    assert replaced["name"] == "Acme"
    assert replaced["revision"] != first["revision"]
    assert [row["sha256"] for row in replaced["revisions"]] == [
        first["revision"],
        replaced["revision"],
    ]
    assert (first_files / "DESIGN.md").read_text() == "first"
    assert (Path(replaced["files_path"]) / "DESIGN.md").read_text() == "second"
    assert get_design_system(first["id"]) == replaced

    other_profile = tmp_path / "other-profile"
    monkeypatch.setenv("FABRIC_HOME", str(other_profile))
    assert list_design_systems() == []
    assert get_design_system(first["id"]) is None

    monkeypatch.setenv("FABRIC_HOME", str(profile_home))
    assert delete_design_system(first["id"]) is True
    assert delete_design_system(first["id"]) is False
    assert list_design_systems() == []


def test_generation_checks_are_atomic_with_replace_and_delete(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path / "profile"))
    first_zip = tmp_path / "first.zip"
    second_zip = tmp_path / "second.zip"
    _write_zip(first_zip, {"DESIGN.md": "first"})
    _write_zip(second_zip, {"DESIGN.md": "second"})

    from fabric_cli.design_system_library import (
        DesignSystemConflictError,
        DesignSystemLibrary,
    )

    library = DesignSystemLibrary()
    original = library.import_archive(first_zip)

    with pytest.raises(DesignSystemConflictError):
        library.replace(original["id"], second_zip, expected_generation=0)
    assert library.get(original["id"]) == original

    with pytest.raises(DesignSystemConflictError):
        library.delete(original["id"], expected_generation=0)
    assert library.get(original["id"]) == original


def test_identical_archives_reuse_one_verified_revision(
    tmp_path: Path, monkeypatch
) -> None:
    profile_home = tmp_path / "profile"
    monkeypatch.setenv("FABRIC_HOME", str(profile_home))
    archive_path = tmp_path / "system.zip"
    _write_zip(archive_path, {"DESIGN.md": "same"})

    from fabric_cli.design_system_library import import_design_system

    first = import_design_system(archive_path)
    second = import_design_system(archive_path)

    assert first["revision"] == second["revision"]
    revisions_root = profile_home / "design-system-library" / "revisions"
    assert [path.name for path in revisions_root.iterdir()] == [first["revision"]]


def test_macos_metadata_is_ignored_but_counted_for_archive_safety(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path / "profile"))
    archive_path = tmp_path / "system.zip"
    _write_zip(
        archive_path,
        {
            "DESIGN.md": "kept",
            "__MACOSX/._DESIGN.md": "ignored",
            "assets/.DS_Store": "ignored too",
            "__MACOSX/.env": "ignored metadata",
        },
    )

    from fabric_cli.design_system_library import import_design_system

    imported = import_design_system(archive_path)
    files = Path(imported["files_path"])

    assert imported["file_count"] == 1
    assert imported["expanded_size"] == len(b"kept")
    assert sorted(path.relative_to(files).as_posix() for path in files.rglob("*")) == [
        "DESIGN.md"
    ]


@pytest.mark.parametrize(
    "member_name",
    [
        "../escape.txt",
        "nested/../../escape.txt",
        "/absolute.txt",
        "//server/share.txt",
        "C:/Windows/file.txt",
        r"C:\Windows\file.txt",
        "safe/file.txt:stream",
        "line\nbreak.txt",
        ".git/config",
        ".ssh/config",
        "node_modules/pkg/index.js",
        ".env",
        ".env.local",
        "keys/id_rsa",
        "keys/private.pem",
    ],
)
def test_import_rejects_unsafe_or_private_paths(
    tmp_path: Path, monkeypatch, member_name: str
) -> None:
    profile_home = tmp_path / "profile"
    monkeypatch.setenv("FABRIC_HOME", str(profile_home))
    archive_path = tmp_path / "unsafe.zip"
    _write_zip_members(archive_path, [(member_name, "secret")])

    from fabric_cli.design_system_library import (
        ArchiveValidationError,
        import_design_system,
        list_design_systems,
    )

    with pytest.raises(ArchiveValidationError):
        import_design_system(archive_path)

    assert not (tmp_path / "escape.txt").exists()
    assert list_design_systems() == []
    staging = profile_home / "design-system-library" / "staging"
    assert staging.is_dir()
    assert list(staging.iterdir()) == []


@pytest.mark.parametrize(
    "entries",
    [
        [("Tokens.json", "one"), ("tokens.JSON", "two")],
        [
            (unicodedata.normalize("NFC", "café.txt"), "one"),
            (unicodedata.normalize("NFD", "café.txt"), "two"),
        ],
        [("theme", "file"), ("theme/token.json", "child")],
        [("theme/token.json", "child"), ("theme", "file")],
    ],
)
def test_import_rejects_unicode_case_and_file_directory_collisions(
    tmp_path: Path,
    monkeypatch,
    entries: list[tuple[str | zipfile.ZipInfo, bytes | str]],
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path / "profile"))
    archive_path = tmp_path / "collision.zip"
    _write_zip_members(archive_path, entries)

    from fabric_cli.design_system_library import ArchiveValidationError, import_design_system

    with pytest.raises(ArchiveValidationError, match="collision"):
        import_design_system(archive_path)


@pytest.mark.parametrize("file_type", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR])
def test_import_rejects_symlinks_and_special_entries(
    tmp_path: Path, monkeypatch, file_type: int
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path / "profile"))
    archive_path = tmp_path / "special.zip"
    info = zipfile.ZipInfo("special")
    info.create_system = 3
    info.external_attr = (file_type | 0o600) << 16
    _write_zip_members(archive_path, [(info, "payload")])

    from fabric_cli.design_system_library import ArchiveValidationError, import_design_system

    with pytest.raises(ArchiveValidationError, match="symlink and special"):
        import_design_system(archive_path)


def test_import_rejects_encrypted_entries_before_extraction(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path / "profile"))
    archive_path = tmp_path / "encrypted.zip"
    _write_zip(archive_path, {"DESIGN.md": "encrypted"})
    _mark_first_entry_encrypted(archive_path)

    from fabric_cli.design_system_library import ArchiveValidationError, import_design_system

    with pytest.raises(ArchiveValidationError, match="encrypted"):
        import_design_system(archive_path)


@pytest.mark.parametrize(
    ("constant", "limit", "entries"),
    [
        ("MAX_ARCHIVE_BYTES", 1, [("a", "a")]),
        ("MAX_ARCHIVE_ENTRIES", 1, [("a", "a"), ("b", "b")]),
        ("MAX_EXPANDED_BYTES", 3, [("a", "aa"), ("b", "bb")]),
        ("MAX_ENTRY_BYTES", 3, [("entry", "four")]),
        ("MAX_COMPRESSION_RATIO", 2, [("compressed", "a" * 1_000)]),
        ("MAX_PATH_DEPTH", 1, [("a/b", "deep")]),
        ("MAX_PATH_LENGTH", 5, [("123456", "long")]),
        ("MAX_PATH_SEGMENT_LENGTH", 5, [("123456", "long")]),
    ],
)
def test_import_enforces_archive_and_path_limits(
    tmp_path: Path,
    monkeypatch,
    constant: str,
    limit: int,
    entries: list[tuple[str | zipfile.ZipInfo, bytes | str]],
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path / "profile"))
    archive_path = tmp_path / "limited.zip"
    _write_zip_members(archive_path, entries)

    from fabric_cli import design_system_library as library

    monkeypatch.setattr(library, constant, limit)
    with pytest.raises(library.ArchiveValidationError):
        library.import_design_system(archive_path)


def test_import_strips_executable_bits_from_regular_files(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path / "profile"))
    archive_path = tmp_path / "executable.zip"
    info = zipfile.ZipInfo("scripts/build.sh")
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o755) << 16
    _write_zip_members(archive_path, [(info, "#!/bin/sh\n")])

    from fabric_cli.design_system_library import import_design_system

    imported = import_design_system(archive_path)
    extracted = Path(imported["files_path"]) / "scripts" / "build.sh"

    assert stat.S_IMODE(extracted.stat().st_mode) == 0o400
    assert stat.S_IMODE(Path(imported["archive_path"]).stat().st_mode) == 0o400


def test_import_rejects_non_zip_and_source_symlink_and_cleans_staging(
    tmp_path: Path, monkeypatch
) -> None:
    profile_home = tmp_path / "profile"
    monkeypatch.setenv("FABRIC_HOME", str(profile_home))
    invalid = tmp_path / "invalid.zip"
    invalid.write_bytes(b"not a zip")

    from fabric_cli.design_system_library import ArchiveValidationError, import_design_system

    with pytest.raises(ArchiveValidationError):
        import_design_system(invalid)

    valid = tmp_path / "valid.zip"
    _write_zip(valid, {"DESIGN.md": "valid"})
    linked = tmp_path / "linked.zip"
    linked.symlink_to(valid)
    with pytest.raises(ArchiveValidationError, match="non-symlink"):
        import_design_system(linked)

    staging = profile_home / "design-system-library" / "staging"
    assert list(staging.iterdir()) == []


def test_failed_atomic_record_replace_leaves_the_old_revision_selected(
    tmp_path: Path, monkeypatch
) -> None:
    profile_home = tmp_path / "profile"
    monkeypatch.setenv("FABRIC_HOME", str(profile_home))
    first_zip = tmp_path / "first.zip"
    second_zip = tmp_path / "second.zip"
    _write_zip(first_zip, {"DESIGN.md": "first"})
    _write_zip(second_zip, {"DESIGN.md": "second"})

    from fabric_cli import design_system_library as library

    first = library.import_design_system(first_zip)
    record_path = (
        profile_home
        / "design-system-library"
        / "records"
        / f"{first['id']}.json"
    )
    before = record_path.read_bytes()
    real_replace = library.os.replace

    def fail_record_replace(source: str | Path, target: str | Path) -> None:
        if Path(target) == record_path:
            raise OSError("simulated interrupted metadata publication")
        real_replace(source, target)

    monkeypatch.setattr(library.os, "replace", fail_record_replace)
    with pytest.raises(library.DesignSystemStorageError, match="atomically write"):
        library.replace_design_system(first["id"], second_zip)

    assert record_path.read_bytes() == before
    selected = library.get_design_system(first["id"])
    assert selected is not None
    assert selected["revision"] == first["revision"]
    assert list((profile_home / "design-system-library" / "staging").iterdir()) == []
    assert not list(record_path.parent.glob("*.tmp"))


def test_inspect_returns_bounded_manifest_inventory_and_design_md_preview(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path / "profile"))
    archive_path = tmp_path / "Acme-system.zip"
    design_md = "# Acme\n\nUse navy and gold.\n" + ("line\n" * 40)
    entries: dict[str, bytes | str] = {
        "DESIGN.md": design_md,
        "package.json": '{"name":"acme"}',
        "a/DESIGN.md": "# nested should not win\n",
        "a/package.json": '{"name":"nested"}',
        "tokens/colors.json": '{"brand":"#123456"}',
        "preview/index.html": "<html></html>",
        "assets/logo.png": b"\x89PNG\r\n\x1a\n" + b"x" * 32,
        "nested/deep/notes.txt": "notes",
    }
    for index in range(210):
        entries[f"files/file-{index:03d}.txt"] = f"payload-{index}"
    _write_zip_stored(archive_path, entries)

    from fabric_cli import design_system_library as library

    imported = library.import_design_system(archive_path)
    inspection = library.inspect_design_system(imported["id"])

    assert inspection["designSystemId"] == imported["id"]
    assert inspection["revisionSha256"] == imported["revision"]
    assert inspection["fileCount"] == imported["file_count"]
    assert inspection["expandedBytes"] == imported["expanded_size"]
    assert inspection["entrypoints"] == {
        "designMd": "DESIGN.md",
        "packageJson": "package.json",
        "html": ["preview/index.html"],
        "tokenFiles": ["tokens/colors.json"],
    }
    assert len(inspection["files"]) == library.MAX_INSPECTION_FILES
    assert inspection["omittedFileCount"] == imported["file_count"] - library.MAX_INSPECTION_FILES
    assert {"path": "DESIGN.md", "size": len(design_md.encode("utf-8"))} in inspection["files"]
    assert all("sha256" not in row for row in inspection["files"])
    assert inspection["files"] == sorted(
        inspection["files"], key=lambda row: str(row["path"]).casefold()
    )
    preview = inspection["designMdPreview"]
    assert preview is not None
    assert preview["path"] == "DESIGN.md"
    assert preview["text"].startswith("# Acme")
    assert preview["truncated"] is False
    assert len(preview["text"].encode("utf-8")) <= library.MAX_DESIGN_MD_PREVIEW_BYTES


def test_inspect_handles_missing_design_md_and_invalid_utf8(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path / "profile"))
    archive_path = tmp_path / "no-design.zip"
    _write_zip(
        archive_path,
        {
            "package.json": '{"name":"no-design"}',
            "tokens/colors.json": '{"brand":"#abcdef"}',
            "preview/home.html": "<html></html>",
        },
    )

    from fabric_cli import design_system_library as library

    imported = library.import_design_system(archive_path)
    inspection = library.inspect_design_system(imported["id"])
    assert "designMd" not in inspection["entrypoints"]
    assert inspection["entrypoints"]["packageJson"] == "package.json"
    assert inspection["designMdPreview"] is None

    bad_archive = tmp_path / "bad-utf8.zip"
    _write_zip(bad_archive, {"DESIGN.md": b"\xff\xfe not utf-8", "tokens/a.json": "{}"})
    replaced = library.replace_design_system(imported["id"], bad_archive)
    inspection = library.inspect_design_system(replaced["id"])
    assert inspection["revisionSha256"] == replaced["revision"]
    assert inspection["entrypoints"]["designMd"] == "DESIGN.md"
    assert inspection["designMdPreview"] is None

    large_bad_archive = tmp_path / "large-bad-utf8.zip"
    _write_zip_stored(
        large_bad_archive,
        {"DESIGN.md": b"# starts as text\n\xff" + (b"x" * 20_000)},
    )
    replaced = library.replace_design_system(imported["id"], large_bad_archive)
    inspection = library.inspect_design_system(replaced["id"])
    assert inspection is not None
    assert inspection["designMdPreview"] is None

    binary_archive = tmp_path / "binary-design-md.zip"
    _write_zip_stored(binary_archive, {"DESIGN.md": b"# text-looking prefix\n\x00binary"})
    replaced = library.replace_design_system(imported["id"], binary_archive)
    inspection = library.inspect_design_system(replaced["id"])
    assert inspection is not None
    assert inspection["designMdPreview"] is None


def test_inspect_tracks_current_revision_and_rejects_tampered_targets(
    tmp_path: Path, monkeypatch
) -> None:
    profile_home = tmp_path / "profile"
    monkeypatch.setenv("FABRIC_HOME", str(profile_home))
    first_zip = tmp_path / "first.zip"
    second_zip = tmp_path / "second.zip"
    _write_zip(first_zip, {"DESIGN.md": "# first\n", "tokens/a.json": "{}"})
    # Keep the large DESIGN.md above the preview cap without tripping the
    # archive compression-ratio guard by storing members uncompressed.
    large_design = "# second revision\n" + ("x" * 20_000)
    _write_zip_stored(
        second_zip,
        {
            "DESIGN.md": large_design,
            "package.json": "{}",
            "preview/index.html": "<html>v2</html>",
        },
    )

    from fabric_cli import design_system_library as library

    first = library.import_design_system(first_zip)
    first_inspection = library.inspect_design_system(first["id"])
    assert first_inspection["revisionSha256"] == first["revision"]
    assert first_inspection["designMdPreview"]["text"].startswith("# first")

    replaced = library.replace_design_system(first["id"], second_zip)
    second_inspection = library.inspect_design_system(first["id"])
    assert second_inspection["revisionSha256"] == replaced["revision"]
    assert second_inspection["revisionSha256"] != first["revision"]
    assert second_inspection["designMdPreview"]["truncated"] is True
    assert (
        len(second_inspection["designMdPreview"]["text"].encode("utf-8"))
        <= library.MAX_DESIGN_MD_PREVIEW_BYTES
    )

    files_root = Path(replaced["files_path"])
    design_md = files_root / "DESIGN.md"
    files_root.chmod(0o700)
    design_md.chmod(0o600)
    design_md.unlink()
    design_md.symlink_to("/etc/passwd")
    with pytest.raises(library.DesignSystemStorageError):
        library.inspect_design_system(first["id"])

    nested_zip = tmp_path / "nested.zip"
    _write_zip(nested_zip, {"nested/DESIGN.md": "# nested\n"})
    nested_record = library.import_design_system(nested_zip)
    nested_files_root = Path(nested_record["files_path"])
    nested_directory = nested_files_root / "nested"
    nested_target = nested_directory / "DESIGN.md"
    outside_directory = tmp_path / "outside"
    outside_directory.mkdir()
    (outside_directory / "DESIGN.md").write_text("outside revision root")
    nested_files_root.chmod(0o700)
    nested_directory.chmod(0o700)
    nested_target.chmod(0o600)
    nested_target.unlink()
    nested_directory.rmdir()
    nested_directory.symlink_to(outside_directory, target_is_directory=True)
    with pytest.raises(library.DesignSystemStorageError):
        library.inspect_design_system(nested_record["id"])
    monkeypatch.setattr(library.os, "supports_dir_fd", set())
    with pytest.raises(library.DesignSystemStorageError):
        library.inspect_design_system(nested_record["id"])

    assert library.inspect_design_system("ds_not_a_valid_id") is None
    assert library.inspect_design_system("ds_" + ("0" * 32)) is None
