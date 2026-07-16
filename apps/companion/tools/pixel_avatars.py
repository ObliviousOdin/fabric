"""Generate the five Fabric pixel avatars as installable Petdex pets.

Five deterministic 16-bit characters, each a personification of the fabric
ethos — Bobbin (thread spool), Patch (quilt golem), Skein (yarn cat),
Shuttle (loom shuttle), Knot (rope sprite) — rendered through the canonical
pet-generation pipeline (`agent.pet.generate.atlas`) into full Codex-contract
spritesheets (1536x1872, 9 rows), validated with `validate_atlas`, and
optionally installed into `<FABRIC_HOME>/pets/` via `register_local_pet`.

Usage (from the repo root):

    python3 apps/companion/tools/pixel_avatars.py --out /tmp/avatars
    python3 apps/companion/tools/pixel_avatars.py --install
    python3 apps/companion/tools/pixel_avatars.py --only skein --out /tmp/a

Previews written per avatar: `<slug>.sheet.png` (labelled contact sheet of
every animation row) and `<slug>.idle.png` (first idle frame at 2x).
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw  # noqa: E402

from agent.pet.generate.atlas import (  # noqa: E402
    CELL_HEIGHT,
    CELL_WIDTH,
    ROW_SPECS,
    atlas_to_webp_bytes,
    compose_atlas,
    mirror_frames,
    validate_atlas,
)
from avatar_kit import frame_counts, up2  # noqa: E402

AVATAR_MODULES = [
    "avatar_bobbin",
    "avatar_patch",
    "avatar_skein",
    "avatar_shuttle",
    "avatar_knot",
]


def build_frames(module) -> dict[str, list[Image.Image]]:
    """Render every drawn state at full cell size; mirror running-left."""
    frames: dict[str, list[Image.Image]] = {}
    for state, count in frame_counts().items():
        frames[state] = [up2(module.draw(state, i, count)) for i in range(count)]
    frames["running-left"] = mirror_frames(frames["running-right"])
    return frames


def contact_sheet(frames: dict[str, list[Image.Image]], name: str) -> Image.Image:
    """A labelled grid of every row at half scale on the brand navy."""
    cell_w, cell_h = CELL_WIDTH // 2, CELL_HEIGHT // 2
    label_w = 70
    rows = [(state, frames.get(state) or []) for state, _row, _count in ROW_SPECS]
    width = label_w + 8 * cell_w + 8
    height = len(rows) * (cell_h + 4) + 28
    sheet = Image.new("RGB", (width, height), (25, 41, 77))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 6), f"{name} - Fabric avatar", fill=(240, 237, 251))
    for r, (state, imgs) in enumerate(rows):
        y = 24 + r * (cell_h + 4)
        draw.text((8, y + cell_h // 2 - 5), state, fill=(148, 129, 230))
        for c, frame in enumerate(imgs):
            small = frame.resize((cell_w, cell_h), Image.NEAREST)
            sheet.paste(small, (label_w + c * cell_w, y), small)
    return sheet


def animated_gif(frames: dict[str, list[Image.Image]]) -> list[Image.Image]:
    """One looping GIF cycling every state at its canonical LOOP_MS pacing."""
    order = [
        ("idle", 2),
        ("waving", 2),
        ("running-right", 2),
        ("running-left", 1),
        ("running", 2),
        ("review", 2),
        ("waiting", 2),
        ("jumping", 2),
        ("failed", 2),
    ]
    out: list[Image.Image] = []
    for state, loops in order:
        imgs = frames.get(state) or []
        for _ in range(loops):
            for frame in imgs:
                bg = Image.new("RGB", frame.size, (25, 41, 77))
                bg.paste(frame, (0, 0), frame)
                out.append(bg)
    return out


def generate(only: str | None):
    for mod_name in AVATAR_MODULES:
        try:
            module = importlib.import_module(mod_name)
        except ModuleNotFoundError:
            print(f"  (skipping {mod_name}: module not written yet)")
            continue
        if only and module.SLUG != only:
            continue
        frames = build_frames(module)
        atlas = compose_atlas(frames)
        report = validate_atlas(atlas)
        yield module, frames, atlas, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write previews + .webp sheets here")
    parser.add_argument("--install", action="store_true", help="register into <FABRIC_HOME>/pets")
    parser.add_argument("--only", help="limit to one avatar slug")
    parser.add_argument("--gif", action="store_true", help="also write an animated <slug>.gif per avatar")
    args = parser.parse_args()

    failures = 0
    for module, frames, atlas, report in generate(args.only):
        status = "ok" if report["ok"] else "FAILED"
        print(f"{module.SLUG:8s} validate={status} errors={report['errors']} warnings={report['warnings']}")
        if not report["ok"]:
            failures += 1
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            contact_sheet(frames, module.NAME).save(args.out / f"{module.SLUG}.sheet.png")
            idle = frames["idle"][0]
            idle.resize((idle.width * 2, idle.height * 2), Image.NEAREST).save(
                args.out / f"{module.SLUG}.idle.png"
            )
            (args.out / f"{module.SLUG}.webp").write_bytes(atlas_to_webp_bytes(atlas))
            if args.gif:
                gif = animated_gif(frames)
                # Every row loops in ~1100 ms; frames in a row share it evenly.
                per_state = {s: max(2, round(110 / max(1, len(frames.get(s) or [])))) for s in frames}
                durations = []
                for state, loops in (
                    ("idle", 2), ("waving", 2), ("running-right", 2), ("running-left", 1),
                    ("running", 2), ("review", 2), ("waiting", 2), ("jumping", 2), ("failed", 2),
                ):
                    durations += [per_state.get(state, 18) * 10] * (len(frames.get(state) or []) * loops)
                gif[0].save(
                    args.out / f"{module.SLUG}.gif",
                    save_all=True,
                    append_images=gif[1:],
                    duration=durations,
                    loop=0,
                )
        if args.install and report["ok"]:
            from agent.pet.store import register_local_pet

            pet = register_local_pet(
                atlas,
                slug=module.SLUG,
                display_name=module.NAME,
                description=module.DESCRIPTION,
            )
            print(f"         installed -> {pet.directory}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
