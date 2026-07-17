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
        hero=True,  # punchier lean/jump/sway for cape masters
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
    """Master pipeline: mid-size, deflood, autocrop, fit, requantize, crisp edges."""
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
    tw = max(1, int(img.width * scale))
    th = max(1, int(img.height * scale))
    # Two-step resize: BOX to ~2x target (anti-alias soft source), then NEAREST
    # into the half-res cell so the final silhouette locks to hard pixels.
    img = img.resize((max(1, tw * 2), max(1, th * 2)), Image.BOX)
    img = img.resize((tw, th), Image.NEAREST)
    # Re-flatten the color field to a pixel-art palette (alpha preserved).
    alpha = img.getchannel("A")
    quant = img.convert("RGB").quantize(colors=28, method=Image.MEDIANCUT).convert("RGBA")
    quant.putalpha(alpha)
    # Kill semi-transparent fringe: alpha snaps to on/off.
    px = quant.load()
    for y in range(quant.height):
        for x in range(quant.width):
            r, g, b, a = px[x, y]
            px[x, y] = (r, g, b, 255 if a >= 128 else 0)
    # Snap pure-white residual studio pixels on the bbox edge (catches soft
    # glow masters the corner flood-fill left behind).
    for y in range(quant.height):
        for x in range(quant.width):
            r, g, b, a = px[x, y]
            if a and r > 245 and g > 245 and b > 245:
                if x == 0 or y == 0 or x == quant.width - 1 or y == quant.height - 1:
                    px[x, y] = (0, 0, 0, 0)
    return quant


def _ground_shadow(img: Image.Image, *, cx: float, width: float, alpha: float = 0.35) -> None:
    """Soft dithered oval under the feet so floating poses still read grounded."""
    from PIL import ImageDraw

    a = max(0, min(255, int(round(90 * alpha))))
    shadow = (13, 21, 44, a)
    d = ImageDraw.Draw(img)
    hw = max(6.0, width * 0.32)
    d.ellipse((cx - hw, GROUND - 2, cx + hw, GROUND + 2), fill=shadow)
    # Dither the rim so it feels 16-bit instead of a soft blob.
    px = img.load()
    for x in range(int(cx - hw), int(cx + hw) + 1):
        for y in (GROUND - 1, GROUND, GROUND + 1):
            if 0 <= x < G_W and 0 <= y < G_H and (x + y) % 2 == 0 and px[x, y][3] < 40:
                px[x, y] = (13, 21, 44, min(255, a + 40))


def _place(img_canvas: Image.Image, master: Image.Image, *, dx: float = 0, dy: float = 0,
           sx: float = 1.0, sy: float = 1.0, rot: float = 0.0, dark: float = 0.0,
           shadow: bool = True):
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
        solid = ImageEnhance.Brightness(m.convert("RGB")).enhance(1.0 - 0.22 * dark).convert("RGBA")
        solid.putalpha(m.getchannel("A"))
        m = solid
    x = int(round(CX + dx - m.width / 2))
    y = int(round(GROUND + dy - m.height))
    if shadow:
        # Shadow stays on the floor even when the body jumps (dy lifts the sprite).
        _ground_shadow(img_canvas, cx=CX + dx, width=m.width, alpha=0.28 if dy < -2 else 0.4)
    img_canvas.alpha_composite(m, (max(-m.width, x), max(-m.height, y)))
    return x, y, m.width, m.height


def _question_hook(img: Image.Image, x: float, y: float, *, wob: float = 0.0) -> None:
    """Chunky violet ? so waiting reads at 0.33 scale (not a 1px squiggle)."""
    hx, hy = x + wob, y
    strand(img, [(hx, hy + 8), (hx + 3, hy + 4), (hx + 1, hy), (hx - 2, hy - 2), (hx - 4, hy + 1)], V[1], thick=True)
    put(img, hx - 1, hy + 4, V[2])
    put(img, hx, hy + 11, V[1])
    put(img, hx, hy + 12, V[2])


