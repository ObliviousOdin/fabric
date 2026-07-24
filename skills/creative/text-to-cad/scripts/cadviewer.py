#!/usr/bin/env python3
"""Build a single-file, portable HTML viewer around a GLB model.

The GLB geometry is base64-embedded directly in the page, so the .html file
is self-contained and shareable — no server, no sidecar asset. Orbit/zoom is
provided by the ``<model-viewer>` web component, loaded from a CDN on first
open (the only network dependency, and only for the widget, never the model).

Usage (any Python 3.11+, no skill venv needed):

    python cadviewer.py part.glb -o part.html --title "Bracket v3"

To produce the GLB from a STEP part, export it first in the generator with
``export_gltf(part, "part.glb", binary=True)``.
"""

from __future__ import annotations

import argparse
import base64
import html
import sys
from pathlib import Path

MODEL_VIEWER_CDN = (
    "https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js"
)

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script type="module" src="{cdn}"></script>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin: 0; font-family: system-ui, sans-serif; background: #10141b; color: #e7ecf3; }}
  header {{ padding: 12px 16px; font-size: 14px; border-bottom: 1px solid #263042; }}
  model-viewer {{ width: 100vw; height: calc(100vh - 46px); background: #10141b; }}
  code {{ color: #9db4d4; }}
</style>
</head>
<body>
<header>{title} &mdash; <code>drag to orbit, scroll to zoom</code></header>
<model-viewer
  src="data:model/gltf-binary;base64,{data}"
  camera-controls
  auto-rotate
  shadow-intensity="1"
  exposure="1.1"
  alt="{title}"></model-viewer>
</body>
</html>
"""


def render_page(glb_bytes: bytes, title: str) -> str:
    """Return a self-contained HTML page embedding *glb_bytes*."""
    if not glb_bytes:
        raise ValueError("GLB payload is empty")
    encoded = base64.b64encode(glb_bytes).decode("ascii")
    return _PAGE.format(
        title=html.escape(title),
        cdn=MODEL_VIEWER_CDN,
        data=encoded,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="GLB model to embed")
    parser.add_argument("-o", "--out", type=Path, required=True,
                        help="output HTML path")
    parser.add_argument("--title", default=None, help="page title")
    args = parser.parse_args(argv)

    if not args.target.is_file():
        raise SystemExit(f"cadviewer: no such file: {args.target}")
    if args.target.suffix.lower() not in {".glb", ".gltf"}:
        raise SystemExit("cadviewer: expects a .glb (binary glTF) file")

    title = args.title or args.target.stem
    page = render_page(args.target.read_bytes(), title)
    args.out.write_text(page, encoding="utf-8")
    kib = len(page.encode("utf-8")) / 1024
    print(f"viewer written: {args.out} ({kib:.0f} KiB, model embedded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
