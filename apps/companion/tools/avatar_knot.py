"""Knot — the rope sprite. The set's earnest strongman (style contract v2).

A friendly overhand knot: two chunky brand-violet rope loops overlapping at
the center like a pretzel, transparent holes punched through each loop so the
knot read is instant. Rope-twist dashes follow each loop's curve, the right
loop crosses visibly OVER the left, and two thick rope ends with frayed cream
tips do all the acting — swaying, waving, wrapping, tapping, going limp.
"""

from __future__ import annotations

import math

from PIL import ImageDraw

from avatar_kit import (
    CX,
    G_H,
    G_W,
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
DESCRIPTION = "A friendly overhand knot that holds everything together."

V = RAMPS["violet"]
C = RAMPS["cream"]
G = RAMPS["gold"]

_VIOLET = set(V)

# Loop proportions (half-res px) — chibi: two fat loops, most of the cell.
BASE_RX, BASE_RY = 15.0, 22.0
LOOP_DX = 9.0  # loop centers sit at CX +/- LOOP_DX
HOLE_DX, HOLE_DY = 3.0, -8.0  # hole offset from its loop center (outward, up)
HOLE_RX, HOLE_RY = 4.6, 6.3


# ── geometry ─────────────────────────────────────────────────────────────
def _geo(dy: float = 0.0, sc: float = 1.0, *, lean: float = 0.0, swell: float = 0.0,
         squash: float = 1.0, loose: float = 1.0):
    """Both loop tubes, ground-anchored. Returns (left, right, fx, fy).

    Each loop is (cx, cy, rx, ry, hx, hy, hrx, hry): outer ellipse + hole.
    ``swell`` grows one loop while shrinking the other (breathing);
    ``loose`` scales the holes (tight knot vs. coming loose).
    """
    loops = []
    for side in (-1, 1):
        rx = (BASE_RX - side * swell) * sc * squash
        ry = (BASE_RY - side * 0.7 * swell) * sc / squash
        cx = CX + lean + side * LOOP_DX * sc * squash
        cy = GROUND + dy - ry
        loops.append((
            cx, cy, rx, ry,
            cx + side * HOLE_DX * sc, cy + HOLE_DY * sc / squash,
            HOLE_RX * sc * loose, HOLE_RY * sc * loose,
        ))
    return loops[0], loops[1], CX + lean, GROUND + dy - BASE_RY * sc / squash + 2


def _annulus(img, geo):
    """One rope loop: violet disc with the hole punched transparent."""
    cx, cy, rx, ry, hx, hy, hrx, hry = geo
    d = ImageDraw.Draw(img)
    d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=V[2])
    d.ellipse((hx - hrx, hy - hry, hx + hrx, hy + hry), fill=(0, 0, 0, 0))


def _body(img, left, right):
    """Left loop first, right loop OVER it — the knot crossing by draw order."""
    _annulus(img, left)
    _annulus(img, right)


def _in_ellipse(x, y, cx, cy, rx, ry, margin: float = 0.0) -> bool:
    return ((x - cx) / (rx + margin)) ** 2 + ((y - cy) / (ry + margin)) ** 2 <= 1.0


# ── details (post-outline) ───────────────────────────────────────────────
def _safe_arc(img, box, a0, a1, color, excl=None):
    """Elliptical arc that only recolors violet rope pixels (never outline,
    holes, or the background); *excl* skips pixels inside another loop."""
    px = img.load()
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    rx, ry = (box[2] - box[0]) / 2, (box[3] - box[1]) / 2
    for deg in range(int(a0), int(a1) + 1):
        a = math.radians(deg)
        x, y = int(round(cx + rx * math.cos(a))), int(round(cy + ry * math.sin(a)))
        if not (0 <= x < G_W and 0 <= y < G_H):
            continue
        if excl is not None and _in_ellipse(x, y, excl[0], excl[1], excl[2], excl[3]):
            continue
        if px[x, y] in _VIOLET:
            px[x, y] = color


