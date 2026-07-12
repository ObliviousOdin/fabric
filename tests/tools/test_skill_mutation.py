"""Cross-process contracts for shared profile skill-mutation locks."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import tools.skill_mutation as mutation
from tools.skill_mutation import (
    MutationLockLease,
    SkillMutationLockError,
    SkillMutationLockTimeout,
    config_mutation_lock,
    pack_mutation_locks,
    skill_mutation_lock,
    validate_mutation_lock_lease,
)


def test_pack_lock_bundle_has_one_fixed_order_and_reentrant_leases(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"

    with pack_mutation_locks(home) as locks:
        assert (locks.config.kind, locks.skills.kind, locks.pack.kind) == (
            "config",
            "skills",
            "pack",
        )
        with skill_mutation_lock(home) as nested:
            assert nested == locks.skills


def test_same_profile_lock_order_inversion_is_rejected(tmp_path: Path) -> None:
    home = tmp_path / "profile"
    with skill_mutation_lock(home):
        with pytest.raises(SkillMutationLockError, match="config -> skills -> pack"):
            with config_mutation_lock(home):
                pytest.fail("inverted lock order unexpectedly acquired")


def test_skill_lock_serializes_processes_and_reports_current_owner(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    ready = tmp_path / "ready"
    script = """
import sys, time
from pathlib import Path
from tools.skill_mutation import skill_mutation_lock
home, ready = Path(sys.argv[1]), Path(sys.argv[2])
with skill_mutation_lock(home, timeout_seconds=5):
    ready.write_text('ready', encoding='utf-8')
    time.sleep(1.0)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(home), str(ready)],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ready.exists(), process.stderr.read() if process.stderr else "child exited"

    with pytest.raises(SkillMutationLockTimeout) as exc_info:
        with skill_mutation_lock(home, timeout_seconds=0.1):
            pytest.fail("contending process unexpectedly acquired the lock")

    assert exc_info.value.owner is not None
    assert exc_info.value.owner["pid"] == process.pid
    assert exc_info.value.owner["kind"] == "skills"
    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stdout + stderr

    with skill_mutation_lock(home, timeout_seconds=1) as lease:
        assert lease.pid == os.getpid()


def test_lock_roots_are_profile_isolated(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    with skill_mutation_lock(first):
        with skill_mutation_lock(second) as lease:
            assert lease.kind == "skills"

    assert (first / ".locks" / "skills.lock").is_file()
    assert (second / ".locks" / "skills.lock").is_file()


def test_stale_named_profile_process_cannot_recreate_renamed_home(
    tmp_path: Path,
) -> None:
    profiles = tmp_path / "profiles"
    old_home = profiles / "old"
    new_home = profiles / "new"
    old_home.mkdir(parents=True)
    old_home.rename(new_home)

    with pytest.raises(
        SkillMutationLockError,
        match="named profile home no longer exists",
    ):
        with skill_mutation_lock(old_home):
            pytest.fail("stale named-profile lock unexpectedly acquired")

    assert not old_home.exists()
    assert new_home.is_dir()


def test_redirected_lock_parent_fails_closed(tmp_path: Path) -> None:
    home = tmp_path / "profile"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()
    try:
        (home / ".locks").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(SkillMutationLockError):
        with skill_mutation_lock(home):
            pytest.fail("redirected lock parent must not be used")


@pytest.mark.skipif(os.name == "nt", reason="POSIX dir-fd race regression")
@pytest.mark.parametrize(
    ("kind", "parent_name", "leaf_name"),
    (("skills", ".locks", "skills.lock"), ("pack", "capability-packs", "lock")),
)
def test_parent_replacement_between_validation_and_lock_open_cannot_redirect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    parent_name: str,
    leaf_name: str,
) -> None:
    home = tmp_path / "profile"
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / leaf_name
    sentinel.write_bytes(b"DO NOT CHANGE")
    real_open = os.open
    swapped = False

    def swap_at_relative_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if not swapped and path == leaf_name and dir_fd is not None:
            # All pathname validation has completed; this is the actual
            # lock-file open. A descriptor-relative open must stay on the
            # pinned directory rather than following the replacement link.
            expected = home / parent_name
            displaced = home / f"{parent_name}.displaced"
            expected.rename(displaced)
            expected.symlink_to(outside, target_is_directory=True)
            swapped = True
        return real_open(path, flags, mode, dir_fd=dir_fd)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", swap_at_relative_open)

    with pytest.raises(SkillMutationLockError, match="parent"):
        with mutation.mutation_file_lock(home, kind=kind):
            pytest.fail("replaced parent unexpectedly acquired a lock")

    assert sentinel.read_bytes() == b"DO NOT CHANGE"
    assert swapped is True


