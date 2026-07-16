"""Bitmap-pet factory: turn a single character image into a full Petdex pet.

Takes one master image (e.g. commissioned pixel art), removes its studio
background with a corner flood-fill, downscales it into the half-res avatar
cell, and animates it puppet-style — breathing, leans, squash-stretch jump
arcs, slumps — with the shared effect layer (sparkles, tear, sweat drop,
question hook, gold attention beacon, motion ticks) on top. The result is a
module-compatible object the `pixel_avatars.py` harness can render, preview,
validate, and install like any hand-drawn avatar.

Usage from a personal-studio module (see --custom-dir):

    from avatar_from_image import bitmap_avatar
    _pet = bitmap_avatar(
        name="Caped Hero", slug="capedhero",
        description="...",
        image=__file__ + "/../refs/hero.png",
        bg_threshold=40,
    )
    NAME, SLUG, DESCRIPTION, draw = _pet.NAME, _pet.SLUG, _pet.DESCRIPTION, _pet.draw

Whole-sprite puppetry keeps every pixel of the source art, so fidelity is
bounded by the master image, not by procedural drawing skill.
"""

from __future__ import annotations

import math
from collections import deque
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageEnhance

from avatar_kit import (
    CX,
    G_H,
    G_W,
    GROUND,
    RAMPS,
    attention_dot,
    bob,
    canvas,
    ease_in_out,
    ease_out,
    follow,
    motion_ticks,
    put,
    sparkle,
    strand,
    sweat_drop,
    tear,
)

V = RAMPS["violet"]
C = RAMPS["cream"]
G = RAMPS["gold"]


def _remove_background(img: Image.Image, threshold: int) -> Image.Image:
    """Flood-fill transparency in from the four corners.

    Only pixels reachable from the border whose color is within *threshold*
    of their nearest corner's color are cleared, so enclosed light regions
    (white gloves, pale stone bodies behind an ink outline) survive.
    """
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]

    def near_bg(p) -> bool:
        return any(
            abs(p[0] - c[0]) + abs(p[1] - c[1]) + abs(p[2] - c[2]) <= threshold * 3
            for c in corners
        )

    seen = bytearray(w * h)
    queue: deque[tuple[int, int]] = deque()
    for x in range(w):
        for y in (0, h - 1):
            queue.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        if not (0 <= x < w and 0 <= y < h) or seen[y * w + x]:
            continue
        seen[y * w + x] = 1
        p = px[x, y]
        if p[3] == 0 or not near_bg(p):
            continue
        px[x, y] = (0, 0, 0, 0)
        queue.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
    return img


def _prepare_master(path: Path, *, bg_threshold: int, max_w: int, max_h: int) -> Image.Image:
    """Master pipeline: mid-size, deflood, autocrop, fit, requantize."""
    img = Image.open(path).convert("RGBA")
    # Work at ~3x target first: soft AA/gradients average out and the flood
    # fill runs fast.
    mid_h = max_h * 3
    if img.height > mid_h:
        img = img.resize((int(img.width * mid_h / img.height), mid_h), Image.BOX)
    img = _remove_background(img, bg_threshold)
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    scale = min(max_w / img.width, max_h / img.height)
    img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.BOX)
    # Re-flatten the color field to a pixel-art palette (alpha preserved).
    alpha = img.getchannel("A")
    quant = img.convert("RGB").quantize(colors=32, method=Image.MEDIANCUT).convert("RGBA")
    quant.putalpha(alpha)
    # Kill semi-transparent fringe: alpha snaps to on/off.
    px = quant.load()
    for y in range(quant.height):
        for x in range(quant.width):
            r, g, b, a = px[x, y]
            px[x, y] = (r, g, b, 255 if a >= 128 else 0)
    return quant


def _place(img_canvas: Image.Image, master: Image.Image, *, dx: float = 0, dy: float = 0,
           sx: float = 1.0, sy: float = 1.0, rot: float = 0.0, dark: float = 0.0):
    """Paste the master anchored bottom-center at the ground line.

    sx/sy squash-stretch about the ground anchor; rot degrees (NEAREST keeps
    the chunky pixels); dark in [0,1] dims the sprite (failed gloom).
    """
    m = master
    if sx != 1.0 or sy != 1.0:
        m = m.resize((max(1, int(m.width * sx)), max(1, int(m.height * sy))), Image.NEAREST)
    if rot:
        m = m.rotate(rot, resample=Image.NEAREST, expand=True)
    if dark > 0:
        solid = ImageEnhance.Brightness(m.convert("RGB")).enhance(1.0 - 0.18 * dark).convert("RGBA")
        solid.putalpha(m.getchannel("A"))
        m = solid
    x = int(round(CX + dx - m.width / 2))
    y = int(round(GROUND + dy - m.height))
    img_canvas.alpha_composite(m, (max(-m.width, x), max(-m.height, y)))
    return x, y, m.width, m.height


