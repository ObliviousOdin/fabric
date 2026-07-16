"""Skein — the yarn cat. The set's cutest member (avatar style contract v2).

A round ball-of-yarn kitten: a sphere of brand-violet yarn with curved
winding arcs crossing at angles, two triangular cat ears with rose inner
flaps, and a loose yarn-strand tail with a cream tip. The face sits right
on the ball's lighter sheen patch — solid-ink hero eyes, a tiny :3 mouth,
permanent blush. Rolls instead of runs, kneads instead of types. The tail
is Skein's emotion appendage: it lags, whips, hooks, and unwinds.
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
    shade_ellipse,
    sparkle,
    strand,
    sweat_drop,
    tear,
)

NAME = "Skein"
SLUG = "skein"
DESCRIPTION = "A ball-of-yarn kitten that rolls everywhere it goes."

V = RAMPS["violet"]
C = RAMPS["cream"]
G = RAMPS["gold"]
ROSE = RAMPS["rose"]

R = 21  # yarn-ball radius at rest (half-res px)


# ── body ─────────────────────────────────────────────────────────────────
def _ear_geo(cx, cy, rx, ry, mode="up", twitch=(0, 0), tw_side=-1, amt=1.0):
    """Two ear triangles (base-inner, base-outer, tip) sitting on the ball.

    *amt* lerps the tip from upright (0.0) to the mode's target (1.0), so
    ears can wilt or sweep progressively instead of snapping between poses.
    """
    ears = []
    for side in (-1, 1):
        bi = (cx + side * 0.20 * rx, cy - 0.975 * ry + 2)
        bo = (cx + side * 0.66 * rx, cy - 0.72 * ry + 2)
        up = (cx + side * 0.60 * rx, cy - ry - 7)
        if mode == "back":  # swept down/out on the rise
            tgt = (cx + side * (0.60 * rx + 7), cy - ry + 1)
        elif mode == "droop":  # flat sideways dejection
            tgt = (cx + side * (0.66 * rx + 8), cy - 0.40 * ry)
        elif mode == "trail":  # streaming upward while the ball falls
            tgt = (cx + side * 0.42 * rx, cy - ry - 11)
        else:  # upright
            tgt = up
        tip = (up[0] + (tgt[0] - up[0]) * amt, up[1] + (tgt[1] - up[1]) * amt)
        if side == tw_side and twitch != (0, 0):
            tip = (tip[0] + twitch[0], tip[1] + twitch[1])
        ears.append((bi, bo, tip))
    return ears


def _body(img, dy, squash, *, lean=0.0, ear_mode="up", ear_twitch=(0, 0), tw_side=-1, ear_amt=1.0):
    """Ball anchored to the ground (bottom = GROUND + dy). Returns geometry."""
    d = ImageDraw.Draw(img)
    rx, ry = R * squash, R / squash
    cx = CX + lean
    bot = GROUND + dy
    cy = bot - ry
    shade_ellipse(img, (cx - rx, cy - ry, cx + rx, cy + ry), "violet")
    ears = _ear_geo(cx, cy, rx, ry, ear_mode, ear_twitch, tw_side, ear_amt)
    for tri in ears:
        d.polygon(tri, fill=V[2])
    return cx, cy, rx, ry, ears


# ── details (post-outline) ───────────────────────────────────────────────
def _windings(img, cx, cy, rx, ry, rot=0.0):
    """Two families of chunky yarn arcs crossing at angles; *rot* rolls them.

    Each strand is 2px thick and lit in place: indigo where it dips into the
    low-right shadow, warm-light where it crests the high-left cap — so the
    winding itself carries the sphere's volume.
    """
    fams = (
        (0.62, (V[0], V[1], V[2]), (0.44, 0.84)),
        (-0.52, (V[1], V[3], V[4]), (0.62,)),
    )
    for phi, (dark, base, lit), minors in fams:
        th = phi + rot
        c, s = math.cos(th), math.sin(th)
        for b in minors:
            for k in range(150):
                u = 2 * math.pi * k / 150
                ux, uy = 0.90 * math.cos(u), b * math.sin(u)
                wx, wy = ux * c - uy * s, ux * s + uy * c
                shade = 0.62 * wx + 0.78 * wy  # + toward the low-right shadow
                col = dark if shade > 0.42 else (lit if shade < -0.50 else base)
                x, y = cx + wx * rx, cy + wy * ry
                put(img, x, y, col)
                put(img, x + 1, y, col)
                put(img, x, y + 1, col)
                put(img, x + 1, y + 1, col)


def _details(img, cx, cy, rx, ry, ears, *, rot=0.0):
    """Winding arcs + rose inner ears + deep rim inside the bottom outline."""
    d = ImageDraw.Draw(img)
    _windings(img, cx, cy, rx, ry, rot)
    # Deep indigo rim, low-right, just inside the outline.
    d.arc((cx - rx + 1, cy - ry + 1, cx + rx - 1, cy + ry - 1), 20, 115, fill=V[0])
    d.arc((cx - rx + 2, cy - ry + 2, cx + rx - 2, cy + ry - 2), 40, 100, fill=V[0])
    # Ears: rose inner flap + a lit left edge / shaded right edge.
    for bi, bo, tp in ears:
        gx = (bi[0] + bo[0] + tp[0]) / 3
        gy = (bi[1] + bo[1] + tp[1]) / 3
        inner = [(p[0] + 0.45 * (gx - p[0]), p[1] + 0.45 * (gy - p[1])) for p in (bi, bo, tp)]
        d.polygon(inner, fill=ROSE[3])
        d.line((bi, tp), fill=V[3])
        d.line((bo, tp), fill=V[1])


def _cat_mouth(img, x, y):
    """Tiny :3 — the kitten omega mouth."""
    put(img, x - 2, y, INK)
    put(img, x - 1, y + 1, INK)
    put(img, x, y, INK)
    put(img, x + 1, y + 1, INK)
    put(img, x + 2, y, INK)


def _face(img, cx, cy, ry, *, mood="open", look=(0, 0), mstyle="cat", cheeks=False):
    """Face directly on the ball: a soft lighter patch with a dithered fringe
    (no hard porcelain plate), then hero eyes / :3 mouth / blush on top.

    The V[3] sheen patch is the ball's lit region — the solid-ink
    :func:`anime_eye_lg` eyes separate cleanly against it."""
    d = ImageDraw.Draw(img)
    cx = int(round(cx))
    ey = int(round(cy - 0.48 * ry))
    # Dithered fringe one px beyond the solid patch so the edge melts in.
    px = img.load()
    for y in range(ey - 5, ey + 12):
        for x in range(cx - 15, cx + 16):
            if (x + y) % 2 and 0 <= x < img.width and 0 <= y < img.height:
                nx, ny = (x - cx) / 15.5, (y - (ey + 3.0)) / 8.5
                if nx * nx + ny * ny <= 1.0 and px[x, y][3] != 0:
                    px[x, y] = V[3]
    d.ellipse((cx - 14, ey - 4, cx + 14, ey + 10), fill=V[3])
    anime_eye_lg(img, cx - 11, ey, mood=mood, look=look)
    anime_eye_lg(img, cx + 8, ey, mood=mood, look=look)
    if mstyle == "cat":
        _cat_mouth(img, cx, ey + 7)
    else:
        mouth(img, cx, ey + 7, mstyle)
    if cheeks:
        blush(img, cx - 14, ey + 6)
        blush(img, cx + 12, ey + 6)
    return ey


def _tail(img, pts, *, tip=True):
    """Loose 2px yarn strand with a cream-tipped end."""
    strand(img, pts, V[1], thick=True)
    for a, b in zip(pts, pts[1:]):  # top-light along each segment
        put(img, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 1, V[2])
    if tip:
        x, y = pts[-1]
        put(img, x, y, C[4])
        put(img, x, y + 1, C[3])


def _paw(img, x, y):
    """A round yarn mitten with a rose pad and a lit crown."""
    d = ImageDraw.Draw(img)
    d.ellipse((x - 3, y - 3, x + 3, y + 2), fill=V[3], outline=INK)
    put(img, x - 1, y - 2, V[4])
    put(img, x, y - 1, ROSE[3])
    put(img, x - 1, y - 1, ROSE[3])


# ── choreography ─────────────────────────────────────────────────────────
def draw(state: str, i: int, n: int):
    img = canvas()
    t = i / n
    ph = 2 * math.pi * t

    if state == "idle":
        squash = 1.0 + 0.035 * math.sin(ph)
        tw = (2, -2) if i == 2 else ((1, -1) if i == 3 else (0, 0))
        cx, cy, rx, ry, ears = _body(img, 0, squash, ear_twitch=tw, tw_side=-1)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, ears)
        sway = 2.5 * math.sin(ph)
        lag = 2.5 * follow(t, 0.18)
        ax, ay = cx - rx + 3, cy + 0.45 * ry
        _tail(
            img,
            [
                (ax, ay),
                (ax - 5, ay + 4 + 0.5 * sway),
                (ax - 10, ay + 7 + 0.8 * lag),
                (ax - 15, ay + 5 + lag),
                (ax - 17, ay + 1 + 0.7 * lag),
            ],
        )
        _face(img, cx, cy, ry, mood="closed" if i == n - 1 else "open", cheeks=True)

    elif state == "running-right":
        bounce = abs(math.sin(ph))
        cx, cy, rx, ry, ears = _body(img, -3.5 * ease_out(bounce), 1.0 + 0.08 * (1 - bounce), lean=3)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, ears, rot=2 * math.pi * t)
        whip = follow(t * 2, 0.2, 3)
        ax, ay = cx - rx + 2, cy
        _tail(img, [(ax, ay), (ax - 7, ay - 4 + whip), (ax - 14, ay - 3 - whip), (ax - 19, ay - 1 + 0.5 * whip)])
        motion_ticks(img, int(cx - rx - 3), int(cy), 1)
        _face(img, cx, cy, ry, mood="focused", look=(1, 0), mstyle="line")

    elif state == "waving":
        cx, cy, rx, ry, ears = _body(img, 0, 1.0)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, ears)
        # Paw pops out of the ball's right side and arcs up in open air.
        sweep = ease_in_out(0.5 + 0.5 * math.sin(math.pi * (2 * t - 0.5)))
        ang = math.pi * (0.02 + 0.50 * sweep)
        pvx, pvy = cx + rx - 4, cy + 1
        px_, py_ = pvx + 12 * math.cos(ang), pvy - 14 * math.sin(ang)
        strand(img, [(pvx, pvy), ((pvx + px_) / 2 + 1, (pvy + py_) / 2 + 1), (px_, py_)], V[3], thick=True)
        _paw(img, int(px_), int(py_))
        ax, ay = cx - rx + 3, cy + 0.45 * ry
        lag = 3 * follow(t, 0.1)
        _tail(img, [(ax, ay), (ax - 6, ay + 2 - 2 * sweep), (ax - 11, ay + 4 - lag)])
        _face(img, cx, cy, ry, mood="happy", mstyle="open", cheeks=True)

    elif state == "jumping":
        # Symmetric arc peaked at the MIDDLE frame: f0 grounded crouch,
        # f1 rise (stretch, ears swept back), f2 apex (floaty + sparkle),
        # f3 descend (ears trailing up, eyes on the ground), f4 GROUNDED
        # landing squash with ear/tail follow-through — lands into f0.
        arc = math.sin(math.pi * i / (n - 1))
        if i == 0:  # anticipation crouch, ears half-pressed
            squash, dy, mode, amt = 1.22, 0.0, "back", 0.35
        elif i == 1:  # rise: stretched tall, ears fully swept back
            squash, dy, mode, amt = 0.90, -17 * arc, "back", 1.0
        elif i == 2:  # apex: hang-time, round again, ears floating up
            squash, dy, mode, amt = 0.96, -17 * arc, "trail", 0.3
        elif i == 3:  # descend: ears stream upward as the ball falls
            squash, dy, mode, amt = 1.02, -17 * arc, "trail", 1.0
        else:  # grounded landing squash, ears still recovering
            squash, dy, mode, amt = 1.15, 0.0, "back", 0.55
        cx, cy, rx, ry, ears = _body(img, dy, squash, ear_mode=mode, ear_amt=amt)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, ears, rot=0.35 * arc)
        # Tail follow-through: tucked in the crouch, dragging below on the
        # rise, level at the apex, whipped up on the descend, splayed along
        # the ground on the landing (so it flows back into f0's tuck).
        ax, ay = cx - rx + 3, cy + 0.45 * ry
        wob = follow(t, 0.2, 1.5)
        tail_pts = (
            [(ax, ay), (ax - 5, ay + 6), (ax - 9, ay + 9 + wob)],
            [(ax, ay), (ax - 4, ay + 8), (ax - 6, ay + 14 + wob)],
            [(ax, ay), (ax - 6, ay + 5), (ax - 11, ay + 6 + wob)],
            [(ax, ay), (ax - 5, ay - 2), (ax - 8, ay - 8 + wob)],
            [(ax, ay), (ax - 7, ay + 6), (ax - 13, ay + 8 + wob)],
        )
        _tail(img, tail_pts[i])
        if i == 2:  # apex glint only — the float beat
            sparkle(img, int(cx - rx - 4), int(cy - ry - 2))
            sparkle(img, int(cx + rx + 4), int(cy - ry + 4), small=True)
        moods = ("focused", "happy", "happy", "open", "happy")
        msts = ("line", "open", "open", "open", "smile")
        _face(
            img,
            cx,
            cy,
            ry,
            mood=moods[i],
            look=(0, 1) if i == 3 else (0, 0),
            mstyle=msts[i],
            cheeks=i != 0,
        )

    elif state == "failed":
        # Progressive come-apart over f0..f3 — the ball deflates flat, the
        # ears wilt from upright to draped, a strand pulls loose along the
        # ground — then settled sulk-breathing f4..f7 (amp <= 1px), ending
        # in a holdable slump. A tear wells up from f3.
        settle = ease_in_out(min(1.0, i / 3))
        squash = 1.0 + 0.30 * settle + 0.02 * math.sin(ph)
        tw = (0, 1) if i in (4, 6) else (0, 0)  # tiny ear-tip sag beats
        cx, cy, rx, ry, ears = _body(img, 0, squash, ear_mode="droop", ear_amt=settle, ear_twitch=tw, tw_side=1)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, ears, rot=-0.10 * settle + 0.03 * math.sin(ph))
        # The pulled-loose strand unwinds further with every slump frame.
        zx = cx + rx - 3
        sag = follow(t, 0.1, 0.8)
        pts = [(zx, GROUND - 2.0)]
        for k in range(2 + int(round(2 * settle))):
            pts.append((zx + 4 * (k + 1), GROUND - (5 if k % 2 == 0 else 1) + (sag if k % 2 else -sag)))
        _tail(img, pts)
        sweat_drop(img, int(cx + 0.45 * rx), cy - ry - 3 + 6 * t)
        if i == 0:  # the gasp before the slump
            ey = _face(img, cx, cy, ry, mood="open", mstyle="open")
        elif i == 1:
            ey = _face(img, cx, cy, ry, mood="open", look=(0, 1), mstyle="wobble")
        else:
            ey = _face(img, cx, cy, ry, mood="sad", look=(0, 1), mstyle="wobble")
        if i >= 3:  # a single tear slides from the right eye
            tear(img, int(cx) + 9, ey + 7 + (i - 3))

    elif state == "waiting":
        squash = 1.0 + 0.02 * math.sin(ph)
        cx, cy, rx, ry, ears = _body(img, 0, squash)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, ears)
        # Tail curls UP into a question-hook beside the left ear, its curl
        # swaying with a lagged wobble.
        ax, ay = cx - rx + 2, cy + 2
        wob = follow(t, 0.15, 1.0)
        _tail(
            img,
            [(ax, ay), (ax - 5, ay - 8), (ax - 7 + wob, ay - 16), (ax - 3 + wob, ay - 21), (ax + 2 + wob, ay - 17), (ax + wob, ay - 13)],
        )
        put(img, ax - 3, ay - 6, V[1])
        attention_dot(img, int(cx + 7), cy - ry - 11 + bob(t, 1.2), t=t)
        _face(img, cx, cy, ry, mood="closed" if i == n - 1 else "open", look=(1, -1), mstyle="cat")

    elif state == "running":  # kneading in place — focused work
        press = math.sin(2 * ph)
        squash = 1.0 + 0.05 * abs(press)
        cx, cy, rx, ry, ears = _body(img, 0, squash)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, ears, rot=0.08 * press)
        lift_l = 5 * ease_out(max(0.0, press))
        lift_r = 5 * ease_out(max(0.0, -press))
        _paw(img, int(cx - 9), int(GROUND - 3 - lift_l))
        _paw(img, int(cx + 9), int(GROUND - 3 - lift_r))
        # Tail swishes double-time behind, counter to the knead beat.
        ax, ay = cx - rx + 3, cy + 0.45 * ry
        swish = follow(t * 2, 0.25, 2.0)
        _tail(img, [(ax, ay), (ax - 5, ay + 4 + swish), (ax - 10, ay + 6 - swish), (ax - 14, ay + 4 + 0.5 * swish)])
        look_x = -1 if press > 0.1 else (1 if press < -0.1 else 0)
        _face(img, cx, cy, ry, mood="focused", look=(look_x, 1), mstyle="line")

    elif state == "review":
        cx, cy, rx, ry, ears = _body(img, 0, 1.0)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, ears)
        # A strand held taut between two paw nubs; eyes read along it.
        tri = 1.0 - abs(2 * t - 1.0)
        scan = ease_in_out(tri)
        sy = int(cy + 0.35 * ry)
        strand(img, [(cx - 10, sy - 1), (cx + 10, sy - 1)], C[3])
        _paw(img, int(cx - 13), sy)
        _paw(img, int(cx + 13), sy)
        # Tail rests curled at the left, drifting with a slow lag.
        ax, ay = cx - rx + 3, cy + 0.45 * ry
        drift = follow(t, 0.18, 1.5)
        _tail(img, [(ax, ay), (ax - 5, ay + 5 + 0.5 * drift), (ax - 10, ay + 8 + drift), (ax - 15, ay + 6 + 0.7 * drift)])
        gx = int(cx - 9 + 18 * scan)
        put(img, gx, sy - 1, G[3])
        put(img, gx, sy - 2, G[4])
        look_x = max(-1, min(1, int(round(-1 + 2 * scan))))
        _face(img, cx, cy, ry, mood="focused", look=(look_x, 1), mstyle="line")

    else:  # pragma: no cover - unknown states fall back to a static body
        cx, cy, rx, ry, ears = _body(img, 0, 1.0)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, ears)
        _face(img, cx, cy, ry)

    return img