@pytest.mark.skipif(os.name != "nt", reason="native Windows pinning regression")
def test_windows_active_lock_parent_cannot_be_replaced(tmp_path: Path) -> None:
    home = tmp_path / "profile"
    with skill_mutation_lock(home):
        parent = home / ".locks"
        with pytest.raises(OSError):
            os.replace(parent, home / ".locks.displaced")


@pytest.mark.skipif(not hasattr(os, "link"), reason="hardlinks unavailable")
def test_hardlinked_lock_file_is_rejected_without_modifying_other_inode(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    lock_parent = home / ".locks"
    lock_parent.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"DO NOT CHANGE")
    try:
        os.link(outside, lock_parent / "skills.lock")
    except OSError as exc:
        pytest.skip(f"hardlink creation unavailable: {exc}")

    with pytest.raises(SkillMutationLockError, match="uniquely linked"):
        with skill_mutation_lock(home):
            pytest.fail("hardlinked lock unexpectedly acquired")

    assert outside.read_bytes() == b"DO NOT CHANGE"


def test_replaced_lock_path_invalidates_active_lease(tmp_path: Path) -> None:
    home = tmp_path / "profile"
    with skill_mutation_lock(home) as lease:
        lock_path = home / ".locks" / "skills.lock"
        displaced = lock_path.with_suffix(".displaced")
        os.replace(lock_path, displaced)
        lock_path.write_bytes(b" ")

        with pytest.raises(SkillMutationLockError, match="pathname"):
            validate_mutation_lock_lease(home, lease, kind="skills")


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory capability")
def test_duplicate_home_fd_remains_bound_to_original_profile_generation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    displaced = tmp_path / "profile-old"

    with skill_mutation_lock(home) as lease:
        descriptor = mutation.duplicate_mutation_home_fd(
            home,
            lease,
            kind="skills",
        )
        assert descriptor is not None
        original_identity = os.fstat(descriptor)
        home.rename(displaced)
        home.mkdir()
        try:
            pinned_identity = os.fstat(descriptor)
            replacement_identity = home.stat()
            assert (pinned_identity.st_dev, pinned_identity.st_ino) == (
                original_identity.st_dev,
                original_identity.st_ino,
            )
            assert (
                replacement_identity.st_dev,
                replacement_identity.st_ino,
            ) != (
                original_identity.st_dev,
                original_identity.st_ino,
            )
        finally:
            os.close(descriptor)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_forked_child_cannot_reuse_parent_lease(tmp_path: Path) -> None:
    home = tmp_path / "profile"
    read_fd, write_fd = os.pipe()
    with skill_mutation_lock(home):
        child = os.fork()
        if child == 0:  # pragma: no cover - assertions run in parent
            os.close(read_fd)
            try:
                with skill_mutation_lock(home, timeout_seconds=0.1):
                    os.write(write_fd, b"acquired")
            except SkillMutationLockTimeout:
                os.write(write_fd, b"timed-out")
            except BaseException as exc:
                os.write(write_fd, f"error:{type(exc).__name__}".encode("ascii"))
            finally:
                os.close(write_fd)
            os._exit(0)
        os.close(write_fd)
        verdict = os.read(read_fd, 64)
        os.close(read_fd)
        _, status = os.waitpid(child, 0)

    assert os.waitstatus_to_exitcode(status) == 0
    assert verdict == b"timed-out"


def test_forged_released_and_wrong_home_leases_are_rejected(tmp_path: Path) -> None:
    home = tmp_path / "profile"
    other = tmp_path / "other"
    forged = MutationLockLease(
        kind="skills",
        token="forged",
        pid=os.getpid(),
        thread_id=0,
        acquired_at="forged",
        home=str(home.resolve()),
        lock_path=str((home / ".locks" / "skills.lock").resolve()),
    )
    with pytest.raises(SkillMutationLockError):
        validate_mutation_lock_lease(home, forged, kind="skills")

    with skill_mutation_lock(home) as active:
        with pytest.raises(SkillMutationLockError, match="another profile"):
            validate_mutation_lock_lease(other, active, kind="skills")
    with pytest.raises(SkillMutationLockError, match="not active"):
        validate_mutation_lock_lease(home, active, kind="skills")


def test_body_oserror_is_not_relabelled_as_lock_preparation(tmp_path: Path) -> None:
    home = tmp_path / "profile"

    with pytest.raises(OSError, match="mutation body failed"):
        with skill_mutation_lock(home):
            raise OSError("mutation body failed")
