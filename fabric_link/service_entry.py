"""Minimal detached-process entrypoint for the Fabric Link host broker."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--fabric-home", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    fabric_home = Path(args.fabric_home).expanduser().resolve()
    workspace = Path(args.workspace).expanduser().resolve()
    if not fabric_home.is_dir() or not workspace.is_dir():
        return 2
    os.environ["FABRIC_HOME"] = str(fabric_home)
    os.chdir(workspace)

    from argparse import Namespace

    from .cli import _host

    return _host(Namespace(relay="", once=False))


if __name__ == "__main__":
    raise SystemExit(main())
