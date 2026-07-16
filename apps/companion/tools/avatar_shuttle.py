"""Shuttle — the loom-shuttle sprite. The set's speedster (v2 style).

A sleek hovering weaving shuttle seen side-on: a pointed navy lozenge hull
(indigo keel low, steel light top) with a violet belly stripe, a small violet
dorsal fin, gold rivets, and ONE big anime porthole eye near the nose — a
round cream window with a violet iris, ink pupil and double glint. A violet
thread streams from the tail and ripples with follow-through: its signature.
The only Fabric avatar that never touches the ground — it floats on a smooth
bob above a soft dithered shadow.
"""

from __future__ import annotations

import math

from PIL import ImageDraw

from avatar_kit import (
    CX,
    GROUND,
    INK,
    RAMPS,
    attention_dot,
    auto_outline,
    blush,
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
)

NAME = "Shuttle"
SLUG = "shuttle"
DESCRIPTION = "A sleek hovering loom shuttle trailing a violet thread."

V = RAMPS["violet"]
N = RAMPS["navy"]
C = RAMPS["cream"]
G = RAMPS["gold"]

# Hull geometry (half-res px): pointed lozenge ~50w x 19h, hover center y=70.
L = 25  # half-length along the axis
HMAX = 9.5  # half-thickness at the middle
HOVER_Y = 70


def _pt(cx: float, cy: float, ang: float, u: float, v: float):
    """Hull-local (u along axis toward nose, v toward belly) -> screen."""
    ca, sa = math.cos(ang), math.sin(ang)
    return (cx + u * ca - v * sa, cy + u * sa + v * ca)


def _half(u: float) -> float:
    """Half-thickness of the hull at axis position u (pointed tips)."""
    return max(0.7, HMAX * (1.0 - (abs(u) / L) ** 1.4))


def _body(img, cx: float, cy: float, ang: float, fin: float = 0.0):
    """Silhouette: dorsal fin then the lozenge hull (base fill only)."""
    d = ImageDraw.Draw(img)
    # Dorsal fin — a violet triangle just behind the middle; ``fin`` in
    # [-1, 1] flaps the tip (up = tall, down = folded).
    tip_u = -4.0 + 2.5 * fin
    tip_h = _half(tip_u) + 5.5 + 3.5 * fin
    p_rear = _pt(cx, cy, ang, -9.5, -(_half(-9.5) - 1.5))
    p_front = _pt(cx, cy, ang, 0.5, -(_half(0.5) - 1.5))
    p_tip = _pt(cx, cy, ang, tip_u, -tip_h)
    d.polygon([p_rear, p_front, p_tip], fill=V[2])
    # Hull: stacked discs along the axis make the pointed lozenge.
    u = -L
    while u <= L:
        r = _half(u)
        x, y = _pt(cx, cy, ang, u, 0)
        d.ellipse((x - r, y - r, x + r, y + r), fill=N[2])
        u += 0.5
    return p_rear, p_front, p_tip


def _paint_hull(img, cx: float, cy: float, ang: float):
    """Per-pixel ramp shader over the base fill: steel light top, navy body,
    violet belly stripe, indigo keel rim — with dithered seams throughout.
    Runs after auto_outline; touches only base-fill (N[2]) pixels."""
    ca, sa = math.cos(ang), math.sin(ang)
    px = img.load()
    rad = int(L + 3)
    x0, x1 = max(0, int(cx) - rad), min(96, int(cx) + rad + 1)
    y0, y1 = max(0, int(cy) - rad), min(104, int(cy) + rad + 1)
    base = N[2]
    for y in range(y0, y1):
        for x in range(x0, x1):
            if px[x, y] != base:
                continue
            rx, ry = x - cx, y - cy
            u = rx * ca + ry * sa
            v = -rx * sa + ry * ca
            if abs(u) > L:
                continue
            h = _half(u)
            if abs(v) > h + 0.9:
                continue
            f = v / h + (0.045 if (x + y) % 2 else -0.045)  # dithered seams
            if v > h - 1.6:
                col = N[0]  # deep keel rim just inside the bottom outline
            elif f < -0.60:
                # top light — warm cream streak toward the high-left rear
                col = C[2] if (f < -0.84 and -15 <= u <= -4) else N[4]
            elif f < -0.26:
                col = N[3]
            elif f < 0.30:
                col = N[2]
            elif f < 0.42:
                col = V[3]  # belly stripe, lit edge
            elif f < 0.66:
                col = V[2]
            elif f < 0.78:
                col = V[1]
            elif f < 0.92:
                col = N[1]
            else:
                col = N[0]
            px[x, y] = col


