#!/usr/bin/env python3
"""Generate a CAD model from a text prompt via the Zoo Text-to-CAD API.

Cloud fallback for organic or underspecified shapes where a parametric
build123d generator is not converging. Requires a ZOO_API_TOKEN environment
variable (create one at zoo.dev). Standard library only — runs under any
Python 3.11+, no skill venv needed.

    python zoo_text_to_cad.py "a 40mm herringbone gear" --format step --out gear.step

The generated model is mesh-derived, not parameter-editable: still run
cadcheck.py and cadsnap.py on the result before delivering it.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://api.zoo.dev"
OUTPUT_FORMATS = ("step", "stl", "glb", "gltf", "obj", "ply", "fbx")
POLL_SECONDS = 5.0
TIMEOUT_SECONDS = 600.0


def build_submit_request(prompt: str, output_format: str) -> tuple[str, bytes]:
    """Return the submission URL and JSON body for *prompt*."""
    if output_format not in OUTPUT_FORMATS:
        raise ValueError(
            f"unsupported format {output_format!r} "
            f"(choose from {', '.join(OUTPUT_FORMATS)})"
        )
    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    url = f"{API_BASE}/ai/text-to-cad/{output_format}"
    body = json.dumps({"prompt": prompt}).encode("utf-8")
    return url, body


def poll_url(operation_id: str) -> str:
    return f"{API_BASE}/user/text-to-cad/{operation_id}"


def require_token() -> str:
    token = os.environ.get("ZOO_API_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "zoo_text_to_cad: ZOO_API_TOKEN is not set; create an API token "
            "at zoo.dev and export it before using the cloud fallback"
        )
    return token


def _call(url: str, token: str, body: bytes | None = None) -> dict:
    request = urllib.request.Request(
        url,
        data=body,
        method="POST" if body is not None else "GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(
            f"zoo_text_to_cad: API error {exc.code} for {url}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"zoo_text_to_cad: network error for {url}: {exc.reason}") from exc


def save_outputs(outputs: dict, out_path: Path, output_format: str) -> list[Path]:
    """Decode the base64 *outputs* map, writing the requested format to *out_path*."""
    written: list[Path] = []
    wanted_suffix = f".{output_format}"
    for name, encoded in sorted(outputs.items()):
        data = base64.b64decode(encoded)
        target = out_path if name.endswith(wanted_suffix) else out_path.with_name(
            out_path.stem + "-" + Path(name).name
        )
        target.write_bytes(data)
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="natural-language part description")
    parser.add_argument("--format", default="step", choices=OUTPUT_FORMATS,
                        help="primary output format (default step)")
    parser.add_argument("--out", type=Path, required=True,
                        help="output file path for the primary format")
    args = parser.parse_args(argv)

    token = require_token()
    url, body = build_submit_request(args.prompt, args.format)
    submitted = _call(url, token, body)
    operation_id = submitted.get("id")
    if not operation_id:
        raise SystemExit(f"zoo_text_to_cad: unexpected response: {submitted}")
    print(f"submitted: {operation_id}")

    deadline = time.monotonic() + TIMEOUT_SECONDS
    while True:
        state = _call(poll_url(operation_id), token)
        status = state.get("status")
        if status == "completed":
            break
        if status == "failed":
            raise SystemExit(
                f"zoo_text_to_cad: generation failed: {state.get('error', 'unknown')}"
            )
        if time.monotonic() > deadline:
            raise SystemExit(
                f"zoo_text_to_cad: timed out after {int(TIMEOUT_SECONDS)}s "
                f"(operation {operation_id} still {status})"
            )
        time.sleep(POLL_SECONDS)

    outputs = state.get("outputs") or {}
    if not outputs:
        raise SystemExit("zoo_text_to_cad: completed with no outputs")
    written = save_outputs(outputs, args.out, args.format)
    for path in written:
        print(f"written: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
