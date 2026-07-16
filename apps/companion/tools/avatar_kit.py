"""Shared drawing kit for the Fabric pixel avatars — art direction v2.

Style contract (every avatar must follow it):

- Draw on a 96x104 half-resolution RGBA grid; frames are upscaled x2
  nearest-neighbor to the 192x208 Petdex cell, so 1 grid px = a chunky 2x2
  screen px and 1px outlines become the classic 2px 16-bit line.
- **Depth through hue-shifted ramps**, not flat tones: every material uses a
  4-5 step ramp from :data:`RAMPS` where shadows slide toward indigo and
  lights toward warm cream (the SNES trick). Shadow sits low-right, light
  high-left, with a 1-2px rim of the deepest step just inside the bottom
  outline, and dithered transitions on large surfaces.
- **Anime-chibi charm**: characters are round and bold with a LARGE face —
  use :func:`anime_eye` (tall sclera + violet iris + double glint), moods via
  the ``mood`` argument, :func:`blush` under the eyes on happy/idle beats,
  :func:`mouth` for expressions. Faces sit on a clear light plate so they
  read at 0.33 scale.
- **Animation with life**: ease, don't lerp — :func:`ease_out`,
  :func:`ease_in_out`, :func:`overshoot`; appendages lag the body with
  :func:`follow` (phase-lagged sine); fast rows add :func:`motion_ticks`;
  jump apexes add :func:`sparkle`; failed rows add :func:`sweat_drop`.
  Loops must cycle: frame n-1 flows into frame 0.
- The ground line is y=100 (leaves the canonical 4 full-res px of padding).
  Hovering avatars float with a visible bob instead.
- Deterministic: no RNG anywhere — frame index alone drives motion.

Draw order per frame: silhouette colors -> :func:`auto_outline` -> interior
details (ramps, bands, stitches) -> face + effects. Details after the outline
pass so they are not re-outlined.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

# ── geometry ─────────────────────────────────────────────────────────────
G_W, G_H = 96, 104  # half-res grid; x2 -> 192x208 Petdex cell
GROUND = 100  # feet rest here (4 full-res px of padding below)
CX = G_W // 2

# ── hue-shifted ramps in the Fabric family ───────────────────────────────
# Index 0 = deepest shadow (indigo-shifted) ... last = warm top-light.
RAMPS = {
    # Brand violet — primary body material (anchored on #4628CC/#7C66E1/#9481E6).
    "violet": [
        (44, 28, 104, 255),
        (70, 40, 204, 255),
        (124, 102, 225, 255),
        (163, 143, 238, 255),
        (208, 196, 250, 255),
    ],
    # Navy/steel — feet, hardware, shuttle hulls (anchored on #19294D).
    "navy": [
        (13, 21, 44, 255),
        (25, 41, 77, 255),
        (48, 70, 116, 255),
        (86, 112, 163, 255),
        (138, 160, 200, 255),
    ],
    # Cream/porcelain — flanges, sclera, highlights (anchored on #F0EDFB).
    "cream": [
        (170, 158, 214, 255),
        (203, 194, 236, 255),
        (226, 220, 246, 255),
        (240, 237, 251, 255),
        (253, 252, 255, 255),
    ],
    # Amber-gold accents — attention dot, stitches of honor (#E09818 family).
    "gold": [
        (122, 74, 16, 255),
        (176, 112, 22, 255),
        (224, 152, 24, 255),
        (245, 196, 92, 255),
        (252, 230, 168, 255),
    ],
    # Rose — blush, ribbons, warm accents (kept dusty to stay on-brand).
    "rose": [
        (128, 52, 88, 255),
        (176, 84, 124, 255),
        (216, 122, 158, 255),
        (240, 168, 194, 255),
        (250, 210, 224, 255),
    ],
    # Neutral gray-lavender (#667085 family) for quilt patches, props.
    "gray": [
        (58, 64, 82, 255),
        (84, 92, 112, 255),
        (112, 122, 143, 255),
        (146, 156, 176, 255),
        (188, 196, 212, 255),
    ],
}

INK = (28, 20, 52, 255)  # outline / pupils — deep violet ink
IRIS = RAMPS["violet"][1]  # anime iris tone

# Back-compat flat aliases (prefer RAMPS in new code).
PALETTE = {
    "ink": INK,
    "navy": RAMPS["navy"][1],
    "navy_l": RAMPS["navy"][2],
    "violet_d": RAMPS["violet"][1],
    "violet": RAMPS["violet"][2],
    "violet_l": RAMPS["violet"][3],
    "lilac": RAMPS["violet"][4],
    "cream": RAMPS["cream"][3],
    "gray": RAMPS["gray"][2],
    "gray_l": RAMPS["gray"][3],
    "gold": RAMPS["gold"][2],
    "rose": RAMPS["rose"][2],
}


def canvas() -> Image.Image:
    """A fresh transparent half-res frame."""
    return Image.new("RGBA", (G_W, G_H), (0, 0, 0, 0))


def up2(img: Image.Image) -> Image.Image:
    """Upscale a half-res frame to the 192x208 Petdex cell."""
    return img.resize((G_W * 2, G_H * 2), Image.NEAREST)


def auto_outline(img: Image.Image) -> Image.Image:
    """Add a 1px ink border around every silhouette edge (holes included)."""
    src = img.load()
    out = img.copy()
    dst = out.load()
    for y in range(G_H):
        for x in range(G_W):
            if src[x, y][3] != 0:
                continue
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < G_W and 0 <= ny < G_H and src[nx, ny][3] != 0:
                    dst[x, y] = INK
                    break
    return out


def put(img: Image.Image, x: float, y: float, color) -> None:
    """Set one grid pixel, silently clipping out-of-bounds."""
    xi, yi = int(round(x)), int(round(y))
    if 0 <= xi < G_W and 0 <= yi < G_H:
        img.load()[xi, yi] = color


# ── easing & secondary motion ────────────────────────────────────────────
def ease_out(t: float) -> float:
    """Cubic ease-out: fast start, soft landing."""
    return 1.0 - (1.0 - t) ** 3


def ease_in_out(t: float) -> float:
    """Smoothstep ease for pendulum-like moves."""
    return t * t * (3.0 - 2.0 * t)


def overshoot(t: float, amount: float = 0.15) -> float:
    """Ease-out that pops past 1.0 and settles (snappy anime arrival)."""
    s = 1.70158 * (1.0 + amount)
    t -= 1.0
    return t * t * ((s + 1.0) * t + s) + 1.0


def follow(t: float, lag: float = 0.12, amp: float = 1.0) -> float:
    """Phase-lagged sine for follow-through on tails/appendages."""
    return amp * math.sin(2 * math.pi * (t - lag))


def bob(t: float, amp: float = 1.5) -> int:
    """Rounded sine bob for phase t in [0,1)."""
    return int(round(amp * math.sin(2 * math.pi * t)))


# ── shading ──────────────────────────────────────────────────────────────
def dither_shade(img: Image.Image, box, color, *, phase: int = 0) -> None:
    """Checkerboard-dither *color* over opaque pixels inside box."""
    x0, y0, x1, y1 = (int(v) for v in box)
    px = img.load()
    for y in range(y0, y1):
        for x in range(x0, x1):
            if (x + y + phase) % 2 == 0 and 0 <= x < G_W and 0 <= y < G_H and px[x, y][3] != 0:
                px[x, y] = color


def shade_ellipse(img: Image.Image, box, ramp: str) -> None:
    """A body ellipse with full ramp depth: base fill, warm light cap
    high-left, indigo shadow crescent low-right, rim shadow, dithered seams.
    Call BEFORE :func:`auto_outline` (it only lays color).
    """
    r = RAMPS[ramp]
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    d.ellipse(box, fill=r[2])
    # Light cap: inset ellipse shifted up-left, then a small hot crescent.
    d.ellipse((x0 + w * 0.10, y0 + h * 0.06, x1 - w * 0.30, y1 - h * 0.45), fill=r[3])
    d.ellipse((x0 + w * 0.18, y0 + h * 0.10, x1 - w * 0.48, y1 - h * 0.62), fill=r[4])
    # Shadow crescent: big inset ellipse of base color over a shadow fill.
    d.ellipse((x0 + w * 0.16, y0 + h * 0.30, x1, y1), fill=r[1])
    d.ellipse((x0 + w * 0.12, y0 + h * 0.22, x1 - w * 0.10, y1 - h * 0.12), fill=r[2])
    # Re-light the cap (the shadow pass clipped it).
    d.ellipse((x0 + w * 0.14, y0 + h * 0.08, x1 - w * 0.34, y1 - h * 0.52), fill=r[3])
    d.ellipse((x0 + w * 0.20, y0 + h * 0.12, x1 - w * 0.50, y1 - h * 0.66), fill=r[4])
    # Dither the light/base and base/shadow seams for the 16-bit blend.
    dither_shade(img, (x0 + w * 0.12, y0 + h * 0.40, x1 - w * 0.20, y0 + h * 0.55), r[2])
    dither_shade(img, (x0 + w * 0.30, y1 - h * 0.30, x1 - w * 0.06, y1 - h * 0.12), r[1], phase=1)


# ── anime face system ────────────────────────────────────────────────────
def anime_eye(img: Image.Image, x: int, y: int, mood: str = "open", look=(0, 0)) -> None:
    """A tall expressive chibi eye anchored at top-left (x, y), ~3x5 px.

    Moods: ``open`` (sclera + iris + double glint), ``happy`` (^ closed-up
    arc), ``closed`` (soft lid line), ``sad`` (iris low + heavy lid),
    ``focused`` (half-lid). ``look`` nudges the iris (dx, dy) in [-1, 1].
    """
    cream, hot = RAMPS["cream"][3], RAMPS["cream"][4]
    dx, dy = look
    if mood == "happy":
        put(img, x, y + 2, INK)
        put(img, x + 1, y + 1, INK)
        put(img, x + 2, y + 2, INK)
        return
    if mood == "closed":
        for ox in range(3):
            put(img, x + ox, y + 3, INK)
        return
    lid = 0
    if mood == "focused":
        lid = 1
    if mood == "sad":
        lid = 1
        dy = max(dy, 0) + 1
    # Sclera column.
    for oy in range(lid, 5):
        for ox in range(3):
            put(img, x + ox, y + oy, cream)
    # Iris + pupil, nudged by look.
    ix, iy = x + dx, y + 1 + dy
    for oy in range(3):
        for ox in range(2):
            put(img, ix + ox + (0 if dx <= 0 else 1), iy + oy, IRIS)
    put(img, ix + (0 if dx <= 0 else 1), iy + 1, INK)
    put(img, ix + 1 + (0 if dx <= 0 else 1), iy + 1, INK)
    # Double glint — the anime soul.
    put(img, x + (0 if dx <= 0 else 1), y + 1 + max(0, dy - 1), hot)
    put(img, x + 2, y + 3, cream)
    if mood == "sad":  # heavy lid line
        for ox in range(3):
            put(img, x + ox, y + lid, INK)


def anime_eye_lg(img: Image.Image, x: int, y: int, mood: str = "open", look=(0, 0)) -> None:
    """The set's hero eye: a 4x6 solid-ink eye anchored at top-left (x, y).

    Petdex-school: big dark rounded eye + one bright catchlight (plus a soft
    violet sheen low-right) — pops on any body tone, melts hearts at 0.33
    scale. Moods: ``open``, ``happy`` (^ arc), ``closed`` (lash line),
    ``sad`` (heavy lid, catchlight sunk low), ``focused`` (flat-lidded).
    ``look`` (dx, dy) in [-1, 1] shifts the catchlight — cheap, readable gaze.
    """
    hot = RAMPS["cream"][4]
    dx, dy = look
    if mood == "happy":
        put(img, x, y + 3, INK)
        put(img, x + 1, y + 2, INK)
        put(img, x + 2, y + 2, INK)
        put(img, x + 3, y + 3, INK)
        return
    if mood == "closed":
        for ox in range(4):
            put(img, x + ox, y + 4, INK)
        put(img, x, y + 5, INK)
        put(img, x + 3, y + 5, INK)
        return
    lid = 0
    if mood == "focused":
        lid = 2
    if mood == "sad":
        lid = 1
        dy = max(dy, 0) + 1
    # Solid ink mass with rounded corners.
    for oy in range(lid, 6):
        for ox in range(4):
            if (oy == lid or oy == 5) and ox in (0, 3):
                continue
            put(img, x + ox, y + oy, INK)
    if mood == "focused":
        for ox in range(4):
            put(img, x + ox, y + lid, INK)  # flat lid line
    if mood == "sad":
        for ox in range(1, 4):
            put(img, x + ox, y + lid, INK)  # heavy outer lid
    # Catchlight follows the gaze; violet sheen anchors the lower edge.
    cx0 = x + 1 + max(-1, min(1, dx))
    cy0 = y + 1 + lid + max(-1, min(1, dy))
    put(img, cx0, cy0, hot)
    put(img, cx0 + 1, cy0, hot)
    put(img, cx0, cy0 + 1, hot)
    put(img, x + 2, y + 4, RAMPS["violet"][3])


def tear(img: Image.Image, x: int, y: float) -> None:
    """A single glistening tear (the failed row's one allowed tear)."""
    yi = int(y)
    put(img, x, yi, RAMPS["navy"][3])
    put(img, x, yi + 1, RAMPS["cream"][2])
    put(img, x, yi + 2, RAMPS["cream"][4])


def blush(img: Image.Image, x: int, y: int) -> None:
    """Two dithered rose cheek pixels (place just below/outside each eye)."""
    rose = RAMPS["rose"][3]
    put(img, x, y, rose)
    put(img, x + 2, y, rose)
    put(img, x + 1, y + 1, RAMPS["rose"][2])


def mouth(img: Image.Image, x: int, y: int, mood: str = "smile") -> None:
    """Tiny mouth: ``smile`` (3px arc), ``open`` (2x2 gasp), ``line``, ``wobble``."""
    if mood == "smile":
        put(img, x - 1, y, INK)
        put(img, x, y + 1, INK)
        put(img, x + 1, y, INK)
    elif mood == "open":
        d = ImageDraw.Draw(img)
        d.ellipse((x - 1, y, x + 1, y + 2), fill=INK)
        put(img, x, y + 1, RAMPS["rose"][1])
    elif mood == "wobble":
        put(img, x - 1, y + 1, INK)
        put(img, x, y, INK)
        put(img, x + 1, y + 1, INK)
    else:  # line
        put(img, x - 1, y, INK)
        put(img, x, y, INK)
        put(img, x + 1, y, INK)


# ── effects ──────────────────────────────────────────────────────────────
def sparkle(img: Image.Image, x: int, y: int, *, small: bool = False) -> None:
    """A four-point star glint (jump apexes, celebrations)."""
    hot, light = RAMPS["cream"][4], RAMPS["violet"][3]
    put(img, x, y, hot)
    for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        put(img, x + ox, y + oy, hot if small else light)
    if not small:
        for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            put(img, x + ox, y + oy, light)


def sweat_drop(img: Image.Image, x: int, y: float) -> None:
    """The classic anime distress drop, sliding down beside the head."""
    d = ImageDraw.Draw(img)
    yi = int(y)
    d.polygon([(x, yi - 2), (x - 1, yi), (x + 1, yi)], fill=RAMPS["cream"][2])
    d.ellipse((x - 1, yi - 1, x + 1, yi + 2), fill=RAMPS["cream"][2])
    put(img, x, yi, RAMPS["cream"][4])
    put(img, x - 1, yi + 1, RAMPS["navy"][3])


def motion_ticks(img: Image.Image, x: int, y: int, dir_x: int, *, count: int = 3) -> None:
    """Short speed lines trailing opposite the travel direction."""
    light = RAMPS["violet"][3]
    for k in range(count):
        lx = x - dir_x * (3 + k * 4)
        ly = y - 4 + k * 4
        for o in range(2 + (k % 2)):
            put(img, lx - dir_x * o, ly, light)


def attention_dot(img: Image.Image, x: int, y: float, *, t: float = 0.0) -> None:
    """The gold 'your turn' beacon — now with a twinkle cycle."""
    d = ImageDraw.Draw(img)
    yi = int(y)
    g = RAMPS["gold"]
    d.ellipse((x - 1, yi - 1, x + 1, yi + 1), fill=g[2])
    put(img, x, yi - 1, g[3])
    put(img, x - 1, yi, g[3])
    put(img, x, yi, g[4])
    if (int(t * 6) % 3) == 0:  # periodic twinkle
        put(img, x + 2, yi - 2, g[4])
        put(img, x - 2, yi + 2, g[3])


def eye(img: Image.Image, x: int, y: int, *, blink: bool = False, sad: bool = False) -> None:
    """Back-compat simple eye (prefer :func:`anime_eye`)."""
    if blink:
        anime_eye(img, x - 1, y - 2, mood="closed")
    elif sad:
        anime_eye(img, x - 1, y - 2, mood="sad")
    else:
        anime_eye(img, x - 1, y - 2)


def strand(img: Image.Image, points, color, *, thick: bool = False) -> None:
    """Draw a 1px (or 2px) polyline thread through *points*."""
    d = ImageDraw.Draw(img)
    d.line([(int(round(x)), int(round(y))) for x, y in points], fill=color, width=2 if thick else 1)


def frame_counts() -> dict[str, int]:
    """The canonical per-row frame counts (mirrors generate/atlas.py ROW_SPECS)."""
    return {
        "idle": 6,
        "running-right": 8,
        "waving": 4,
        "jumping": 5,
        "failed": 8,
        "waiting": 6,
        "running": 6,
        "review": 6,
    }
