"""Shuttle v3 "The Weaver Bird" — Skein's hovering sibling (style contract v2).

Shuttle is an ANIMAL FIRST: a round navy weaver-bird chick — a Kirby-round
ramp-shaded sphere (warm light cap high-left, indigo shadow low-right, deep
rim inside the bottom outline, dithered seams) with a big cream belly/face
patch, tiny cream-tipped wings, a small ink-rimmed gold beak, and three
head-feather ticks. Hero eyes sit low on the cream patch, blush on happy
beats. Its fiber-craft trait is carried, not worn: a violet THREAD held in
the beak, whose trailing end ripples with follow-through in every frame —
Shuttle's emotion appendage. The set's hoverer: it floats on a smooth bob
above a soft dithered ground shadow and only touches down when it all fails.

Row gags: idle is a serene hover with settling wings and a slow last-frame
blink; running-right zips ahead leaning, wings swept back, long thread wake;
waving hovers upright and waves one wing BIG; jumping sketches a joyful
loop-de-loop, the thread spiralling below at the apex; failed flutters down
and LANDS in a ruffled heap, thread tangled around its belly, tear from f3;
waiting curls the beak-thread into a question hook under the gold dot;
running WEAVES tight left-right shuttle passes, laying cream weft lines that
accumulate below; review hovers still, tracking the fresh weft line with its
eyes and a head turn, and nods approval on the last frame.
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
    follow,
    motion_ticks,
    put,
    sparkle,
    strand,
    sweat_drop,
    tear,
)

NAME = "Shuttle"
SLUG = "shuttle"
DESCRIPTION = "A round weaver-bird chick that hovers everywhere, weaving with the violet thread in its beak."

V = RAMPS["violet"]
N = RAMPS["navy"]
C = RAMPS["cream"]
G = RAMPS["gold"]
ROSE = RAMPS["rose"]

R = 17.0  # chick body radius at rest (half-res px)
HOVER_Y = 64.0  # hover center; bottom of the body floats ~19px off the ground

REST_WING = (0.32, 0.0, 9.0)  # (lift angle, tip x-sweep, length)

# Head-feather ticks: (base x-offset, tip dx, tip dy, sway gain, droop dx).
TUFT = (
    (-4.5, -3.0, -6.0, 0.85, -7.0),
    (0.0, 0.5, -8.0, 1.0, 2.5),
    (4.5, 3.5, -5.0, 1.15, 7.0),
)


# ── body ─────────────────────────────────────────────────────────────────
def _body(img, cx, cy, *, squash=1.0, wings=(REST_WING, REST_WING), sway=0.0, droop=0.0):
    """Silhouette pass: wings + head-feather ticks first (the body dome covers
    their roots), then the per-pixel ramp-shaded navy sphere — warm cap
    high-left, indigo shadow low-right, deep rim inside the bottom outline,
    dithered seams. Returns geometry for the detail/face passes."""
    d = ImageDraw.Draw(img)
    rx, ry = R * squash, R / squash
    # Wings: little paddles pivoting at the body sides; ``ang`` lifts the
    # tip (0 = folded down-out), ``tdx`` sweeps it for travel/trailing.
    winfo = []
    for side, (ang, tdx, ln) in zip((-1, 1), wings):
        pvx, pvy = cx + side * (rx - 1.5), cy - 1.0
        a = -0.85 + ang
        dxu, dyu = side * math.cos(a), -math.sin(a)
        tip = (pvx + dxu * ln + tdx, pvy + dyu * ln)
        px_, py_ = -dyu, dxu  # perpendicular: the paddle's width axis
        d.polygon(
            [
                (pvx + px_ * 3.2, pvy + py_ * 3.2),
                (pvx - px_ * 3.2, pvy - py_ * 3.2),
                (tip[0] - px_ * 2.0, tip[1] - py_ * 2.0),
                (tip[0] + px_ * 2.0, tip[1] + py_ * 2.0),
            ],
            fill=N[2],
        )
        # Round the paddle end so the wing reads as a soft nub, not a spike.
        d.ellipse((tip[0] - 2.2, tip[1] - 2.2, tip[0] + 2.2, tip[1] + 2.2), fill=N[2])
        winfo.append((pvx, pvy, tip, side))
    # Head-feather ticks (chunky little triangles); *sway* lags them,
    # *droop* flops them out to the sides.
    top = cy - ry
    tinfo = []
    for off, tdx, tdy, k, out in TUFT:
        ddx = tdx + sway * k + droop * out
        ddy = tdy + droop * (abs(tdy) + 2.5)
        tip = (cx + off + ddx, top + 1.2 + ddy)
        d.polygon([(cx + off - 1.6, top + 4.0), (cx + off + 1.6, top + 4.0), tip], fill=N[2])
        tinfo.append(tip)
    # The chick sphere, ramp-shaded per pixel.
    px = img.load()
    for yi in range(int(math.floor(cy - ry)), int(math.ceil(cy + ry)) + 1):
        nyv = (yi - cy) / ry
        for xi in range(int(math.floor(cx - rx)), int(math.ceil(cx + rx)) + 1):
            if not (0 <= xi < G_W and 0 <= yi < G_H):
                continue
            nxv = (xi - cx) / rx
            rr = nxv * nxv + nyv * nyv
            if rr > 1.0:
                continue
            tsh = 0.52 * nxv + 0.80 * nyv + (0.05 if (xi + yi) % 2 else -0.05)
            if nyv > 0.45 and rr > 0.80:
                col = N[0]  # deep rim just inside the bottom outline
            elif tsh > 0.55:
                col = N[1]
            elif tsh > -0.35:
                col = N[2]
            elif tsh > -0.78:
                col = N[3]
            else:
                col = N[4]  # warm-steel cap high-left
            px[xi, yi] = col
    return cx, cy, rx, ry, winfo, tinfo


def _details(img, geo):
    """Post-outline accents: lit wing edges + cream wing tips, light feather
    tips — laid after auto_outline so they are never re-outlined."""
    _cx, _cy, _rx, _ry, winfo, tinfo = geo
    for pvx, pvy, tip, _side in winfo:
        ux, uy = tip[0] - pvx, tip[1] - pvy
        ln = max(1.0, math.hypot(ux, uy))
        ux, uy = ux / ln, uy / ln
        mx, my = (pvx + tip[0]) / 2, (pvy - 1 + tip[1]) / 2
        strand(img, [(pvx, pvy - 1), (mx, my)], N[3])  # lit leading edge
        # Cream-dipped tip: a 4px dab across the paddle end.
        put(img, tip[0], tip[1], C[4])
        put(img, tip[0] - ux, tip[1] - uy, C[3])
        put(img, tip[0] - uy, tip[1] + ux, C[3])
        put(img, tip[0] + uy, tip[1] - ux, C[3])
    for tx, ty in tinfo:
        put(img, tx, ty, N[3])
        put(img, tx, ty + 1, N[3])


def _assemble(img, cx, cy, *, squash=1.0, wings=(REST_WING, REST_WING), sway=0.0, droop=0.0):
    """Silhouette -> ink outline -> details. Returns (image, geometry)."""
    geo = _body(img, cx, cy, squash=squash, wings=wings, sway=sway, droop=droop)
    img = auto_outline(img)
    _details(img, geo)
    return img, geo


# ── face (post-outline) ──────────────────────────────────────────────────
def _beak(img, bx, by, mode="closed"):
    """The small gold beak, ink-rimmed so it reads on the cream patch."""
    for ox in range(-2, 3):
        put(img, bx + ox, by - 1, INK)
    put(img, bx - 3, by, INK)
    put(img, bx + 3, by, INK)
    for ox, col in ((-2, G[3]), (-1, G[4]), (0, G[3]), (1, G[2]), (2, G[2])):
        put(img, bx + ox, by, col)
    put(img, bx - 2, by + 1, INK)
    put(img, bx + 2, by + 1, INK)
    if mode == "open":  # chirp: rose gap between the mandibles
        for ox, col in ((-1, ROSE[1]), (0, ROSE[1]), (1, ROSE[0])):
            put(img, bx + ox, by + 1, col)
    else:
        for ox, col in ((-1, G[2]), (0, G[2]), (1, G[1])):
            put(img, bx + ox, by + 1, col)
    put(img, bx - 1, by + 2, INK)
    put(img, bx + 1, by + 2, INK)
    put(img, bx, by + 2, G[1])
    put(img, bx, by + 3, INK)


def _face(img, cx, cy, rx, ry, *, mood="open", look=(0, 0), fdx=0.0, fdy=0.0, beak="closed", cheeks=False):
    """The cream belly/face patch painted straight onto the body (solid core,
    dithered fringe, clipped inside the sphere so the navy rim survives),
    then hero eyes LOW on it, the gold beak, and blush. Returns the eye
    anchor; the beak tip (thread anchor) is at (ex, ey + 9)."""
    px = img.load()
    pcx, pcy = cx + fdx, cy + 2.0 + fdy
    prx, pry = 11.0, 12.0
    for yi in range(int(pcy - pry) - 2, int(pcy + pry) + 3):
        for xi in range(int(pcx - prx) - 2, int(pcx + prx) + 3):
            if not (0 <= xi < G_W and 0 <= yi < G_H):
                continue
            bxn, byn = (xi - cx) / rx, (yi - cy) / ry
            if bxn * bxn + byn * byn > 0.88:
                continue  # keep the navy margin + bottom rim
            nxp, nyp = (xi - pcx) / prx, (yi - pcy) / pry
            rp = nxp * nxp + nyp * nyp
            if rp > 1.30 or (rp > 1.0 and (xi + yi) % 2 == 0):
                continue
            cur = px[xi, yi]
            if cur[3] == 0 or cur[:3] == INK[:3]:
                continue
            tshp = 0.45 * nxp + 0.75 * nyp
            if tshp > 0.55:
                col = C[2]
            elif tshp < -0.55:
                col = C[4]
            else:
                col = C[3]
            px[xi, yi] = col
    ex, ey = int(round(cx + fdx)), int(round(cy - 4 + fdy))
    anime_eye_lg(img, ex - 9, ey, mood=mood, look=look)
    anime_eye_lg(img, ex + 6, ey, mood=mood, look=look)
    _beak(img, ex, ey + 6, beak)
    if cheeks:
        for oy in (5, 6):  # doubled: a soft 2-row blush that reads at 0.33x
            blush(img, ex - 12, ey + oy)
            blush(img, ex + 10, ey + oy)
    return ex, ey


def _tear_rim(img, x, y):
    """Kit tear on an ink backing so it reads on the cream patch."""
    d = ImageDraw.Draw(img)
    d.ellipse((x - 1, int(y) - 1, x + 1, int(y) + 3), fill=INK)
    tear(img, x, y)


# ── props ────────────────────────────────────────────────────────────────
def _thread(img, pts, *, tip=True):
    """The signature beak-thread: 2px violet strand with a cream tip."""
    strand(img, pts, V[1], thick=True)
    for a, b in zip(pts, pts[1:]):  # top-light along each segment
        put(img, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 1, V[2])
    if tip:
        x, y = pts[-1]
        put(img, x, y, C[4])
        put(img, x, y + 1, C[3])


def _weft(img, x0, x1, y):
    """One woven cream weft line with a subtle two-tone twill texture."""
    xi0, xi1 = int(round(min(x0, x1))), int(round(max(x0, x1)))
    for x in range(xi0, xi1 + 1):
        put(img, x, y, C[3] if (x + y) % 3 else C[2])
        if (x + y) % 5 == 0:
            put(img, x, y + 1, C[1])


def _shadow(img, cx, alt):
    """Soft dithered hover shadow on the ground line (never outlined)."""
    prox = 0.55 + 0.45 * max(0.0, 1.0 - max(0.0, alt) / 40.0)
    w = max(5, int(round(15 * prox)))
    d = ImageDraw.Draw(img)
    xi = int(round(cx))
    d.line((xi - w + 2, GROUND, xi + w - 2, GROUND), fill=N[0])
    for x in (xi - w, xi - w + 1, xi + w - 1, xi + w):
        if x % 2 == 0:
            put(img, x, GROUND, N[0])
    for x in range(xi - w + 3, xi + w - 2):
        if x % 2 == 1:
            put(img, x, GROUND + 1, N[0])


# ── choreography ─────────────────────────────────────────────────────────
def draw(state: str, i: int, n: int):
    img = canvas()
    t = i / n
    ph = 2 * math.pi * t

    if state == "idle":
        # Serene hover: wings settle on a lagged beat, thread ripples,
        # slow blink on the last frame.
        cy = HOVER_Y + 2.5 * math.sin(ph)
        squash = 1.0 + 0.02 * math.sin(ph + 0.5)
        wl = (0.22 + 0.10 * math.sin(ph - 0.7), 0.0, 9.0)
        wr = (0.22 + 0.10 * math.sin(ph - 1.1), 0.0, 9.0)
        img, geo = _assemble(img, CX, cy, squash=squash, wings=(wl, wr), sway=1.2 * follow(t, 0.12))
        cx, cyb, rx, ry = geo[:4]
        ex, ey = _face(img, cx, cyb, rx, ry, mood="closed" if i == n - 1 else "open", cheeks=True)
        ax, ay = ex, ey + 9
        _thread(img, [
            (ax - 1, ay),
            (ax - 3, ay + 5 + 0.4 * follow(t, 0.10, 1.2)),
            (ax - 6, ay + 10 + 0.7 * follow(t, 0.22, 2.2)),
            (ax - 9, ay + 14 + follow(t, 0.34, 3.0)),
            (ax - 13, ay + 16 + follow(t, 0.46, 3.6)),
        ])
        _shadow(img, cx, GROUND - (cyb + ry))

    elif state == "running-right":
        # Zips forward leaning in, wings swept back, long thread wake.
        cy = HOVER_Y - 2 + 1.5 * math.sin(2 * ph)
        wl = (0.90 + 0.30 * math.sin(2 * ph), -6.0, 10.0)
        wr = (0.70 + 0.30 * math.sin(2 * ph + 0.8), -5.0, 9.0)
        img, geo = _assemble(img, CX + 4, cy, wings=(wl, wr), sway=-4.5, droop=0.12)
        cx, cyb, rx, ry = geo[:4]
        ex, ey = _face(img, cx, cyb, rx, ry, mood="focused", look=(1, 0), fdx=2.0, fdy=0.5)
        ax, ay = ex, ey + 9
        _thread(img, [
            (ax, ay),
            (ax - 2, ay + 7 + follow(t * 2, 0.08, 1.2)),
            (ax - 8, ay + 11 + follow(t * 2, 0.20, 2.2)),
            (ax - 16, ay + 12 + follow(t * 2, 0.32, 3.2)),
            (ax - 24, ay + 10 + follow(t * 2, 0.44, 4.0)),
        ])
        motion_ticks(img, int(cx - rx - 3), int(cy), 1)
        for k, oy in ((0, -9), (1, 8)):  # two cream speed ticks
            xx = int(cx - rx) - 3 - 3 * ((i + k) % 2)
            for o in range(3):
                put(img, xx - o, cy + oy, C[3])
        _shadow(img, cx, GROUND - (cyb + ry))

    elif state == "waving":
        # Hovers upright and waves the right wing BIG through open air.
        cy = HOVER_Y + bob(t, 1.5)
        wl = (0.25 + 0.10 * math.sin(ph + 2.0), 0.0, 10.0)
        wr = (1.50 + 0.85 * math.sin(ph), 0.0, 13.0)
        img, geo = _assemble(img, CX, cy, wings=(wl, wr), sway=1.5 * follow(t, 0.15))
        cx, cyb, rx, ry = geo[:4]
        ex, ey = _face(img, cx, cyb, rx, ry, mood="happy", beak="open", cheeks=True)
        ax, ay = ex, ey + 9
        _thread(img, [
            (ax - 1, ay),
            (ax - 3, ay + 5 + follow(t, 0.10, 1.8)),
            (ax - 6, ay + 10 + follow(t, 0.24, 2.8)),
            (ax - 10, ay + 14 + follow(t, 0.38, 3.4)),
        ])
        if i == 1:  # glint at the top of the wave
            wtip = geo[4][1][2]
            sparkle(img, int(wtip[0]) + 3, int(wtip[1]) - 3)
        _shadow(img, cx, GROUND - (cyb + ry))

    elif state == "jumping":
        # Joyful loop-de-loop: dips, rises nose-up, sparkles at the apex
        # while the thread spirals below, then settles back onto the hover.
        arc = math.sin(math.pi * i / (n - 1))
        cy = HOVER_Y + 4 - 31 * arc
        wings_by = (
            ((1.15, 0.0, 9.0), 1.08, 1.0, "open", (0, -1), "closed", 0.10),
            ((-0.30, 0.0, 10.0), 0.94, -2.0, "happy", (0, 0), "closed", 0.35),
            ((0.95, 0.0, 11.0), 1.00, -1.0, "happy", (0, 0), "open", 0.0),
            ((1.25, 0.0, 10.0), 1.00, 1.0, "open", (0, 1), "closed", -0.25),
            ((0.45, 0.0, 9.0), 1.06, 0.5, "happy", (0, 0), "closed", 0.05),
        )
        wing, squash, fdy, mood, look, bk, droop = wings_by[i]
        img, geo = _assemble(img, CX, cy, squash=squash, wings=(wing, wing), sway=2 * follow(t, 0.2), droop=droop)
        cx, cyb, rx, ry = geo[:4]
        ex, ey = _face(img, cx, cyb, rx, ry, mood=mood, look=look, fdy=fdy, beak=bk, cheeks=i != 0)
        ax, ay = ex, ey + 9
        wob = follow(t, 0.2, 1.5)
        if i == 0:  # anticipation: the thread coils in tight
            pts = [(ax, ay), (ax, ay + 5), (ax - 3, ay + 9 + wob), (ax - 7, ay + 8 + wob)]
        elif i == 1:  # rise: thread whips straight below
            pts = [(ax, ay), (ax - 1, ay + 7), (ax - 4, ay + 13 + wob), (ax - 5, ay + 19 + wob)]
        elif i == 2:  # apex: the loop-de-loop written in thread
            pts = [(ax, ay)]
            scx, scy = ax - 3, ay + 10
            for k in range(9):
                a = math.pi / 2 + k * math.pi / 4
                pts.append((scx + 6.5 * math.cos(a), scy - 6.5 * math.sin(a) + 0.3 * wob))
        elif i == 3:  # descend: the loop unwinds up behind
            pts = [(ax, ay), (ax + 3, ay - 2), (ax + 7, ay - 6 + wob), (ax + 4, ay - 10 + wob), (ax - 1, ay - 8 + wob)]
        else:  # recover into the idle hang
            pts = [(ax, ay), (ax - 1, ay + 5), (ax - 3, ay + 10 + wob), (ax - 7, ay + 14 + wob)]
        _thread(img, pts)
        if i == 2:
            sparkle(img, int(cx - rx - 5), int(cy - ry + 2))
            sparkle(img, int(cx + rx + 5), int(cy - ry + 6), small=True)
        _shadow(img, cx, GROUND - (cyb + ry))

    elif state == "failed":
        # The hover gives out: flutters down over f0..f3 and LANDS (the only
        # grounded beat in the set) in a ruffled heap, feathers askew, thread
        # tangled around its belly; settled sulk-breathing f4..f7, tear from f3.
        settle = ease_in_out(min(1.0, i / 3))
        squash = 1.0 + 0.16 * settle + (0.015 * math.sin(ph) if i >= 3 else 0.0)
        bot = (HOVER_Y + R) + (GROUND - (HOVER_Y + R)) * settle
        cy = bot - R / squash
        if i == 0:  # both wings flung up in the gasp
            wings = ((1.55, 0.0, 10.0), (1.55, 0.0, 10.0))
        elif i == 1:  # desperate flutter, out of sync
            wings = ((0.25, 0.0, 10.0), (1.35, 0.0, 10.0))
        elif i == 2:
            wings = ((1.30, 0.0, 10.0), (0.20, 0.0, 10.0))
        else:  # crumpled askew: one bent up, one splayed flat
            tw = 0.10 if i == 5 else 0.0
            wings = ((1.05 + tw, -1.0, 9.0), (-0.32, 2.0, 9.0))
        img, geo = _assemble(img, CX, cy, squash=squash, wings=wings, sway=0.8 * follow(t, 0.1), droop=settle)
        cx, cyb, rx, ry = geo[:4]
        if i == 0:
            mood, bk = "open", "open"  # the gasp
        elif i == 1:
            mood, bk = "open", "closed"
        else:
            mood, bk = "sad", "closed"
        ex, ey = _face(img, cx, cyb, rx, ry, mood=mood, look=(0, 1), beak=bk, fdy=0.5 * settle)
        ax, ay = ex, ey + 9
        if i < 3:  # the thread streams up beside its head as it drops
            f1, f2 = follow(t, 0.10, 1.5), follow(t, 0.25, 2.5)
            pts = [(ax, ay), (ax + 5, ay - 2), (ax + 10, ay - 7 + f1), (ax + 13, ay - 13 + f2), (ax + 12, ay - 18 + f2)]
        else:  # tangled around the belly, loose end limp on the ground
            sag = follow(t, 0.15, 0.8)
            pts = [
                (ax, ay + 1),
                (cx - rx + 3, cyb + ry - 6 + 0.4 * sag),
                (cx + rx - 3, cyb + ry - 8),
                (cx - rx + 2, cyb + ry - 3 + 0.5 * sag),
                (cx + rx - 2, cyb + ry - 5),
                (cx + rx + 6, GROUND - 1),
                (cx + rx + 11, GROUND - 1 + 0.5 * sag),
            ]
        _thread(img, pts)
        if 1 <= i <= 3:  # loose feathers shaken off the flutter
            for fx, fy in ((cx - 19, cyb - 12 + 4 * i), (cx + 17, cyb - 16 + 5 * i)):
                put(img, fx, fy, N[3])
                put(img, fx + 1, fy, N[3])
                put(img, fx + 1, fy - 1, C[3])
        sweat_drop(img, int(cx + 0.42 * rx), cyb - ry - 3 + 6 * t)
        if i >= 3:  # a single tear slides from the right eye
            _tear_rim(img, ex + 9, ey + 7 + min(i - 3, 3))
        _shadow(img, cx, GROUND - (cyb + ry))

    elif state == "waiting":
        # Head-tilted hover; the beak-thread curls into a question hook
        # right under the twinkling gold dot. Blink on the last frame.
        cy = HOVER_Y + bob(t, 1.5)
        wl = (0.20 + 0.08 * math.sin(ph - 0.5), 0.0, 9.0)
        wr = (0.30 + 0.08 * math.sin(ph - 0.9), 0.0, 9.0)
        img, geo = _assemble(img, CX, cy, wings=(wl, wr), sway=2.5)
        cx, cyb, rx, ry = geo[:4]
        ex, ey = _face(
            img, cx, cyb, rx, ry,
            mood="closed" if i == n - 1 else "open", look=(1, -1), fdx=1.5, cheeks=True,
        )
        ax, ay = ex, ey + 9
        wob = follow(t, 0.2, 1.2)
        _thread(img, [
            (ax, ay),
            (ax + 6, ay + 4),
            (ax + 12, ay + 2 + 0.3 * wob),
            (ax + 16, ay - 3 + 0.6 * wob),
            (ax + 18 + wob, ay - 9),
            (ax + 15 + wob, ay - 14),
            (ax + 11 + wob, ay - 12),
        ])
        put(img, ax + 17, ay + 7, V[1])  # the question's dot
        attention_dot(img, int(cx + 16), cy - ry - 9 + bob(t, 1.2), t=t)
        _shadow(img, cx, GROUND - (cyb + ry))

    elif state == "running":
        # Focused work — WEAVING: tight left-right shuttle passes that lay
        # cream weft lines onto the cloth accumulating below (f5 ends where
        # f0 begins, so the sweep loops seamlessly).
        k, step = i // 3, i % 3
        frac = (step + 0.5) / 3.0
        ltr = k == 0
        edge = 16
        y_line = 89 if ltr else 85
        tipx = (CX - edge + frac * 2 * edge) if ltr else (CX + edge - frac * 2 * edge)
        dirx = 1 if ltr else -1
        bx_ = max(CX - 13.0, min(CX + 13.0, tipx))
        cy = 62 + 1.2 * math.sin(2 * ph)
        wl = (0.75 + 0.25 * math.sin(4 * math.pi * t), -dirx * 3.0, 9.0)
        wr = (0.75 + 0.25 * math.sin(4 * math.pi * t + 1.2), -dirx * 3.0, 9.0)
        img, geo = _assemble(img, bx_, cy, wings=(wl, wr), sway=-dirx * 3.0)
        cx, cyb, rx, ry = geo[:4]
        ex, ey = _face(img, cx, cyb, rx, ry, mood="focused", look=(dirx, 1), fdx=1.5 * dirx, fdy=1.0)
        _weft(img, CX - edge, CX + edge, 93)  # finished cloth
        if not ltr:
            _weft(img, CX - edge, CX + edge, 89)  # the pass laid last loop-half
        if ltr:
            _weft(img, CX - edge, tipx, y_line)  # the growing pass
        else:
            _weft(img, tipx, CX + edge, y_line)
        ax, ay = ex, ey + 9
        _thread(
            img,
            [(ax, ay), ((ax + tipx) / 2 - dirx * 2 + follow(t, 0.2, 2.0), (ay + y_line) / 2 + 1), (tipx, y_line - 1)],
            tip=False,
        )
        put(img, tipx, y_line, G[3])  # the working stitch
        put(img, tipx, y_line - 1, G[4])
        motion_ticks(img, int(cx - dirx * (rx + 3)), int(cy), dirx)
        _shadow(img, cx, GROUND - (cyb + ry))

    elif state == "review":
        # Hovers still over the fresh cloth, tracking the newest weft line
        # with eyes + a head turn; approving nod on the last frame.
        nod = i == n - 1
        scan = ease_in_out(min(1.0, i / (n - 2)))
        cy = 62 + (2.5 if nod else 0.8 * math.sin(ph))
        fdx = 0.0 if nod else -2.0 + 4.0 * scan
        wl = (0.22 + 0.07 * math.sin(ph - 0.6), 0.0, 9.0)
        wr = (0.22 + 0.07 * math.sin(ph - 1.0), 0.0, 9.0)
        img, geo = _assemble(img, CX, cy, wings=(wl, wr), sway=1.5 * follow(t, 0.22) - 0.8 * fdx)
        cx, cyb, rx, ry = geo[:4]
        for y_line in (85, 89, 93):
            _weft(img, CX - 16, CX + 16, y_line)
        gx = int(round(CX - 14 + 28 * scan))
        put(img, gx, 85, G[3])  # gold stitch riding the newest line
        put(img, gx, 84, G[4])
        if nod:
            ex, ey = _face(img, cx, cyb, rx, ry, mood="happy", beak="open", cheeks=True)
        else:
            look_x = max(-1, min(1, int(round(-1 + 2 * scan))))
            ex, ey = _face(img, cx, cyb, rx, ry, mood="focused", look=(look_x, 1), fdx=fdx, fdy=0.5)
        ax, ay = ex, ey + 9
        _thread(img, [
            (ax - 1, ay),
            (ax - 3, ay + 5 + 0.5 * follow(t, 0.12, 1.0)),
            (ax - 6, ay + 9 + follow(t, 0.26, 1.8)),
            (ax - 9, ay + 12 + follow(t, 0.40, 2.4)),
        ])
        _shadow(img, cx, GROUND - (cyb + ry))

    else:  # pragma: no cover - unknown states fall back to a static hover
        img, geo = _assemble(img, CX, HOVER_Y)
        cx, cyb, rx, ry = geo[:4]
        ex, ey = _face(img, cx, cyb, rx, ry)
        _thread(img, [(ex, ey + 9), (ex - 3, ey + 14), (ex - 8, ey + 17)])
        _shadow(img, cx, GROUND - (cyb + ry))

    return img
