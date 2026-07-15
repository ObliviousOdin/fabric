"""Entry point so the relay can be launched with ``python -m``.

Run from the plugin directory:

    cd plugins/fabric-achievements
    python -m relay --host 0.0.0.0 --port 9137 --state ./roster.json
"""
from __future__ import annotations

from .server import main

if __name__ == "__main__":
    raise SystemExit(main())
