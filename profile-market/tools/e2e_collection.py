#!/usr/bin/env python3
# Portions adapted from teknium1/hermes-star-trek-profiles.
# Copyright (c) 2026 Teknium. MIT licensed; see ../THIRD_PARTY_NOTICES.md.
"""Exercise generated distributions through the real Fabric CLI in isolation."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from collection_common import CollectionError, load_collection_source
from validate_collection import validate


ROOT = Path(__file__).resolve().parents[1]


def resolve_binary(value: str) -> str:
    candidate = Path(value).expanduser()
    if candidate.parent != Path(".") or "/" in value or "\\" in value:
        if not candidate.is_file():
            raise CollectionError(f"Fabric executable not found: {value}")
        return str(candidate.resolve())
    resolved = shutil.which(value)
    if resolved is None:
        raise CollectionError(f"Fabric executable not found on PATH: {value}")
    return resolved


def run(
    command: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
    timeout: int = 1800,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CollectionError(f"command timed out: {' '.join(command)}") from exc


def require_success(proc: subprocess.CompletedProcess[str], action: str) -> None:
    if proc.returncode == 0:
        return
    stdout = proc.stdout[-8000:] if proc.stdout else ""
    stderr = proc.stderr[-8000:] if proc.stderr else ""
    raise CollectionError(f"{action} failed\nstdout:\n{stdout}\nstderr:\n{stderr}")


def copy_market(destination: Path) -> Path:
    market = destination / "profile-market"
    shutil.copytree(
        ROOT,
        market,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".pytest_cache"),
    )
    return market


def assert_installed_profile(
    installed: Path,
    source_profile: dict,
) -> None:
    slug = source_profile["slug"]
    if not installed.is_dir():
        raise CollectionError(f"{slug}: Fabric did not create the profile directory")
    soul = (installed / "SOUL.md").read_text(encoding="utf-8")
    if source_profile["name"] not in soul or source_profile["core_identity"] not in soul:
        raise CollectionError(f"{slug}: installed SOUL omitted identity content")
    config = yaml.safe_load((installed / "config.yaml").read_text(encoding="utf-8"))
    if config != {"model": "", "display": {"skin": slug}}:
        raise CollectionError(f"{slug}: installed config is not provider/model neutral")
    skin = yaml.safe_load((installed / "skins" / f"{slug}.yaml").read_text(encoding="utf-8"))
    if skin.get("name") != slug or skin.get("branding", {}).get("agent_name") != source_profile["name"]:
        raise CollectionError(f"{slug}: installed skin identity mismatch")
    manifest = yaml.safe_load((installed / "distribution.yaml").read_text(encoding="utf-8"))
    if manifest.get("name") != slug or not manifest.get("source"):
        raise CollectionError(f"{slug}: Fabric did not stamp distribution provenance")


def e2e(fabric_bin: str) -> tuple[int, int]:
    # Run structural and behavioral checks before handing payloads to Fabric.
    profile_count, category_count = validate()
    source = load_collection_source(ROOT)

    with tempfile.TemporaryDirectory(prefix="fabric_profile_market_e2e_") as temp:
        temp_root = Path(temp)
        market = copy_market(temp_root)
        fabric_home = temp_root / "fabric-home"
        fabric_home.mkdir()
        env = dict(os.environ)
        # FABRIC_HOME is an official process-isolation input, not pack behavior
        # configuration. HERMES_HOME remains synchronized for compatibility
        # paths in current Fabric releases.
        env["FABRIC_HOME"] = str(fabric_home)
        env["HERMES_HOME"] = str(fabric_home)
        env.pop("HERMES_PROFILE", None)

        install_proc = run(
            [
                sys.executable,
                str(market / "manage.py"),
                "install",
                "--all",
                "--yes",
                "--fabric-bin",
                fabric_bin,
            ],
            env=env,
            cwd=market,
        )
        require_success(install_proc, "collection install")

        installed_root = fabric_home / "profiles"
        for profile in source["profiles"]:
            installed = installed_root / profile["slug"]
            assert_installed_profile(installed, profile)
            described = run(
                [fabric_bin, "profile", "describe", profile["slug"]],
                env=env,
                cwd=market,
                timeout=300,
            )
            require_success(described, f"description read for {profile['slug']}")
            if profile["description"] not in described.stdout:
                raise CollectionError(
                    f"{profile['slug']}: fresh install did not set routing description"
                )

        # One relationship-focused update test proves distribution-owned
        # identity refreshes while user-owned memory, config, and description
        # remain unchanged. It deliberately chooses from data rather than a
        # frozen slug or collection count.
        sample = source["profiles"][0]
        slug = sample["slug"]
        installed = installed_root / slug
        memory = installed / "memories" / "MEMORY.md"
        memory.parent.mkdir(parents=True, exist_ok=True)
        memory.write_text("LOCAL USER MEMORY\n", encoding="utf-8")
        local_config = 'model: "local-user-model"\ndisplay:\n  skin: local-user-skin\n'
        (installed / "config.yaml").write_text(local_config, encoding="utf-8")

        # Corrupt only the installed distribution-owned copy. The canonical
        # generated source must stay deterministic or the manager should reject
        # it before mutation. A normal update should restore this local drift.
        source_soul = market / "profiles" / slug / "SOUL.md"
        expected_soul = source_soul.read_text(encoding="utf-8")
        installed_soul = installed / "SOUL.md"
        installed_soul.write_text(
            expected_soul + "\n<!-- E2E LOCAL STALE COPY -->\n",
            encoding="utf-8",
        )
        update_proc = run(
            [
                sys.executable,
                str(market / "manage.py"),
                "update",
                slug,
                "--yes",
                "--fabric-bin",
                fabric_bin,
            ],
            env=env,
            cwd=market,
            timeout=600,
        )
        require_success(update_proc, f"update for {slug}")
        if installed_soul.read_text(encoding="utf-8") != expected_soul:
            raise CollectionError(f"{slug}: update did not restore distribution-owned SOUL")
        if (installed / "config.yaml").read_text(encoding="utf-8") != local_config:
            raise CollectionError(f"{slug}: update overwrote local config")
        if memory.read_text(encoding="utf-8") != "LOCAL USER MEMORY\n":
            raise CollectionError(f"{slug}: update overwrote local memory")
        described = run(
            [fabric_bin, "profile", "describe", slug],
            env=env,
            cwd=market,
            timeout=300,
        )
        require_success(described, f"description preservation read for {slug}")
        if sample["description"] not in described.stdout:
            raise CollectionError(f"{slug}: update overwrote routing description")

    return profile_count, category_count


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fabric-bin",
        default="fabric",
        metavar="PATH",
        help="Fabric executable to exercise (default: fabric)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        fabric_bin = resolve_binary(args.fabric_bin)
        profile_count, category_count = e2e(fabric_bin)
    except (CollectionError, OSError, yaml.YAMLError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(
        f"E2E validated {profile_count} native Fabric profile install(s) across "
        f"{category_count} category/categories and one preserving update."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
