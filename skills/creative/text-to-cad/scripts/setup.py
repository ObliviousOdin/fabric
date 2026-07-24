#!/usr/bin/env python3
"""Create the isolated, cross-platform Text-to-CAD virtual environment."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv


REQUIRED_IMPORTS = "import build123d, stl, matplotlib, ezdxf"


def interpreter_path(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def ready(python: Path) -> bool:
    return python.is_file() and subprocess.run(
        [str(python), "-c", REQUIRED_IMPORTS],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def main() -> int:
    if sys.version_info < (3, 11):
        print(
            f"Text-to-CAD setup requires Python >= 3.11 (found {sys.version_info.major}.{sys.version_info.minor})",
            file=sys.stderr,
        )
        return 1

    skill_dir = Path(__file__).resolve().parent.parent
    requirements = skill_dir / "requirements.txt"
    fabric_home = Path(os.environ.get("FABRIC_HOME", Path.home() / ".fabric")).expanduser()
    venv_dir = fabric_home / "text-to-cad" / "venv"
    python = interpreter_path(venv_dir)

    print("\nText-to-CAD Skill — Environment Setup\n")
    print(f"Python {sys.version_info.major}.{sys.version_info.minor}")

    if not ready(python):
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        uv = shutil.which("uv")
        if uv:
            run([uv, "venv", str(venv_dir), "--python", "3.11", "--quiet"])
            python = interpreter_path(venv_dir)
            run([uv, "pip", "install", "--python", str(python), "--quiet", "-r", str(requirements)])
        else:
            venv.EnvBuilder(with_pip=True, clear=False).create(venv_dir)
            python = interpreter_path(venv_dir)
            run([str(python), "-m", "pip", "install", "--quiet", "-r", str(requirements)])

        if not ready(python):
            print("Text-to-CAD setup verification failed.", file=sys.stderr)
            return 1

    print(f"\nEnvironment ready. Interpreter:\n{python}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
