"""Knot v2 "The Knot-Eared Bunny" — Skein's sibling (avatar style contract v2).

Knot is an ANIMAL FIRST: a round cream-ramp bunny — a soft pear of porcelain
cream (warm light cap high-left, indigo-lavender shadow low-right, dithered
seams) with a fluffy 3px tail puff, two stubby feet, hero eyes low on the
face, a tiny rose nose and permanent blush. Its fiber-craft trait is what its
own body does, not what it is: TWO LONG EARS (cream outer, violet-ramp inner)
rise from its head and are TIED TOGETHER in a single overhand knot near the
tips, little tips flaring above the bulge — an unmistakable silhouette. The
tied ear-pair is Knot's emotion appendage: it sways as one unit with follow()
lag in every frame, trails on hops, streams up at jump apexes, curls a loose
tip into question hooks... and in the failed row the knot comes undone.

Row gags: idle "metronome bow" (ears sway, tail counters, blink last);
running-right "double-hop" (two bunny hops, ears trailing); waving "flag-paw"
(one paw arcs while the ear-knot bobs); jumping "moon-hop" (ears stream
straight up at the apex + sparkles, grounded landing squash); failed "the
knot comes undone" (ears untie and flop down both sides of the face, tear
from f3); waiting "question-tip" (a loose tip curls into the hook under the
gold dot, foot taps); running "re-tying practice" (paws grow a rope loop,
gold stitch at the crossing, ears bounce with effort); review "antenna
audit" (ears lean forward, eyes scan a cream thread, approval nod last).
"""

from __future__ import annotations

import math

from PIL import ImageDraw

from avatar_kit import (
    CX,
    GROUND,
    INK,
    RAMPS,
    anime_eye_lg,
    attention_dot,
    auto_outline,
    blush,
    bob,
    canvas,
    ease_in_out,
    ease_out,
    follow,
    motion_ticks,
    mouth,
    put,
    sparkle,
    strand,
    sweat_drop,
    tear,
)

NAME = "Knot"
SLUG = "knot"
DESCRIPTION = "A cream bunny whose long ears are tied together in a tidy overhand knot."

V = RAMPS["violet"]
C = RAMPS["cream"]
G = RAMPS["gold"]
ROSE = RAMPS["rose"]

RX = 14.0  # body half-width before the pear widening (half-res px)
RY = 17.0  # body half-height
PEAR = 0.20  # extra width toward the bottom (the bunny tummy)
EAR_W = 2.7  # ear tube radius at the root (~5-6px wide ears)
TIP_W = 1.9  # tip tube radius above the knot
KNOT_R = 3.9  # the overhand-knot bulge
HOLE_R = 1.0  # the little loop hole punched through the knot

_CREAM = set(C)


# ── body ─────────────────────────────────────────────────────────────────
def _pear_w(u: float, rx: float) -> float:
    """Silhouette half-width at normalized height u in [-1, 1] (1 = bottom)."""
    return rx * (1.0 + PEAR * max(0.0, u)) * math.sqrt(max(0.0, 1.0 - u * u))


def _in_pear(x: float, y: float, cx: float, cy: float, rx: float, ry: float) -> bool:
    u = (y - cy) / ry
    if u < -1.0 or u > 1.0:
        return False
    return abs(x - cx) <= _pear_w(u, rx)


