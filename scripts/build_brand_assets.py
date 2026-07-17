#!/usr/bin/env python3
"""Build Fabric's deterministic, dependency-light brand asset bundle.

Canonical sources live in apps/design-system/src/brand/fabric. Generated files
stay under apps/design-system/dist/brand; product-specific installation is a
separate, reviewable step so this command cannot overwrite an in-progress web
manifest or platform icon set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageColor, ImageDraw, __version__ as PILLOW_VERSION


ROOT = Path(__file__).resolve().parents[1]
DESIGN_SYSTEM_ROOT = ROOT / "apps" / "design-system"
SOURCE_DIR = DESIGN_SYSTEM_ROOT / "src" / "brand" / "fabric"
OUTPUT_DIR = DESIGN_SYSTEM_ROOT / "dist" / "brand"

CANONICAL_PRIMARY = "#4628CC"
APP_ICON_BACKGROUND = "#EFEEE9"
MARK_GRADIENT_STOPS = (
    (0.00, "#3B267D"),
    (0.24, "#3E2B83"),
    (0.39, "#5239B6"),
    (0.46, "#5A47D7"),
    (0.72, "#5A47D8"),
    (1.00, "#5F5CEE"),
)
MARK_GRADIENT_X_RANGE = (20.0, 108.0)
GENERATOR_VERSION = 3
PINNED_PILLOW_VERSION = "12.2.0"
SVG_SOURCE_NAMES = (
    "mark.svg",
    "mark-mono.svg",
    "wordmark.svg",
    "wordmark-on-dark.svg",
)
REFERENCE_SOURCE_NAME = "reference-mark.jpg"
REFERENCE_SOURCE_SIZE = (1024, 1024)
MARK_PNG_SIZES = (16, 32, 64, 128, 180, 192, 512, 1024)
APP_ICON_SIZES = (180, 192, 512, 1024)
ICO_SIZES = (16, 32, 48, 64, 128, 256)
MASTER_SIZE = 2048

_PATH_TOKEN_RE = re.compile(
    r"[A-Za-z]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _parse_view_box(root: ET.Element) -> tuple[float, float, float, float]:
    raw = root.attrib.get("viewBox", "")
    values = tuple(float(value) for value in raw.replace(",", " ").split())
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        raise ValueError("mark.svg must declare a positive four-value viewBox")
    return values  # type: ignore[return-value]


def _canonical_geometry(
    source_dir: Path,
) -> tuple[
    tuple[float, float, float, float],
    list[list[tuple[float, float]]],
]:
    mark_path = source_dir / "mark.svg"
    mono_path = source_dir / "mark-mono.svg"
    wordmark_path = source_dir / "wordmark.svg"
    dark_wordmark_path = source_dir / "wordmark-on-dark.svg"

    for source in (mark_path, mono_path, wordmark_path, dark_wordmark_path):
        if not source.is_file():
            raise FileNotFoundError(f"missing canonical brand source: {source}")

    mark_root = ET.parse(mark_path).getroot()
    mono_root = ET.parse(mono_path).getroot()
    view_box = _parse_view_box(mark_root)

    gradient = next(
        (
            element
            for element in mark_root.iter()
            if element.attrib.get("id") == "fabric-mark-gradient"
        ),
        None,
    )
    if gradient is None or gradient.attrib.get("gradientUnits") != "userSpaceOnUse":
        raise ValueError("mark.svg must define the canonical user-space gradient")
    try:
        gradient_x_range = tuple(
            float(gradient.attrib[name]) for name in ("x1", "x2")
        )
    except (KeyError, ValueError) as exc:
        raise ValueError("mark.svg must define numeric gradient x bounds") from exc
    if gradient_x_range != MARK_GRADIENT_X_RANGE:
        raise ValueError("mark.svg gradient x bounds do not match the raster contract")

    mark_elements = [
        element
        for element in mark_root.iter()
        if _local_name(element) == "path"
        and element.attrib.get("data-fabric-mark") == "true"
    ]
    mono_elements = [
        element
        for element in mono_root.iter()
        if _local_name(element) == "path"
        and element.attrib.get("data-fabric-mark") == "true"
    ]
    if not mark_elements or len(mark_elements) != len(mono_elements):
        raise ValueError("mark sources must contain matching canonical mark paths")

    color_fill = "url(#fabric-mark-gradient)"
    for mark_element, mono_element in zip(mark_elements, mono_elements, strict=True):
        if mark_element.attrib.get("fill") not in {None, color_fill}:
            raise ValueError("mark.svg must use the canonical Fabric gradient")
        if mono_element.attrib.get("fill") not in {None, "currentColor"}:
            raise ValueError("mark-mono.svg must use currentColor")
        if mark_element.attrib.get("d") != mono_element.attrib.get("d"):
            raise ValueError("color and monochrome compact marks must share geometry")

    color_group = next(
        (element for element in mark_root.iter() if element.attrib.get("id") == "fabric-mark"),
        None,
    )
    mono_group = next(
        (
            element
            for element in mono_root.iter()
            if element.attrib.get("id") == "fabric-mark-mono"
        ),
        None,
    )
    if color_group is None or color_group.attrib.get("fill") != color_fill:
        raise ValueError("mark.svg must apply the canonical Fabric gradient")
    if mono_group is None or mono_group.attrib.get("fill") != "currentColor":
        raise ValueError("mark-mono.svg must apply currentColor")

    for wordmark in (wordmark_path, dark_wordmark_path):
        root = ET.parse(wordmark).getroot()
        if any(_local_name(element) == "text" for element in root.iter()):
            raise ValueError(f"{wordmark.name} must use vector paths, not live text")
        brackets = [
            element
            for element in root.iter()
            if element.attrib.get("data-fabric-bracket") == "true"
        ]
        if len(brackets) != 1:
            raise ValueError(
                f"{wordmark.name} must preserve exactly one bracket underline"
            )

    point_groups = [
        _svg_path_points(mark_element.attrib["d"])
        for mark_element in mark_elements
    ]
    return view_box, point_groups


def _svg_path_points(path_data: str) -> list[tuple[float, float]]:
    """Sample the absolute M/L/H/V/C/Z subset used by the compact mark."""

    tokens = _PATH_TOKEN_RE.findall(path_data)
    index = 0
    command = ""
    cursor = (0.0, 0.0)
    start = (0.0, 0.0)
    points: list[tuple[float, float]] = []

    def number() -> float:
        nonlocal index
        if index >= len(tokens) or tokens[index].isalpha():
            raise ValueError("invalid compact mark path data")
        value = float(tokens[index])
        index += 1
        return value

    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
        if command == "M":
            cursor = (number(), number())
            start = cursor
            points.append(cursor)
            command = "L"
        elif command == "L":
            cursor = (number(), number())
            points.append(cursor)
        elif command == "H":
            cursor = (number(), cursor[1])
            points.append(cursor)
        elif command == "V":
            cursor = (cursor[0], number())
            points.append(cursor)
        elif command == "C":
            origin = cursor
            control_1 = (number(), number())
            control_2 = (number(), number())
            destination = (number(), number())
            for step in range(1, 25):
                t = step / 24
                inverse = 1 - t
                x = (
                    inverse**3 * origin[0]
                    + 3 * inverse**2 * t * control_1[0]
                    + 3 * inverse * t**2 * control_2[0]
                    + t**3 * destination[0]
                )
                y = (
                    inverse**3 * origin[1]
                    + 3 * inverse**2 * t * control_1[1]
                    + 3 * inverse * t**2 * control_2[1]
                    + t**3 * destination[1]
                )
                points.append((x, y))
            cursor = destination
        elif command in {"Z", "z"}:
            points.append(start)
            command = ""
        elif command:
            raise ValueError(
                "compact mark path uses unsupported SVG command " + command
            )
        else:
            raise ValueError("invalid compact mark path data")

    if len(points) < 4 or points[0] != points[-1]:
        raise ValueError("compact mark path must be a closed shape")
    return points


def _render_master(
    view_box: tuple[float, float, float, float],
    point_groups: Iterable[Iterable[tuple[float, float]]],
    *,
    foreground: str | None,
    background: str | None,
    geometry_scale: float = 1,
) -> Image.Image:
    x, y, width, height = view_box
    if not math.isclose(width, height):
        raise ValueError("compact mark viewBox must be square")
    canvas_color = (0, 0, 0, 0)
    if background is not None:
        canvas_color = (*ImageColor.getrgb(background), 255)
    image = Image.new("RGBA", (MASTER_SIZE, MASTER_SIZE), canvas_color)
    scale = MASTER_SIZE / width
    center_x = x + width / 2
    center_y = y + height / 2
    mask = Image.new("L", (MASTER_SIZE, MASTER_SIZE), 0)
    mask_draw = ImageDraw.Draw(mask)
    for points in point_groups:
        translated = [
            (
                (center_x + (point_x - center_x) * geometry_scale - x) * scale,
                (center_y + (point_y - center_y) * geometry_scale - y) * scale,
            )
            for point_x, point_y in points
        ]
        mask_draw.polygon(translated, fill=255)

    if foreground is None:
        gradient_row = Image.new("RGBA", (MASTER_SIZE, 1))
        pixels = gradient_row.load()
        if pixels is None:
            raise RuntimeError("unable to allocate gradient pixel buffer")
        stops = [
            (offset, ImageColor.getrgb(color))
            for offset, color in MARK_GRADIENT_STOPS
        ]
        gradient_start, gradient_end = MARK_GRADIENT_X_RANGE
        for pixel_x in range(MASTER_SIZE):
            user_x = x + pixel_x / (MASTER_SIZE - 1) * width
            position = max(
                0.0,
                min(1.0, (user_x - gradient_start) / (gradient_end - gradient_start)),
            )
            for index, (right_offset, right_color) in enumerate(stops[1:], start=1):
                if position <= right_offset:
                    left_offset, left_color = stops[index - 1]
                    span = right_offset - left_offset
                    amount = 0 if span == 0 else (position - left_offset) / span
                    color = tuple(
                        round(left + (right - left) * amount)
                        for left, right in zip(left_color, right_color, strict=True)
                    )
                    pixels[pixel_x, 0] = (*color, 255)
                    break
            else:
                pixels[pixel_x, 0] = (*stops[-1][1], 255)
        foreground_image = gradient_row.resize(
            (MASTER_SIZE, MASTER_SIZE),
            Image.Resampling.NEAREST,
        )
    else:
        foreground_image = Image.new(
            "RGBA",
            (MASTER_SIZE, MASTER_SIZE),
            (*ImageColor.getrgb(foreground), 255),
        )
    foreground_image.putalpha(mask)
    image.alpha_composite(foreground_image)
    return image


def _resize(master: Image.Image, size: int) -> Image.Image:
    return master.resize((size, size), Image.Resampling.LANCZOS)


def _save_png(image: Image.Image, target: Path) -> None:
    image.save(target, format="PNG", optimize=True, compress_level=9)


def _asset_record(
    target: Path,
    *,
    kind: str,
    media_type: str,
    width: int,
    height: int,
) -> dict[str, str | int]:
    return {
        "kind": kind,
        "mediaType": media_type,
        "width": width,
        "height": height,
        "sha256": _sha256(target),
    }


def _expected_asset_names() -> set[str]:
    return {
        *(f"fabric-{name}" for name in SVG_SOURCE_NAMES),
        *(f"fabric-mark-{size}.png" for size in MARK_PNG_SIZES),
        *(f"fabric-app-icon-{size}.png" for size in APP_ICON_SIZES),
        "fabric-maskable-512.png",
        "fabric-favicon.ico",
        "fabric-app-icon.icns",
    }


def generate_assets(
    output_dir: Path = OUTPUT_DIR,
    source_dir: Path = SOURCE_DIR,
) -> dict[str, object]:
    """Generate the isolated brand bundle and return its integrity manifest."""

    if PILLOW_VERSION != PINNED_PILLOW_VERSION:
        raise RuntimeError(
            "brand asset generation requires the project-pinned Pillow "
            f"{PINNED_PILLOW_VERSION}; found {PILLOW_VERSION}. "
            "Use .venv/bin/python."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    view_box, point_groups = _canonical_geometry(source_dir)
    transparent = _render_master(
        view_box,
        point_groups,
        foreground=None,
        background=None,
    )
    app_icon = _render_master(
        view_box,
        point_groups,
        foreground=None,
        background=APP_ICON_BACKGROUND,
    )
    maskable = _render_master(
        view_box,
        point_groups,
        foreground="#FFFFFF",
        background=CANONICAL_PRIMARY,
        # W3C maskable icons reserve a centered circular safe zone with an
        # 80% diameter. The symbol is asymmetric, so shrink its geometry
        # around the canvas center instead of relying on rectangular padding.
        geometry_scale=0.72,
    )

    assets: dict[str, dict[str, str | int]] = {}
    sources: dict[str, dict[str, str | int]] = {}

    for name in SVG_SOURCE_NAMES:
        source = source_dir / name
        target_name = "fabric-" + name
        target = output_dir / target_name
        shutil.copyfile(source, target)
        root = ET.parse(source).getroot()
        _, _, width, height = _parse_view_box(root)
        assets[target_name] = _asset_record(
            target,
            kind="vector-source",
            media_type="image/svg+xml",
            width=int(width),
            height=int(height),
        )
        sources[name] = {
            "path": source.relative_to(ROOT).as_posix(),
            "sha256": _sha256(source),
        }

    reference = source_dir / REFERENCE_SOURCE_NAME
    if not reference.is_file():
        raise FileNotFoundError(f"missing supplied logo reference: {reference}")
    with Image.open(reference) as reference_image:
        if reference_image.format != "JPEG" or reference_image.size != REFERENCE_SOURCE_SIZE:
            raise ValueError(
                "reference-mark.jpg must remain the supplied "
                f"{REFERENCE_SOURCE_SIZE[0]}x{REFERENCE_SOURCE_SIZE[1]} JPEG"
            )
    sources[REFERENCE_SOURCE_NAME] = {
        "path": reference.relative_to(ROOT).as_posix(),
        "sha256": _sha256(reference),
        "width": REFERENCE_SOURCE_SIZE[0],
        "height": REFERENCE_SOURCE_SIZE[1],
        "role": "audit-reference-only; generated assets use vector geometry",
    }

    for size in MARK_PNG_SIZES:
        name = f"fabric-mark-{size}.png"
        target = output_dir / name
        _save_png(_resize(transparent, size), target)
        assets[name] = _asset_record(
            target,
            kind="transparent-mark",
            media_type="image/png",
            width=size,
            height=size,
        )

    for size in APP_ICON_SIZES:
        name = f"fabric-app-icon-{size}.png"
        target = output_dir / name
        _save_png(_resize(app_icon, size), target)
        assets[name] = _asset_record(
            target,
            kind="app-icon",
            media_type="image/png",
            width=size,
            height=size,
        )

    maskable_name = "fabric-maskable-512.png"
    maskable_target = output_dir / maskable_name
    _save_png(_resize(maskable, 512), maskable_target)
    assets[maskable_name] = _asset_record(
        maskable_target,
        kind="maskable-app-icon",
        media_type="image/png",
        width=512,
        height=512,
    )

    favicon_name = "fabric-favicon.ico"
    favicon_target = output_dir / favicon_name
    _resize(app_icon, max(ICO_SIZES)).save(
        favicon_target,
        format="ICO",
        sizes=[(size, size) for size in ICO_SIZES],
    )
    assets[favicon_name] = _asset_record(
        favicon_target,
        kind="multi-size-favicon",
        media_type="image/x-icon",
        width=max(ICO_SIZES),
        height=max(ICO_SIZES),
    )

    icns_name = "fabric-app-icon.icns"
    icns_target = output_dir / icns_name
    _resize(app_icon, 1024).save(icns_target, format="ICNS")
    assets[icns_name] = _asset_record(
        icns_target,
        kind="multi-size-app-icon",
        media_type="image/icns",
        width=1024,
        height=1024,
    )

    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "generatorVersion": GENERATOR_VERSION,
        "generatorSha256": _sha256(Path(__file__)),
        "encoder": f"Pillow {PINNED_PILLOW_VERSION}",
        "brand": "Fabric",
        "canonicalPrimary": CANONICAL_PRIMARY,
        "compactMark": "stylized F with feather nib and eye dot",
        "wordmark": "Fabric symbol lockup with bracket underline",
        "sourceViewBox": [int(value) for value in view_box],
        "sources": dict(sorted(sources.items())),
        "assets": dict(sorted(assets.items())),
    }
    manifest_path = output_dir / "brand-assets.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def check_assets(
    output_dir: Path = OUTPUT_DIR,
    source_dir: Path = SOURCE_DIR,
) -> list[str]:
    """Return stale or missing generated paths without mutating output_dir."""

    issues: list[str] = []
    manifest_path = output_dir / "brand-assets.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ["brand-assets.json: missing"]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"brand-assets.json: invalid ({exc})"]

    if manifest.get("generatorVersion") != GENERATOR_VERSION:
        issues.append("brand-assets.json: generator version is stale")
    if manifest.get("generatorSha256") != _sha256(Path(__file__)):
        issues.append("brand-assets.json: generator hash is stale")
    if manifest.get("canonicalPrimary") != CANONICAL_PRIMARY:
        issues.append("brand-assets.json: canonical primary is stale")

    sources = manifest.get("sources")
    if not isinstance(sources, dict):
        issues.append("brand-assets.json: sources must be an object")
    else:
        for name in (*SVG_SOURCE_NAMES, REFERENCE_SOURCE_NAME):
            record = sources.get(name)
            source = source_dir / name
            if not isinstance(record, dict):
                issues.append(f"{name}: source record missing")
            elif not source.is_file():
                issues.append(f"{name}: source missing")
            elif record.get("sha256") != _sha256(source):
                issues.append(f"{name}: source hash is stale")

    assets = manifest.get("assets")
    if not isinstance(assets, dict):
        issues.append("brand-assets.json: assets must be an object")
        return issues

    expected_names = _expected_asset_names()
    for name in sorted(expected_names - set(assets)):
        issues.append(f"{name}: asset record missing")

    for name, record in assets.items():
        target = output_dir / name
        if not isinstance(record, dict):
            issues.append(f"{name}: invalid asset record")
        elif not target.is_file():
            issues.append(f"{name}: missing")
        elif record.get("sha256") != _sha256(target):
            issues.append(f"{name}: stale")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify committed assets without rewriting them",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="override the generated bundle destination",
    )
    args = parser.parse_args(argv)

    if args.check:
        issues = check_assets(args.output_dir)
        if issues:
            print("Fabric brand assets are not current:", file=sys.stderr)
            for issue in issues:
                print("  - " + issue, file=sys.stderr)
            return 1
        print("fabric-brand-assets: OK")
        return 0

    manifest = generate_assets(args.output_dir)
    print(
        "generated "
        + str(len(manifest["assets"]))
        + " brand assets in "
        + str(args.output_dir)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
