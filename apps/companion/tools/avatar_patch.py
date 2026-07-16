"""Patch — the quilt golem. A huggable patchwork cube-critter.

A soft rounded-square golem stitched from four brand-toned quilt squares
(cream, gray, violet, navy), each puffed with its own ramp shading and
joined by running stitches with gold cross-stitch accents. The face lives
directly ON the top-left cream square — one big solid-ink anime eye and one
sewn-on button eye for lopsided handmade charm — and a loose gold basting
thread springs from the crown seam as Patch's emotion ahoge. Stubby
floating mitts and rounded navy feet do the rest. Personifies Fabric's
"many pieces, one fabric" ethos.
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

NAME = "Patch"
SLUG = "patch"
DESCRIPTION = "A huggable quilt golem stitched from brand-toned squares."

V = RAMPS["violet"]
N = RAMPS["navy"]
C = RAMPS["cream"]
G = RAMPS["gold"]
GY = RAMPS["gray"]

# Body proportions (half-res px) — chibi: a big soft quilt cube.
BODY_W, BODY_H = 46, 40
BODY_BOT = 95  # rest bottom of the torso; feet reach GROUND below it


# ── masked pixel helpers (never paint outside the silhouette or over ink) ──
def _mput(img, x, y, color) -> None:
    xi, yi = int(round(x)), int(round(y))
    if 0 <= xi < G_W and 0 <= yi < G_H:
        px = img.load()
        p = px[xi, yi]
        if p[3] != 0 and p != INK:
            px[xi, yi] = color


def _hline(img, x0, x1, y, color) -> None:
    for x in range(int(round(x0)), int(round(x1)) + 1):
        _mput(img, x, y, color)


def _vline(img, x, y0, y1, color) -> None:
    for y in range(int(round(y0)), int(round(y1)) + 1):
        _mput(img, x, y, color)


def _dither(img, box, color, *, phase: int = 0) -> None:
    """Masked checkerboard dither (never touches ink or transparency)."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    for y in range(y0, y1):
        for x in range(x0, x1):
            if (x + y + phase) % 2 == 0:
                _mput(img, x, y, color)


# ── body ─────────────────────────────────────────────────────────────────
def _quads(left, top, right, bot, sx, sy, *, puff=-1, sep=0, detach=(0, 0)):
    """The four quilt squares in draw order (hanging TR last).

    Returns [(box, ramp, corners)] where corners follows PIL's
    (top-left, top-right, bottom-right, bottom-left).
    """
    tl = [left, top, sx, sy]
    tr = [sx, top, right, sy]
    bl = [left, sy, sx, bot]
    br = [sx, sy, right, bot]
    if puff == 0:  # cream + navy swell
        tl[0] -= 1
        tl[1] -= 1
        br[2] += 1
    elif puff == 1:  # gray + violet swell
        tr[2] += 1
        tr[1] -= 1
        bl[0] -= 1
    if sep:
        tl = [tl[0] - sep, tl[1] - sep, tl[2] - sep, tl[3] - sep]
        tr = [tr[0] + sep, tr[1] - sep, tr[2] + sep, tr[3] - sep]
        bl = [bl[0] - sep, bl[1] + sep, bl[2] - sep, bl[3] + sep]
        br = [br[0] + sep, br[1] + sep, br[2] + sep, br[3] + sep]
    dx, dyv = detach
    if dx or dyv:
        tr = [tr[0] + dx, tr[1] + dyv, tr[2] + dx, tr[3] + dyv]
    return [
        (tuple(tl), "cream", (True, False, False, False)),
        (tuple(bl), "violet", (False, False, False, True)),
        (tuple(br), "navy", (False, False, True, False)),
        (tuple(tr), "gray", (False, True, False, False)),
    ]


