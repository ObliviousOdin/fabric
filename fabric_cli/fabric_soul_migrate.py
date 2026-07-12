"""Migrate byte-identical upstream default SOUL.md files to Fabric identity.

Host-install counterpart to ``docker/cont-init.d-fabric/04-migrate-fabric-soul``.
Only rewrites souls whose sha256 matches a known upstream default template.
User-customized souls are never touched.

Usage:
  python -m fabric_cli.fabric_soul_migrate
  python -m fabric_cli.fabric_soul_migrate --home /path/to/FABRIC_HOME
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path
from typing import Iterable

# public-release-audit: allow-legacy-compat -- reads the previous home variable during upgrades
_LEGACY_HOME_ENV = "HERMES_HOME"

# Keep in sync with docker/cont-init.d-fabric/04-migrate-fabric-soul
LEGACY_SEED_HASH = "82fa3438d86f8b95c6e96be89d853c8b561b3e6973ed61c90e70e0231dd24a7e"
LEGACY_IDENTITY_HASHES = frozenset(
    {
        LEGACY_SEED_HASH,
        # fabric_cli.default_soul.DEFAULT_SOUL_MD / agent.prompt_builder.DEFAULT_AGENT_IDENTITY
        "2765a846e1bb371d78d3b93b403dfb0f8d1ba1a9895edb5f608367abfe81194d",
        # fabric_cli.doctor --fix basic template
        "bcb2bde23d754b3cc91278c798d96326b2383f1f96eb7c7a0e10f6680d41e91c",
    }
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _branded_soul_text() -> str:
    from fabric_cli.fabric_brand import resolve_default_soul

    return resolve_default_soul()


def migrate_soul_file(path: Path, *, branded_text: str | None = None) -> bool:
    """Rewrite *path* if it is a known upstream default. Return True if changed."""
    if not path.is_file():
        return False
    digest = _sha256_file(path)
    if digest not in LEGACY_IDENTITY_HASHES:
        return False
    text = branded_text if branded_text is not None else _branded_soul_text()
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return True


def iter_soul_paths(home: Path) -> Iterable[Path]:
    yield home / "SOUL.md"
    profiles = home / "profiles"
    if profiles.is_dir():
        for profile_dir in sorted(profiles.iterdir()):
            if profile_dir.is_dir():
                yield profile_dir / "SOUL.md"


def migrate_hermes_home_souls(home: Path | str) -> int:
    """Migrate all allow-listed souls under *home*. Return count changed."""
    home_path = Path(home).expanduser()
    branded = _branded_soul_text()
    changed = 0
    for soul in iter_soul_paths(home_path):
        if migrate_soul_file(soul, branded_text=branded):
            changed += 1
            print(f"[fabric-soul] migrated upstream-default {soul}")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate byte-identical default SOUL.md files to Fabric identity."
    )
    parser.add_argument(
        "--home",
        default=(
            os.environ.get("FABRIC_HOME")
            or os.environ.get(_LEGACY_HOME_ENV)
            or str(Path.home() / ".fabric")
        ),
        help="FABRIC_HOME path (default: $FABRIC_HOME or ~/.fabric)",
    )
    args = parser.parse_args(argv)
    home = Path(args.home).expanduser()
    if not home.exists():
        print(f"[fabric-soul] home does not exist: {home}", file=sys.stderr)
        return 1
    changed = migrate_hermes_home_souls(home)
    if changed:
        print(f"[fabric-soul] migrated {changed} soul file(s) under {home}")
    else:
        print(f"[fabric-soul] no default souls needed migration under {home}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