def _details(img, cx: float, cy: float, ang: float, fin_pts) -> None:
    """Post-shader accents: fin ramp edges + gold rivets along the hull."""
    p_rear, p_front, p_tip = fin_pts
    strand(img, [p_front, p_tip], V[3])
    strand(img, [p_rear, p_tip], V[1])
    put(img, p_tip[0], p_tip[1], V[4])
    for u in (-20, -14, 2):
        x, y = _pt(cx, cy, ang, u, -0.5)
        put(img, x, y, G[3])
        put(img, x, y + 1, G[1])


def _eye(img, cx: float, cy: float, ang: float, mood: str = "open", look=(0, 0), lid: float = 0.0):
    """The big cyclops porthole: cream window, violet iris, double glint.
    ``lid`` in [0, 1] slides a navy eyelid down (1 = blink)."""
    d = ImageDraw.Draw(img)
    ex, ey = (int(round(c)) for c in _pt(cx, cy, ang, 11, -0.5))
    r = 5
    d.ellipse((ex - r, ey - r, ex + r, ey + r), fill=C[3], outline=INK)
    d.arc((ex - r + 1, ey - r + 1, ex + r - 1, ey + r - 1), 150, 245, fill=C[4])
    if mood == "happy":
        d.arc((ex - 4, ey - 2, ex + 4, ey + 5), 180, 360, fill=INK)
        return
    if lid >= 1.0:  # full blink: soft lash arc on the porcelain lid
        d.ellipse((ex - r + 1, ey - r + 1, ex + r - 1, ey + r - 1), fill=C[2])
        d.arc((ex - 4, ey - 4, ex + 4, ey + 4), 15, 165, fill=INK)
        d.ellipse((ex - r, ey - r, ex + r, ey + r), outline=INK)
        return
    dx, dy = look
    ix, iy = ex + dx, ey + dy
    d.ellipse((ix - 2, iy - 2, ix + 2, iy + 2), fill=V[1])
    d.ellipse((ix - 2, iy - 2, ix + 1, iy + 1), fill=V[2])
    d.rectangle((ix - 1, iy - 1, ix, iy), fill=INK)
    put(img, ix - 1, iy - 2, C[4])  # double glint — the anime soul
    put(img, ix, iy - 2, C[4])
    put(img, ix + 1, iy + 1, C[3])
    if lid > 0:  # porcelain eyelid slides down over the window
        cov = int(round(lid * 2 * r))
        for row in range(cov):
            yy = ey - r + row
            half = int(math.sqrt(max(0, r * r - (yy - ey) ** 2)))
            d.line((ex - half, yy, ex + half, yy), fill=C[1])
        yy = ey - r + cov
        half = int(math.sqrt(max(0, r * r - (yy - ey) ** 2)))
        d.line((ex - half, yy, ex + half, yy), fill=INK)
        d.ellipse((ex - r, ey - r, ex + r, ey + r), outline=INK)