def _body(img, dy=0.0, squash=1.0, *, lean=0, feet_phase=None, foot_tap=0.0,
          puff=-1, sep=0, detach=(0, 0)):
    """Quilt torso + feet anchored at the ground. Returns the geometry dict."""
    d = ImageDraw.Draw(img)
    h = BODY_H / squash
    w = BODY_W * squash
    cx = CX + lean
    bot = int(round(BODY_BOT + dy))
    top = int(round(bot - h))
    left = int(round(cx - w / 2))
    right = int(round(cx + w / 2))
    sx = int(round(cx))
    sy = int(round(top + (bot - top) * 0.5))

    # Feet: two rounded navy boots reaching the ground.
    if feet_phase is None:
        lifts = (0.0, foot_tap)
    else:
        step = math.sin(2 * math.pi * feet_phase)
        lifts = (max(0.0, step) * 3, max(0.0, -step) * 3)
    feet = []
    for side, lift in zip((-1, 1), lifts):
        fx = sx + side * 12 + side * sep
        y1 = int(round(GROUND + min(dy, 0) - lift))
        d.rounded_rectangle((fx - 6, y1 - 7, fx + 6, y1), radius=3, fill=N[2])
        feet.append((fx, y1))

    # The four quilt squares (drawn edge-to-edge; seams painted in _details).
    quads = _quads(left, top, right, bot, sx, sy, puff=puff, sep=sep, detach=detach)
    for box, ramp, corners in quads:
        d.rounded_rectangle(box, radius=7, corners=corners, fill=RAMPS[ramp][2])

    # Plush maker's tag on the top-left square (rides that patch).
    tlb = quads[0][0]
    tx, ty = int(round(tlb[0])) + 7, int(round(tlb[1]))
    d.rectangle((tx, ty - 4, tx + 5, ty + 1), fill=C[2])

    return {
        "cx": sx, "left": left, "right": right, "top": top, "bot": bot,
        "sx": sx, "sy": sy, "quads": quads, "sep": sep, "detach": detach,
        "feet": feet,
    }


def _cross(img, x, y) -> None:
    """A tiny gold cross-stitch X accent."""
    for o in (-1, 1):
        _mput(img, x + o, y + o, G[2])
        _mput(img, x + o, y - o, G[3])
    _mput(img, x, y, G[3])


