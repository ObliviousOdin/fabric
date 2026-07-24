from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from packaging.tags import sys_tags

from fabric_link import core_install
from fabric_link.core_install import (
    LinkCoreInstallError,
    LinkCoreStatus,
    install_release_wheel,
)


def _wheel_name(version: str = "1.2.3") -> str:
    tag = next(
        candidate
        for candidate in sys_tags()
        if candidate.interpreter == "py3" and candidate.abi == "none"
    )
    return f"fabric_link_core-{version}-py3-none-{tag.platform}.whl"


def _ready_status() -> LinkCoreStatus:
    return LinkCoreStatus(
        installed=True,
        protocol_version=3,
        ciphersuite="MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519",
        package_version="1.2.3",
        module_path="/protected/fabric_link_core.py",
        error=None,
    )


def test_release_wheel_is_copied_rehashed_and_installed_from_private_path(
    tmp_path,
    monkeypatch,
):
    wheel = tmp_path / _wheel_name()
    wheel.write_bytes(b"reviewed-native-wheel")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    installed_paths: list[Path] = []

    monkeypatch.setattr(
        core_install,
        "_distribution_version",
        lambda name: "1.2.3",
    )

    def capture_install(path: Path) -> None:
        assert path.parent != tmp_path
        assert path.read_bytes() == wheel.read_bytes()
        installed_paths.append(path)

    monkeypatch.setattr(core_install, "_install_wheel", capture_install)
    monkeypatch.setattr(core_install, "_verify_installed_core", _ready_status)

    status = install_release_wheel(wheel, expected_sha256=digest)

    assert status.installed is True
    assert len(installed_paths) == 1
    assert not installed_paths[0].exists()


def test_release_wheel_requires_matching_manifest_checksum(tmp_path, monkeypatch):
    wheel = tmp_path / _wheel_name()
    wheel.write_bytes(b"tampered")
    monkeypatch.setattr(
        core_install,
        "_distribution_version",
        lambda name: "1.2.3",
    )

    with pytest.raises(LinkCoreInstallError, match="wheel_sha256_mismatch"):
        install_release_wheel(wheel, expected_sha256="0" * 64)


def test_release_wheel_rejects_symlink(tmp_path):
    target = tmp_path / _wheel_name()
    target.write_bytes(b"wheel")
    link = tmp_path / f"fabric_link_core-1.2.3-py3-none-{target.name}.whl"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")

    with pytest.raises(LinkCoreInstallError, match="regular_file"):
        install_release_wheel(link, expected_sha256="0" * 64)
