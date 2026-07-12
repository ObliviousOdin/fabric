"""Safe legacy-home migration from ``~/.hermes`` to ``~/.fabric``.

The migration is deliberately non-destructive until the new tree has been
copied and verified.  By default the legacy source is renamed to a timestamped
rollback directory after the new Fabric home is committed atomically.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import psutil

from fabric_constants import _get_platform_default_fabric_home


@dataclass(frozen=True)
class HomeMigrationResult:
    source: str
    target: str
    backup: str | None
    previous_target_backup: str | None
    copied_entries: int
    skipped_old_engine: bool
    souls_migrated: int


class HomeMigrationError(RuntimeError):
    """Raised when a home migration cannot proceed safely."""


_PROVIDER_ACCOUNT_STATE_FILE = "provider-accounts.json"
_PROVIDER_ACCOUNT_LOCK_FILE = "provider-accounts.lock"
_PROVIDER_ACCOUNT_REPAIR_DIR = ".provider-account-repair"
_PROVIDER_ACCOUNT_TEMP_FILE_PREFIX = ".provider-accounts.json.tmp."

# public-release-audit: allow-legacy-compat -- locates customer data created before the Fabric home migration
_LEGACY_HOME_DIRNAME = ".hermes"
# public-release-audit: allow-legacy-compat -- excludes the pre-Fabric bundled checkout from customer-data migration
_LEGACY_ENGINE_DIRNAME = "hermes-agent"


def default_legacy_home() -> Path:
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        return base / _LEGACY_HOME_DIRNAME.lstrip(".")
    return Path.home() / _LEGACY_HOME_DIRNAME


def default_fabric_home() -> Path:
    return _get_platform_default_fabric_home()


def _is_nonempty_dir(path: Path) -> bool:
    try:
        return path.is_dir() and next(path.iterdir(), None) is not None
    except OSError:
        return False


def _read_live_gateway_pid(source: Path) -> int | None:
    pid_path = source / "gateway.pid"
    raw = ""
    try:
        raw = pid_path.read_text(encoding="utf-8").strip()
        # Newer PID files may be JSON; older ones are a bare integer.
        if raw.startswith("{"):
            payload = json.loads(raw)
            raw = str(payload.get("pid") or "")
        pid = int(raw)
        if pid > 0 and psutil.pid_exists(pid):
            return pid
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError, OSError):
        pass

    # Older launchd/systemd services did not always write gateway.pid. Detect
    # the exact CLI/module argv shape as a second safety net. Exact elements
    # avoid false positives from shell commands whose `-c` string merely
    # mentions the words "gateway run".
    for process in psutil.process_iter(["pid", "cmdline"]):
        try:
            pid = int(process.info.get("pid") or 0)
            argv = [str(part) for part in (process.info.get("cmdline") or [])]
        except (psutil.Error, TypeError, ValueError):
            continue
        if pid <= 0 or pid == os.getpid() or not argv:
            continue
        is_module = any(
            module in argv for module in ("hermes_cli.main", "fabric_cli.main")
        )
        is_console = any(Path(arg).name in {"hermes", "fabric"} for arg in argv[:2])
        references_source = any(str(source) in arg for arg in argv)
        if (
            references_source
            and (is_module or is_console)
            and "gateway" in argv
            and "run" in argv
        ):
            return pid
    return None


def _ignore_factory(source: Path, *, include_old_engine: bool) -> Callable[[str, list[str]], set[str]]:
    source_resolved = source.resolve()
    runtime_names = {
        "gateway.pid",
        "gateway.lock",
        ".tick.lock",
        ".dispatcher.lock",
        ".sync.lock",
        _PROVIDER_ACCOUNT_LOCK_FILE,
    }

    def _ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {name for name in names if name in runtime_names}
        ignored.update(
            name
            for name in names
            if name.startswith(_PROVIDER_ACCOUNT_TEMP_FILE_PREFIX)
        )
        try:
            at_root = Path(directory).resolve() == source_resolved
        except OSError:
            at_root = False
        # The old checkout/venv is application code, not customer data. A fresh
        # Fabric engine is installed separately and should never inherit it.
        if at_root and not include_old_engine and _LEGACY_ENGINE_DIRNAME in names:
            ignored.add(_LEGACY_ENGINE_DIRNAME)
        return ignored

    return _ignore


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _critical_files(source: Path, include_old_engine: bool) -> list[Path]:
    candidates = [
        ".env",
        "config.yaml",
        "auth.json",
        "state.db",
        "kanban.db",
        "response_store.db",
        "SOUL.md",
        "USER.md",
        "MEMORY.md",
        _PROVIDER_ACCOUNT_STATE_FILE,
    ]
    result = [source / name for name in candidates if (source / name).is_file()]
    # Profile config/secrets are launch-critical and small enough to hash.
    profiles = source / "profiles"
    if profiles.is_dir():
        for pattern in (
            "*/config.yaml",
            "*/.env",
            "*/SOUL.md",
            f"*/{_PROVIDER_ACCOUNT_STATE_FILE}",
        ):
            result.extend(path for path in profiles.glob(pattern) if path.is_file())
    repair_dirs = [source / _PROVIDER_ACCOUNT_REPAIR_DIR]
    if profiles.is_dir():
        repair_dirs.extend(profiles.glob(f"*/{_PROVIDER_ACCOUNT_REPAIR_DIR}"))
    for repair_dir in repair_dirs:
        if repair_dir.is_dir():
            result.extend(path for path in repair_dir.rglob("*") if path.is_file())
    if include_old_engine:
        marker = source / _LEGACY_ENGINE_DIRNAME / "pyproject.toml"
        if marker.is_file():
            result.append(marker)
    return result


def _verify_copy(source: Path, staging: Path, *, include_old_engine: bool) -> None:
    for original in _critical_files(source, include_old_engine):
        relative = original.relative_to(source)
        copied = staging / relative
        if not copied.is_file():
            raise HomeMigrationError(f"verification failed: missing {relative}")
        if original.stat().st_size != copied.stat().st_size:
            raise HomeMigrationError(f"verification failed: size mismatch for {relative}")
        if _hash_file(original) != _hash_file(copied):
            raise HomeMigrationError(f"verification failed: checksum mismatch for {relative}")


def _merge_missing(scaffold: Path, staging: Path) -> None:
    """Copy only paths absent from *staging*.

    Legacy customer state stays authoritative while harmless files created by
    a just-completed Fabric install (such as the brand skin or newly bundled
    skills) are retained.
    """
    for item in sorted(scaffold.rglob("*")):
        relative = item.relative_to(scaffold)
        destination = staging / relative
        if destination.exists() or destination.is_symlink():
            continue
        if item.is_symlink():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(os.readlink(item))
        elif item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


def _harden_provider_account_artifacts(root: Path) -> None:
    """Apply private modes to default and named-profile account artifacts."""
    homes = [root]
    profiles = root / "profiles"
    try:
        profiles_stat = os.lstat(profiles)
        if stat.S_ISDIR(profiles_stat.st_mode):
            with os.scandir(profiles) as entries:
                homes.extend(
                    profiles / entry.name
                    for entry in entries
                    if entry.is_dir(follow_symlinks=False)
                )
    except FileNotFoundError:
        pass
    except OSError:
        pass

    for profile_home in homes:
        state = profile_home / _PROVIDER_ACCOUNT_STATE_FILE
        if state.is_file():
            try:
                state.chmod(0o600)
            except OSError:
                pass
        repair = profile_home / _PROVIDER_ACCOUNT_REPAIR_DIR
        if not repair.is_dir():
            continue
        for path in [repair, *repair.rglob("*")]:
            try:
                path.chmod(0o700 if path.is_dir() else 0o600)
            except OSError:
                pass


def _rebind_migrated_provider_account_stores(root: Path) -> None:
    """Fence exact default/named stores while the migrated tree is staged.

    Discovery is limited to the supported structural locations: the root
    profile and one directory level below ``profiles``.  Rebinding uses the
    provider-account domain API; migration never edits store JSON directly.
    """
    from fabric_cli.provider_accounts import rebind_restored_account_store

    def has_state_entry(profile_home: Path) -> bool:
        try:
            os.lstat(profile_home / _PROVIDER_ACCOUNT_STATE_FILE)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise HomeMigrationError(
                "could not inspect migrated provider-account state"
            ) from exc
        return True

    homes: list[Path] = []
    if has_state_entry(root):
        homes.append(root)

    profiles = root / "profiles"
    try:
        profiles_stat = os.lstat(profiles)
        if not stat.S_ISDIR(profiles_stat.st_mode):
            profiles_stat = None
    except FileNotFoundError:
        profiles_stat = None
    except OSError as exc:
        raise HomeMigrationError(
            "could not inspect migrated profile state"
        ) from exc
    try:
        if profiles_stat is None:
            raise FileNotFoundError
        with os.scandir(profiles) as entries:
            for entry in entries:
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                except OSError as exc:
                    raise HomeMigrationError(
                        "could not inspect migrated profile state"
                    ) from exc
                profile_home = profiles / entry.name
                if has_state_entry(profile_home):
                    homes.append(profile_home)
    except FileNotFoundError:
        pass
    except HomeMigrationError:
        raise
    except OSError as exc:
        raise HomeMigrationError(
            "could not inspect migrated profile state"
        ) from exc

    for profile_home in sorted(homes, key=os.fspath):
        rebind_restored_account_store(home=profile_home)


def migrate_home(
    source: Path,
    target: Path,
    *,
    archive_source: bool = True,
    include_old_engine: bool = False,
    allow_running: bool = False,
    merge_existing: bool = False,
) -> HomeMigrationResult:
    """Copy *source* to *target*, verify it, then optionally archive *source*.

    The target is assembled in a sibling staging directory and committed with
    ``os.replace``. Existing non-empty targets are merged only with explicit
    ``merge_existing=True``; legacy customer state wins every conflict.
    """
    source = Path(source).expanduser().resolve()
    target = Path(target).expanduser().resolve()
    if source == target:
        raise HomeMigrationError("source and target are the same directory")
    if not source.is_dir():
        raise HomeMigrationError(f"legacy home does not exist: {source}")
    target_nonempty = _is_nonempty_dir(target)
    if target_nonempty and not merge_existing:
        raise HomeMigrationError(f"target already exists and is not empty: {target}")
    if target.exists() and not target.is_dir():
        raise HomeMigrationError(f"target exists and is not a directory: {target}")

    live_pid = _read_live_gateway_pid(source)
    if live_pid is not None and not allow_running:
        raise HomeMigrationError(
            f"gateway process {live_pid} is still running from {source}; "
            "stop the gateway before migrating"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.migrating-{os.getpid()}-{int(time.time())}")
    if staging.exists():
        raise HomeMigrationError(f"staging path already exists: {staging}")

    backup: Path | None = None
    previous_target_backup: Path | None = None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if archive_source:
        backup = source.with_name(f"{source.name}.pre-fabric-{stamp}")
        if backup.exists():
            raise HomeMigrationError(f"rollback directory already exists: {backup}")
    if target_nonempty:
        previous_target_backup = target.with_name(f"{target.name}.pre-merge-{stamp}")
        if previous_target_backup.exists():
            raise HomeMigrationError(
                f"previous-target rollback directory already exists: {previous_target_backup}"
            )
    souls_migrated = 0
    try:
        shutil.copytree(
            source,
            staging,
            symlinks=True,
            copy_function=shutil.copy2,
            ignore=_ignore_factory(source, include_old_engine=include_old_engine),
        )
        _verify_copy(source, staging, include_old_engine=include_old_engine)

        # Only rewrite known, byte-identical stock SOUL files. Custom identity
        # files remain byte-for-byte untouched.
        from fabric_cli.fabric_soul_migrate import migrate_hermes_home_souls

        souls_migrated = migrate_hermes_home_souls(staging)

        if target_nonempty:
            _merge_missing(target, staging)

        _harden_provider_account_artifacts(staging)
        # This runs before the staging directory is atomically installed, so
        # no target runtime can observe source-machine OAuth fences. Private
        # modes are restored first because the domain parser rejects
        # over-permissive account-state files by design.
        _rebind_migrated_provider_account_stores(staging)

        if target.exists():
            if target_nonempty:
                assert previous_target_backup is not None
                os.replace(target, previous_target_backup)
            else:
                target.rmdir()
        os.replace(staging, target)

        if archive_source:
            assert backup is not None
            os.replace(source, backup)

        receipt = target / "migration-hermes-to-fabric.json"
        payload = {
            "source": str(source),
            "target": str(target),
            "backup": str(backup) if backup else None,
            "previous_target_backup": (
                str(previous_target_backup) if previous_target_backup else None
            ),
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "old_engine_excluded": not include_old_engine,
            "souls_migrated": souls_migrated,
        }
        receipt.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        try:
            target.chmod(0o700)
            receipt.chmod(0o600)
        except OSError:
            pass
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if previous_target_backup and previous_target_backup.exists() and not target.exists():
            os.replace(previous_target_backup, target)
        raise

    copied_entries = sum(1 for _ in target.rglob("*"))
    return HomeMigrationResult(
        source=str(source),
        target=str(target),
        backup=str(backup) if backup else None,
        previous_target_backup=(
            str(previous_target_backup) if previous_target_backup else None
        ),
        copied_entries=copied_entries,
        skipped_old_engine=not include_old_engine,
        souls_migrated=souls_migrated,
    )


def format_plan(source: Path, target: Path, *, include_old_engine: bool) -> str:
    source = Path(source).expanduser()
    target = Path(target).expanduser()
    lines = [
        "Fabric home migration plan",
        f"  source: {source}",
        f"  target: {target}",
        "  legacy source: archived after verified copy",
        f"  old engine checkout: {'included' if include_old_engine else 'excluded (fresh Fabric engine is installed separately)'}",
        "  secrets/config/sessions/profiles/skills/cron/checkpoints: preserved",
        "  runtime PID/lock files: excluded",
    ]
    return "\n".join(lines)


def result_json(result: HomeMigrationResult) -> str:
    return json.dumps(asdict(result), indent=2)