def _body(img, dy, squash, *, lean=0.0, tail_shift=(0.0, 0.0)):
    """Ramp-shaded cream pear anchored to the ground (bottom = GROUND + dy).

    The tail puff is laid first so the tummy overlaps its root; the pear is
    painted per-pixel with sphere shading (warm cap high-left, lavender
    shadow low-right, deep rim at the bottom) and dithered seams. Ears are
    drawn separately ON TOP so the tied pair always reads.
    """
    rx, ry = RX * squash, RY / squash
    cx = CX + lean
    bot = GROUND + dy
    cy = bot - ry
    top = cy - ry
    # Fluffy tail puff peeking out low on the left, behind the body.
    tu = 0.52
    tx = cx - _pear_w(tu, rx) - 2.0 + tail_shift[0]
    ty = cy + tu * ry + tail_shift[1]
    _disc(img, tx, ty, 2.9, C[3])
    px = img.load()
    for yi in range(int(math.floor(top)), int(math.ceil(bot)) + 1):
        u = (yi - cy) / ry
        if u < -1.0 or u > 1.0:
            continue
        w = _pear_w(u, rx)
        if w < 0.6:
            continue
        for xi in range(int(round(cx - w)), int(round(cx + w)) + 1):
            if not (0 <= xi < img.width and 0 <= yi < img.height):
                continue
            nx = (xi - cx) / w * math.sqrt(max(0.0, 1.0 - u * u))
            tsh = 0.50 * nx + 0.84 * u + (0.045 if (xi + yi) % 2 else -0.045)
            if tsh > 0.68:
                col = C[1]
            elif tsh > 0.32:
                col = C[2]
            elif tsh > -0.62:
                col = C[3]
            else:
                col = C[4]
            px[xi, yi] = col
    # Round crown cap: the pear apex is too pointy, so a soft dome bulges
    # up between the ear roots (sphere-shaded like the rest of the head).
    ccx, ccy, crx, cry = cx, top + 4.2, 7.4 * squash, 6.7
    for yi in range(int(ccy - cry) - 1, int(ccy) + 1):
        for xi in range(int(ccx - crx) - 1, int(ccx + crx) + 2):
            if not (0 <= xi < img.width and 0 <= yi < img.height):
                continue
            dx, dyy = (xi - ccx) / crx, (yi - ccy) / cry
            if dx * dx + dyy * dyy > 1.0:
                continue
            tsh = 0.55 * dx + 0.45 * dyy + (0.05 if (xi + yi) % 2 else -0.05)
            if tsh > 0.62:
                col = C[2]
            elif tsh < -0.42:
                col = C[4]
            else:
                col = C[3]
            px[xi, yi] = col
    return cx, cy, rx, ry, top, (tx, ty)


# ── small stamps ─────────────────────────────────────────────────────────
def _disc(img, x, y, r, col):
    ImageDraw.Draw(img).ellipse((x - r, y - r, x + r, y + r), fill=col)


def _cput(img, x, y, col):
    """put() that only recolors cream body pixels (keeps ink/holes crisp)."""
    xi, yi = int(round(x)), int(round(y))
    if 0 <= xi < img.width and 0 <= yi < img.height and img.load()[xi, yi] in _CREAM:
        img.load()[xi, yi] = col


def _vdisc(img, x, y, r, col):
    """Stamp a disc of *col* over cream pixels only (inner-ear violet)."""
    px = img.load()
    for yi in range(int(y - r), int(y + r) + 2):
        for xi in range(int(x - r), int(x + r) + 2):
            if not (0 <= xi < img.width and 0 <= yi < img.height):
                continue
            if (xi - x) ** 2 + (yi - y) ** 2 <= r * r and px[xi, yi] in _CREAM:
                px[xi, yi] = col