def _dither_safe(img, box, color, *, phase: int = 0):
    """Checkerboard dither that only touches violet rope pixels."""
    x0, y0, x1, y1 = (int(v) for v in box)
    px = img.load()
    for y in range(max(0, y0), min(G_H, y1)):
        for x in range(max(0, x0), min(G_W, x1)):
            if (x + y + phase) % 2 == 0 and px[x, y] in _VIOLET:
                px[x, y] = color


def _loop_shade(img, geo, side: int, excl=None):
    """Torus ramp: warm light high-left, indigo shadow + deep rim low-right,
    shaded hole rim (dark above, lit below)."""
    cx, cy, rx, ry, hx, hy, hrx, hry = geo
    ob1 = (cx - rx + 1, cy - ry + 1, cx + rx - 1, cy + ry - 1)
    ob2 = (cx - rx + 2, cy - ry + 2, cx + rx - 2, cy + ry - 2)
    if side < 0:  # left loop keeps out of the overlap band
        _safe_arc(img, ob1, 165, 285, V[3], excl)
        _safe_arc(img, ob2, 185, 265, V[4], excl)
        _safe_arc(img, ob1, 50, 150, V[1], excl)
        _safe_arc(img, ob2, 65, 135, V[0], excl)
    else:
        _safe_arc(img, ob1, 170, 295, V[3])
        _safe_arc(img, ob2, 190, 275, V[4])
        _safe_arc(img, ob1, 5, 125, V[1])
        _safe_arc(img, ob2, 20, 110, V[0])
        _safe_arc(img, (cx - rx + 3, cy - ry + 3, cx + rx - 3, cy + ry - 3), 35, 95, V[0])
    hb = (hx - hrx - 1, hy - hry - 1, hx + hrx + 1, hy + hry + 1)
    _safe_arc(img, hb, 150, 390, V[1], excl if side < 0 else None)
    _safe_arc(img, hb, 50, 130, V[3], excl if side < 0 else None)


def _dashes(img, geo, *, phase: float = 0.0, excl=None):
    """Short rope-twist dashes riding the tube midline; *phase* rolls them."""
    cx, cy, rx, ry, hx, hy, hrx, hry = geo
    mcx, mcy = (cx + hx) / 2, (cy + hy) / 2
    mrx, mry = (rx + hrx) / 2 + 0.5, (ry + hry) / 2 + 0.5
    px = img.load()
    darker = {V[2]: V[1], V[3]: V[1], V[4]: V[3], V[1]: V[0]}
    ca, sa = math.cos(0.85), math.sin(0.85)
    for k in range(11):
        u = 2 * math.pi * (k + phase) / 11
        bx, by = mcx + mrx * math.cos(u), mcy + mry * math.sin(u)
        tx, ty = -mrx * math.sin(u), mry * math.cos(u)
        norm = math.hypot(tx, ty) or 1.0
        tx, ty = tx / norm, ty / norm
        dxx, dyy = tx * ca - ty * sa, tx * sa + ty * ca  # tangent + rope twist
        for s in (-1.4, -0.5, 0.5, 1.4):
            xi, yi = int(round(bx + s * dxx)), int(round(by + s * dyy))
            if not (0 <= xi < G_W and 0 <= yi < G_H):
                continue
            if excl is not None and _in_ellipse(xi, yi, excl[0], excl[1], excl[2], excl[3]):
                continue
            c = px[xi, yi]
            if c in darker:
                px[xi, yi] = darker[c]


def _face_oval(fx: float, fy: float):
    """The lit crossing region that hosts the face (body material, no plate)."""
    return (fx, fy + 4, 12.5, 8.0)


