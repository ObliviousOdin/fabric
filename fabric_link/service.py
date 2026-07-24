"""Current-user service lifecycle for the outbound-only Fabric Link broker."""

from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence

from fabric_constants import get_fabric_home

from .store import _ensure_private_directory, _harden_private_path

_SERVICE_MARKER = "Managed by Fabric Link"
_LAUNCHD_LABEL = "com.fabric.link"
_SYSTEMD_UNIT = "fabric-link.service"
_WINDOWS_TASK = r"\Fabric\Link"
_VALID_ACTIONS = frozenset(
    {"install", "uninstall", "start", "stop", "restart", "status"}
)


class LinkServiceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class LinkServiceStatus:
    manager: str
    installed: bool
    running: bool
    starts_on_login: bool
    definition: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


Runner = Callable[..., subprocess.CompletedProcess[str]]


class LinkServiceManager:
    """Install and control one unprivileged per-user Link broker.

    Definitions are intentionally separate from the existing messaging gateway
    service. The broker opens no listener and executes only ``fabric link
    host`` with the current profile home and an explicit working directory.
    """

    def __init__(
        self,
        *,
        platform: str | None = None,
        fabric_home: Path | None = None,
        workspace: Path | None = None,
        python_executable: Path | None = None,
        runner: Runner = subprocess.run,
        user_home: Path | None = None,
    ) -> None:
        self.platform = platform or _platform_name()
        if self.platform not in {"darwin", "linux", "windows"}:
            raise LinkServiceError("link_service_platform_unsupported")
        self.fabric_home = (fabric_home or get_fabric_home()).expanduser().resolve()
        self.link_home = self.fabric_home / "link"
        self.workspace = (workspace or Path.cwd()).expanduser().resolve()
        if not self.workspace.is_dir():
            raise LinkServiceError("link_service_workspace_invalid")
        self.python_executable = (
            python_executable or Path(sys.executable)
        ).expanduser().resolve()
        if not self.python_executable.is_file():
            raise LinkServiceError("link_service_python_unavailable")
        self.user_home = (user_home or Path.home()).expanduser().resolve()
        self._run = runner

    @property
    def manager(self) -> str:
        return {
            "darwin": "launchd",
            "linux": "systemd-user",
            "windows": "task-scheduler",
        }[self.platform]

    @property
    def definition_path(self) -> Path:
        if self.platform == "darwin":
            return (
                self.user_home
                / "Library"
                / "LaunchAgents"
                / f"{_LAUNCHD_LABEL}.plist"
            )
        if self.platform == "linux":
            return (
                self.user_home
                / ".config"
                / "systemd"
                / "user"
                / _SYSTEMD_UNIT
            )
        return self.link_home / "fabric-link-task.xml"

    def install(
        self,
        *,
        force: bool = False,
        start_now: bool = True,
        start_on_login: bool = True,
    ) -> LinkServiceStatus:
        existing = self.definition_path
        if existing.exists():
            if not _is_managed_definition(existing):
                raise LinkServiceError("link_service_definition_conflict")
            if not force:
                current = self.status()
                if current.installed:
                    if start_now and not current.running:
                        self.start()
                    return self.status()
        _ensure_private_directory(self.link_home)
        if self.platform == "darwin":
            self._install_launchd(start_on_login=start_on_login)
        elif self.platform == "linux":
            self._install_systemd(start_on_login=start_on_login)
        else:
            self._install_windows(start_on_login=start_on_login, force=force)
        if start_now:
            self.start()
        return self.status()

    def uninstall(self) -> LinkServiceStatus:
        if self.platform == "darwin":
            self._stop_launchd(ignore_missing=True)
            self._remove_managed_definition()
        elif self.platform == "linux":
            self._systemctl("disable", "--now", _SYSTEMD_UNIT, check=False)
            self._remove_managed_definition()
            self._systemctl("daemon-reload", check=False)
        else:
            self._schtasks("/Delete", "/TN", _WINDOWS_TASK, "/F", check=False)
            self._remove_managed_definition()
        return self.status()

    def start(self) -> LinkServiceStatus:
        self._require_installed()
        if self.platform == "darwin":
            self._start_launchd()
        elif self.platform == "linux":
            self._systemctl("start", _SYSTEMD_UNIT)
        else:
            self._schtasks("/Run", "/TN", _WINDOWS_TASK)
        return self.status()

    def stop(self) -> LinkServiceStatus:
        if self.platform == "darwin":
            self._stop_launchd(ignore_missing=True)
        elif self.platform == "linux":
            self._systemctl("stop", _SYSTEMD_UNIT, check=False)
        else:
            self._schtasks("/End", "/TN", _WINDOWS_TASK, check=False)
        return self.status()

    def restart(self) -> LinkServiceStatus:
        self._require_installed()
        if self.platform == "darwin":
            self._stop_launchd(ignore_missing=True)
            self._start_launchd()
        elif self.platform == "linux":
            self._systemctl("restart", _SYSTEMD_UNIT)
        else:
            self._schtasks("/End", "/TN", _WINDOWS_TASK, check=False)
            self._schtasks("/Run", "/TN", _WINDOWS_TASK)
        return self.status()

    def status(self) -> LinkServiceStatus:
        installed = self._is_installed()
        running = False
        starts_on_login = False
        if self.platform == "darwin":
            running = self._launchctl(
                "print",
                f"gui/{os.getuid()}/{_LAUNCHD_LABEL}",
                check=False,
            ).returncode == 0
            if installed:
                try:
                    value = plistlib.loads(self.definition_path.read_bytes())
                    starts_on_login = bool(value.get("RunAtLoad", False))
                except (OSError, plistlib.InvalidFileException):
                    starts_on_login = False
        elif self.platform == "linux":
            running = (
                self._systemctl(
                    "is-active",
                    "--quiet",
                    _SYSTEMD_UNIT,
                    check=False,
                ).returncode
                == 0
            )
            starts_on_login = (
                self._systemctl(
                    "is-enabled",
                    "--quiet",
                    _SYSTEMD_UNIT,
                    check=False,
                ).returncode
                == 0
            )
        else:
            query = self._schtasks(
                "/Query",
                "/TN",
                _WINDOWS_TASK,
                "/FO",
                "LIST",
                "/V",
                check=False,
            )
            installed = query.returncode == 0 and installed
            lowered = query.stdout.lower()
            running = installed and "running" in lowered
            starts_on_login = installed and "<logontrigger>" in _read_text(
                self.definition_path
            ).lower()
        return LinkServiceStatus(
            manager=self.manager,
            installed=installed,
            running=running,
            starts_on_login=starts_on_login,
            definition=str(self.definition_path),
        )

    def execute(
        self,
        action: str,
        *,
        force: bool = False,
        start_now: bool = True,
        start_on_login: bool = True,
    ) -> LinkServiceStatus:
        if action not in _VALID_ACTIONS:
            raise LinkServiceError("unknown_link_service_action")
        if action == "install":
            return self.install(
                force=force,
                start_now=start_now,
                start_on_login=start_on_login,
            )
        if action == "uninstall":
            return self.uninstall()
        return getattr(self, action)()

    def _is_installed(self) -> bool:
        return self.definition_path.is_file() and _is_managed_definition(
            self.definition_path
        )

    def _require_installed(self) -> None:
        if not self._is_installed():
            raise LinkServiceError("link_service_not_installed")

    def _remove_managed_definition(self) -> None:
        path = self.definition_path
        if not path.exists():
            return
        if not _is_managed_definition(path):
            raise LinkServiceError("link_service_definition_conflict")
        try:
            path.unlink()
        except OSError as exc:
            raise LinkServiceError("link_service_remove_failed") from exc

    def _install_launchd(self, *, start_on_login: bool) -> None:
        log_dir = self.fabric_home / "logs"
        _ensure_private_directory(log_dir)
        value = {
            "Label": _LAUNCHD_LABEL,
            "ProgramArguments": self._command(),
            "EnvironmentVariables": {"FABRIC_HOME": str(self.fabric_home)},
            "WorkingDirectory": str(self.workspace),
            "RunAtLoad": start_on_login,
            "KeepAlive": {"SuccessfulExit": False} if start_on_login else False,
            "ProcessType": "Background",
            "StandardOutPath": str(log_dir / "link.log"),
            "StandardErrorPath": str(log_dir / "link-errors.log"),
            "FabricManagedMarker": _SERVICE_MARKER,
        }
        _atomic_write(
            self.definition_path,
            plistlib.dumps(value, fmt=plistlib.FMT_XML, sort_keys=True),
            mode=0o600,
        )

    def _install_systemd(self, *, start_on_login: bool) -> None:
        command = " ".join(_systemd_quote(value) for value in self._command())
        unit = "\n".join(
            [
                f"# {_SERVICE_MARKER}",
                "[Unit]",
                "Description=Fabric Link outbound broker",
                "After=network-online.target",
                "Wants=network-online.target",
                "",
                "[Service]",
                "Type=simple",
                f"ExecStart={command}",
                f"WorkingDirectory={_systemd_quote(str(self.workspace))}",
                f"Environment={_systemd_quote(f'FABRIC_HOME={self.fabric_home}')}",
                "Restart=on-failure",
                "RestartSec=3",
                "NoNewPrivileges=true",
                "PrivateTmp=true",
                "ProtectSystem=strict",
                f"ReadWritePaths={_systemd_quote(str(self.fabric_home))}",
                f"ReadWritePaths={_systemd_quote(str(self.workspace))}",
                "",
                "[Install]",
                "WantedBy=default.target",
                "",
            ]
        ).encode("utf-8")
        _atomic_write(self.definition_path, unit, mode=0o600)
        self._systemctl("daemon-reload")
        if start_on_login:
            self._systemctl("enable", _SYSTEMD_UNIT)
        else:
            self._systemctl("disable", _SYSTEMD_UNIT, check=False)

    def _install_windows(self, *, start_on_login: bool, force: bool) -> None:
        existing_task = self._schtasks(
            "/Query",
            "/TN",
            _WINDOWS_TASK,
            check=False,
        )
        if existing_task.returncode == 0 and not _is_managed_definition(
            self.definition_path
        ):
            raise LinkServiceError("link_service_definition_conflict")
        sid = _windows_current_sid(self._run)
        triggers = (
            "<Triggers><LogonTrigger><Enabled>true</Enabled>"
            "</LogonTrigger></Triggers>"
            if start_on_login
            else "<Triggers />"
        )
        command = _xml_escape(str(self.python_executable))
        arguments = _xml_escape(" ".join(_windows_quote(v) for v in self._command()[1:]))
        working = _xml_escape(str(self.workspace))
        xml = (
            '<?xml version="1.0" encoding="UTF-16"?>'
            '<Task version="1.4" '
            'xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
            f"<RegistrationInfo><Description>{_SERVICE_MARKER}</Description>"
            "</RegistrationInfo>"
            f"<Principals><Principal id=\"Author\"><UserId>{_xml_escape(sid)}</UserId>"
            "<LogonType>InteractiveToken</LogonType>"
            "<RunLevel>LeastPrivilege</RunLevel></Principal></Principals>"
            f"{triggers}"
            "<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>"
            "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>"
            "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>"
            "<AllowStartOnDemand>true</AllowStartOnDemand>"
            "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>"
            "<Enabled>true</Enabled></Settings>"
            f"<Actions Context=\"Author\"><Exec><Command>{command}</Command>"
            f"<Arguments>{arguments}</Arguments>"
            f"<WorkingDirectory>{working}</WorkingDirectory>"
            "</Exec></Actions></Task>"
        ).encode("utf-16")
        _atomic_write(self.definition_path, xml, mode=0o600)
        args = ["/Create", "/TN", _WINDOWS_TASK, "/XML", str(self.definition_path)]
        if force:
            args.append("/F")
        self._schtasks(*args)

    def _command(self) -> list[str]:
        return [
            str(self.python_executable),
            "-m",
            "fabric_link.service_entry",
            "--fabric-home",
            str(self.fabric_home),
            "--workspace",
            str(self.workspace),
        ]

    def _start_launchd(self) -> None:
        domain = f"gui/{os.getuid()}"
        current = self._launchctl(
            "print",
            f"{domain}/{_LAUNCHD_LABEL}",
            check=False,
        )
        if current.returncode != 0:
            self._launchctl("bootstrap", domain, str(self.definition_path))
        self._launchctl("kickstart", "-k", f"{domain}/{_LAUNCHD_LABEL}")

    def _stop_launchd(self, *, ignore_missing: bool) -> None:
        result = self._launchctl(
            "bootout",
            f"gui/{os.getuid()}/{_LAUNCHD_LABEL}",
            check=False,
        )
        if result.returncode != 0 and not ignore_missing:
            raise LinkServiceError("link_service_stop_failed")

    def _systemctl(
        self,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._execute(["systemctl", "--user", *args], check=check)

    def _launchctl(
        self,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._execute(["launchctl", *args], check=check)

    def _schtasks(
        self,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._execute(["schtasks.exe", *args], check=check)

    def _execute(
        self,
        argv: Sequence[str],
        *,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = self._run(
                list(argv),
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise LinkServiceError("link_service_manager_unavailable") from exc
        if check and result.returncode != 0:
            raise LinkServiceError("link_service_command_failed")
        return result


def _platform_name() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def _is_managed_definition(path: Path) -> bool:
    try:
        content = path.read_bytes()
    except OSError:
        return False
    return _SERVICE_MARKER.encode("utf-8") in content or _SERVICE_MARKER.encode(
        "utf-16-le"
    ) in content


def _atomic_write(path: Path, content: bytes, *, mode: int) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink():
            raise LinkServiceError("link_service_parent_unsafe")
        fd, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=str(path.parent),
        )
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, mode)
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            try:
                os.chmod(path, mode)
            except OSError:
                pass
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                Path(temporary).unlink()
            except OSError:
                pass
            raise
        _harden_private_path(path, directory=False)
    except LinkServiceError:
        raise
    except OSError as exc:
        raise LinkServiceError("link_service_definition_write_failed") from exc


def _systemd_quote(value: str) -> str:
    # systemd accepts JSON-style double quoting for these simple UTF-8 paths.
    return json.dumps(value.replace("%", "%%"), ensure_ascii=False)


def _windows_quote(value: str) -> str:
    if not value or re.search(r'[\\s"]', value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _windows_current_sid(runner: Runner) -> str:
    executable = shutil.which("whoami") or "whoami.exe"
    try:
        result = runner(
            [executable, "/user", "/fo", "csv", "/nh"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
        )
        match = re.search(r'"(S-1-[0-9-]+)"', result.stdout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LinkServiceError("windows_sid_unavailable") from exc
    if result.returncode != 0 or match is None:
        raise LinkServiceError("windows_sid_unavailable")
    return match.group(1)


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _read_text(path: Path) -> str:
    try:
        encoded = path.read_bytes()
    except OSError:
        return ""
    if encoded.startswith((b"\xff\xfe", b"\xfe\xff")):
        return encoded.decode("utf-16", errors="ignore")
    return encoded.decode("utf-8", errors="ignore")
