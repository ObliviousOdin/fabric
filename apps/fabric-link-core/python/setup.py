"""Build only platform-native Fabric Link Core wheels.

The universal ``fabric-agent`` wheel remains pure Python. This companion is
the sole distribution that carries the generated UniFFI module and the adjacent
OpenMLS dynamic library, so ctypes can load only an artifact built for the
current platform. We intentionally do not publish an sdist: an unsupported
platform must fail closed instead of compiling unreviewed local crypto.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist
from setuptools.command.bdist_wheel import bdist_wheel

PACKAGE_ROOT = Path(__file__).resolve().parent
CORE_ROOT = PACKAGE_ROOT.parent
REPOSITORY_ROOT = CORE_ROOT.parents[1]


def _version() -> str:
    project = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    value = project["project"]["version"]
    if not isinstance(value, str) or not value:
        raise RuntimeError("Fabric project version is invalid")
    return value


def _library_name() -> str:
    if sys.platform == "darwin":
        return "libfabric_link_core.dylib"
    if sys.platform.startswith("win"):
        return "fabric_link_core.dll"
    return "libfabric_link_core.so"


class BuildPy(build_py):
    """Generate the binding and copy its matching native library into a wheel."""

    def run(self) -> None:
        super().run()
        library = CORE_ROOT / "target" / "release" / _library_name()
        subprocess.run(
            ["cargo", "build", "--release", "--locked", "--features", "bindgen"],
            cwd=CORE_ROOT,
            check=True,
        )
        if not library.is_file():
            raise RuntimeError(f"Fabric Link native library was not built: {library}")
        destination = Path(self.build_lib).resolve()
        subprocess.run(
            [
                "cargo",
                "run",
                "--release",
                "--locked",
                "--features",
                "bindgen",
                "--bin",
                "fabric-link-bindgen",
                "--",
                "generate",
                str(library),
                "--language",
                "python",
                "--out-dir",
                str(destination),
                "--no-format",
            ],
            cwd=CORE_ROOT,
            check=True,
        )
        shutil.copy2(library, destination / library.name)
        legal_destination = destination / "fabric_link_core_licenses"
        legal_destination.mkdir(exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / "LICENSE", legal_destination / "LICENSE")
        shutil.copy2(REPOSITORY_ROOT / "NOTICE", legal_destination / "NOTICE")
        mit_license = legal_destination / "LICENSES"
        mit_license.mkdir(exist_ok=True)
        shutil.copy2(
            REPOSITORY_ROOT / "LICENSES" / "MIT-nous-research.txt",
            mit_license / "MIT-nous-research.txt",
        )


class PlatformWheel(bdist_wheel):
    """Tag the ctypes binding as platform-specific but Python-ABI independent."""

    def finalize_options(self) -> None:
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self) -> tuple[str, str, str]:
        _python, _abi, platform = super().get_tag()
        return "py3", "none", platform


class NoSourceDistribution(sdist):
    """Never let an unsupported platform fall back to compiling Link crypto."""

    def run(self) -> None:
        raise RuntimeError("fabric-link-core publishes wheels only; source builds are disabled")


setup(
    version=_version(),
    cmdclass={
        "bdist_wheel": PlatformWheel,
        "build_py": BuildPy,
        "sdist": NoSourceDistribution,
    },
)