def _crossing(img, left, right, avoid=None):
    """Ink seam + crevice shadow where the right loop passes OVER the left.

    *avoid* is an ellipse (cx, cy, rx, ry) the seam stays out of — the face
    sits on the crossing, so the crevice quiets down beneath it.
    """
    lcx, lcy, lrx, lry, lhx, lhy, lhrx, lhry = left
    rcx, rcy, rrx, rry = right[:4]
    px = img.load()
    for deg in range(90, 271):
        a = math.radians(deg)
        offs = ((-0.4, INK), (1.4, V[0])) if deg >= 170 else ((-0.4, INK),)
        for off, col in offs:
            x = rcx + (rrx + off) * math.cos(a)
            y = rcy + (rry + off) * math.sin(a)
            xi, yi = int(round(x)), int(round(y))
            if not (0 <= xi < G_W and 0 <= yi < G_H):
                continue
            if not _in_ellipse(x, y, lcx, lcy, lrx - 1.0, lry - 1.0):
                continue
            if _in_ellipse(x, y, lhx, lhy, lhrx + 1.0, lhry + 1.0):
                continue
            if avoid is not None and _in_ellipse(x, y, *avoid):
                continue
            if px[xi, yi] in _VIOLET:
                px[xi, yi] = col


def _details(img, left, right, *, dash_phase: float = 0.0, face=None):
    _loop_shade(img, left, -1, excl=right)
    _loop_shade(img, right, +1)
    lcx, lcy, lrx, lry = left[:4]
    rcx, rcy, rrx, rry = right[:4]
    _dither_safe(img, (lcx - lrx + 3, lcy - lry + 3, lcx - 5, lcy - lry + 9), V[3])
    _dither_safe(img, (rcx + 6, rcy + rry * 0.5, rcx + rrx - 1, rcy + rry - 4), V[1], phase=1)
    _dashes(img, left, phase=dash_phase, excl=right)
    _dashes(img, right, phase=dash_phase + 0.5)
    _crossing(img, left, right, avoid=_face_oval(*face) if face else None)


# ── rope ends ────────────────────────────────────────────────────────────
def _fray(img, x, y, ang, wiggle: float = 0.0):
    """Three splayed cream fibers at the rope end's tip."""
    for k, spread in enumerate((-0.7, 0.0, 0.7)):
        a = ang + spread + 0.3 * wiggle * (1 if k != 1 else -1)
        col = C[4] if k == 1 else C[3]
        for r in ((1.4, 2.6, 3.8) if k == 1 else (1.4, 2.8)):
            put(img, x + r * math.cos(a), y + r * math.sin(a), col)


def _end(img, pts, *, wiggle: float = 0.0, fray: bool = True):
    """A thick rope end: dark underside, lit top-left, frayed cream tip.

    Each segment is layered with offsets perpendicular to its own direction,
    so the tube stays uniformly chunky whether it hangs, trails, or waves.
    """
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        norm = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / norm, dx / norm
        if ny > 0 or (ny == 0 and nx > 0):  # normal points up(-left) = light side
            nx, ny = -nx, -ny
        layers = [(-1.0, V[0], True), (0.0, V[1], True), (1.0, V[2], True)]
        if norm >= 4.0:  # thin top-light only on longer runs (no corner lint)
            layers.append((1.8, V[3], False))
        for off, col, thick in layers:
            strand(img, [(a[0] + off * nx, a[1] + off * ny), (b[0] + off * nx, b[1] + off * ny)], col, thick=thick)
    if fray:
        (x2, y2), (x1, y1) = pts[-2], pts[-1]
        _fray(img, x1, y1, math.atan2(y1 - y2, x1 - x2), wiggle)


def _puff(img, x, y):
    """A tiny effort puff (hard-at-work huffing)."""
    put(img, x, y, C[4])
    for ox, oy in ((-1, 0), (1, 0), (0, -1)):
        put(img, x + ox, y + oy, C[2])
    put(img, x - 1, y - 1, C[3])


