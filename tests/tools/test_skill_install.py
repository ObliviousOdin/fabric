from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path, PurePosixPath

import pytest

from tools import skill_install
from tools.skill_install import (
    FILE_ATTRIBUTE_REPARSE_POINT,
    UnsafePathError,
    is_path_redirect,
    iter_regular_files,
    normalize_relative_path,
    normalize_skill_install_path,
    resolve_relative_path,
    resolve_skill_install_path,
    sha256_tree,
    validate_portable_tree_paths,
    validate_skill_name,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("skill", "skill"),
        ("category\\skill", "category/skill"),
        ("category//./nested/skill", "category/nested/skill"),
        ("  category/skill  ", "category/skill"),
        ("café/設計", "café/設計"),
    ],
)
def test_normalize_relative_path_canonicalizes_portable_paths(
    value: str, expected: str
) -> None:
    assert normalize_relative_path(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        ".",
        "/absolute",
        r"\absolute",
        r"\\server\share\skill",
        "//server/share/skill",
        r"C:\skills\skill",
        "C:/skills/skill",
        r"C:skills\skill",
        "../outside",
        r"..\outside",
        "inside/../../outside",
        "inside\nname",
        "inside\x00name",
        "inside/name.",
        "inside/name /child",
        "inside/na*me",
        "inside/name:stream",
        "inside/NUL.txt",
        "inside/com1",
        "inside/COM¹.txt",
        "inside/LPT²",
        "inside/cafe\u0301",
    ],
)
def test_normalize_relative_path_rejects_unsafe_cross_platform_values(
    value: object,
) -> None:
    with pytest.raises(UnsafePathError, match="^Unsafe relative path:"):
        normalize_relative_path(value)  # type: ignore[arg-type]


def test_validate_skill_name_requires_one_component() -> None:
    assert validate_skill_name("my-skill") == "my-skill"
    with pytest.raises(UnsafePathError, match="nested paths"):
        validate_skill_name("category/my-skill")


def test_normalize_skill_install_path_binds_final_component() -> None:
    assert (
        normalize_skill_install_path(r"design\tools\review", "review")
        == "design/tools/review"
    )
    with pytest.raises(UnsafePathError, match="final component"):
        normalize_skill_install_path("design/review-copy", "review")