def bitmap_avatar(*, name: str, slug: str, description: str, image,
                  bg_threshold: int = 40, max_w: int = 86, max_h: int = 92):
    """Build a harness-compatible avatar module from one master image."""
    master = _prepare_master(Path(image).resolve(), bg_threshold=bg_threshold,
                             max_w=max_w, max_h=max_h)

    def draw(state: str, i: int, n: int):
        img = canvas()
        t = i / n
        ph = 2 * math.pi * t

        if state == "idle":
            breath = math.sin(ph)
            x, y, w, h = _place(img, master, dy=min(0, -bob(t, 1.0)),
                                sx=1.0 + 0.008 * breath, sy=1.0 - 0.008 * breath)

        elif state == "running-right":
            bounce = ease_out(abs(math.sin(2 * ph)))
            x, y, w, h = _place(img, master, dx=2, dy=-4 * bounce,
                                sx=1.0 + 0.04 * (1 - bounce), sy=1.0 - 0.04 * (1 - bounce),
                                rot=-5)
            motion_ticks(img, x - 4, y + h // 2, 1)

        elif state == "waving":
            rock = (0, -7, -10, -5)[i]
            x, y, w, h = _place(img, master, rot=rock, dy=-1 if i in (1, 2) else 0)
            if i == 2:
                sparkle(img, x + w + 3, y + 4, small=True)
            if i >= 1:
                sparkle(img, x + w - 2, y - 4, small=(i != 2))

        elif state == "jumping":
            arc = math.sin(math.pi * i / (n - 1))
            if i == 0 or i == n - 1:
                x, y, w, h = _place(img, master, sx=1.10, sy=0.90)
            else:
                x, y, w, h = _place(img, master, dy=-14 * arc, sx=1.0 - 0.05 * arc,
                                    sy=1.0 + 0.05 * arc)
            if i == 2:
                sparkle(img, x - 4, y + 2)
                sparkle(img, x + w + 3, y + 8, small=True)

        elif state == "failed":
            settle = ease_in_out(min(1.0, i / 3))
            sulk = 0.5 * math.sin(ph)
            x, y, w, h = _place(img, master, rot=-7 * settle, dy=max(0, sulk),
                                sx=1.0 + 0.05 * settle, sy=1.0 - 0.06 * settle,
                                dark=settle)
            if i >= 3:
                tear(img, x + int(w * 0.72), y + int(h * 0.38) + (i - 3))
            sweat_drop(img, x + w - 2, y + 6 + 4 * t)

        elif state == "waiting":
            sway = follow(t, 0.0, 1.2)
            x, y, w, h = _place(img, master, dx=sway)
            hx, hy = x + w - 2, y - 4
            strand(img, [(hx - 2, hy + 6), (hx + 2, hy + 2), (hx, hy - 2), (hx - 3, hy)], V[1])
            put(img, hx - 1, hy + 9, V[1])
            attention_dot(img, CX, y - 10 + bob(t, 1.5), t=t)

        elif state == "running":  # focused work in place
            jitter = 1 if i % 2 == 0 else -1
            press = abs(math.sin(ph * 1.5))
            x, y, w, h = _place(img, master, dx=jitter, dy=-2 * press, rot=-2)
            motion_ticks(img, x - 4, y + h // 2, 1)
            motion_ticks(img, x + w + 4, y + h // 2 + 4, -1)
            # Visible progress: gold pips accumulate underfoot.
            for k in range(i // 2 + 1):
                put(img, CX - 8 + k * 4, GROUND + 1, G[2])
                put(img, CX - 8 + k * 4, GROUND, G[3])

        elif state == "review":
            nod = i == n - 1
            scan = ease_in_out(min(1.0, i / (n - 2)))
            x, y, w, h = _place(img, master, dx=int(2 * math.sin(ph)),
                                rot=3 if nod else 0)
            line_y = y + int(h * 0.55)
            strand(img, [(x - 8, line_y + 2), (x - 5, line_y), (x - 1, line_y)], C[3])
            put(img, x - 8 + int(7 * scan), line_y, G[2])
            put(img, x - 8 + int(7 * scan), line_y - 1, G[3])
            if nod:
                sparkle(img, x - 6, line_y - 6, small=True)

        else:  # pragma: no cover
            _place(img, master)
        return img

    return SimpleNamespace(NAME=name, SLUG=slug, DESCRIPTION=description, draw=draw)
