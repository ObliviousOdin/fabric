"""Bobbin v4 "The Thread Mouse" — Skein's sibling (avatar style contract v2).

Bobbin is an ANIMAL FIRST: a round porcelain-cream mouse — a soft ramp-shaded
pear of cream (light cap high-left, indigo-lavender shadow low-right, dithered
seams) with two BIG round ears set high (cream outer, rose inner pads), hero
eyes low on the face, a 1px rose nose, whisker dots, and permanent blush. Its
fiber-craft trait is carried, not worn: a tiny wound spool (cream flanges,
violet thread band) hugged to its chest like a plushie in every frame, and a
long curly thread TAIL (violet strand, cream tip) that is Bobbin's emotion
appendage — it drifts, streams, hooks into question marks, and goes limp.

Row gags: idle squeezes the spool on the exhale; running-right scurries with
the spool tucked underarm; waving flags one paw with the spool in the other;
jumping thrusts the spool triumphantly overhead at the apex; failed drops the
spool and watches it roll away trailing thread; waiting hugs it tighter under
the gold dot; running winds its own tail-thread onto the spool; review reads
the thread held taut off the spool, ears perked forward.
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

NAME = "Bobbin"
SLUG = "bobbin"
DESCRIPTION = "A porcelain thread mouse that hugs its little wound spool like a plushie."

V = RAMPS["violet"]
C = RAMPS["cream"]
G = RAMPS["gold"]
ROSE = RAMPS["rose"]

RX = 15.0  # body half-width before the pear widening (half-res px)
RY = 19.0  # body half-height
PEAR = 0.16  # extra width toward the bottom (the mouse tummy)
EAR_R = 7.0


# ── body ─────────────────────────────────────────────────────────────────
def _pear_w(u: float, rx: float) -> float:
    """Silhouette half-width at normalized height u in [-1, 1] (1 = bottom)."""
    return rx * (1.0 + PEAR * max(0.0, u)) * math.sqrt(max(0.0, 1.0 - u * u))


def _in_pear(x: float, y: float, cx: float, cy: float, rx: float, ry: float) -> bool:
    u = (y - cy) / ry
    if u < -1.0 or u > 1.0:
        return False
    return abs(x - cx) <= _pear_w(u, rx)


def _ear_geo(cx, top, squash, mode="up", amt=1.0, twitch=(0, 0), tw_side=-1):
    """Two big round ear circles set high; *amt* lerps upright -> mode target."""
    ears = []
    for side in (-1, 1):
        ux, uy = cx + side * 10.0 * squash, top + 2.0
        r = EAR_R
        if mode == "back":  # pressed back/down (crouch, sprint)
            tx, ty = cx + side * 12.5 * squash, top + 6.5
        elif mode == "droop":  # dejection: slid low on the sides
            tx, ty = cx + side * 13.5 * squash, top + 10.0
            r = EAR_R - 1.0 * amt
        elif mode == "trail":  # airborne: floating up
            tx, ty = cx + side * 9.0 * squash, top - 2.5
        elif mode == "perk":  # attentive forward tilt (reading)
            tx, ty = cx + side * 8.0 * squash, top + 0.5
        else:
            tx, ty = ux, uy
        ex, ey = ux + (tx - ux) * amt, uy + (ty - uy) * amt
        if side == tw_side and twitch != (0, 0):
            ex, ey = ex + twitch[0], ey + twitch[1]
        ears.append((ex, ey, r))
    return ears


def _body(img, dy, squash, *, lean=0.0, ear_mode="up", ear_amt=1.0, ear_twitch=(0, 0), tw_side=-1):
    """Ramp-shaded cream pear anchored to the ground (bottom = GROUND + dy).

    Ears are laid first so the head dome overlaps their roots; the pear is
    painted per-pixel with sphere shading (warm cap high-left, lavender
    shadow low-right, deep rim at the bottom) and dithered seams.
    """
    d = ImageDraw.Draw(img)
    rx, ry = RX * squash, RY / squash
    cx = CX + lean
    bot = GROUND + dy
    cy = bot - ry
    top = cy - ry
    ears = _ear_geo(cx, top, squash, ear_mode, ear_amt, ear_twitch, tw_side)
    for ex, ey, r in ears:
        d.ellipse((ex - r, ey - r, ex + r, ey + r), fill=C[3])
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
    return cx, cy, rx, ry, ears


# ── details (post-outline) ───────────────────────────────────────────────
def _ear_detail(img, ears, cx, cy, rx, ry):
    """Shade each ear as a mini sphere with a rose inner pad, clipped to the
    part of the ear that is not hidden behind the head dome."""
    px = img.load()
    for ex, ey, r in ears:
        for yi in range(int(ey - r) - 1, int(ey + r) + 2):
            for xi in range(int(ex - r) - 1, int(ex + r) + 2):
                if not (0 <= xi < img.width and 0 <= yi < img.height):
                    continue
                dx, dyy = (xi - ex) / r, (yi - ey) / r
                if dx * dx + dyy * dyy > 1.0:
                    continue
                if _in_pear(xi, yi, cx, cy, rx, ry):
                    continue  # head in front of the ear root
                cur = px[xi, yi]
                if cur[3] == 0 or cur[:3] == INK[:3]:
                    continue  # keep the outline crisp
                pdx, pdy = dx / 0.52, (dyy - 0.10) / 0.60
                if pdx * pdx + pdy * pdy <= 1.0:  # rose inner pad
                    col = ROSE[2] if (0.5 * dx + 0.8 * dyy) > 0.15 else ROSE[3]
                else:
                    tsh = 0.60 * dx + 0.78 * dyy + (0.05 if (xi + yi) % 2 else -0.05)
                    if tsh > 0.55:
                        col = C[1]
                    elif tsh > 0.20:
                        col = C[2]
                    elif tsh < -0.62:
                        col = C[4]
                    else:
                        col = C[3]
                px[xi, yi] = col


def _spool(img, sx, sy, *, phase=0, tipped=False):
    """The signature prop: a tiny wound spool, ink-rimmed so it always reads.

    Upright 6x8 (two cream flange lines, violet thread band); *tipped* lays it
    on its side 8x6 for rolling, with the band lines turned vertical and
    scrolled by *phase* so it visibly spins.
    """
    d = ImageDraw.Draw(img)
    sx, sy = int(round(sx)), int(round(sy))
    if not tipped:
        x0, y0, x1, y1 = sx - 3, sy - 4, sx + 2, sy + 3
        d.rectangle((x0 - 1, y0 - 1, x1 + 1, y1 + 1), fill=INK)
        d.rectangle((x0, y0 + 1, x1, y1 - 1), fill=V[2])
        for k, yy in enumerate(range(y0 + 1, y1)):
            if (k + phase) % 2 == 0:
                d.line((x0 + 1, yy, x1 - 1, yy), fill=V[1])
        d.line((x0, y0 + 1, x0, y1 - 1), fill=V[3])  # lit left of the band
        d.line((x1, y0 + 1, x1, y1 - 1), fill=V[1])
        d.line((x0, y0, x1, y0), fill=C[3])  # flanges
        put(img, x0, y0, C[4])
        put(img, x0 + 1, y0, C[4])
        d.line((x0, y1, x1, y1), fill=C[2])
        put(img, x1, y1, C[1])
    else:
        x0, y0, x1, y1 = sx - 4, sy - 3, sx + 3, sy + 2
        d.rectangle((x0 - 1, y0 - 1, x1 + 1, y1 + 1), fill=INK)
        d.rectangle((x0 + 1, y0, x1 - 1, y1), fill=V[2])
        for k, xx in enumerate(range(x0 + 1, x1)):
            if (k + phase) % 2 == 0:
                d.line((xx, y0 + 1, xx, y1 - 1), fill=V[1])
        d.line((x0 + 1, y0, x1 - 1, y0), fill=V[3])  # lit top of the band
        d.line((x0 + 1, y1, x1 - 1, y1), fill=V[1])
        d.line((x0, y0, x0, y1), fill=C[3])  # flanges (now the wheels)
        put(img, x0, y0, C[4])
        d.line((x1, y0, x1, y1), fill=C[2])
        put(img, x1, y1, C[1])


def _paw(img, x, y):
    """A tiny cream mitten, ink-rimmed so it reads on the cream body."""
    d = ImageDraw.Draw(img)
    d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=C[3], outline=INK)
    put(img, x - 1, y - 1, C[4])
    put(img, x, y, ROSE[3])


def _tail(img, pts, *, tip=True):
    """The long curly thread tail: 2px violet strand with a cream tip."""
    strand(img, pts, V[1], thick=True)
    for a, b in zip(pts, pts[1:]):  # top-light along each segment
        put(img, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 1, V[2])
    if tip:
        x, y = pts[-1]
        put(img, x, y, C[4])
        put(img, x, y + 1, C[3])


def _tail_anchor(cx, cy, rx, ry, side=1):
    """Where the tail leaves the body, low on the given side."""
    return cx + side * (_pear_w(0.72, rx) - 1.0), cy + 0.72 * ry


def _along(pts, f):
    """Point at fraction *f* of the arc length of polyline *pts*."""
    segs = list(zip(pts, pts[1:]))
    lens = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segs]
    total = sum(lens)
    if total <= 0:
        return pts[-1]
    dist = max(0.0, min(1.0, f)) * total
    for (a, b), seg in zip(segs, lens):
        if dist <= seg and seg > 0:
            r = dist / seg
            return (a[0] + (b[0] - a[0]) * r, a[1] + (b[1] - a[1]) * r)
        dist -= seg
    return pts[-1]


def _tear_rim(img, x, y):
    """Kit tear on an ink backing so it reads on the cream body."""
    d = ImageDraw.Draw(img)
    d.ellipse((x - 1, int(y) - 1, x + 1, int(y) + 3), fill=INK)
    tear(img, x, y)


def _face(img, cx, cy, rx, ry, *, mood="open", look=(0, 0), mstyle="smile", cheeks=False):
    """Mouse face low on the head, on a soft lit plate (solid C[4] core with
    a dithered fringe, clipped to the pear): hero eyes, 1px rose nose, tiny
    mouth, whiskers flicking out past the cheek outline, blush on happy beats.
    """
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
            if rr <= 1.0 or (xi + yi) % 2:  # solid core, dithered fringe
                px[xi, yi] = C[4]
    anime_eye_lg(img, cx - 10, ey, mood=mood, look=look)
    anime_eye_lg(img, cx + 7, ey, mood=mood, look=look)
    put(img, cx, ey + 5, ROSE[1])  # the 1px nose
    mouth(img, cx, ey + 7, mstyle)
    for sgn in (-1, 1):  # whiskers flick out past the cheeks into open air
        for dyy in (4, 7):
            u = (ey + dyy - cy) / ry
            wx = _pear_w(u, rx)
            for k in (2, 3):
                put(img, cx + sgn * int(round(wx + k)), ey + dyy, C[2])
    if cheeks:
        blush(img, cx - 14, ey + 6)
        blush(img, cx + 12, ey + 6)
    return ey


# ── choreography ─────────────────────────────────────────────────────────
def draw(state: str, i: int, n: int):
    img = canvas()
    t = i / n
    ph = 2 * math.pi * t

    if state == "idle":
        squash = 1.0 + 0.03 * math.sin(ph)
        tw = (1, -2) if i == 2 else (0, 0)  # left-ear twitch beat
        cx, cy, rx, ry, ears = _body(img, 0, squash, ear_twitch=tw, tw_side=-1)
        img = auto_outline(img)
        _ear_detail(img, ears, cx, cy, rx, ry)
        ax, ay = _tail_anchor(cx, cy, rx, ry)
        lag = follow(t, 0.18, 2.0)
        _tail(
            img,
            [
                (ax, ay),
                (ax + 4, ay + 2),
                (ax + 8, ay + 2 + 0.5 * lag),
                (ax + 12, ay - 1 + lag),
                (ax + 13, ay - 6 + lag),
                (ax + 9, ay - 8 + 0.7 * lag),
                (ax + 6, ay - 5 + 0.5 * lag),
            ],
        )
        chest = cy + 0.45 * ry
        hug = 1 if i == 3 else 0  # squeeze the spool on the exhale
        _spool(img, cx, chest + hug)
        _paw(img, cx - 5 + hug, chest + 2)
        _paw(img, cx + 5 - hug, chest + 2)
        mood = "happy" if i == 3 else ("closed" if i == n - 1 else "open")
        _face(img, cx, cy, rx, ry, mood=mood, mstyle="smile", cheeks=True)

    elif state == "running-right":
        bounce = abs(math.sin(ph))  # two quick scurry-hops per loop
        cx, cy, rx, ry, ears = _body(
            img, -3 * ease_out(bounce), 1.0 + 0.06 * (1 - bounce), lean=3, ear_mode="back", ear_amt=0.9
        )
        img = auto_outline(img)
        _ear_detail(img, ears, cx, cy, rx, ry)
        axl, ayl = _tail_anchor(cx, cy, rx, ry, side=-1)
        whip = follow(t * 2, 0.2, 3)
        _tail(
            img,
            [
                (axl, ayl),
                (axl - 6, ayl - 3 + whip),
                (axl - 12, ayl - 2 - whip),
                (axl - 17, ayl - 5 + 0.5 * whip),
                (axl - 19, ayl - 9 + 0.5 * whip),
            ],
        )
        _spool(img, cx - 11, cy + 7)  # tucked underarm
        _paw(img, cx - 10, cy + 2)
        motion_ticks(img, int(cx - rx - 4), int(cy), 1)
        _face(img, cx, cy, rx, ry, mood="focused", look=(1, 0), mstyle="line")

    elif state == "waving":
        sweep = (0.0, 0.75, 1.0, 0.55)[i]
        cx, cy, rx, ry, ears = _body(img, 1 if i == 0 else 0, 1.0)
        img = auto_outline(img)
        _ear_detail(img, ears, cx, cy, rx, ry)
        ax, ay = _tail_anchor(cx, cy, rx, ry)
        lag = follow(t, 0.1, 2)
        _tail(
            img,
            [
                (ax, ay),
                (ax + 5, ay - 2 * sweep),
                (ax + 9, ay - 3 - lag),
                (ax + 8, ay - 8 - lag),
                (ax + 4, ay - 8 + 0.5 * lag),
            ],
        )
        # Big wave: the arm pivots at the shoulder edge and arcs through open
        # sky (capped short of the ear so the paw never crosses the face).
        pvy = cy - 1
        pvx = cx + _pear_w((pvy - cy) / ry, rx)
        ang = math.pi * (0.04 + 0.24 * ease_in_out(sweep))
        wx, wy = pvx + 13 * math.cos(ang), pvy - 12 * math.sin(ang)
        strand(img, [(pvx - 2, pvy), ((pvx + wx) / 2, (pvy + wy) / 2 + 1), (wx, wy)], C[2], thick=True)
        _paw(img, int(wx), int(wy))
        if i == 2:
            sparkle(img, int(wx) + 3, int(wy) - 3, small=True)
        chest = cy + 0.45 * ry
        _spool(img, cx - 4, chest)  # spool safe in the other paw
        _paw(img, cx - 8, chest + 2)
        _face(img, cx, cy, rx, ry, mood="happy", mstyle="open", cheeks=True)

    elif state == "jumping":
        # Grounded five-beat arc peaked at the middle frame; the spool is
        # thrust triumphantly overhead at the apex.
        arc = math.sin(math.pi * i / (n - 1))
        if i == 0:  # anticipation crouch
            squash, dy, mode, amt = 1.20, 0.0, "back", 0.4
        elif i == 1:  # rise: stretched, ears swept back
            squash, dy, mode, amt = 0.92, -16 * arc, "back", 1.0
        elif i == 2:  # apex: hang-time
            squash, dy, mode, amt = 0.97, -16 * arc, "trail", 0.6
        elif i == 3:  # descend: ears streaming up
            squash, dy, mode, amt = 1.02, -16 * arc, "trail", 1.0
        else:  # grounded landing squash
            squash, dy, mode, amt = 1.14, 0.0, "back", 0.5
        cx, cy, rx, ry, ears = _body(img, dy, squash, ear_mode=mode, ear_amt=amt)
        img = auto_outline(img)
        _ear_detail(img, ears, cx, cy, rx, ry)
        ax, ay = _tail_anchor(cx, cy, rx, ry)
        wob = follow(t, 0.2, 1.5)
        tail_pts = (
            [(ax, ay), (ax + 5, ay + 3), (ax + 10, ay + 4 + wob)],
            [(ax, ay), (ax + 3, ay + 6), (ax + 5, ay + 11 + wob)],
            [(ax, ay), (ax + 5, ay + 1), (ax + 9, ay - 2 + wob), (ax + 12, ay + 1)],
            [(ax, ay), (ax + 4, ay - 5), (ax + 6, ay - 11 + wob)],
            [(ax, ay), (ax + 6, ay + 3), (ax + 12, ay + 4 + wob)],
        )
        _tail(img, tail_pts[i])
        top = cy - ry
        chest = cy + 0.45 * ry
        if i == 2:  # spool overhead + sparkles
            _spool(img, cx, top - 11)
            _paw(img, cx - 4, top - 4)
            _paw(img, cx + 4, top - 4)
            sparkle(img, int(cx - 13), int(top - 8))
            sparkle(img, int(cx + 16), int(top - 11), small=True)
        else:
            lift = (0, 4, 0, 3, 0)[i]
            _spool(img, cx, chest - lift)
            _paw(img, cx - 5, chest + 2 - lift)
            _paw(img, cx + 5, chest + 2 - lift)
        moods = ("focused", "open", "happy", "open", "happy")
        msts = ("line", "open", "open", "open", "smile")
        _face(img, cx, cy, rx, ry, mood=moods[i], look=(0, 1) if i == 3 else (0, 0), mstyle=msts[i], cheeks=i in (2, 4))

    elif state == "failed":
        # The spool slips and rolls away over f0..f3 (trailing thread), the
        # mouse deflates and its ears droop; settled sulk f4..f7 staring at it.
        settle = ease_in_out(min(1.0, i / 3))
        squash = 1.0 + 0.26 * settle + 0.02 * math.sin(ph)
        tw = (0, 1) if i in (4, 6) else (0, 0)  # tiny ear-sag beats
        cx, cy, rx, ry, ears = _body(img, 0, squash, ear_mode="droop", ear_amt=settle, ear_twitch=tw, tw_side=1)
        img = auto_outline(img)
        _ear_detail(img, ears, cx, cy, rx, ry)
        axl, ayl = _tail_anchor(cx, cy, rx, ry, side=-1)
        sag = follow(t, 0.1, 0.8)
        _tail(
            img,
            [
                (axl, ayl),
                (axl - 5, GROUND - 1 + 0.5 * sag),
                (axl - 9, GROUND - 2 - 0.5 * sag),
                (axl - 13, GROUND - 1 + sag),
            ],
        )
        chest = cy + 0.45 * ry
        hx, hy = cx + 6, chest + 1  # the paw the thread still hangs from
        if i == 0:  # the slip: spool tumbling off the paws
            _spool(img, cx + 7, chest + 4, phase=1)
            strand(img, [(hx, hy), (cx + 8, chest + 1)], V[1])
        else:
            sx = (0, 17, 28, 38, 37, 37, 37, 37)[i] + cx  # overshoot, settle
            sy = GROUND - 3
            _spool(img, sx, sy, phase=i, tipped=True)
            mid = ((hx + sx - 5) / 2, GROUND - 1 + 0.5 * sag)
            strand(img, [(hx, hy), mid, (sx - 5, GROUND - 3)], V[1])
        _paw(img, cx + 2, chest + 2)
        _paw(img, hx, hy)
        sweat_drop(img, int(cx + 0.45 * rx), cy - ry - 2 + 6 * t)
        if i == 0:  # the gasp
            ey = _face(img, cx, cy, rx, ry, mood="open", look=(1, 1), mstyle="open")
        elif i == 1:
            ey = _face(img, cx, cy, rx, ry, mood="open", look=(1, 1), mstyle="wobble")
        else:
            ey = _face(img, cx, cy, rx, ry, mood="sad", look=(1, 1), mstyle="wobble")
        if i >= 3:  # a single tear slides from the right eye
            _tear_rim(img, int(cx) + 9, ey + 7 + (i - 3))

    elif state == "waiting":
        squash = 1.0 + 0.02 * math.sin(ph)
        tw = (1, -1) if i == 1 else (0, 0)
        cx, cy, rx, ry, ears = _body(img, 0, squash, ear_twitch=tw, tw_side=1)
        img = auto_outline(img)
        _ear_detail(img, ears, cx, cy, rx, ry)
        # Tail rises past the hip and curls into a question hook in the open
        # air beside the head, right under the gold dot.
        ax, ay = _tail_anchor(cx, cy, rx, ry)
        wob = follow(t, 0.15, 1.0)
        _tail(
            img,
            [
                (ax, ay),
                (cx + 19, cy + 6),
                (cx + 22 + wob, cy - 3),
                (cx + 22 + wob, cy - 10),
                (cx + 18 + wob, cy - 14),
                (cx + 15 + wob, cy - 12),
            ],
        )
        attention_dot(img, int(cx + 21), cy - 19 + bob(t, 1.2), t=t)
        chest = cy + 0.45 * ry
        _spool(img, cx, chest - 1)  # hugged tighter
        _paw(img, cx - 4, chest - 1)
        _paw(img, cx + 4, chest - 1)
        _face(img, cx, cy, rx, ry, mood="closed" if i == n - 1 else "open", look=(1, -1), mstyle="smile", cheeks=True)

    elif state == "running":  # focused work: winding its tail-thread onto the spool
        press = math.sin(2 * ph)
        cx, cy, rx, ry, ears = _body(img, -2 * abs(press), 1.0 + 0.04 * (1 - abs(press)))
        img = auto_outline(img)
        _ear_detail(img, ears, cx, cy, rx, ry)
        chest = cy + 0.45 * ry
        ax, ay = _tail_anchor(cx, cy, rx, ry)
        sw = follow(t * 2, 0.25, 2.0)
        pts = [
            (ax, ay),
            (ax + 6, ay - 2 + 0.5 * sw),
            (ax + 8, ay - 9 + sw),
            (cx + 9, chest + 3),
            (cx + 4, chest),
        ]
        _tail(img, pts, tip=False)
        _spool(img, cx, chest, phase=i)  # the band visibly winds up
        _paw(img, cx - 5, chest + 2)
        _paw(img, cx + 6, chest - 5 + (1 if press > 0 else 0))  # guide paw taps
        gx, gy = _along(pts, (2 * t) % 1.0)  # gold progress stitch rides the strand
        put(img, gx, gy, G[3])
        put(img, gx, gy - 1, G[4])
        _face(img, cx, cy, rx, ry, mood="focused", look=(1 if press >= 0 else 0, 1), mstyle="line")

    elif state == "review":
        nod = i == n - 1
        cx, cy, rx, ry, ears = _body(img, 1 if nod else 0, 1.0, ear_mode="perk")
        img = auto_outline(img)
        _ear_detail(img, ears, cx, cy, rx, ry)
        ax, ay = _tail_anchor(cx, cy, rx, ry)
        drift = follow(t, 0.18, 1.5)
        _tail(
            img,
            [
                (ax, ay),
                (ax + 4, ay + 2 + 0.5 * drift),
                (ax + 8, ay + 1 + drift),
                (ax + 10, ay - 3 + 0.7 * drift),
            ],
        )
        chest = cy + 0.45 * ry
        _spool(img, cx - 8, chest)  # spool in the left paw...
        _paw(img, cx - 11, chest + 3)
        line_y = chest - 2
        strand(img, [(cx - 5, line_y), (cx + 11, line_y)], V[1])  # ...thread held taut
        _paw(img, cx + 13, line_y + 1)
        scan = ease_in_out(min(1.0, i / (n - 2)))
        gx = int(cx - 4 + 14 * scan)
        put(img, gx, line_y, G[3])
        put(img, gx, line_y - 1, G[4])
        if nod:
            _face(img, cx, cy, rx, ry, mood="happy", mstyle="smile", cheeks=True)
        else:
            look_x = max(-1, min(1, int(round(-1 + 2 * scan))))
            _face(img, cx, cy, rx, ry, mood="focused", look=(look_x, 1), mstyle="line")

    else:  # pragma: no cover - unknown states fall back to a static body
        cx, cy, rx, ry, ears = _body(img, 0, 1.0)
        img = auto_outline(img)
        _ear_detail(img, ears, cx, cy, rx, ry)
        _spool(img, cx, cy + 0.45 * ry)
        _face(img, cx, cy, rx, ry)

    return img