def test_resolve_relative_path_returns_strict_existing_child(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    child = root / "category" / "skill"
    child.mkdir(parents=True)

    assert resolve_relative_path(root, r"category\skill") == child.resolve()


def test_resolve_relative_path_allows_missing_destination_only_when_requested(
    tmp_path: Path,
) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    expected = (root / "new" / "skill").resolve()

    assert resolve_relative_path(root, "new/skill", must_exist=False) == expected
    with pytest.raises(UnsafePathError, match="does not exist"):
        resolve_relative_path(root, "new/skill")


def test_resolve_skill_install_path_normalizes_and_binds_name(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    assert (
        resolve_skill_install_path(root, "group/tool", "tool")
        == (root / "group" / "tool").resolve()
    )


def test_resolve_relative_path_rejects_non_directory_intermediate(
    tmp_path: Path,
) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    (root / "occupied").write_text("not a directory")

    with pytest.raises(UnsafePathError, match="intermediate component"):
        resolve_relative_path(root, "occupied/skill", must_exist=False)


def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")


def test_resolve_relative_path_rejects_redirect_component(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    _symlink_or_skip(root / "redirect", outside, directory=True)

    with pytest.raises(UnsafePathError, match="reparse-point components"):
        resolve_relative_path(root, "redirect/skill", must_exist=False)
    assert not (outside / "skill").exists()


def test_resolve_relative_path_allows_valid_redirected_trust_root(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real-skills"
    child = real_root / "skill"
    child.mkdir(parents=True)
    linked_root = tmp_path / "skills"
    _symlink_or_skip(linked_root, real_root, directory=True)

    assert resolve_relative_path(linked_root, "skill") == child.resolve()


def test_resolve_relative_path_rejects_broken_redirected_root(tmp_path: Path) -> None:
    linked_root = tmp_path / "skills"
    _symlink_or_skip(linked_root, tmp_path / "missing", directory=True)

    with pytest.raises(UnsafePathError, match="Unsafe root"):
        resolve_relative_path(linked_root, "skill", must_exist=False)


def test_is_path_redirect_handles_missing_regular_and_symlink(tmp_path: Path) -> None:
    regular = tmp_path / "regular"
    regular.write_text("content")
    link = tmp_path / "link"
    _symlink_or_skip(link, regular)

    assert is_path_redirect(tmp_path / "missing") is False
    assert is_path_redirect(regular) is False
    assert is_path_redirect(link) is True


def test_is_path_redirect_uses_win32_attributes_for_python_311(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "junction"
    candidate.mkdir()
    monkeypatch.setattr(skill_install, "_is_windows", lambda: True)
    monkeypatch.setattr(
        skill_install,
        "_get_windows_file_attributes",
        lambda path: FILE_ATTRIBUTE_REPARSE_POINT,
    )

    assert is_path_redirect(candidate) is True


def test_is_path_redirect_accepts_regular_win32_attributes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "directory"
    candidate.mkdir()
    monkeypatch.setattr(skill_install, "_is_windows", lambda: True)
    monkeypatch.setattr(
        skill_install,
        "_get_windows_file_attributes",
        lambda path: 0x00000010,
    )

    assert is_path_redirect(candidate) is False


def test_is_path_redirect_propagates_win32_attribute_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    monkeypatch.setattr(skill_install, "_is_windows", lambda: True)

    def fail(_path: Path) -> int:
        raise OSError("attribute lookup failed")

    monkeypatch.setattr(skill_install, "_get_windows_file_attributes", fail)
    with pytest.raises(OSError, match="attribute lookup failed"):
        is_path_redirect(candidate)


@pytest.mark.skipif(os.name != "nt", reason="native Windows junction check")
def test_native_windows_junction_is_rejected_below_skills_root(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    outside = tmp_path / "outside"
    junction = root / "junction"
    root.mkdir()
    outside.mkdir()
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert is_path_redirect(junction) is True

    with pytest.raises(UnsafePathError, match="reparse-point components"):
        resolve_relative_path(root, "junction/skill", must_exist=False)

    assert not (outside / "skill").exists()


def test_iter_regular_files_orders_complete_posix_paths_by_utf8(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    (root / "a").mkdir(parents=True)
    (root / "a" / "item.txt").write_text("nested")
    (root / "a.txt").write_text("sibling")
    (root / "z.txt").write_text("last")

    entries = iter_regular_files(root)

    assert [relative.as_posix() for relative, _path in entries] == [
        "a.txt",
        "a/item.txt",
        "z.txt",
    ]
    assert all(path.is_absolute() for _relative, path in entries)


def test_iter_regular_files_rejects_empty_tree(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    (root / "nested").mkdir(parents=True)
    with pytest.raises(UnsafePathError, match="at least one regular file"):
        iter_regular_files(root)


def test_iter_regular_files_rejects_redirect_anywhere_in_tree(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    _symlink_or_skip(root / "leak.txt", outside)

    with pytest.raises(UnsafePathError, match="redirects are not allowed"):
        iter_regular_files(root)


def test_iter_regular_files_rejects_redirect_root(tmp_path: Path) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    (real_root / "file.txt").write_text("content")
    linked_root = tmp_path / "linked"
    _symlink_or_skip(linked_root, real_root, directory=True)

    with pytest.raises(UnsafePathError, match="reparse-point roots"):
        iter_regular_files(linked_root)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unavailable")
def test_iter_regular_files_rejects_fifo(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    os.mkfifo(root / "pipe")

    with pytest.raises(UnsafePathError, match="unsupported filesystem entry"):
        iter_regular_files(root)


@pytest.mark.skipif(
    os.name == "nt", reason="reserved name cannot be created on Windows"
)
def test_iter_regular_files_rejects_nonportable_entry_name(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "NUL.txt").write_text("not portable")

    with pytest.raises(UnsafePathError, match="reserved Windows device"):
        iter_regular_files(root)


def test_tree_rejects_casefold_path_collision() -> None:
    with pytest.raises(UnsafePathError, match="cross-platform path collision"):
        skill_install._validate_portable_tree_paths((
            PurePosixPath("A.md"),
            PurePosixPath("a.md"),
        ))


@pytest.mark.parametrize(
    "path",
    ("payload.txt:stream", "NUL.txt", "trailing.", "bad\x1fname"),
)
def test_validate_portable_tree_paths_rejects_windows_aliases(path: str) -> None:
    with pytest.raises(UnsafePathError):
        validate_portable_tree_paths(("SKILL.md", path))


def test_validate_portable_tree_paths_rejects_case_collision_before_write() -> None:
    with pytest.raises(UnsafePathError, match="cross-platform path collision"):
        validate_portable_tree_paths(("SKILL.md", "Docs/Guide.md", "docs/guide.md"))


@pytest.mark.parametrize(
    "paths",
    [
        ("Docs/one.md", "docs/two.md"),
        ("src/Tools/one.py", "src/tools/two.py"),
        ("tool", "tool/run.py"),
        ("tool", "TOOL/run.py"),
        ("assets/Icon", "assets/icon/data.bin"),
    ],
)
def test_validate_portable_tree_paths_rejects_ancestor_and_kind_aliases(
    paths: tuple[str, ...],
) -> None:
    with pytest.raises(UnsafePathError, match="cross-platform"):
        validate_portable_tree_paths(paths)


def test_snapshot_file_limit_rejects_before_file_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "SKILL.md").write_bytes(b"12345")
    real_read = skill_install.os.read
    file_reads = 0

    def count_reads(descriptor: int, size: int) -> bytes:
        nonlocal file_reads
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            file_reads += 1
        return real_read(descriptor, size)

    monkeypatch.setattr(skill_install.os, "read", count_reads)
    with pytest.raises(UnsafePathError, match="exceeds 4 bytes"):
        skill_install.capture_tree_snapshot(root, max_file_bytes=4)

    assert file_reads == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor walker")
def test_snapshot_count_limit_rejects_before_opening_next_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "a.md").write_text("a", encoding="utf-8")
    (root / "b.md").write_text("b", encoding="utf-8")
    real_open = skill_install.os.open
    opened_files: list[str] = []

    def record_open(path, flags, mode=0o777, *, dir_fd=None):
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if dir_fd is not None and stat.S_ISREG(os.fstat(descriptor).st_mode):
            opened_files.append(str(path))
        return descriptor

    monkeypatch.setattr(skill_install.os, "open", record_open)
    with pytest.raises(UnsafePathError, match="more than 1 files"):
        skill_install.capture_tree_snapshot(root, max_files=1)

    assert opened_files == ["a.md"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor walker")
def test_snapshot_growth_probe_reads_only_remaining_budget_plus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "growing.md").write_bytes(b"x")
    real_read = skill_install.os.read
    requested: list[int] = []

    def grow_on_read(descriptor: int, size: int) -> bytes:
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            requested.append(size)
            return b"x" * size
        return real_read(descriptor, size)

    monkeypatch.setattr(skill_install.os, "read", grow_on_read)
    with pytest.raises(UnsafePathError, match="grew beyond 3 bytes"):
        skill_install.capture_tree_snapshot(root, max_file_bytes=3)

    assert requested == [4]


@pytest.mark.skipif(
    os.name == "nt", reason="NFD filename behavior is platform-specific"
)
def test_tree_rejects_non_nfc_filename(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "cafe\u0301.md").write_text("nfd", encoding="utf-8")

    with pytest.raises(UnsafePathError, match="NFC Unicode normalization"):
        sha256_tree(root)


@pytest.mark.skipif(os.name == "nt", reason="POSIX openat hardening")
def test_sha256_tree_rejects_directory_to_symlink_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    checked = root / "checked"
    outside = tmp_path / "outside"
    checked.mkdir(parents=True)
    outside.mkdir()
    (checked / "inside.txt").write_text("inside", encoding="utf-8")
    (outside / "outside.txt").write_text("outside", encoding="utf-8")
    original_open = skill_install.os.open
    swapped = False

    def swapping_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if path == "checked" and dir_fd is not None and not swapped:
            swapped = True
            checked.rename(root / "checked-original")
            checked.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(skill_install.os, "open", swapping_open)
    with pytest.raises(UnsafePathError, match="safely open directory"):
        sha256_tree(root)
    assert swapped is True


@pytest.mark.skipif(
    os.name == "nt" or not hasattr(os, "mkfifo"),
    reason="POSIX openat/FIFO hardening",
)
def test_sha256_tree_rejects_regular_file_to_fifo_swap_without_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    victim = root / "victim"
    victim.write_text("regular", encoding="utf-8")
    original_open = skill_install.os.open
    swapped = False

    def swapping_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if path == "victim" and dir_fd is not None and not swapped:
            swapped = True
            victim.unlink()
            os.mkfifo(victim)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(skill_install.os, "open", swapping_open)
    with pytest.raises(UnsafePathError, match="changed before open"):
        sha256_tree(root)
    assert swapped is True


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor walker")
def test_sha256_tree_stops_when_open_file_grows_past_byte_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "growing.txt").write_bytes(b"x")
    original_read = skill_install.os.read

    def endless_read(descriptor: int, size: int) -> bytes:
        opened = os.fstat(descriptor)
        if opened.st_size == 1:
            return b"x" * min(size, 8)
        return original_read(descriptor, size)

    monkeypatch.setattr(skill_install.os, "read", endless_read)
    with pytest.raises(UnsafePathError, match="grew beyond 10 bytes"):
        sha256_tree(root, max_file_bytes=10, max_total_bytes=20)


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor walker")
def test_sha256_tree_detects_same_inode_mutation_during_close_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    victim = root / "victim.txt"
    victim.write_text("old", encoding="utf-8")
    original_close = skill_install.os.close
    mutated = False

    def mutating_close(descriptor: int) -> None:
        nonlocal mutated
        opened = os.fstat(descriptor)
        if stat.S_ISREG(opened.st_mode) and not mutated:
            mutated = True
            victim.write_text("new content", encoding="utf-8")
        original_close(descriptor)

    monkeypatch.setattr(skill_install.os, "close", mutating_close)
    with pytest.raises(UnsafePathError, match="file changed while hashing"):
        sha256_tree(root)
    assert mutated is True


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor walker")
def test_sha256_tree_detects_directory_mutation_during_close_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    child = root / "child"
    child.mkdir(parents=True)
    (child / "first.txt").write_text("first", encoding="utf-8")
    original_close = skill_install.os.close
    mutated = False

    def mutating_close(descriptor: int) -> None:
        nonlocal mutated
        opened = os.fstat(descriptor)
        if stat.S_ISDIR(opened.st_mode) and descriptor != -1 and not mutated:
            # The first non-root directory close happens after its initial
            # visit. Adding a sibling must invalidate the tree snapshot.
            mutated = True
            (child / "extra.txt").write_text("extra", encoding="utf-8")
        original_close(descriptor)

    monkeypatch.setattr(skill_install.os, "close", mutating_close)
    with pytest.raises(UnsafePathError, match="directory changed"):
        sha256_tree(root)
    assert mutated is True


def _expected_tree_digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files, key=lambda value: value.encode("utf-8")):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(files[relative]).hexdigest().encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def test_sha256_tree_uses_path_nul_hex_digest_nul_framing(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    files = {
        "a.txt": b"alpha\n",
        "nested/b.bin": b"\x00\xffpayload",
    }
    for relative, payload in reversed(tuple(files.items())):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    assert sha256_tree(root) == _expected_tree_digest(files)


def test_sha256_tree_changes_when_path_or_payload_changes(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    path = root / "first.txt"
    path.write_bytes(b"same")
    original = sha256_tree(root)

    path.rename(root / "second.txt")
    renamed = sha256_tree(root)
    assert renamed != original

    (root / "second.txt").write_bytes(b"changed")
    assert sha256_tree(root) not in {original, renamed}


def test_sha256_tree_rejects_excessive_directory_depth(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    current = root
    for _index in range(skill_install._MAX_TREE_DEPTH + 1):
        current /= "a"
    current.mkdir(parents=True)
    (current / "leaf.txt").write_text("leaf", encoding="utf-8")

    with pytest.raises(UnsafePathError, match="directory nesting exceeds"):
        sha256_tree(root)


def test_sha256_tree_rejects_excessive_directory_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    for name in ("a", "b", "c"):
        child = root / name
        child.mkdir()
        (child / "leaf.txt").write_text(name, encoding="utf-8")
    monkeypatch.setattr(skill_install, "_MAX_TREE_DIRECTORIES", 2)

    with pytest.raises(UnsafePathError, match="more than 2 directories"):
        sha256_tree(root)


def test_snapshot_enumeration_enforces_entry_bound_while_streaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "one.txt").write_text("one", encoding="utf-8")
    (root / "two.txt").write_text("two", encoding="utf-8")
    monkeypatch.setattr(skill_install, "_MAX_TREE_ENTRIES", 1)

    with pytest.raises(UnsafePathError, match="more than 1 entries"):
        skill_install.capture_tree_snapshot(root)