# ── face ─────────────────────────────────────────────────────────────────
def _face_glow(img, fx: int, fy: int):
    """Lift the crossing to its warm light step so the face sits on lit rope.

    One-step ramp brighten inside the face oval with a dithered rim — pure
    body material catching the key light, NOT a bolted-on plate. Only violet
    rope pixels are touched (outline, holes, and effects stay intact).
    """
    cx, cy, rx, ry = _face_oval(fx, fy)
    lighter = {V[0]: V[1], V[1]: V[2], V[2]: V[3], V[3]: V[4]}
    px = img.load()
    for y in range(int(cy - ry), int(cy + ry) + 2):
        for x in range(int(cx - rx), int(cx + rx) + 2):
            if not (0 <= x < G_W and 0 <= y < G_H):
                continue
            d2 = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
            if d2 > 1.0 or (d2 > 0.72 and (x + y) % 2):
                continue  # dithered rim melts the glow into the rope
            c = px[x, y]
            if c in lighter:
                px[x, y] = lighter[c]


def _face(img, fx, fy, *, mood="open", look=(0, 0), mouth_mood="smile", cheeks=False):
    """Hero face directly on the rope at the central crossing (no plate):
    solid-ink anime_eye_lg pair on the glow-lit material + mouth + blush."""
    fx, fy = int(round(fx)), int(round(fy))
    _face_glow(img, fx, fy)
    anime_eye_lg(img, fx - 9, fy, mood=mood, look=look)
    anime_eye_lg(img, fx + 6, fy, mood=mood, look=look)
    mouth(img, fx, fy + 9, mouth_mood)
    if cheeks:
        blush(img, fx - 13, fy + 6)
        blush(img, fx + 11, fy + 6)