def bitmap_avatar(*, name: str, slug: str, description: str, image,
                  bg_threshold: int = 40, max_w: int = 88, max_h: int = 94,
                  hero: bool = False):
    """Build a harness-compatible avatar module from one master image.

    Pass ``hero=True`` for cape/superhero masters: amplifies lean, jump arc,
    and idle sway so a rigid bitmap still reads as lively at pet scale.
    """
    master = _prepare_master(Path(image).resolve(), bg_threshold=bg_threshold,
                             max_w=max_w, max_h=max_h)
    # Hero masters get punchier puppet ranges (cape silhouette does free work).
    amp = 1.35 if hero else 1.0

    def draw(state: str, i: int, n: int):
        img = canvas()
        t = i / n
        ph = 2 * math.pi * t

        if state == "idle":
            # Readable breath + soft cape sway (rot) — 0.008 squash was invisible at 0.33.
            breath = math.sin(ph)
            sway = 1.8 * amp * math.sin(ph)
            x, y, w, h = _place(
                img,
                master,
                dy=min(0, -bob(t, 1.6 * amp)),
                sx=1.0 + 0.028 * amp * breath,
                sy=1.0 - 0.024 * amp * breath,
                rot=sway * 0.9 if hero else sway * 0.35,
            )

        elif state == "running-right":
            bounce = ease_out(abs(math.sin(2 * ph)))
            lean = -8 * amp if hero else -5
            x, y, w, h = _place(
                img,
                master,
                dx=3,
                dy=-6 * amp * bounce,
                sx=1.0 + 0.06 * (1 - bounce),
                sy=1.0 - 0.05 * (1 - bounce),
                rot=lean - 2 * bounce,
            )
            motion_ticks(img, x - 5, y + h // 2, 1, count=4)
            if hero:
                motion_ticks(img, x - 2, y + h // 3, 1, count=2)

        elif state == "waving":
            # Bigger rock + lift so a whole-body wave sells the greeting beat.
            rock = tuple(int(v * amp) for v in (0, -10, -14, -6))[min(i, 3)]
            lift = -2 if i in (1, 2) else 0
            x, y, w, h = _place(img, master, rot=rock, dy=lift)
            if i >= 1:
                sparkle(img, x + w - 1, y - 3, small=(i != 2))
            if i == 2:
                sparkle(img, x + w + 4, y + 6, small=True)
                sparkle(img, x + w // 2, y - 6, small=True)

        elif state == "jumping":
            # Symmetric arc: crouch → rise → apex sparkle → fall → land squash.
            arc = math.sin(math.pi * i / max(1, n - 1))
            if i == 0:
                x, y, w, h = _place(img, master, sx=1.14, sy=0.86, rot=-4 if hero else 0)
            elif i == n - 1:
                x, y, w, h = _place(img, master, sx=1.12, sy=0.88, rot=3 if hero else 0)
            else:
                stretch = 0.07 * amp * arc
                x, y, w, h = _place(
                    img,
                    master,
                    dy=-18 * amp * arc,
                    sx=1.0 - stretch,
                    sy=1.0 + stretch,
                    rot=(-6 if hero else -2) if i < n // 2 else (4 if hero else 1),
                )
            if i == 2 or (n >= 5 and i == n // 2):
                sparkle(img, x - 5, y + 2)
                sparkle(img, x + w + 3, y + 8, small=True)
                if hero:
                    sparkle(img, x + w // 2, y - 4, small=True)

        elif state == "failed":
            settle = ease_in_out(min(1.0, i / 3))
            sulk = 0.8 * math.sin(ph)
            x, y, w, h = _place(
                img,
                master,
                rot=(-12 if hero else -7) * settle,
                dy=max(0, sulk),
                sx=1.0 + 0.07 * settle,
                sy=1.0 - 0.08 * settle,
                dark=settle,
            )
            if i >= 2:
                tear(img, x + int(w * 0.68), y + int(h * 0.36) + max(0, i - 3))
            sweat_drop(img, x + w - 1, y + 4 + 5 * t)

        elif state == "waiting":
            sway = follow(t, 0.0, 2.0 * amp)
            x, y, w, h = _place(img, master, dx=sway, rot=sway * 0.6)
            # Question hook on the free side of the silhouette.
            _question_hook(img, x + w + 1, y + 6, wob=follow(t, 0.2, 1.2))
            attention_dot(img, CX + 2, y - 12 + bob(t, 1.8), t=t)

        elif state == "running":  # focused work in place — power pose bounce
            press = abs(math.sin(ph * 1.5))
            jitter = (2 if i % 2 == 0 else -2) if hero else (1 if i % 2 == 0 else -1)
            x, y, w, h = _place(
                img,
                master,
                dx=jitter,
                dy=-3.5 * amp * press,
                rot=(-4 if hero else -2) - 2 * press,
                sx=1.0 + 0.03 * press,
                sy=1.0 - 0.03 * press,
            )
            motion_ticks(img, x - 5, y + h // 2, 1, count=3)
            motion_ticks(img, x + w + 5, y + h // 2 + 3, -1, count=3)
            # Gold progress pips accumulate underfoot.
            for k in range(min(5, i // 2 + 1)):
                put(img, CX - 10 + k * 5, GROUND + 1, G[2])
                put(img, CX - 10 + k * 5, GROUND, G[3])
                put(img, CX - 10 + k * 5 + 1, GROUND, G[4])

        elif state == "review":
            nod = i == n - 1
            scan = ease_in_out(min(1.0, i / max(1, n - 2)))
            x, y, w, h = _place(
                img,
                master,
                dx=int(3 * math.sin(ph)),
                rot=(6 if nod else -2 + 4 * scan),
                dy=-1 if nod else 0,
            )
            line_y = y + int(h * 0.52)
            strand(img, [(x - 10, line_y + 2), (x - 6, line_y), (x - 1, line_y)], C[3], thick=True)
            gx = x - 10 + int(9 * scan)
            put(img, gx, line_y, G[2])
            put(img, gx, line_y - 1, G[3])
            put(img, gx + 1, line_y - 1, G[4])
            if nod:
                sparkle(img, x - 7, line_y - 7, small=True)
                sparkle(img, x + w // 2, y - 4, small=True)

        else:  # pragma: no cover
            _place(img, master)
        return img

    return SimpleNamespace(NAME=name, SLUG=slug, DESCRIPTION=description, draw=draw)
