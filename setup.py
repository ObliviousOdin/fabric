from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import tempfile

from setuptools import setup
from setuptools.command.build import build as _build
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.egg_info import egg_info as _egg_info


REPO_ROOT = Path(__file__).parent.resolve()
INSTALLER_SCRIPT_NAMES = ("install.sh", "install.ps1")


def _source_tree_is_writable() -> bool:
    probe = REPO_ROOT / ".setuptools-write-probe"
    try:
        with probe.open("w", encoding="utf-8") as handle:
            handle.write("")
        probe.unlink()
    except OSError:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def _temporary_build_dir(kind: str) -> str:
    return tempfile.mkdtemp(prefix=f"fabric-agent-{kind}-")


def _would_write_under_source(path_value: str | None) -> bool:
    if path_value is None:
        return True
    path = Path(path_value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return False
    return True


class ReadOnlySourceBuild(_build):
    def finalize_options(self) -> None:
        if (
            not _source_tree_is_writable()
            and _would_write_under_source(self.build_base)
        ):
            self.build_base = _temporary_build_dir("build")
        super().finalize_options()


class ReadOnlySourceEggInfo(_egg_info):
    def finalize_options(self) -> None:
        if (
            not _source_tree_is_writable()
            and _would_write_under_source(self.egg_base)
        ):
            self.egg_base = _temporary_build_dir("egg-info")
        super().finalize_options()


class FabricBuildPy(_build_py):
    """Bundle the canonical installers without writing into the source tree."""

    def _installer_outputs(self) -> list[Path]:
        target_dir = Path(self.build_lib) / "fabric_cli" / "scripts"
        return [target_dir / name for name in INSTALLER_SCRIPT_NAMES]

    def run(self) -> None:
        super().run()
        # Editable installs import fabric_cli from this checkout, where
        # dep_ensure already finds the canonical root scripts directly.
        if getattr(self, "editable_mode", False):
            return
        source_dir = REPO_ROOT / "scripts"
        outputs = self._installer_outputs()
        self.mkpath(str(outputs[0].parent))
        for name, target in zip(INSTALLER_SCRIPT_NAMES, outputs, strict=True):
            self.copy_file(str(source_dir / name), str(target))

    def get_outputs(self, include_bytecode: bool = True) -> list[str]:
        outputs = super().get_outputs(include_bytecode)
        if getattr(self, "editable_mode", False):
            return outputs
        return [*outputs, *(str(path) for path in self._installer_outputs())]


def _data_file_tree(root_name: str) -> list[tuple[str, list[str]]]:
    root = REPO_ROOT / root_name
    grouped: defaultdict[str, list[str]] = defaultdict(list)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(REPO_ROOT)
        grouped[str(rel_path.parent)].append(str(rel_path))
    return sorted(grouped.items())


setup(
    cmdclass={
        "build": ReadOnlySourceBuild,
        "build_py": FabricBuildPy,
        "egg_info": ReadOnlySourceEggInfo,
    },
    data_files=[
        *_data_file_tree("locales"),
        *_data_file_tree("optional-mcps"),
        *_data_file_tree("skills"),
        *_data_file_tree("optional-skills"),
    ]
)