def _thread(img, pts) -> None:
    """The signature violet thread wake, with a lit fleck and cream tip."""
    strand(img, pts, V[1])
    if len(pts) > 2:
        mx, my = pts[len(pts) // 2]
        put(img, mx, my, V[3])
    tx, ty = pts[-1]
    put(img, tx, ty, C[4])


def _shadow(img, cx: float, gap: float, footprint: float) -> None:
    """Soft dithered hover shadow on the ground line (never outlined)."""
    prox = 0.55 + 0.45 * max(0.0, 1.0 - gap / 45.0)
    w = max(4, int(round(footprint * 0.5 * prox)))
    xi = int(round(cx))
    d = ImageDraw.Draw(img)
    d.line((xi - w + 2, 100, xi + w - 2, 100), fill=N[0])
    for x in (xi - w, xi - w + 1, xi + w - 1, xi + w):
        if x % 2 == 0:
            put(img, x, 100, N[0])
    for x in range(xi - w + 3, xi + w - 2):
        if x % 2 == 1:
            put(img, x, 101, N[0])


def _assemble(img, cx, cy, ang, fin=0.0):
    """Body -> outline -> shader -> details. Returns the outlined image."""
    fin_pts = _body(img, cx, cy, ang, fin)
    img = auto_outline(img)
    _paint_hull(img, cx, cy, ang)
    _details(img, cx, cy, ang, fin_pts)
    return img


def _footprint(ang: float) -> float:
    return L * abs(math.cos(ang)) + HMAX * abs(math.sin(ang))


def draw(state: str, i: int, n: int):
    img = canvas()
    t = i / n
    ph = 2 * math.pi * t

    if state == "idle":
        cy = HOVER_Y + 3 * math.sin(ph)
        ang = 0.05 * math.sin(ph + 0.9)
        cx = CX
        img = _assemble(img, cx, cy, ang, fin=0.15 * math.sin(ph))
        tx, ty = _pt(cx, cy, ang, -L, 0)
        _thread(img, [
            (tx, ty),
            (tx - 5, ty + 1 + follow(t, 0.10, 1.8)),
            (tx - 10, ty + 1 + follow(t, 0.22, 2.8)),
            (tx - 15, ty + follow(t, 0.34, 3.6)),
            (tx - 19, ty + follow(t, 0.46, 4.0)),
        ])
        _eye(img, cx, cy, ang, look=(1, 0), lid=1.0 if i == n - 1 else 0.0)
        bx, by = _pt(cx, cy, ang, 4, 2.6)
        blush(img, int(bx), int(by))
        _shadow(img, cx, GROUND - (cy + HMAX), _footprint(ang) * 2)

    elif state == "running-right":
        cx = CX + 5
        cy = HOVER_Y - 1 + 2 * math.sin(2 * ph)
        ang = 0.20  # nose tilts down-forward
        img = _assemble(img, cx, cy, ang, fin=-0.2)
        tx, ty = _pt(cx, cy, ang, -L, 0)
        _thread(img, [
            (tx, ty),
            (tx - 7, ty - 1 + follow(t * 2, 0.10, 2.2)),
            (tx - 14, ty - 2 + follow(t * 2, 0.22, 3.2)),
            (tx - 21, ty - 3 + follow(t * 2, 0.34, 4.2)),
            (tx - 26, ty - 3 + follow(t * 2, 0.46, 4.8)),
        ])
        motion_ticks(img, int(tx) - 2, int(cy), 1)
        for k, oy in ((0, -8), (1, 7)):  # cream speed ticks
            xx = int(tx) - 4 - 3 * ((i + k) % 2)
            for o in range(3):
                put(img, xx - o, cy + oy, C[3])
        _eye(img, cx, cy, ang, look=(2, 0))
        _shadow(img, cx, GROUND - (cy + 12), _footprint(ang) * 2)

    elif state == "waving":
        cx = CX
        cy = HOVER_Y + bob(t, 1.5)
        ang = -0.14  # tilts back amiably
        flap = 2.0 * ease_in_out(0.5 + 0.5 * math.sin(ph)) - 1.0
        img = _assemble(img, cx, cy, ang, fin=flap)
        tx, ty = _pt(cx, cy, ang, -L, 0)
        _thread(img, [
            (tx, ty),
            (tx - 6, ty + 2 + follow(t, 0.12, 1.6)),
            (tx - 12, ty + 3 + follow(t, 0.24, 2.4)),
            (tx - 17, ty + 3 + follow(t, 0.36, 3.0)),
        ])
        if i == 1:
            sx, sy = _pt(cx, cy, ang, 7, -13)
            sparkle(img, int(sx), int(sy))
        elif i == 3:
            sx, sy = _pt(cx, cy, ang, 17, -9)
            sparkle(img, int(sx), int(sy), small=True)
        _eye(img, cx, cy, ang, mood="happy")
        bx, by = _pt(cx, cy, ang, 4, 2.6)
        blush(img, int(bx), int(by))
        _shadow(img, cx, GROUND - (cy + HMAX), _footprint(ang) * 2)

    elif state == "jumping":
        t2 = i / (n - 1)
        arc = math.sin(math.pi * t2)
        cy = HOVER_Y + 3 - 27 * ease_out(arc)
        cx = CX
        ang = -0.42 * math.cos(math.pi * t2)  # nose-up rising, level at apex
        img = _assemble(img, cx, cy, ang, fin=0.5 * arc)
        tx, ty = _pt(cx, cy, ang, -L, 0)
        _thread(img, [  # thread whips below
            (tx, ty),
            (tx - 4, ty + 4 + 3 * arc + follow(t2, 0.1, 1.5)),
            (tx - 8, ty + 8 + 5 * arc + follow(t2, 0.2, 2.5)),
            (tx - 10, ty + 13 + 6 * arc + follow(t2, 0.3, 3.0)),
        ])
        if i == 2:  # apex sparkles
            sparkle(img, int(cx) - 20, int(cy) - 12)
            sparkle(img, int(cx) + 18, int(cy) - 9, small=True)
        elif i == 3:
            sparkle(img, int(cx) + 14, int(cy) - 13, small=True)
        happy = i in (1, 2, 3)
        _eye(img, cx, cy, ang, mood="happy" if happy else "open",
             look=(1, -2) if i == 0 else (1, 2))
        if happy:
            bx, by = _pt(cx, cy, ang, 4, 2.6)
            blush(img, int(bx), int(by))
        _shadow(img, cx, GROUND - (cy + HMAX), _footprint(ang) * 2)

    elif state == "failed":
        cx = CX
        cy = HOVER_Y + 7 + 0.6 * math.sin(ph)  # sinks low, bob nearly flat
        ang = 0.52  # powered down, nose ~30 deg down
        img = _assemble(img, cx, cy, ang, fin=-0.8)
        tx, ty = _pt(cx, cy, ang, -L, 0)
        sway = 0.8 * math.sin(ph)
        _thread(img, [  # tangled droop off the raised tail
            (tx, ty),
            (tx - 3, ty + 4),
            (tx - 6, ty + 8 + sway),
            (tx - 2, ty + 10 + sway),
            (tx - 5, ty + 6),
            (tx - 4, ty + 13 + sway),
        ])
        sx, sy = _pt(cx, cy, ang, -8, -12)
        sweat_drop(img, int(sx), sy + 4 * t)
        _eye(img, cx, cy, ang, look=(0, 2), lid=0.45)
        _shadow(img, cx, GROUND - (cy + 13), _footprint(ang) * 2)

    elif state == "waiting":
        cx = CX
        cy = HOVER_Y + bob(t, 1.5)
        ang = -math.pi / 2 + 0.04 * math.sin(ph)  # vertical, nose up
        img = _assemble(img, cx, cy, ang, fin=0.45 + 0.15 * math.sin(ph))
        nx, ny = _pt(cx, cy, ang, L, 0)
        attention_dot(img, int(nx), ny - 7, t=t)
        tx, ty = _pt(cx, cy, ang, -L, 0)
        _thread(img, [  # trailing thread curls into a question-hook
            (tx, ty),
            (tx + 4, ty),
            (tx + 9, ty - 1),
            (tx + 13, ty - 4),
            (tx + 13, ty - 9),
            (tx + 9, ty - 12),
            (tx + 5, ty - 10),
        ])
        put(img, tx + 10, ty + 3, V[1])  # the question dot
        _eye(img, cx, cy, ang, look=(0, -2), lid=1.0 if i == n - 1 else 0.0)
        _shadow(img, cx, GROUND - (cy + L), _footprint(ang) * 2)

    elif state == "running":  # weaving at full speed in place
        s = 1 if i % 2 == 0 else -1
        cx = CX + s
        cy = HOVER_Y + 1.5 * math.sin(2 * ph)
        ang = 0.05 * s
        img = _assemble(img, cx, cy, ang, fin=-0.1)
        tx, ty = _pt(cx, cy, ang, -L, 0)
        _thread(img, [  # thread whips side to side, crossing itself
            (tx, ty),
            (tx - 4, ty + follow(t * 2, 0.00, 3.5)),
            (tx - 9, ty + follow(t * 2, 0.15, 5.5)),
            (tx - 13, ty + follow(t * 2, 0.30, 7.0)),
            (tx - 16, ty + follow(t * 2, 0.45, 8.0)),
        ])
        motion_ticks(img, int(tx) - 1, int(cy), 1)
        nx, _ = _pt(cx, cy, ang, L, 0)
        motion_ticks(img, int(nx) + 2, int(cy), -1)
        _eye(img, cx, cy, ang, mood="open", look=(2, 0), lid=0.3)
        _shadow(img, cx, GROUND - (cy + HMAX), _footprint(ang) * 2)

    elif state == "review":
        sweep = math.sin(ph)
        vel = math.cos(ph)
        cx = CX + 8 * sweep
        cy = HOVER_Y + 1.2 * math.sin(2 * ph)
        ang = 0.04 * vel
        img = _assemble(img, cx, cy, ang)
        # The faint cream weft line it scans, drawn beneath the hull.
        for k, x in enumerate(range(20, 77, 4)):
            put(img, x, 88, C[2] if k % 3 == 0 else C[1])
            put(img, x + 1, 88, C[1])
        tx, ty = _pt(cx, cy, ang, -L, 0)
        stretch = 1.0 + 0.3 * vel  # wake stretches against the motion
        _thread(img, [
            (tx, ty),
            (tx - 5 * stretch, ty + 1 + follow(t, 0.12, 1.5)),
            (tx - 10 * stretch, ty + 2 + follow(t, 0.24, 2.2)),
            (tx - 15 * stretch, ty + 2 + follow(t, 0.36, 2.8)),
        ])
        _eye(img, cx, cy, ang, look=(int(round(2 * vel)), 1), lid=0.3)
        _shadow(img, cx, GROUND - (cy + HMAX), _footprint(ang) * 2)

    else:  # pragma: no cover — unknown states fall back to a static hover
        img = _assemble(img, CX, HOVER_Y, 0.0)
        _eye(img, CX, HOVER_Y, 0.0)
        _shadow(img, CX, GROUND - (HOVER_Y + HMAX), L * 2.0)

    return img