def _resample(pts, step=0.7):
    out = []
    for a, b in zip(pts, pts[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        k = max(1, int(d / step))
        for j in range(k):
            f = j / k
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    out.append(pts[-1])
    return out


def _tube(img, pts, r0, r1, col):
    smp = _resample(pts)
    m = max(1, len(smp) - 1)
    for k, (x, y) in enumerate(smp):
        _disc(img, x, y, r0 + (r1 - r0) * k / m, col)


# ── the tied ears (the signature) ────────────────────────────────────────
def _tied_ears(cx, top, s=1.0, *, kx=0.0, ky=0.0, tip_dx=0.0, tips="flare",
               spread=1.0, hook_wob=0.0):
    """Two ear tubes rising from the head, converging into an overhand knot.

    (kx, ky) offset the knot — the whole tied unit sways with it; *tip_dx*
    lags the little tips past the knot for follow-through. Tip modes:
    ``flare`` (resting v), ``up`` (streaming at the apex), ``sweep`` (both
    trailing a hop), ``fwd`` (antenna lean), ``hook`` (question-mark curl).
    """
    K = (cx + kx, top - 13.0 + ky)
    tubes = []
    for side in (-1, 1):
        pts = [
            (cx + side * 10.6 * s, top + 11.0),
            (cx + side * 10.0 * s + 0.30 * kx, top + 4.0 + 0.40 * ky),
            (cx + side * 8.8 * s + 0.65 * kx, top - 6.0 + 0.75 * ky),
            (K[0] + side * 1.7, K[1] + 2.0),
        ]
        tubes.append((pts, EAR_W, 1.9))
    tip_tubes = []
    if tips == "up":
        for side in (-1, 1):
            tip_tubes.append(([
                (K[0] + side * 1.0, K[1] - 2.6),
                (K[0] + side * 1.6 + tip_dx, K[1] - 5.6),
                (K[0] + side * 2.2 + 1.3 * tip_dx, K[1] - 8.4),
            ], TIP_W, 1.35))
    elif tips == "sweep":  # both tips trailing the same way (hops)
        for side, ln in ((-1, 1.0), (1, 0.72)):
            tip_tubes.append(([
                (K[0] + side * 1.0, K[1] - 2.5),
                (K[0] - 3.0 * ln + 0.4 * tip_dx + side * 1.4, K[1] - 3.8 - side * 1.3),
                (K[0] - 5.6 * ln + 0.7 * tip_dx + side * 1.4, K[1] - 4.6 - side * 1.8),
            ], TIP_W, 1.35))
    elif tips == "fwd":  # antennae leaning at the work under review
        for side in (-1, 1):
            tip_tubes.append(([
                (K[0] + side * 1.2, K[1] - 1.8),
                (K[0] + side * 3.6 + 0.5 * tip_dx, K[1] - 0.6),
                (K[0] + side * 5.8 + tip_dx, K[1] + 0.8),
            ], TIP_W, 1.35))
    elif tips == "hook":  # right tip curls into the question hook
        tip_tubes.append(([
            (K[0] - 1.0, K[1] - 2.5),
            (K[0] - 2.5 + tip_dx, K[1] - 4.8),
            (K[0] - 3.6 + 1.3 * tip_dx, K[1] - 6.8),
        ], TIP_W, 1.35))
        w = hook_wob
        tip_tubes.append(([
            (K[0] + 1.0, K[1] - 2.5),
            (K[0] + 3.2, K[1] - 5.4),
            (K[0] + 4.5 + w, K[1] - 9.2),
            (K[0] + 2.9 + w, K[1] - 12.2),
            (K[0] + 0.3 + w, K[1] - 12.6),
            (K[0] - 1.6 + w, K[1] - 10.6),
        ], 1.7, 1.25))
    else:  # flare — the resting v (left tip a touch longer: hand-tied)
        for side, ln in ((-1, 1.0), (1, 0.82)):
            tip_tubes.append(([
                (K[0] + side * 1.1, K[1] - 2.5),
                (K[0] + side * 2.8 * spread + tip_dx, K[1] - 2.5 - 2.3 * ln),
                (K[0] + side * 4.4 * spread + 1.3 * tip_dx, K[1] - 2.5 - 4.2 * ln),
            ], TIP_W, 1.35))
    return {"tubes": tubes, "knot": K, "tips": tip_tubes}


def _flop_ears(cx, top, s=1.0, u=1.0, *, sag=0.0, twitch=0.0):
    """The knot undone: two separate ears lerping from upright (u=0) to a
    full flop down both sides of the face (u=1)."""
    tubes = []
    for side in (-1, 1):
        bx, by = cx + side * 10.6 * s, top + 11.0
        upright = [
            (bx, by),
            (bx - side * 0.6, by - 7.0),
            (bx - side * 1.8, by - 14.0),
            (bx - side * 3.2, by - 19.0),
        ]
        flopped = [  # up over the shoulder, then draped down past the cheek
            (bx, by),
            (bx + side * 3.0, by - 4.5),
            (bx + side * 6.2, by + 1.5),
            (bx + side * 7.0, by + 8.5 + sag + (twitch if side > 0 else 0.0)),
        ]
        pts = [(a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)
               for a, b in zip(upright, flopped)]
        tubes.append((pts, EAR_W, 2.2))
    return {"tubes": tubes, "knot": None, "tips": []}


def _ears_fill(img, geo):
    """Silhouette pass: cream tubes + the knot bulge with its little loop
    hole punched transparent (pre-outline, so the hole gets an ink ring)."""
    for pts, r0, r1 in geo["tubes"]:
        _tube(img, pts, r0, r1, C[3])
    for pts, r0, r1 in geo["tips"]:
        _tube(img, pts, r0, r1, C[3])
    if geo["knot"]:
        kx, ky = geo["knot"]
        _disc(img, kx, ky, KNOT_R, C[3])
        _disc(img, kx, ky - 0.3, HOLE_R, (0, 0, 0, 0))


def _ear_detail(img, geo):
    """Post-outline pass: lit/shaded ear edges, the violet inner-ear leaf
    (widening toward the tip), the knot bulge shaded as a mini sphere."""
    for tube_kind, (pts, r0, r1) in ([("ear", tb) for tb in geo["tubes"]]
                                     + [("tip", tp) for tp in geo["tips"]]):
        smp = _resample(pts, 0.6)
        m = max(1, len(smp) - 1)
        for k in range(m):
            x, y = smp[k]
            tx, ty = smp[k + 1][0] - x, smp[k + 1][1] - y
            norm = math.hypot(tx, ty) or 1.0
            nx, ny = -ty / norm, tx / norm
            if nx + ny > 0:  # normal points up-left = light side
                nx, ny = -nx, -ny
            r = r0 + (r1 - r0) * k / m
            _cput(img, x + nx * (r - 0.6), y + ny * (r - 0.6), C[4])
            _cput(img, x - nx * (r - 0.6), y - ny * (r - 0.6), C[2])
        for k, (x, y) in enumerate(smp):
            f = k / m
            if tube_kind == "ear":  # inner leaf: peaks mid-ear, thins at ends
                rr = 1.15 * ease_in_out(min(1.0, f / 0.45)) - (0.55 * max(0.0, f - 0.55) / 0.45)
            else:
                rr = 0.7
            if rr >= 0.55:
                _vdisc(img, x, y, rr, V[2])
        _vdisc(img, smp[-1][0], smp[-1][1], 0.8, V[3])  # inner peek at the tip
    if geo["knot"]:
        _knot_detail(img, geo["knot"])


def _flop_redraw(img, geo, cx, hy):
    """Re-lay the undone ears OVER the face (guarded stamps keep the ink
    outline crisp) and carve their body-facing edge with an ink rim so the
    flop reads on the cream head. *hy* is the head-center height."""
    px = img.load()
    for pts, r0, r1 in geo["tubes"]:
        smp = _resample(pts, 0.55)
        m = max(1, len(smp) - 1)
        for k, (x, y) in enumerate(smp):
            _vdisc(img, x, y, (r0 + (r1 - r0) * k / m) - 0.25, C[3])
        for k in range(m):
            x, y = smp[k]
            tx, ty = smp[k + 1][0] - x, smp[k + 1][1] - y
            norm = math.hypot(tx, ty) or 1.0
            nx, ny = -ty / norm, tx / norm
            if nx + ny > 0:
                nx, ny = -nx, -ny
            r = (r0 + (r1 - r0) * k / m) - 0.25
            _cput(img, x + nx * (r - 0.5), y + ny * (r - 0.5), C[4])
            _cput(img, x - nx * (r - 0.5), y - ny * (r - 0.5), C[2])
        for k, (x, y) in enumerate(smp):
            r = (r0 + (r1 - r0) * k / m) - 0.25
            _vdisc(img, x, y, max(0.7, r - 1.8), V[2])
        # Ink rim on the side facing the head, from the bend to the tip.
        for k in range(int(0.30 * m), m + 1):
            x, y = smp[k]
            vx, vy = cx - x, hy - y
            norm = math.hypot(vx, vy) or 1.0
            vx, vy = vx / norm, vy / norm
            r = (r0 + (r1 - r0) * k / m) + 0.35
            xi, yi = int(round(x + vx * r)), int(round(y + vy * r))
            if 0 <= xi < img.width and 0 <= yi < img.height and px[xi, yi] in _CREAM:
                px[xi, yi] = INK
        # Round tip cap over the body.
        ex, ey_ = smp[-1]
        txx, tyy = ex - smp[-2][0], ey_ - smp[-2][1]
        norm = math.hypot(txx, tyy) or 1.0
        for ang in (-0.5, 0.0, 0.5):
            ca, sa = math.cos(ang), math.sin(ang)
            dxx = (txx * ca - tyy * sa) / norm
            dyy = (txx * sa + tyy * ca) / norm
            xi = int(round(ex + dxx * (r1 + 0.2)))
            yi = int(round(ey_ + dyy * (r1 + 0.2)))
            if 0 <= xi < img.width and 0 <= yi < img.height and px[xi, yi] in _CREAM:
                px[xi, yi] = INK


def _knot_detail(img, K):
    kx, ky = K
    px = img.load()
    for yi in range(int(ky - KNOT_R) - 1, int(ky + KNOT_R) + 2):
        for xi in range(int(kx - KNOT_R) - 1, int(kx + KNOT_R) + 2):
            if not (0 <= xi < img.width and 0 <= yi < img.height):
                continue
            dx, dy = (xi - kx) / KNOT_R, (yi - ky) / KNOT_R
            if dx * dx + dy * dy > 1.0 or px[xi, yi] not in _CREAM:
                continue
            tsh = 0.60 * dx + 0.78 * dy + (0.05 if (xi + yi) % 2 else -0.05)
            if tsh > 0.55:
                col = C[1]
            elif tsh > 0.20:
                col = C[2]
            elif tsh < -0.55:
                col = C[4]
            else:
                col = C[3]
            px[xi, yi] = col
    # Ink creases where the ears cinch into the bulge — the knot pops out.
    for deg in tuple(range(24, 72, 8)) + tuple(range(108, 156, 8)):
        a = math.radians(deg)
        xi = int(round(kx + (KNOT_R + 0.15) * math.cos(a)))
        yi = int(round(ky + (KNOT_R + 0.15) * math.sin(a)))
        if 0 <= xi < img.width and 0 <= yi < img.height and px[xi, yi] in _CREAM:
            px[xi, yi] = INK


# ── details (post-outline) ───────────────────────────────────────────────
def _tail_detail(img, tx, ty, cx, cy, rx, ry):
    """Light the tail puff (hot cap up-left, shadow low-right) and carve the
    body edge through it with ink so the puff reads as attached behind."""
    px = img.load()
    for yi in range(int(ty) - 4, int(ty) + 5):
        u = (yi - cy) / ry
        if not -1.0 < u < 1.0:
            continue
        xe = int(round(cx - _pear_w(u, rx)))
        if (xe - tx) ** 2 + (yi - ty) ** 2 <= (2.9 + 0.4) ** 2:
            if 0 <= xe < img.width and 0 <= yi < img.height and px[xe, yi] in _CREAM:
                px[xe, yi] = INK
    _cput(img, tx - 1.6, ty - 1.6, C[4])
    _cput(img, tx - 0.6, ty - 2.2, C[4])
    _cput(img, tx - 2.3, ty - 0.6, C[4])
    _cput(img, tx - 1.4, ty - 0.8, C[4])
    _cput(img, tx - 0.4, ty + 1.8, C[2])
    _cput(img, tx - 2.0, ty + 1.2, C[2])


def _foot(img, x, bot, *, lift=0.0):
    """A stubby ink-rimmed bunny foot resting on the ground."""
    d = ImageDraw.Draw(img)
    y = bot - lift
    d.ellipse((x - 3, y - 4, x + 3, y), fill=C[3], outline=INK)
    put(img, x - 1, y - 3, C[4])
    put(img, x + 1, y - 1, C[2])


def _paw(img, x, y):
    """A tiny cream mitten, ink-rimmed so it reads on the cream body."""
    d = ImageDraw.Draw(img)
    d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=C[3], outline=INK)
    put(img, x - 1, y - 1, C[4])
    put(img, x, y, ROSE[3])


def _tear_rim(img, x, y):
    """Kit tear on an ink backing so it reads on the cream body."""
    d = ImageDraw.Draw(img)
    d.ellipse((x - 1, int(y) - 1, x + 1, int(y) + 3), fill=INK)
    tear(img, x, y)


def _face(img, cx, cy, rx, ry, *, mood="open", look=(0, 0), mstyle="smile", cheeks=False):
    """Bunny face low on the head, on a soft lit plate (solid C[4] core with
    a dithered fringe, clipped to the pear): hero eyes, tiny rose nose right
    between them, tiny mouth, blush on the happy beats."""
    cxr = cx
    cx = int(round(cx))
    ey = int(round(cy - 0.36 * ry))
    px = img.load()
    for yi in range(ey - 5, ey + 12):
        for xi in range(cx - 15, cx + 16):
            if not (0 <= xi < img.width and 0 <= yi < img.height):
                continue
            nx, ny = (xi - cx) / 14.0, (yi - (ey + 3.0)) / 7.5
            rr = nx * nx + ny * ny
            if rr > 1.3 or not _in_pear(xi, yi, cxr, cy, rx, ry):
                continue
            if px[xi, yi] not in _CREAM:
                continue  # never repaint a flopped ear lying on the cheek
            if rr <= 1.0 or (xi + yi) % 2:  # solid core, dithered fringe
                px[xi, yi] = C[4]
    anime_eye_lg(img, cx - 10, ey, mood=mood, look=look)
    anime_eye_lg(img, cx + 7, ey, mood=mood, look=look)
    put(img, cx, ey + 4, ROSE[2])  # the tiny rose nose
    put(img, cx, ey + 5, ROSE[1])
    mouth(img, cx, ey + 7, mstyle)
    if cheeks:
        blush(img, cx - 14, ey + 6)
        blush(img, cx + 12, ey + 6)
    return ey


# ── choreography ─────────────────────────────────────────────────────────
def draw(state: str, i: int, n: int):
    img = canvas()
    t = i / n
    ph = 2 * math.pi * t

    if state == "idle":  # gag: the metronome bow — tied ears sway, tail counters
        squash = 1.0 + 0.03 * math.sin(ph)
        sway = 2.4 * math.sin(ph)
        lag = follow(t, 0.18, 2.2)  # tips lag the knot every frame
        cx, cy, rx, ry, top, tail = _body(
            img, 0, squash, tail_shift=(-0.4 * math.sin(ph), -0.6 * math.sin(ph))
        )
        geo = _tied_ears(cx, top, rx / RX, kx=sway, tip_dx=lag)
        _ears_fill(img, geo)
        img = auto_outline(img)
        _ear_detail(img, geo)
        _tail_detail(img, *tail, cx, cy, rx, ry)
        _foot(img, cx - 6.5, GROUND)
        _foot(img, cx + 6.5, GROUND)
        mood = "closed" if i == n - 1 else "open"
        _face(img, cx, cy, rx, ry, mood=mood, mstyle="smile", cheeks=True)

    elif state == "running-right":  # gag: the double-hop, ears trailing behind
        bounce = abs(math.sin(ph))  # two bunny hops per loop
        dy = -5.5 * ease_out(bounce)
        cx, cy, rx, ry, top, tail = _body(
            img, dy, 1.0 + 0.07 * (1 - bounce), lean=3, tail_shift=(0.5, -0.5)
        )
        whip = follow(2 * t, 0.2, 2.0)
        geo = _tied_ears(cx, top, rx / RX, kx=-6.0 - 1.2 * whip, ky=2.5,
                         tips="sweep", tip_dx=-2.0 - whip)
        _ears_fill(img, geo)
        img = auto_outline(img)
        _ear_detail(img, geo)
        _tail_detail(img, *tail, cx, cy, rx, ry)
        bot = GROUND + dy
        _foot(img, cx - 5, min(bot + 1.5, GROUND))  # back foot kicked
        _foot(img, cx + 8, bot)  # front foot reaching
        motion_ticks(img, int(cx - rx - 4), int(cy), 1)
        _face(img, cx, cy, rx, ry, mood="focused", look=(1, 0), mstyle="line")

    elif state == "waving":  # gag: the flag-paw — ear-knot bobs happily
        sweep = (0.0, 0.75, 1.0, 0.55)[i]
        cx, cy, rx, ry, top, tail = _body(img, 1 if i == 0 else 0, 1.0)
        geo = _tied_ears(cx, top, rx / RX, kx=1.5 * follow(t, 0.1, 1.5),
                         ky=-2.5 * ease_in_out(sweep), tip_dx=follow(t, 0.15, 1.5))
        _ears_fill(img, geo)
        img = auto_outline(img)
        _ear_detail(img, geo)
        _tail_detail(img, *tail, cx, cy, rx, ry)
        _foot(img, cx - 6.5, GROUND)
        _foot(img, cx + 6.5, GROUND)
        # The arm pivots at the shoulder edge and arcs through open sky.
        pvy = cy + 1
        pvx = cx + _pear_w((pvy - cy) / ry, rx) - 1
        ang = math.pi * (0.02 + 0.46 * ease_in_out(sweep))
        wx, wy = pvx + 13 * math.cos(ang), pvy - 13 * math.sin(ang)
        strand(img, [(pvx - 2, pvy), ((pvx + wx) / 2, (pvy + wy) / 2 + 1), (wx, wy)], C[2], thick=True)
        _paw(img, int(wx), int(wy))
        if i == 2:
            sparkle(img, int(wx) + 3, int(wy) - 3, small=True)
        _paw(img, cx - 5, int(cy + 0.42 * ry))  # other paw rests on the tummy
        _face(img, cx, cy, rx, ry, mood="happy", mstyle="open", cheeks=True)

    elif state == "jumping":  # gag: the moon-hop — ears stream straight up at the apex
        arc = math.sin(math.pi * i / (n - 1))
        if i == 0:  # anticipation crouch, ears pressed low
            squash, dy, ky, tips, spread = 1.18, 0.0, 4.0, "flare", 0.8
        elif i == 1:  # rise: stretched, knot dragged down by inertia
            squash, dy, ky, tips, spread = 0.92, -16 * arc, 6.0, "flare", 0.7
        elif i == 2:  # apex: hang-time, ears streaming straight up
            squash, dy, ky, tips, spread = 0.97, -16 * arc, -4.0, "up", 1.0
        elif i == 3:  # descend: ears still streaming while the body falls
            squash, dy, ky, tips, spread = 1.02, -16 * arc, -6.0, "up", 1.0
        else:  # grounded landing squash, ears overshooting down to settle
            squash, dy, ky, tips, spread = 1.16, 0.0, 5.0, "flare", 1.3
        tshift = ((0, 0.5), (0, 2.0), (0, 0.0), (0, -2.5), (0.5, 1.0))[i]
        cx, cy, rx, ry, top, tail = _body(img, dy, squash, tail_shift=tshift)
        wob = follow(t, 0.2, 1.2)
        geo = _tied_ears(cx, top, rx / RX, ky=ky, tips=tips, spread=spread, tip_dx=wob)
        _ears_fill(img, geo)
        img = auto_outline(img)
        _ear_detail(img, geo)
        _tail_detail(img, *tail, cx, cy, rx, ry)
        bot = GROUND + dy
        if i == 0:
            _foot(img, cx - 7, GROUND)
            _foot(img, cx + 7, GROUND)
        elif i == n - 1:  # landing: feet splayed wide
            _foot(img, cx - 8.5, GROUND)
            _foot(img, cx + 8.5, GROUND)
        else:  # airborne: feet dangling under the body
            _foot(img, cx - 5.5, bot + 1)
            _foot(img, cx + 5.5, bot + 1)
        if i == 2:  # apex glint only — the float beat
            K = geo["knot"]
            sparkle(img, int(K[0] - 9), int(K[1] - 6))
            sparkle(img, int(K[0] + 9), int(K[1] - 2), small=True)
        moods = ("focused", "open", "happy", "open", "happy")
        msts = ("line", "open", "open", "open", "smile")
        _face(img, cx, cy, rx, ry, mood=moods[i], look=(0, 1) if i == 3 else (0, 0),
              mstyle=msts[i], cheeks=i in (2, 4))

    elif state == "failed":  # gag: THE KNOT COMES UNDONE — ears flop down the face
        settle = ease_in_out(min(1.0, i / 3))
        squash = 1.0 + 0.14 * settle + 0.015 * math.sin(ph)
        cx, cy, rx, ry, top, tail = _body(img, 0, squash, tail_shift=(0, 1.5 * settle))
        if i == 0:  # the slip: tips pop apart, the knot slides loose
            geo = _tied_ears(cx, top, rx / RX, ky=-1.5, tips="flare", spread=1.9)
        else:  # untied: ears lerp into the full flop, then hold it
            u = ease_in_out((0.30, 0.65, 1.0)[i - 1] if i <= 3 else 1.0)
            sag = follow(t, 0.1, 0.8)  # lagged sub-pixel sulk breathing
            geo = _flop_ears(cx, top, rx / RX, u, sag=sag,
                             twitch=1.0 if i in (5, 7) else 0.0)
        _ears_fill(img, geo)
        img = auto_outline(img)
        _ear_detail(img, geo)
        _tail_detail(img, *tail, cx, cy, rx, ry)
        _foot(img, cx - 7.5, GROUND)
        _foot(img, cx + 7.5, GROUND)
        sweat_drop(img, int(cx + 0.5 * rx + 4), top - 2 + 6 * t)
        if i == 0:  # the gasp
            ey = _face(img, cx, cy, rx, ry, mood="open", look=(0, 1), mstyle="open")
        elif i == 1:
            ey = _face(img, cx, cy, rx, ry, mood="open", look=(0, 1), mstyle="wobble")
        else:
            ey = _face(img, cx, cy, rx, ry, mood="sad", look=(0, 1), mstyle="wobble")
        if i >= 1:  # the undone ears drape OVER the face, ink-rimmed
            _flop_redraw(img, geo, cx, top + 9)
        if i >= 3:  # a single tear slides from the right eye
            _tear_rim(img, int(cx) + 9, ey + 7 + (i - 3))

    elif state == "waiting":  # gag: the question-tip under the gold dot
        squash = 1.0 + 0.02 * math.sin(ph)
        cx, cy, rx, ry, top, tail = _body(img, 0, squash)
        wob = 1.0 if i % 2 == 0 else 0.0
        geo = _tied_ears(cx, top, rx / RX, kx=0.8 * follow(t, 0.2, 1.5),
                         tips="hook", hook_wob=wob, tip_dx=0.6 * follow(t, 0.3, 1.5))
        _ears_fill(img, geo)
        img = auto_outline(img)
        _ear_detail(img, geo)
        _tail_detail(img, *tail, cx, cy, rx, ry)
        _foot(img, cx - 6.5, GROUND)
        _foot(img, cx + 6.5, GROUND, lift=2 if i % 2 else 0)  # the foot tap
        K = geo["knot"]
        attention_dot(img, int(K[0] + 2), int(K[1]) - 17 + bob(t, 1.2), t=t)
        _face(img, cx, cy, rx, ry, mood="closed" if i == n - 1 else "open",
              look=(1, -1), mstyle="smile", cheeks=True)

    elif state == "running":  # gag: re-tying practice — the rope loop grows
        press = math.sin(2 * ph)
        squash = 1.0 + 0.03 * (1 - abs(press))
        cx, cy, rx, ry, top, tail = _body(img, 0, squash)
        geo = _tied_ears(cx, top, rx / RX, kx=1.2 * follow(2 * t, 0.2, 1.5),
                         ky=-2.2 * abs(press), tip_dx=follow(2 * t, 0.3, 2.0))
        _ears_fill(img, geo)
        img = auto_outline(img)
        _ear_detail(img, geo)
        _tail_detail(img, *tail, cx, cy, rx, ry)
        _foot(img, cx - 8, GROUND)
        _foot(img, cx + 8, GROUND)
        # The practice rope: a loop hanging from the paws, growing downward
        # frame by frame; a gold stitch marks the crossing between the paws.
        d = ImageDraw.Draw(img)
        lr = 2.2 + 2.4 * i / (n - 1)
        cyx = int(cy + 0.42 * ry) + 1  # the crossing, held at chest height
        lrx, lry = lr * 1.15, lr
        d.ellipse((cx - lrx, cyx, cx + lrx, cyx + 2 * lry), outline=V[1], width=2)
        d.arc((cx - lrx, cyx, cx + lrx, cyx + 2 * lry), 195, 345, fill=V[2])
        tap = 1 if press > 0 else 0
        strand(img, [(cx - 1, cyx + 1), (cx - 4, cyx - 2)], V[1], thick=True)
        strand(img, [(cx + 1, cyx + 1), (cx + 4, cyx - 2)], V[1], thick=True)
        put(img, cx - 5, cyx - 4, C[4])  # frayed rope tips
        put(img, cx + 5, cyx - 4, C[4])
        _paw(img, cx - 6, int(cyx - 2 + tap))
        _paw(img, cx + 6, int(cyx - 1 - tap))
        put(img, cx, cyx, G[3])
        put(img, cx, cyx - 1, G[4])
        _face(img, cx, cy, rx, ry, mood="focused", look=(0, 1), mstyle="line")

    elif state == "review":  # gag: the antenna audit — ears lean at the thread
        nod = i == n - 1
        cx, cy, rx, ry, top, tail = _body(img, 1 if nod else 0, 1.0)
        geo = _tied_ears(cx, top, rx / RX, ky=4.5 + (2.0 if nod else 0.0),
                         tips="fwd", tip_dx=0.8 * follow(t, 0.2, 1.2))
        _ears_fill(img, geo)
        img = auto_outline(img)
        _ear_detail(img, geo)
        _tail_detail(img, *tail, cx, cy, rx, ry)
        _foot(img, cx - 6.5, GROUND)
        _foot(img, cx + 6.5, GROUND)
        ty = int(cy + 0.40 * ry)
        strand(img, [(cx - 9, ty + 1), (cx + 9, ty + 1)], INK)  # thread shadow
        strand(img, [(cx - 9, ty), (cx + 9, ty)], C[4])  # the cream thread
        _paw(img, cx - 11, ty + 1)
        _paw(img, cx + 11, ty + 1)
        scan = ease_in_out(min(1.0, i / (n - 2)))
        gx = int(cx - 8 + 16 * scan)
        put(img, gx, ty, G[3])
        put(img, gx, ty - 1, G[4])
        if nod:
            _face(img, cx, cy, rx, ry, mood="happy", mstyle="smile", cheeks=True)
        else:
            look_x = max(-1, min(1, int(round(-1 + 2 * scan))))
            _face(img, cx, cy, rx, ry, mood="focused", look=(look_x, 1), mstyle="line")

    else:  # pragma: no cover - unknown states fall back to a static body
        cx, cy, rx, ry, top, tail = _body(img, 0, 1.0)
        geo = _tied_ears(cx, top, rx / RX)
        _ears_fill(img, geo)
        img = auto_outline(img)
        _ear_detail(img, geo)
        _tail_detail(img, *tail, cx, cy, rx, ry)
        _face(img, cx, cy, rx, ry)

    return img