# ── choreography ─────────────────────────────────────────────────────────
def draw(state: str, i: int, n: int):
    img = canvas()
    t = i / n
    ph = 2 * math.pi * t

    if state == "idle":
        left, right, fx, fy = _geo(swell=1.1 * math.sin(ph))
        _body(img, left, right)
        img = auto_outline(img)
        _details(img, left, right, face=(fx, fy))
        sway = 2.0 * math.sin(ph)
        lag = 2.0 * follow(t, 0.18)
        axl, ayl = left[0] - left[2] + 2, left[1] + 6
        axr, ayr = right[0] + right[2] - 2, right[1] + 6
        _end(img, [(axl, ayl), (axl - 5 + 0.4 * sway, ayl + 7), (axl - 9 + 0.9 * lag, GROUND - 2)])
        _end(img, [(axr, ayr), (axr + 5 + 0.4 * sway, ayr + 7), (axr + 9 + 0.9 * lag, GROUND - 2)])
        _face(img, fx, fy, mood="closed" if i == n - 1 else "open", cheeks=True)

    elif state == "running-right":
        bounce = abs(math.sin(2 * ph))
        left, right, fx, fy = _geo(dy=-4 * ease_out(bounce), lean=3, squash=1.0 + 0.06 * (1 - bounce))
        _body(img, left, right)
        img = auto_outline(img)
        _details(img, left, right, dash_phase=4 * t, face=(fx, fy))  # dashes roll forward
        whip = follow(2 * t, 0.2, 2.5)
        whip2 = follow(2 * t, 0.35, 2.5)
        axl, ayl = left[0] - left[2] + 2, left[1] + 6
        _end(img, [(axl, ayl), (axl - 8, ayl - 2 + whip), (axl - 15, ayl + 1 - whip), (axl - 21, ayl + 3 + 0.5 * whip)])
        axr, ayr = right[0] + right[2] - 4, right[1] - right[3] + 8
        _end(img, [(axr, ayr), (axr - 1, ayr - 9), (axr - 10, ayr - 13 + 0.6 * whip2), (axr - 19, ayr - 15 - 0.6 * whip2)])
        motion_ticks(img, int(left[0] - left[2] - 3), int(left[1]), 1)
        _face(img, fx, fy, mood="focused", look=(1, 0), mouth_mood="line")

    elif state == "waving":
        left, right, fx, fy = _geo()
        _body(img, left, right)
        img = auto_outline(img)
        _details(img, left, right, face=(fx, fy))
        # Right end spirals up overhead with an eased pendulum; tip wiggles.
        s = ease_in_out(0.5 + 0.5 * math.sin(math.pi * (2 * t - 0.5)))
        axr, ayr = right[0] + right[2] - 3, right[1] + 2
        bx, by = axr + 3, ayr - 8 - 8 * s
        ang = math.pi * (0.06 + 0.62 * s)
        ex, ey = bx + 9 * math.cos(ang * 0.6), by - 9 * math.sin(ang * 0.6)
        tx, ty = bx + 19 * math.cos(ang), by - 19 * math.sin(ang)
        curl = (tx + 3 * math.cos(ang + 1.7), ty - 3 * math.sin(ang + 1.7))
        _end(img, [(axr, ayr), (bx, by), (ex, ey), (tx, ty), curl], wiggle=1.0 if i % 2 == 0 else -1.0)
        axl, ayl = left[0] - left[2] + 2, left[1] + 6
        _end(img, [(axl, ayl), (axl - 5, ayl + 7), (axl - 9 + 1.2 * follow(t, 0.1), GROUND - 2)])
        _face(img, fx, fy, mood="happy", mouth_mood="open", cheeks=True)

    elif state == "jumping":
        # Symmetric arc peaked at the MIDDLE frame: f0 cinch-crouch, f1
        # spring (ends dragged below), f2 apex (knot loosens mid-air +
        # sparkle), f3 descend (ends flung up), f4 GROUNDED landing squash
        # that flows straight back into the f0 crouch.
        arc = math.sin(math.pi * i / (n - 1))
        if i == 0:  # anticipation: the whole knot cinches down tight
            left, right, fx, fy = _geo(sc=0.96, squash=1.14, loose=0.78)
        elif i == n - 1:  # landing: grounded, wide, holes still slack
            left, right, fx, fy = _geo(sc=0.97, squash=1.2, loose=0.88)
        else:  # airborne: holes loosen toward the apex (mid-air slack gag)
            descend = i > (n - 1) // 2
            left, right, fx, fy = _geo(
                dy=-15 * arc + (1 if descend else 0),
                squash=1.0 - 0.05 * arc,
                loose=1.0 + 0.24 * arc + (0.04 if descend else 0.0),
            )
        _body(img, left, right)
        img = auto_outline(img)
        _details(img, left, right, dash_phase=0.6 * i, face=(fx, fy))
        axl, ayl = left[0] - left[2] + 2, left[1] + 6
        axr, ayr = right[0] + right[2] - 2, right[1] + 6
        drift = follow(t, 0.2, 1.5)
        if i == 0:  # ends braced against the ground, coiled close
            _end(img, [(axl, ayl), (axl - 4, ayl + 6), (axl - 6, GROUND - 2)])
            _end(img, [(axr, ayr), (axr + 4, ayr + 6), (axr + 6, GROUND - 2)])
            _face(img, fx, fy, mood="focused", mouth_mood="line")
        elif i == 1:  # rising: ends drag straight down, left behind
            _end(img, [(axl, ayl), (axl - 4 + drift, ayl + 10), (axl - 5 + drift, ayl + 17)])
            _end(img, [(axr, ayr), (axr + 4 - drift, ayr + 10), (axr + 5 - drift, ayr + 17)])
            _face(img, fx, fy, mood="happy", look=(0, -1), mouth_mood="open", cheeks=True)
        elif i == 2:  # apex: weightless — ends drift out level, sparkle
            _end(img, [(axl, ayl), (axl - 7, ayl + 4 + drift), (axl - 13, ayl + 6)])
            _end(img, [(axr, ayr), (axr + 7, ayr + 4 + drift), (axr + 13, ayr + 6)])
            sparkle(img, int(left[0] - left[2] - 6), int(left[1] - left[3] - 2))
            sparkle(img, int(right[0] + right[2] + 5), int(right[1] - right[3] + 4), small=True)
            _face(img, fx, fy, mood="happy", mouth_mood="open", cheeks=True)
        elif i == 3:  # descending: inertia flings the ends up past the loops
            _end(img, [(axl, ayl), (axl - 6, ayl - 8), (axl - 9, ayl - 15)])
            _end(img, [(axr, ayr), (axr + 6, ayr - 8), (axr + 9, ayr - 15)])
            _face(img, fx, fy, mood="open", look=(0, 1), mouth_mood="open")
        else:  # touchdown: ends splay wide along the ground
            _end(img, [(axl, ayl), (axl - 8, ayl + 8), (axl - 14, GROUND - 1)])
            _end(img, [(axr, ayr), (axr + 8, ayr + 8), (axr + 14, GROUND - 1)])
            _face(img, fx, fy, mood="happy", mouth_mood="smile", cheeks=True)

    elif state == "failed":  # the knot comes half-undone, then sits with it
        # Progressive come-apart over f0..f3 (right loop droops with a tiny
        # overshoot pop at f3), then settled sulk-breathing f4..f7 (<=1px)
        # ending in a holdable slump. Kit tear() wells up from f3.
        slump = (0.12, 0.45, 0.78, 1.06, 1.0, 1.0, 1.0, 1.0)[i]
        bre = 0.5 * math.sin(ph)  # sulk breath, sub-pixel amplitude

        def lp(a: float, b: float) -> float:
            return a + (b - a) * slump

        ry_l = lp(22.0, 20.0) + 0.5 * bre
        lgeo = (CX - 9, GROUND - ry_l, lp(15.0, 15.5), ry_l,
                CX - 12, lp(70.0, 73.0) - 0.4 * bre, lp(4.6, 5.5), lp(6.3, 6.5))
        ry_r = lp(22.0, 13.0) + 0.3 * bre
        rgeo = (lp(57.0, 60.0), GROUND - ry_r, lp(15.0, 16.0), ry_r,
                lp(60.0, 65.5), lp(70.0, 87.0) - 0.4 * bre, lp(4.6, 7.0), lp(6.3, 5.0))
        fy = (GROUND - ry_l) + 2 + slump
        _body(img, lgeo, rgeo)
        img = auto_outline(img)
        _details(img, lgeo, rgeo, face=(CX, fy))
        # Rope ends slide from a hang into a full ground-level sprawl; the
        # tips keep a follow()-lagged twitch through the sulk hold.
        sl = min(1.0, slump)
        dr = follow(t, 0.25, 0.8)
        axl, ayl = lgeo[0] - lgeo[2] + 2, lgeo[1] + 6
        axr, ayr = rgeo[0] + rgeo[2] - 2, rgeo[1] + 4
        _end(img, [(axl, ayl), (axl - 5 - 3 * sl, ayl + 7 - sl), (axl - 9 - 5 * sl + dr, GROUND - 2 + sl)])
        _end(img, [(axr, ayr), (axr + 4 + 3 * sl, min(ayr + 7.0, GROUND - 3)), (axr + 7 + 5 * sl - dr, GROUND - 2 + sl)])
        if i >= 3:
            tear(img, CX - 8, fy + 7 + (i - 3))
        sweat_drop(img, CX + 17, 63 + 5 * t)
        _face(img, CX, fy, mood="sad", look=(0, 1), mouth_mood="wobble")

    elif state == "waiting":
        left, right, fx, fy = _geo(swell=0.5 * math.sin(ph))
        _body(img, left, right)
        img = auto_outline(img)
        _details(img, left, right, face=(fx, fy))
        # Left end curls into a question-hook under the twinkling gold dot;
        # the hook tip keeps a tiny alternating wobble so it never freezes.
        wob = 1 if i % 2 == 0 else 0
        axl, ayl = left[0] - left[2] + 2, left[1] + 4
        _end(img, [(axl, ayl), (axl - 5, ayl - 7), (axl - 7 - wob, ayl - 15), (axl - 3, ayl - 20),
                   (axl + 1 + wob, ayl - 16), (axl - 1, ayl - 12)])
        put(img, axl - 4, ayl - 5, V[1])
        attention_dot(img, int(axl - 4), ayl - 27 + bob(t, 1.2), t=t)
        # Right end taps the ground on alternate frames.
        axr, ayr = right[0] + right[2] - 2, right[1] + 6
        _end(img, [(axr, ayr), (axr + 5, ayr + 5), (axr + 8, GROUND - 1 - (0 if i % 2 else 4))])
        _face(img, fx, fy, mood="closed" if i == n - 1 else "open", look=(-1, -1), mouth_mood="line")

    elif state == "running":  # hard at work: ends wrap-and-unwrap the base
        pulse = math.sin(2 * ph)
        left, right, fx, fy = _geo(squash=1.0 + 0.035 * pulse, loose=1.0 - 0.06 * abs(pulse))
        _body(img, left, right)
        img = auto_outline(img)
        _details(img, left, right, dash_phase=2 * t, face=(fx, fy))
        wl = ease_in_out(0.5 + 0.5 * math.sin(2 * ph))
        wr = ease_in_out(0.5 + 0.5 * math.sin(2 * ph + math.pi))
        fl = follow(2 * t, 0.15, 1.5)
        fr = follow(2 * t, 0.4, 1.5)
        axl, ayl = left[0] - left[2] + 2, left[1] + 6
        axr, ayr = right[0] + right[2] - 2, right[1] + 6
        tipx = (CX - 28) + 34 * wl
        _end(img, [(axl, ayl), ((axl + tipx) / 2 - 2, GROUND - 4 + 2 * wl), (tipx, GROUND - 3 - 6 * wl + fl)], wiggle=fl)
        tipx = (CX + 28) - 34 * wr
        _end(img, [(axr, ayr), ((axr + tipx) / 2 + 2, GROUND - 4 + 2 * wr), (tipx, GROUND - 3 - 6 * wr + fr)], wiggle=fr)
        if wl > 0.85:
            _puff(img, int(left[0] - left[2] - 5), int(left[1] - 12))
        if wr > 0.85:
            _puff(img, int(right[0] + right[2] + 5), int(right[1] - 12))
        lookx = 1 if wl > 0.7 else (-1 if wr > 0.7 else 0)
        _face(img, fx, fy, mood="focused", look=(lookx, 1), mouth_mood="line")

    elif state == "review":  # both ends hold a taut cream strand, eyes scan
        left, right, fx, fy = _geo()
        _body(img, left, right)
        img = auto_outline(img)
        _details(img, left, right, face=(fx, fy))
        sy = fy + 13
        flex = follow(t, 0.3, 0.6)  # elbows flex as the strand is fed along
        axl, ayl = left[0] - left[2] + 2, left[1] + 6
        axr, ayr = right[0] + right[2] - 2, right[1] + 6
        _end(img, [(axl, ayl), (axl - 2, ayl + 7 + flex), (CX - 19, sy + 3), (CX - 15, sy + 1)])
        _end(img, [(axr, ayr), (axr + 2, ayr + 7 - flex), (CX + 19, sy + 3), (CX + 15, sy + 1)])
        strand(img, [(CX - 13, sy + 1), (CX - 10, sy), (CX + 10, sy), (CX + 13, sy + 1)], C[3])
        scan = ease_in_out(1.0 - abs(2 * t - 1.0))
        gx = CX - 10 + 20 * scan
        put(img, gx, sy, G[2])
        put(img, gx, sy - 1, G[3])
        lookx = max(-1, min(1, int(round(-1 + 2 * scan))))
        _face(img, fx, fy, mood="focused", look=(lookx, 1), mouth_mood="line")

    else:  # pragma: no cover - unknown states fall back to a static body
        left, right, fx, fy = _geo()
        _body(img, left, right)
        img = auto_outline(img)
        _details(img, left, right, face=(fx, fy))
        _face(img, fx, fy)

    return img
