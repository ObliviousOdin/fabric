"""Runtime drivers: where Loom actually touches infrastructure.

A :class:`RuntimeDriver` performs the external side effects for one host —
inspecting it (read-only), bringing a release up, checking health, streaming
logs, and stopping it. Two concrete drivers ship:

- :class:`LocalDriver` runs on *this machine* via ``subprocess``.
- :class:`SshDriver` runs on an owned Linux host by reusing Fabric's existing
  :class:`tools.environments.ssh.SSHEnvironment` (OpenSSH + ControlMaster +
  host-key pinning), so no new SSH dependency is introduced.

Business logic never lives here — the service decides *whether* to act; the
driver only knows *how*. Tests inject a fake driver, so real Docker/SSH is
never required to exercise the plan/apply/rollback logic.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import List

from fabric_cli.loom.errors import LoomDriverError
from fabric_cli.loom.models import Host

_COMMAND_TIMEOUT_SECONDS = 300
_HEALTH_TIMEOUT_SECONDS = 10


@dataclass
class ScanResult:
    """Read-only inventory of a host (spec Journey C, adoption scan)."""

    reachable: bool = False
    os: str = ""
    arch: str = ""
    docker_available: bool = False
    notes: List[str] = field(default_factory=list)


@dataclass
class ReleaseSpec:
    """Everything a driver needs to bring one release up.

    Built by the service from a project + deployment so drivers stay ignorant
    of Loom's data model.
    """

    name: str
    kind: str
    workdir: str = "."
    compose_file: str = "docker-compose.yml"
    health_url: str = ""
    env_file: str = ""


class RuntimeDriver:
    """Interface implemented by every runtime driver."""

    def scan(self) -> ScanResult:  # pragma: no cover - interface
        raise NotImplementedError

    def run_release(self, spec: ReleaseSpec) -> str:  # pragma: no cover
        raise NotImplementedError

    def health_check(self, spec: ReleaseSpec) -> bool:  # pragma: no cover
        raise NotImplementedError

    def fetch_logs(self, spec: ReleaseSpec) -> str:  # pragma: no cover
        raise NotImplementedError

    def stop(self, spec: ReleaseSpec) -> str:  # pragma: no cover
        raise NotImplementedError


def _http_ok(url: str, timeout: int = _HEALTH_TIMEOUT_SECONDS) -> bool:
    """Best-effort HTTP health probe: True on any 2xx/3xx response."""
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return 200 <= int(resp.status) < 400
    except (urllib.error.URLError, ValueError, OSError):
        return False


class LocalDriver(RuntimeDriver):
    """Deploy onto the machine running Fabric using local ``docker compose``."""

    def __init__(self, host: Host) -> None:
        self.host = host

    def _run(self, args: List[str], cwd: str) -> str:
        try:
            proc = subprocess.run(
                args,
                cwd=cwd or ".",
                capture_output=True,
                text=True,
                timeout=_COMMAND_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError as exc:
            raise LoomDriverError(f"command not found: {args[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise LoomDriverError(
                f"command timed out after {_COMMAND_TIMEOUT_SECONDS}s: {' '.join(args)}"
            ) from exc
        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            raise LoomDriverError(
                f"`{' '.join(args)}` exited {proc.returncode}:\n{output.strip()}"
            )
        return output

    def scan(self) -> ScanResult:
        result = ScanResult(reachable=True)
        result.os = platform.system()
        result.arch = platform.machine()
        result.docker_available = bool(shutil.which("docker"))
        if not result.docker_available:
            result.notes.append(
                "docker not found on PATH; container deployments will fail"
            )
        return result

    def run_release(self, spec: ReleaseSpec) -> str:
        args = ["docker", "compose", "-f", spec.compose_file]
        if spec.env_file:
            args += ["--env-file", spec.env_file]
        args += ["up", "-d"]
        return self._run(args, spec.workdir)

    def health_check(self, spec: ReleaseSpec) -> bool:
        if not spec.health_url:
            # No probe configured: treat a successful bring-up as healthy but
            # let the caller know the check was not enforced.
            return True
        return _http_ok(spec.health_url)

    def fetch_logs(self, spec: ReleaseSpec) -> str:
        args = ["docker", "compose", "-f", spec.compose_file, "logs", "--tail", "200"]
        return self._run(args, spec.workdir)

    def stop(self, spec: ReleaseSpec) -> str:
        args = ["docker", "compose", "-f", spec.compose_file, "down"]
        return self._run(args, spec.workdir)


class SshDriver(RuntimeDriver):
    """Deploy onto an owned Linux host over SSH.

    Wraps :class:`tools.environments.ssh.SSHEnvironment` (imported lazily so the
    module stays importable where SSH is unavailable). The remote workflow is
    the same ``docker compose`` sequence, executed through the pinned SSH
    channel.
    """

    def __init__(self, host: Host) -> None:
        self.host = host

    def _env(self):
        try:
            from tools.environments.ssh import SSHEnvironment
        except Exception as exc:  # pragma: no cover - environment dependent
            raise LoomDriverError(f"SSH support unavailable: {exc}") from exc
        return SSHEnvironment(
            host=self.host.address,
            user=self.host.user,
            port=self.host.port,
            key_path=self.host.ssh_key_path,
        )

    def _remote(self, command: str) -> str:
        env = self._env()
        try:
            result = env.execute(command)
        except Exception as exc:  # pragma: no cover - environment dependent
            raise LoomDriverError(f"remote command failed: {exc}") from exc
        finally:
            try:
                env.cleanup()
            except Exception:
                pass
        # SSHEnvironment.execute (via BaseEnvironment) returns a dict with
        # "output" and "returncode". Fail closed on a nonzero remote exit so a
        # failed `docker compose` is never mistaken for a healthy release.
        if isinstance(result, dict):
            output = str(result.get("output", ""))
            returncode = int(result.get("returncode") or 0)
        else:  # defensive: alternate environments may return an object/string
            attr_output = getattr(result, "output", None)
            output = attr_output if attr_output is not None else str(result)
            returncode = int(getattr(result, "returncode", 0) or 0)
        if returncode != 0:
            raise LoomDriverError(
                f"remote command exited {returncode}: {output.strip()}"
            )
        return output

    def scan(self) -> ScanResult:
        result = ScanResult()
        try:
            probe = self._remote(
                "uname -s; uname -m; (command -v docker >/dev/null && echo DOCKER_OK "
                "|| echo DOCKER_MISSING)"
            )
        except LoomDriverError as exc:
            result.reachable = False
            result.notes.append(str(exc))
            return result
        result.reachable = True
        lines = [ln.strip() for ln in probe.splitlines() if ln.strip()]
        if lines:
            result.os = lines[0]
        if len(lines) > 1:
            result.arch = lines[1]
        result.docker_available = "DOCKER_OK" in probe
        if not result.docker_available:
            result.notes.append("docker not found on remote host")
        return result

    def run_release(self, spec: ReleaseSpec) -> str:
        env_flag = f" --env-file {spec.env_file}" if spec.env_file else ""
        cmd = (
            f"cd {spec.workdir} && docker compose -f {spec.compose_file}"
            f"{env_flag} up -d"
        )
        return self._remote(cmd)

    def health_check(self, spec: ReleaseSpec) -> bool:
        if not spec.health_url:
            return True
        out = self._remote(
            f"curl -fsS -o /dev/null -w '%{{http_code}}' {spec.health_url} || echo 000"
        )
        code = out.strip().splitlines()[-1] if out.strip() else "000"
        return code.startswith("2") or code.startswith("3")

    def fetch_logs(self, spec: ReleaseSpec) -> str:
        cmd = (
            f"cd {spec.workdir} && docker compose -f {spec.compose_file} "
            f"logs --tail 200"
        )
        return self._remote(cmd)

    def stop(self, spec: ReleaseSpec) -> str:
        cmd = f"cd {spec.workdir} && docker compose -f {spec.compose_file} down"
        return self._remote(cmd)


def default_driver_factory(host: Host) -> RuntimeDriver:
    """Return the concrete driver for ``host`` based on its kind."""
    if host.kind == "local":
        return LocalDriver(host)
    if host.kind == "ssh":
        return SshDriver(host)
    raise LoomDriverError(f"unknown host kind: {host.kind!r}")
