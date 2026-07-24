"""Install and inspect Fabric Link's platform-native OpenMLS companion.

The universal ``fabric-agent`` package cannot safely carry one native library
for every operating system. Release installers therefore ship a separate,
platform-tagged ``fabric-link-core`` wheel. This module keeps installation
explicit and fail-closed: a release wheel needs its manifest SHA-256, and a
source build is allowed only from a complete Fabric checkout.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.metadata
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

from .core import LinkCoreUnavailable, load_openmls_core
from .protocol import FABRIC_LINK_PROTOCOL_VERSION

_CIPHERSUITE = "MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class LinkCoreInstallError(RuntimeError):
    """A stable, non-secret failure from native companion management."""


@dataclass(frozen=True)
class LinkCoreStatus:
    installed: bool
    protocol_version: int | None
    ciphersuite: str | None
    package_version: str | None
    module_path: str | None
    error: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def core_status() -> LinkCoreStatus:
    try:
        core = load_openmls_core()
        binding = core._binding  # Narrow adapter owns validation of this object.
        package_version = _distribution_version("fabric-link-core")
        module_path = getattr(binding, "__file__", None)
        return LinkCoreStatus(
            installed=True,
            protocol_version=int(binding.fabric_link_protocol_version()),
            ciphersuite=str(binding.fabric_link_ciphersuite()),
            package_version=package_version,
            module_path=str(Path(module_path).resolve()) if module_path else None,
            error=None,
        )
    except LinkCoreUnavailable as exc:
        return LinkCoreStatus(
            installed=False,
            protocol_version=None,
            ciphersuite=None,
            package_version=None,
            module_path=None,
            error=str(exc),
        )


def install_release_wheel(
    wheel_path: Path,
    *,
    expected_sha256: str,
) -> LinkCoreStatus:
    expected = str(expected_sha256 or "").strip().lower()
    if not _SHA256_RE.fullmatch(expected):
        raise LinkCoreInstallError("wheel_sha256_required")
    source = Path(wheel_path).expanduser()
    try:
        source_lstat = source.lstat()
    except OSError as exc:
        raise LinkCoreInstallError("wheel_not_found") from exc
    if stat.S_ISLNK(source_lstat.st_mode) or not stat.S_ISREG(source_lstat.st_mode):
        raise LinkCoreInstallError("wheel_must_be_regular_file")
    if source_lstat.st_mode & stat.S_IWOTH:
        raise LinkCoreInstallError("wheel_is_world_writable")

    _validate_wheel_identity(source.name)
    with tempfile.TemporaryDirectory(prefix="fabric-link-core-install-") as raw_tmp:
        private_root = Path(raw_tmp)
        os.chmod(private_root, 0o700)
        private_wheel = private_root / source.name
        with source.open("rb") as source_stream, private_wheel.open("xb") as target:
            shutil.copyfileobj(source_stream, target)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(private_wheel, 0o600)
        actual = _sha256(private_wheel)
        if not secrets_compare(actual, expected):
            raise LinkCoreInstallError("wheel_sha256_mismatch")
        _install_wheel(private_wheel)

    return _verify_installed_core()


def install_from_source(project_root: Path | None = None) -> LinkCoreStatus:
    root = (
        Path(project_root).expanduser().resolve()
        if project_root is not None
        else Path(__file__).resolve().parents[1]
    )
    package_root = root / "apps" / "fabric-link-core" / "python"
    cargo_manifest = root / "apps" / "fabric-link-core" / "Cargo.toml"
    if not package_root.is_dir() or not cargo_manifest.is_file():
        raise LinkCoreInstallError("fabric_link_source_checkout_required")
    uv = shutil.which("uv")
    cargo = shutil.which("cargo")
    if uv is None:
        raise LinkCoreInstallError("uv_required")
    if cargo is None:
        raise LinkCoreInstallError("rust_toolchain_required")

    with tempfile.TemporaryDirectory(prefix="fabric-link-core-build-") as raw_tmp:
        output = Path(raw_tmp)
        env = os.environ.copy()
        env.setdefault("RUSTUP_TOOLCHAIN", "1.97.1")
        try:
            subprocess.run(
                [uv, "build", "--wheel", "--out-dir", str(output)],
                cwd=package_root,
                env=env,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise LinkCoreInstallError("native_core_build_failed") from exc
        wheels = list(output.glob("fabric_link_core-*.whl"))
        if len(wheels) != 1:
            raise LinkCoreInstallError("native_core_build_output_invalid")
        _validate_wheel_identity(wheels[0].name)
        _install_wheel(wheels[0])

    return _verify_installed_core()


def _validate_wheel_identity(filename: str) -> None:
    try:
        distribution, version, _build, tags = parse_wheel_filename(filename)
    except Exception as exc:
        raise LinkCoreInstallError("invalid_native_core_wheel") from exc
    if canonicalize_name(str(distribution)) != "fabric-link-core":
        raise LinkCoreInstallError("wrong_native_core_distribution")
    agent_version = _distribution_version("fabric-agent")
    if agent_version is not None and str(version) != agent_version:
        raise LinkCoreInstallError("native_core_version_mismatch")
    if not tags.intersection(set(sys_tags())):
        raise LinkCoreInstallError("native_core_platform_mismatch")


def _install_wheel(wheel: Path) -> None:
    uv = shutil.which("uv")
    if uv is not None:
        command = [
            uv,
            "pip",
            "install",
            "--python",
            sys.executable,
            "--no-deps",
            "--reinstall",
            str(wheel),
        ]
    else:
        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--force-reinstall",
            str(wheel),
        ]
    try:
        subprocess.run(command, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LinkCoreInstallError("native_core_install_failed") from exc


def _verify_installed_core() -> LinkCoreStatus:
    probe = (
        "import json, fabric_link_core as c; "
        "print(json.dumps({'protocol_version': c.fabric_link_protocol_version(), "
        "'ciphersuite': c.fabric_link_ciphersuite(), "
        "'module_path': c.__file__}))"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", probe],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise LinkCoreInstallError("native_core_verification_failed") from exc
    if (
        payload.get("protocol_version") != FABRIC_LINK_PROTOCOL_VERSION
        or payload.get("ciphersuite") != _CIPHERSUITE
    ):
        raise LinkCoreInstallError("native_core_contract_mismatch")
    return LinkCoreStatus(
        installed=True,
        protocol_version=FABRIC_LINK_PROTOCOL_VERSION,
        ciphersuite=_CIPHERSUITE,
        package_version=_distribution_version("fabric-link-core"),
        module_path=str(Path(payload["module_path"]).resolve()),
        error=None,
    )


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def secrets_compare(left: str, right: str) -> bool:
    """Constant-time digest comparison without accepting non-hex values."""
    return hmac.compare_digest(left, right)