def _details(img, g) -> None:
    """Per-patch puffy ramp shading, seams, stitches, feet (post-outline)."""
    d = ImageDraw.Draw(img)
    joined = g["sep"] == 0 and g["detach"] == (0, 0)

    for box, ramp, corners in g["quads"]:
        x0, y0, x1, y1 = (int(round(v)) for v in box)
        r = RAMPS[ramp]
        qw, qh = x1 - x0, y1 - y0
        # Warm light cap up-left with a dithered falloff over the crown.
        _hline(img, x0 + 2, x1 - 3, y0 + 1, r[3])
        _vline(img, x0 + 1, y0 + 2, y1 - 3, r[3])
        _dither(img, (x0 + 2, y0 + 2, x0 + 2 + int(qw * 0.55), y0 + 2 + int(qh * 0.42)), r[3])
        _hline(img, x0 + 2, x0 + 6, y0 + 2, r[4])
        _vline(img, x0 + 2, y0 + 3, y0 + 4, r[4])
        # Indigo shadow low-right with a dithered rise + deep rim.
        _vline(img, x1 - 1, y0 + 3, y1 - 1, r[1])
        _hline(img, x0 + 2, x1 - 1, y1, r[1])
        _dither(img, (x0 + int(qw * 0.42), y1 - int(qh * 0.40), x1 - 1, y1), r[1], phase=1)
        _hline(img, x1 - 9, x1 - 1, y1, r[0])
        _vline(img, x1 - 1, y1 - 3, y1, r[0])
        # Running-stitch dashes just inside the body border.
        thread = V[2] if ramp == "cream" else C[4]
        ctl, ctr, cbr, cbl = corners
        if ctl or ctr:
            for xx in range(x0 + 4, x1 - 3, 5):
                _mput(img, xx, y0, thread)
                _mput(img, xx + 1, y0, thread)
        if cbl or cbr:
            for xx in range(x0 + 4, x1 - 3, 5):
                _mput(img, xx, y1, thread)
                _mput(img, xx + 1, y1, thread)
        if ctl or cbl:
            for yy in range(y0 + 4, y1 - 3, 5):
                _mput(img, x0, yy, thread)
                _mput(img, x0, yy + 1, thread)
        if ctr or cbr:
            for yy in range(y0 + 4, y1 - 3, 5):
                _mput(img, x1, yy, thread)
                _mput(img, x1, yy + 1, thread)

    # Quilt seams with cream running stitches.
    left, right, top, bot = g["left"], g["right"], g["top"], g["bot"]
    sx, sy = g["sx"], g["sy"]
    if joined:
        _vline(img, sx, top + 1, bot - 1, N[0])
        _hline(img, left + 1, right - 1, sy, N[0])
        for yy in range(top + 3, bot - 2, 4):
            _mput(img, sx, yy, C[4])
            _mput(img, sx, yy + 1, C[4])
        for xx in range(left + 3, right - 2, 4):
            _mput(img, xx, sy, C[4])
            _mput(img, xx + 1, sy, C[4])
    elif g["detach"] != (0, 0):
        # The top-right square hangs loose: seams only where still joined.
        _vline(img, sx, sy, bot - 1, N[0])
        _hline(img, left + 1, sx, sy, N[0])
        for yy in range(sy + 2, bot - 2, 4):
            _mput(img, sx, yy, C[4])
            _mput(img, sx, yy + 1, C[4])
        for xx in range(left + 3, sx - 1, 4):
            _mput(img, xx, sy, C[4])
            _mput(img, xx + 1, sy, C[4])
        trb = next(b for b, rname, _c in g["quads"] if rname == "gray")
        d.rounded_rectangle(
            tuple(int(round(v)) for v in trb),
            radius=7, corners=(False, True, False, False), outline=INK,
        )

    # Gold cross-stitch accents on the violet and gray squares (the cream
    # square hosts the face, so it stays clear).
    for box, ramp, _c in g["quads"]:
        x0, y0, x1, y1 = (int(round(v)) for v in box)
        if ramp == "violet":
            _cross(img, x0 + 6, (y0 + y1) // 2 + 2)
        elif ramp == "gray":
            _cross(img, x1 - 6, y1 - 5)

    # Maker's tag: warm sheen + a violet brand stripe.
    tlb = g["quads"][0][0]
    tx, ty = int(round(tlb[0])) + 7, int(round(tlb[1]))
    _hline(img, tx + 1, tx + 4, ty - 3, C[4])
    _hline(img, tx + 1, tx + 4, ty - 1, V[2])

    # Feet: tuck crease + navy ramp + ground rim.
    for fx, f1 in g["feet"]:
        _hline(img, fx - 6, fx + 6, bot, INK)
        if f1 - bot >= 3:
            _hline(img, fx - 5, fx + 5, bot + 1, N[3])
            _mput(img, fx - 5, bot + 2, N[3])
            _dither(img, (fx - 3, f1 - 2, fx + 5, f1), N[1], phase=1)
            _hline(img, fx - 4, fx + 4, f1, N[0])


# ── mitts, face, effects ─────────────────────────────────────────────────
def _arm_y(g) -> int:
    return g["top"] + int(round((g["bot"] - g["top"]) * 0.62))


def _mitt(img, x, y) -> None:
    """A stubby floating navy mitt (drawn post-outline, self-outlined)."""
    d = ImageDraw.Draw(img)
    xi, yi = int(round(x)), int(round(y))
    d.ellipse((xi - 3, yi - 3, xi + 3, yi + 3), fill=N[3], outline=INK)
    put(img, xi - 1, yi - 2, N[4])
    put(img, xi - 2, yi - 1, N[4])
    put(img, xi + 1, yi + 1, N[1])
    put(img, xi + 2, yi + 1, N[1])
    put(img, xi, yi + 2, N[2])


def _mitts(img, g, l_off=(0, 0), r_off=(0, 0)) -> None:
    ay = _arm_y(g)
    _mitt(img, g["left"] - 3 + l_off[0], ay + l_off[1])
    _mitt(img, g["right"] + 3 + r_off[0], ay + r_off[1])


def _button_eye(img, x, y) -> None:
    """The sewn-on button eye: cream disc, ink rim, two thread holes."""
    d = ImageDraw.Draw(img)
    d.ellipse((x, y, x + 6, y + 6), fill=C[2], outline=INK)
    put(img, x + 2, y + 1, C[4])
    put(img, x + 1, y + 2, C[4])
    put(img, x + 4, y + 5, C[1])
    put(img, x + 5, y + 4, C[1])
    put(img, x + 2, y + 3, INK)
    put(img, x + 4, y + 3, INK)


def _face(img, g, *, mood="open", look=(0, 0), mouth_mood="smile",
          cheeks=False, dx=0) -> None:
    """The face lives ON the top-left cream quilt square (no plate):
    one solid-ink hero eye + one sewn-on button eye + mouth."""
    tlb = g["quads"][0][0]
    x0, y0 = int(round(tlb[0])), int(round(tlb[1]))
    fx = x0 + 4 + dx  # hero-eye anchor, riding the cream patch
    fy = y0 + 6
    anime_eye_lg(img, fx, fy, mood=mood, look=look)
    _button_eye(img, fx + 8, fy - 1)
    mouth(img, fx + 6, fy + 8, mouth_mood)
    if cheeks:
        blush(img, fx - 2, fy + 7)
        blush(img, fx + 12, fy + 7)


def _ahoge(img, g, pose: str, t: float) -> None:
    """Patch's soul thread: a loose gold basting strand at the crown seam.

    Rooted where the center seam meets the crown, it perks, streams, wilts,
    and curls into question hooks — emotion in every row, with follow() lag.
    """
    rx, ry = g["sx"], g["top"]
    root = (rx, ry)
    if pose == "perk":  # fully vertical, proud
        pts = [(rx, ry - 4), (rx + 1, ry - 8), (rx, ry - 12)]
    elif pose == "rest":
        sway = follow(t, 0.15, 2)
        pts = [(rx + 1, ry - 4), (rx + 2 + sway, ry - 8), (rx - 1 + sway, ry - 11)]
    elif pose == "flick":  # idle life-beat: tip snaps up
        pts = [(rx + 1, ry - 4), (rx + 2, ry - 9), (rx + 3, ry - 13)]
    elif pose == "stream":  # running: streams straight back
        whip = follow(t * 2, 0.2, 3)
        pts = [(rx - 5, ry - 4), (rx - 10, ry - 6 + whip / 2), (rx - 14, ry - 5 + whip)]
    elif pose == "flat":  # crouch/landing: flattened sideways
        pts = [(rx + 4, ry - 1), (rx + 8, ry), (rx + 11, ry + 1)]
    elif pose == "trail":  # rising: the thread trails below the crown
        pts = [(rx + 4, ry), (rx + 7, ry + 3), (rx + 9, ry + 7)]
    elif pose == "float":  # apex: weightless, straight up
        pts = [(rx, ry - 5), (rx - 1, ry - 9), (rx + 1, ry - 13)]
    elif pose == "up":  # descending: streams upward behind the fall
        pts = [(rx + 2, ry - 4), (rx + 5, ry - 8), (rx + 7, ry - 12)]
    elif pose == "wilt":  # failed: draped over the crown edge
        droop = min(1.0, t * 3)
        wob = follow(t, 0.1, 0.7) * droop
        pts = [
            (rx + 3, ry - 3 + 3 * droop),
            (rx + 6, ry - 2 + 5 * droop + wob / 2),
            (rx + 9, ry + 6 * droop + wob),
        ]
    elif pose == "hook":  # waiting: curls into a question mark
        f = ease_in_out(min(1.0, t * 3))
        wob = 1 if (int(t * 6) % 2 == 0 and t > 0.4) else 0
        pts = [
            (rx + 2, ry - 5),
            (rx + 4 + 2 * f, ry - 9 - f),
            (rx + 2 + 2 * f + wob, ry - 12 - 2 * f),
            (rx - 1 + f, ry - 10 - 2 * f),
        ]
        strand(img, [root, *pts], G[1], thick=True)
        strand(img, [root, *pts], G[2])
        put(img, pts[-1][0], pts[-1][1], C[4])
        put(img, rx + 2, ry - 6, G[2])  # the question dot
        return
    elif pose == "whip":  # working: counter-whips the knead beat
        whip = follow(t, 0.2, 3)
        pts = [(rx - whip, ry - 5), (rx - 2 * whip, ry - 9), (rx - whip, ry - 12)]
    else:
        pts = [(rx, ry - 6), (rx, ry - 10)]
    strand(img, [root, pts[0]], G[1], thick=True)
    strand(img, pts, G[2])
    put(img, pts[-1][0], pts[-1][1], C[4])


def _steam(img, x, y, big) -> None:
    """A tiny cream effort puff with a fading wisp above."""
    put(img, x, y, C[3])
    put(img, x + 1, y, C[4])
    put(img, x + 1, y - 1, C[4])
    put(img, x - 1, y - 1, C[2])
    put(img, x, y - 3, C[2])
    if big:
        put(img, x, y - 1, C[4])
        put(img, x + 2, y, C[3])
        put(img, x + 1, y - 4, C[1])


# ── choreography ─────────────────────────────────────────────────────────
def draw(state: str, i: int, n: int):
    img = canvas()
    t = i / n
    ph = 2 * math.pi * t

    if state == "idle":
        dy = bob(t, 1.2)
        g = _body(img, dy, 1.0, puff=i % 2)
        img = auto_outline(img)
        _details(img, g)
        _mitts(img, g,
               l_off=(0, round(follow(t, 0.18, 2.0))),
               r_off=(0, round(follow(t, 0.32, 2.0))))
        _ahoge(img, g, "flick" if i == 2 else "rest", t)
        _face(img, g, mood="closed" if i == n - 1 else "open",
              mouth_mood="smile", cheeks=True)

    elif state == "running-right":
        bounce = abs(math.sin(2 * ph))
        pump = math.sin(2 * ph)
        g = _body(img, -4 * ease_out(bounce), 1.0 + 0.06 * (1 - bounce),
                  lean=3, feet_phase=t * 2)
        img = auto_outline(img)
        _details(img, g)
        _mitts(img, g,
               l_off=(round(3 * pump), -2 - round(1.5 * pump)),
               r_off=(round(-3 * pump), -2 + round(1.5 * pump)))
        motion_ticks(img, g["left"] - 3, (g["top"] + g["bot"]) // 2, 1)
        _ahoge(img, g, "stream", t)
        _face(img, g, mood="open", look=(1, 0), mouth_mood="smile", dx=2)

    elif state == "waving":
        sweep = ease_in_out(0.5 + 0.5 * math.sin(math.pi * (2 * t - 0.5)))
        g = _body(img, -round(1.5 * sweep), 1.0)
        img = auto_outline(img)
        _details(img, g)
        _mitt(img, g["left"] - 3, _arm_y(g) + round(follow(t, 0.2, 1.5)))
        ang = math.radians(-20 + 145 * sweep)
        px_, py_ = g["right"] - 6, g["top"] + 6
        wx = px_ + 18 * math.cos(ang)
        wy = py_ - 18 * math.sin(ang)
        vel = math.cos(math.pi * (2 * t - 0.5))  # swing direction
        if abs(vel) > 0.3:  # motion trail along the swing arc
            for back, col in ((0.35, C[2]), (0.6, V[3])):
                a2 = ang - math.copysign(back, vel)
                put(img, px_ + 18 * math.cos(a2), py_ - 18 * math.sin(a2), col)
        _mitt(img, wx, wy)
        if sweep > 0.85:
            sparkle(img, int(round(wx)) + 6, int(round(wy)) - 2, small=True)
        _ahoge(img, g, "perk", t)
        _face(img, g, mood="happy", mouth_mood="open", cheeks=True)

    elif state == "jumping":
        # Symmetric arc peaked at the middle frame: f0 crouch, f1 rise,
        # f2 apex (quilt squares drift apart + sparkles), f3 descend,
        # f4 GROUNDED landing squash — the loop lands back into f0.
        arc = math.sin(math.pi * i / (n - 1))
        if i == 0:  # anticipation crouch
            g = _body(img, 0, 1.18)
            img = auto_outline(img)
            _details(img, g)
            _mitts(img, g, l_off=(0, 2), r_off=(0, 3))
            _ahoge(img, g, "flat", t)
            _face(img, g, mood="focused", look=(0, -1), mouth_mood="line")
        elif i == n - 1:  # landing squash, boots planted, dust kicks
            g = _body(img, 0, 1.10)
            img = auto_outline(img)
            _details(img, g)
            _mitts(img, g, l_off=(-2, -3), r_off=(2, -3))
            _ahoge(img, g, "flat", t)
            for side in (-1, 1):
                put(img, g["cx"] + side * 22, GROUND - 2, C[2])
                put(img, g["cx"] + side * 24, GROUND - 4, C[1])
            _face(img, g, mood="happy", mouth_mood="smile", cheeks=True)
        else:
            sep = 2 if i == (n - 1) // 2 else 0  # separation at the apex ONLY
            g = _body(img, -15 * arc, 1.0 - 0.08 * arc, sep=sep)
            img = auto_outline(img)
            _details(img, g)
            if sep:  # apex: weightless — sparkles in the quilt gaps
                _mitts(img, g, l_off=(-3, -5), r_off=(3, -5))
                _ahoge(img, g, "float", t)
                sparkle(img, g["cx"], g["sy"], small=True)
                sparkle(img, g["cx"] - 14, g["sy"], small=True)
                sparkle(img, g["cx"] + 14, g["sy"], small=True)
                sparkle(img, g["right"] + 7, g["top"] - 3)
                _face(img, g, mood="happy", mouth_mood="open", cheeks=True)
            elif i < (n - 1) // 2:  # rising: mitts + thread trail below
                _mitts(img, g, l_off=(-2, 3), r_off=(2, 3))
                _ahoge(img, g, "trail", t)
                _face(img, g, mood="open", look=(0, -1), mouth_mood="open")
            else:  # descending: mitts flung up, eyes on the landing
                _mitts(img, g, l_off=(-2, -6), r_off=(2, -6))
                _ahoge(img, g, "up", t)
                _face(img, g, mood="open", look=(0, 1), mouth_mood="smile")

    elif state == "failed":
        # Progressive come-apart over f0-f3 (slump deepens, the gray square
        # shears loose), then settled sulk-breathing f4-f7 (amp <= 1px) —
        # ending in a holdable slumped pose.
        settle = ease_in_out(min(1.0, i / 3))
        breath = 1 if i in (5, 6) else 0
        detach = (round(3 * settle), round(6 * settle))
        g = _body(img, 3 * settle + breath, 1.0 + 0.10 * settle, detach=detach)
        img = auto_outline(img)
        _details(img, g)
        _mitts(img, g,
               l_off=(-round(2 * settle), round(4 * settle) + breath),
               r_off=(round(2 * settle), round(5 * settle)))
        _ahoge(img, g, "wilt", t)
        if detach != (0, 0):
            # Torn stitch frays in the crack + threads off the loose square.
            sway = follow(t, 0.1, 1.0)
            trb = next(b for b, rname, _c in g["quads"] if rname == "gray")
            x0, y0, x1, y1 = (int(round(v)) for v in trb)
            strand(img, [(x0 + 5, y0), (x0 + 4, y0 - 3)], C[3])
            strand(img, [(x0 + 13, y0), (x0 + 14, y0 - 4)], C[3])
            strand(img, [(x1 - 2, y1 - 1), (x1 + 1 + round(sway), y1 + 3),
                         (x1 + round(2 * sway), y1 + 7)], C[3])
        if i >= 3:  # a single tear wells under the hero eye
            tlb = g["quads"][0][0]
            tear(img, int(round(tlb[0])) + 6,
                 int(round(tlb[1])) + 13 + min(i - 3, 3))
        sweat_drop(img, g["left"] - 4, g["top"] + 5 + 5 * t)
        _face(img, g, mood="sad", look=(0, 1), mouth_mood="wobble")

    elif state == "waiting":
        dy = bob(t, 1.0)
        g = _body(img, dy, 1.0, foot_tap=2.0 if i % 2 else 0.0, puff=i % 2)
        img = auto_outline(img)
        _details(img, g)
        _mitts(img, g, l_off=(0, round(follow(t, 0.2, 1.5))), r_off=(0, 1))
        # The basting thread curls into a question-hook above the crown.
        _ahoge(img, g, "hook", t)
        attention_dot(img, g["cx"] + 13, g["top"] - 12 + bob(t, 1.5), t=t)
        _face(img, g, mood="closed" if i == n - 1 else "open",
              look=(1, -1), mouth_mood="line")

    elif state == "running":  # focused work in place: kneading dough
        k = math.sin(2 * ph)
        press = abs(k)
        lean = round(3 * k)
        g = _body(img, round(1.5 * press), 1.0 + 0.05 * press, lean=lean)
        img = auto_outline(img)
        _details(img, g)
        _mitts(img, g,
               l_off=(2 + round(2 * k), round(2 * press)),
               r_off=(-2 + round(2 * k), round(2 * press)))
        side = -1 if i % 2 else 1
        _steam(img, g["cx"] + side * (BODY_W // 2 + 6),
               g["top"] + 9 - 2 * (i % 3), i % 3 == 2)
        _ahoge(img, g, "whip", t)
        _face(img, g, mood="focused",
              look=(1 if k > 0.2 else (-1 if k < -0.2 else 0), 0),
              mouth_mood="line", dx=round(0.7 * lean))

    elif state == "review":
        pos = ease_in_out(min(2 * t, 2 - 2 * t))
        g = _body(img, 0, 1.0)
        img = auto_outline(img)
        _details(img, g)
        d = ImageDraw.Draw(img)
        cx, sy = g["cx"], g["sy"] + 2
        # A cream swatch card with a gold thread pattern, held out front.
        d.rounded_rectangle((cx - 9, sy - 3, cx + 9, sy + 7),
                            radius=2, fill=C[3], outline=INK)
        _hline(img, cx - 7, cx + 7, sy + 5, C[1])
        zig = [(cx - 7 + 2 * k2, sy + (0 if k2 % 2 == 0 else 2))
               for k2 in range(8)]
        strand(img, zig, G[2])
        put(img, cx - 6, sy - 1, G[3])
        put(img, cx + 6, sy - 1, G[3])
        scan = int(round(-6 + 12 * pos))
        put(img, cx + scan, sy + 4, G[3])
        put(img, cx + scan, sy + 3, G[4])
        # Left mitt steadies the card; right mitt reads along under it.
        _mitt(img, cx - 12, sy + 5)
        _mitt(img, cx - 6 + 12 * pos, sy + 11)
        _ahoge(img, g, "rest", t)
        _face(img, g, mood="focused",
              look=(int(round(-1 + 2 * pos)), 1), mouth_mood="line")

    else:  # pragma: no cover - unknown states fall back to a static body
        g = _body(img, 0, 1.0)
        img = auto_outline(img)
        _details(img, g)
        _mitts(img, g)
        _ahoge(img, g, "rest", t)
        _face(img, g)

    return img
