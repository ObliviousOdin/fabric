"""Patch — the patchwork puppy. Skein's sibling (avatar style contract v2).

A round violet-ramp puppy bean with a lighter muzzle bump, a tiny navy
nose, and two FLOPPY mismatched ears sewn on like quilt patches — one
navy-ramp, one gray-ramp, each with cream seam stitches at the root. A
cream stitched square patch rides one brow (dashed border + one gold
cross-stitch); it peels a corner when things go wrong. The short stitched
tail is Patch's emotion appendage: it wags, blurs, hooks into question
marks, and lies flat in a sulk. Bounds instead of runs, digs instead of
types.
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
    dither_shade,
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

NAME = "Patch"
SLUG = "patch"
DESCRIPTION = "A patchwork puppy with mismatched sewn-on ears and a waggy stitched tail."

V = RAMPS["violet"]
N = RAMPS["navy"]
C = RAMPS["cream"]
G = RAMPS["gold"]
GY = RAMPS["gray"]
ROSE = RAMPS["rose"]

RX, RY = 19, 21  # bean radii at rest (taller than wide — a sitting pup)


# ── stamped appendages (own ink rim, composited over the body) ───────────
def _bez(p0, p1, p2, u):
    w0, w1, w2 = (1 - u) * (1 - u), 2 * u * (1 - u), u * u
    return (
        w0 * p0[0] + w1 * p1[0] + w2 * p2[0],
        w0 * p0[1] + w1 * p1[1] + w2 * p2[1],
    )


def _limb(img, base, ctrl, tip, ramp, r0, r1, *, seam=None):
    """A tapered disc-chain along a quad bezier, stamped with its own ink
    outline so it reads cleanly over the body. *seam* draws cream running
    stitches: "root" (across the base — sewn-on ears) or "spine" (along the
    centerline — the stitched tail)."""
    tmp = canvas()
    d = ImageDraw.Draw(tmp)
    steps = 12
    pts = []
    for k in range(steps):
        u = k / (steps - 1)
        x, y = _bez(base, ctrl, tip, u)
        r = r0 + (r1 - r0) * u
        pts.append((x, y, r, u))
        d.ellipse((x - r, y - r, x + r, y + r), fill=ramp[2])
    # In-place lighting: warm streak up-left, indigo streak low-right.
    for x, y, r, u in pts:
        if 0.05 < u < 0.75:
            put(tmp, x - 0.5 * r, y - 0.5 * r, ramp[3])
            put(tmp, x - 0.5 * r + 1, y - 0.5 * r, ramp[3])
        if u > 0.35:
            put(tmp, x + 0.45 * r, y + 0.45 * r, ramp[1])
    put(tmp, pts[1][0] - 1, pts[1][1] - pts[1][2] + 1, ramp[4])
    put(tmp, tip[0], tip[1], ramp[1])
    if seam == "root":  # sewn-on: dashes across the attachment
        vx, vy = ctrl[0] - base[0], ctrl[1] - base[1]
        ln = math.hypot(vx, vy) or 1.0
        dx_, dy_ = vx / ln, vy / ln
        nx, ny = -dy_, dx_
        for k in (-2, 0, 2):
            put(tmp, base[0] + 2 * dx_ + k * nx, base[1] + 2 * dy_ + k * ny, C[4])
    elif seam == "spine":  # stitched seam along the tail's centerline
        for u in (0.30, 0.62):
            x, y = _bez(base, ctrl, tip, u)
            x2, y2 = _bez(base, ctrl, tip, u + 0.12)
            put(tmp, x, y - 1, C[4])
            put(tmp, (x + x2) / 2, (y + y2) / 2 - 1, C[4])
    img.alpha_composite(auto_outline(tmp))


def _ear_bases(cx, cy, rx, ry):
    return (cx - 0.50 * rx, cy - 0.86 * ry), (cx + 0.50 * rx, cy - 0.86 * ry)


def _ears(img, cx, cy, rx, ry, spec_l, spec_r):
    """The mismatched sewn-on ears, rooted at the crown and WIDER at the
    bottom lobe (the floppy-beagle teardrop). Each spec = (base_off,
    ctrl_off, tip_off) relative to the root; navy left, gray right."""
    bl, br = _ear_bases(cx, cy, rx, ry)
    # The navy ear leads with lifted steps so it separates from dark
    # backdrops at small scale (family-critic fix).
    navy_lifted = [N[1], N[2], N[3], N[4], N[4]]
    for (bx, by), (bo, co, to), ramp in ((bl, spec_l, navy_lifted), (br, spec_r, GY)):
        base = (bx + bo[0], by + bo[1])
        ctrl = (base[0] + co[0], base[1] + co[1])
        tip = (base[0] + to[0], base[1] + to[1])
        _limb(img, base, ctrl, tip, ramp, 2.4, 3.0, seam="root")


def _ear_rest(side, sway=0.0):
    return ((0, 0), (side * 6, 3), (side * 6 + sway, 14))


def _tail(img, base, ctrl_off, tip_off, *, ghosts=()):
    """The short stitched tail — Patch's emotion carrier. *ghosts* are extra
    (ctrl_off, tip_off) poses smeared in light violet for a blur-wag."""
    for co, to in ghosts:
        d = ImageDraw.Draw(img)
        for k in range(6):
            u = k / 5
            x, y = _bez(base, (base[0] + co[0], base[1] + co[1]), (base[0] + to[0], base[1] + to[1]), u)
            r = 1.9 - 0.8 * u
            d.ellipse((x - r, y - r, x + r, y + r), fill=V[3])
    ctrl = (base[0] + ctrl_off[0], base[1] + ctrl_off[1])
    tip = (base[0] + tip_off[0], base[1] + tip_off[1])
    _limb(img, base, ctrl, tip, V, 1.9, 1.1, seam="spine")


def _wag(theta, length=7.5, drop=1.5):
    """ctrl/tip offsets for a tail at *theta* rad above the outward axis."""
    c, s = math.cos(theta), math.sin(theta)
    return (0.55 * length * c, -0.55 * length * s - drop), (length * c, -length * s)


def _paw(img, x, y):
    """A stubby violet forepaw with a lit crown and two toe dents."""
    d = ImageDraw.Draw(img)
    d.ellipse((x - 3, y - 2, x + 3, y + 3), fill=V[3], outline=INK)
    put(img, x - 1, y - 1, V[4])
    put(img, x - 2, y, V[4])
    put(img, x - 1, y + 2, V[1])
    put(img, x + 1, y + 2, V[1])


# ── body ─────────────────────────────────────────────────────────────────
def _body(img, dy, squash, *, lean=0.0):
    """Ramp-shaded bean + seated haunches, anchored at GROUND + dy."""
    d = ImageDraw.Draw(img)
    rx, ry = RX * squash, RY / squash
    cx = CX + lean
    bot = GROUND + dy
    cy = bot - ry
    shade_ellipse(img, (cx - rx, cy - ry, cx + rx, cy + ry), "violet")
    # Haunches: soft side bumps that make the bean read as a sitting pup.
    d.ellipse((cx - rx - 2, bot - 12, cx - rx + 9, bot - 1), fill=V[2])
    d.ellipse((cx + rx - 9, bot - 12, cx + rx + 2, bot - 1), fill=V[2])
    return cx, cy, rx, ry, bot


def _details(img, cx, cy, rx, ry, bot):
    """Post-outline depth: deep low-right rim + haunch shadow."""
    d = ImageDraw.Draw(img)
    d.arc((cx - rx + 1, cy - ry + 1, cx + rx - 1, cy + ry - 1), 25, 110, fill=V[0])
    d.arc((cx - rx + 2, cy - ry + 2, cx + rx - 2, cy + ry - 2), 45, 95, fill=V[0])
    dither_shade(img, (cx + rx - 7, bot - 8, cx + rx + 2, bot - 2), V[1], phase=1)


# ── face ─────────────────────────────────────────────────────────────────
def _face(img, cx, cy, ry, *, mood="open", look=(0, 0), mstyle="smile",
          cheeks=False, dx=0, tongue=False):
    """Puppy face low on the bean: dithered sheen plate, hero eyes, lighter
    muzzle bump, tiny navy nose, small mouth. Returns the eye-row y."""
    d = ImageDraw.Draw(img)
    cx = int(round(cx)) + dx
    ey = int(round(cy - 0.40 * ry))
    px = img.load()
    for y in range(ey - 5, ey + 13):  # dithered fringe melts the plate in
        for x in range(cx - 15, cx + 16):
            if (x + y) % 2 and 0 <= x < img.width and 0 <= y < img.height:
                nx, ny = (x - cx) / 15.5, (y - (ey + 3.0)) / 8.5
                if nx * nx + ny * ny <= 1.0 and px[x, y][3] != 0:
                    px[x, y] = V[3]
    d.ellipse((cx - 14, ey - 4, cx + 14, ey + 10), fill=V[3])
    d.ellipse((cx - 5, ey + 3, cx + 5, ey + 11), fill=V[4])  # muzzle bump
    anime_eye_lg(img, cx - 11, ey, mood=mood, look=look)
    anime_eye_lg(img, cx + 8, ey, mood=mood, look=look)
    for ox, oy in ((-1, 0), (0, 0), (-1, 1), (0, 1)):  # tiny navy nose
        put(img, cx + ox, ey + 4 + oy, N[1])
    put(img, cx - 1, ey + 4, N[3])
    mouth(img, cx, ey + 8, mstyle)
    if tongue:
        put(img, cx, ey + 11, ROSE[3])
        put(img, cx, ey + 12, ROSE[2])
    if cheeks:
        blush(img, cx - 14, ey + 6)
        blush(img, cx + 12, ey + 6)
    return ey


def _brow_patch(img, cx, ey, *, peel=0, t=0.0, dx=0):
    """The cream quilt square sewn over the right brow: indigo seam ring,
    cream fill, cream dashes crossing the seam, one gold cross-stitch.
    *peel* > 0 folds the top-right corner open, loose stitch threads spring.
    """
    d = ImageDraw.Draw(img)
    cx += dx
    x0, y0, x1, y1 = cx + 1, ey - 8, cx + 8, ey - 2
    d.rectangle((x0, y0, x1, y1), outline=V[1], fill=C[2])
    for x in range(x0 + 1, x1):  # shadowed lower-right half of the cloth
        for y in range(y0 + 1, y1):
            if x - x0 + y - y0 > 6 and (x + y) % 2:
                put(img, x, y, C[1])
    put(img, x0 + 1, y0 + 1, C[4])  # catch-light corner
    # Corner stitch ticks crossing the seam (sewn-on, not printed).
    put(img, x0 - 1, y0 - 1, C[4])
    put(img, x1 + 1, y0 - 1, C[4])
    put(img, x0 - 1, y1 + 1, C[4])
    put(img, x1 + 1, y1 + 1, C[4])
    # Gold cross-stitch of honor at the center.
    mx, my = (x0 + x1) // 2, (y0 + y1) // 2
    for o in (-1, 1):
        put(img, mx + o, my + o, G[2])
        put(img, mx + o, my - o, G[3])
    put(img, mx, my, G[3])
    if peel > 0:  # the failed row's corner peel
        d.polygon([(x1 - peel, y0), (x1, y0), (x1, y0 + peel)], fill=V[2])
        d.polygon([(x1 - peel, y0), (x1 + 1, y0 - peel - 1), (x1 + 1, y0)], fill=C[3])
        put(img, x1 + 1, y0 - peel - 1, C[4])
        put(img, x1 - peel, y0, INK)
        sway = follow(t, 0.1, 1.0)
        strand(img, [(x1 + 1, y0 - peel), (x1 + 3 + sway, y0 - peel - 2)], C[3])
        strand(img, [(x1 - peel, y0 - 1), (x1 - peel + 1 + sway, y0 - 4)], C[3])


def _puff(img, x, y, big):
    """A tiny cream effort puff with a fading wisp."""
    put(img, x, y, C[3])
    put(img, x + 1, y, C[4])
    put(img, x + 1, y - 1, C[4])
    put(img, x - 1, y - 1, C[2])
    put(img, x, y - 3, C[2])
    if big:
        put(img, x, y - 1, C[4])
        put(img, x + 2, y, C[3])
        put(img, x + 1, y - 4, C[1])


def _tail_base(cx, cy, rx, ry, side=1):
    return (cx + side * (rx - 3), cy + 0.68 * ry)


# ── choreography ─────────────────────────────────────────────────────────
def draw(state: str, i: int, n: int):
    img = canvas()
    t = i / n
    ph = 2 * math.pi * t

    if state == "idle":
        squash = 1.0 + 0.03 * math.sin(ph)
        cx, cy, rx, ry, bot = _body(img, 0, squash)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, bot)
        _paw(img, cx - 7, bot - 3)
        _paw(img, cx + 7, bot - 3)
        # Slow contented wag with follow-through lag.
        theta = 0.80 + 0.35 * follow(t, 0.15)
        co, to = _wag(theta)
        _tail(img, _tail_base(cx, cy, rx, ry), co, to)
        ey = _face(img, cx, cy, ry, mood="closed" if i == n - 1 else "open",
                   cheeks=True)
        _brow_patch(img, int(round(cx)), ey)
        # Gag: the left ear flops up on f2 and resettles with overshoot.
        lift = -6 if i == 2 else (1 if i == 3 else 0)
        sway = follow(t, 0.25, 1.0)
        _ears(img, cx, cy, rx, ry,
              ((0, 0), (-6, 3 + lift * 0.4), (-6 + sway, 14 + lift)),
              _ear_rest(1, follow(t, 0.4, 1.0)))

    elif state == "running-right":
        # Happy puppy bound: two big gallop arcs per loop, ears flapping.
        bounce = ease_out(abs(math.sin(ph)))
        cx, cy, rx, ry, bot = _body(img, -8 * bounce, 1.06 - 0.12 * bounce, lean=3)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, bot)
        gallop = 3 * math.sin(ph)
        _paw(img, cx - 7 + gallop, bot - 3)
        _paw(img, cx + 7 - gallop, bot - 3)
        # Tail trails behind (left), streaming up and whipping double-time.
        whip = follow(t * 2, 0.2, 2.5)
        co, to = _wag(0.7 + 0.22 * whip)
        base = _tail_base(cx, cy, rx, ry, side=-1)
        _tail(img, base, (-co[0], co[1]), (-to[0], to[1]))
        motion_ticks(img, int(cx - rx - 4), int(cy), 1)
        ey = _face(img, cx, cy, ry, mood="happy" if i in (3, 4) else "open",
                   look=(1, 0), mstyle="open" if i == 3 else "smile",
                   dx=2, tongue=(i == 3))
        _brow_patch(img, int(round(cx)), ey, dx=2)
        flap_l = 0.5 + 0.5 * math.sin(2 * math.pi * (2 * t - 0.10))
        flap_r = 0.5 + 0.5 * math.sin(2 * math.pi * (2 * t - 0.22))
        _ears(img, cx, cy, rx, ry,
              ((0, 0), (-6, 3 - 4 * flap_l), (-8, 14 - 12 * flap_l)),
              ((0, 0), (6, 3 - 4 * flap_r), (8, 14 - 12 * flap_r)))

    elif state == "waving":
        cx, cy, rx, ry, bot = _body(img, 0, 1.0)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, bot)
        _paw(img, cx + 7, bot - 3)
        # Left paw sweeps up beside the head on an eased arc.
        sweep = (0.0, 0.75, 1.0, 0.55)[i]
        ang = math.pi * (0.10 + 0.45 * ease_in_out(sweep))
        pvx, pvy = cx - rx + 3, cy + 4
        wx, wy = pvx - 11 * math.cos(ang), pvy - 15 * math.sin(ang)
        strand(img, [(pvx, pvy), ((pvx + wx) / 2 - 1, (pvy + wy) / 2), (wx, wy)], V[3], thick=True)
        _paw(img, int(round(wx)), int(round(wy)))
        if sweep == 1.0:
            sparkle(img, int(round(wx)) - 5, int(round(wy)) - 3, small=True)
        # Blur-wag: the tail is so happy it ghosts two earlier positions.
        theta = 0.65 + 0.45 * math.sin(2 * math.pi * (2 * t - 0.15))
        prev1 = 0.65 + 0.45 * math.sin(2 * math.pi * (2 * (t - 0.125) - 0.15))
        prev2 = 0.65 + 0.45 * math.sin(2 * math.pi * (2 * (t - 0.25) - 0.15))
        co, to = _wag(theta)
        _tail(img, _tail_base(cx, cy, rx, ry), co, to,
              ghosts=(_wag(prev1), _wag(prev2)))
        ey = _face(img, cx, cy, ry, mood="happy", mstyle="open", cheeks=True)
        _brow_patch(img, int(round(cx)), ey)
        _ears(img, cx, cy, rx, ry,  # ears perk up with the hello
              ((0, 0), (-5, -2), (-6, -7 + i % 2)),
              ((0, 0), (5, -2), (6, -7 + (i + 1) % 2)))

    elif state == "jumping":
        # Five-beat leap: f0 grounded crouch, f1 rise, f2 apex (EARS FLOAT
        # with a gap of sky + sparkles), f3 descend, f4 grounded landing.
        arc = math.sin(math.pi * i / (n - 1))
        squash = (1.20, 0.92, 1.0, 1.02, 1.16)[i]
        cx, cy, rx, ry, bot = _body(img, -15 * arc, squash)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, bot)
        if i in (0, n - 1):
            _paw(img, cx - 7, bot - 3)
            _paw(img, cx + 7, bot - 3)
        else:  # airborne tuck
            _paw(img, cx - 6, bot - 5)
            _paw(img, cx + 6, bot - 5)
        wob = follow(t, 0.2, 1.5)
        tails = (
            ((3, 2), (5, 4)),        # tucked in the crouch
            ((4, 3), (7, 6)),        # dragging on the rise
            ((5, -1), (9, -2)),      # level at the apex
            ((4, -4), (7, -9)),      # whipped up on the descend
            ((5, -3), (9, -5)),      # splayed follow-through on landing
        )
        co, to = tails[i]
        _tail(img, _tail_base(cx, cy, rx, ry), co, (to[0], to[1] + wob))
        if i == 2:
            sparkle(img, int(cx - rx - 5), int(cy - ry - 4))
            sparkle(img, int(cx + rx + 5), int(cy - ry + 2), small=True)
        if i == n - 1:  # landing dust
            put(img, cx - rx - 3, GROUND - 1, C[2])
            put(img, cx + rx + 3, GROUND - 1, C[2])
            put(img, cx - rx - 5, GROUND - 3, C[1])
            put(img, cx + rx + 5, GROUND - 3, C[1])
        moods = ("focused", "open", "happy", "open", "happy")
        msts = ("line", "open", "open", "smile", "smile")
        looks = ((0, -1), (0, -1), (0, 0), (0, 1), (0, 0))
        ey = _face(img, cx, cy, ry, mood=moods[i], look=looks[i],
                   mstyle=msts[i], cheeks=i in (2, 4))
        _brow_patch(img, int(round(cx)), ey)
        ears = (
            (((0, 0), (-7, 1), (-9, 7)), ((0, 0), (7, 1), (9, 7))),          # pressed
            (((0, 0), (-5, 6), (-4, 14)), ((0, 0), (5, 6), (4, 14))),        # swept down
            (((1, -9), (-4, -4), (-5, -8)), ((-1, -9), (4, -4), (5, -8))),   # FLOAT: sky gap
            (((0, -2), (-5, -4), (-6, -10)), ((0, -2), (5, -4), (6, -10))),  # trailing up
            (((0, 0), (-8, 3), (-9, 12)), ((0, 0), (8, 3), (9, 12))),        # overshoot
        )
        _ears(img, cx, cy, rx, ry, *ears[i])

    elif state == "failed":
        # Progressive slump f0..f3 (ear droops over an eye, the brow patch
        # peels a corner, the tail falls flat), then settled sulk f4..f7.
        settle = ease_in_out(min(1.0, i / 3))
        squash = 1.0 + 0.20 * settle + 0.015 * math.sin(ph)
        cx, cy, rx, ry, bot = _body(img, 0, squash)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, bot)
        _paw(img, cx - 7, bot - 3)
        _paw(img, cx + 7, bot - 3)
        # Tail sinks from a half-wag to flat along the ground.
        sag = follow(t, 0.1, 0.8)
        theta = 0.5 - 0.75 * settle
        co, to = _wag(theta, drop=2.0 + 2 * settle)
        base = _tail_base(cx, cy, rx, ry)
        _tail(img, base, co, (to[0], min(to[1] + sag, GROUND - 1 - base[1])))
        sweat_drop(img, int(cx + 16), cy - ry + 6 * t)
        if i == 0:
            ey = _face(img, cx, cy, ry, mood="open", mstyle="open")
        elif i == 1:
            ey = _face(img, cx, cy, ry, mood="open", look=(0, 1), mstyle="wobble")
        else:
            ey = _face(img, cx, cy, ry, mood="sad", look=(0, 1), mstyle="wobble")
        _brow_patch(img, int(round(cx)), ey, peel=round(3 * settle), t=t)
        if i >= 3:  # a single tear from the eye that can still see
            tear(img, int(cx) + 10, ey + 8 + min(i - 3, 2))
        # The gray ear just sags lower and lower...
        bl, br = _ear_bases(cx, cy, rx, ry)
        _limb(img, br, (br[0] + 6, br[1] + 4),
              (br[0] + 7 + 2 * settle, br[1] + 15 + 2 * settle),
              GY, 2.4, 3.0, seam="root")
        # ...while the navy ear slides fully over the left eye (drawn last).
        eye_l = (cx - 10, ey + 4)
        rest_tip = (bl[0] - 6, bl[1] + 14)
        tip = (rest_tip[0] + (eye_l[0] - rest_tip[0]) * settle,
               rest_tip[1] + (eye_l[1] - rest_tip[1]) * settle)
        ctrl = (bl[0] - 6 + 4 * settle, bl[1] + 3 - settle)
        _limb(img, bl, ctrl, tip, N, 2.4, 3.0 + 0.5 * settle, seam="root")

    elif state == "waiting":
        squash = 1.0 + 0.02 * math.sin(ph)
        cx, cy, rx, ry, bot = _body(img, 0, squash, lean=1)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, bot)
        _paw(img, cx - 7, bot - 3)
        _paw(img, cx + 7, bot - 3)
        # The tail tip curls up into the question hook...
        f = ease_in_out(min(1.0, t * 3))
        wob = follow(t, 0.15, 1.0)
        base = _tail_base(cx, cy, rx, ry)
        _tail(img, base, (7 * f + 3 * (1 - f), -6 * f - 2),
              (2 * f + 9 * (1 - f), -11 * f - 1 + wob))
        # ...and the gold beacon hovers overhead like the siblings'.
        attention_dot(img, int(cx + 2), int(cy - ry - 9) + bob(t, 1.0), t=t)
        # Head tilt: face shifts 2px, ears hang asymmetrically.
        ey = _face(img, cx, cy, ry, mood="closed" if i == n - 1 else "open",
                   look=(1, 0), dx=2)
        _brow_patch(img, int(round(cx)), ey, dx=2)
        _ears(img, cx, cy, rx, ry,
              ((0, -1), (-6, 1), (-6, 10 + wob)),
              ((1, 1), (6, 4), (6, 16)))

    elif state == "running":  # focused work: determined digging
        press = math.sin(2 * ph)
        e_l, e_r = ease_out(max(0.0, press)), ease_out(max(0.0, -press))
        cx, cy, rx, ry, bot = _body(img, 0, 1.0 + 0.05 * abs(press),
                                    lean=round(2 * press))
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, bot)
        _paw(img, cx - 8 - 4 * e_l, bot - 2 + e_l)
        _paw(img, cx + 8 + 4 * e_r, bot - 2 + e_r)
        if abs(press) > 0.5:  # effort puff where the paw hits
            side = -1 if press > 0 else 1
            _puff(img, int(cx + side * 15), GROUND - 5 - (i % 2), i % 3 == 2)
        # Tail wags double-time — work is fun when you're a puppy.
        co, to = _wag(0.8 + 0.3 * follow(t * 2, 0.2))
        _tail(img, _tail_base(cx, cy, rx, ry), co, to)
        look_x = -1 if press > 0.2 else (1 if press < -0.2 else 0)
        ey = _face(img, cx, cy, ry, mood="focused", look=(look_x, 1), mstyle="line")
        _brow_patch(img, int(round(cx)), ey)
        flap_l = 0.5 + 0.5 * math.sin(2 * math.pi * (2 * t - 0.12))
        flap_r = 0.5 + 0.5 * math.sin(2 * math.pi * (2 * t - 0.28))
        _ears(img, cx, cy, rx, ry,
              ((0, 0), (-6, 3), (-6, 14 - 4 * flap_l)),
              ((0, 0), (6, 3), (6, 14 - 4 * flap_r)))

    elif state == "review":
        cx, cy, rx, ry, bot = _body(img, 0, 1.0)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, bot)
        # A cream thread lies across the ground, pinned under the left paw;
        # a gold marker scans it and the eyes track along.
        tri = 1.0 - abs(2 * t - 1.0)
        scan = ease_in_out(tri)
        strand(img, [(cx - 16, GROUND - 2), (cx - 4, GROUND - 1),
                     (cx + 8, GROUND - 2), (cx + 19, GROUND - 3)], C[3])
        _paw(img, cx - 13, GROUND - 3)
        _paw(img, cx + 7, bot - 3)
        gx = int(round(cx - 10 + 26 * scan))
        put(img, gx, GROUND - 3, G[3])
        put(img, gx, GROUND - 4, G[4])
        # Tail rests in a slow attentive drift.
        co, to = _wag(0.6 + 0.15 * follow(t, 0.18))
        _tail(img, _tail_base(cx, cy, rx, ry), co, to)
        look_x = max(-1, min(1, int(round(-1 + 2 * scan))))
        ey = _face(img, cx, cy, ry, mood="focused", look=(look_x, 1), mstyle="line")
        _brow_patch(img, int(round(cx)), ey)
        # Gag: the gray ear cups up like a listening dish.
        cup_wob = follow(t, 0.2, 0.8)
        _ears(img, cx, cy, rx, ry,
              _ear_rest(-1),
              ((0, 0), (6, -5), (3 + cup_wob, -10)))

    else:  # pragma: no cover - unknown states fall back to a static body
        cx, cy, rx, ry, bot = _body(img, 0, 1.0)
        img = auto_outline(img)
        _details(img, cx, cy, rx, ry, bot)
        _paw(img, cx - 7, bot - 3)
        _paw(img, cx + 7, bot - 3)
        co, to = _wag(0.55)
        _tail(img, _tail_base(cx, cy, rx, ry), co, to)
        ey = _face(img, cx, cy, ry, cheeks=True)
        _brow_patch(img, int(round(cx)), ey)
        _ears(img, cx, cy, rx, ry, _ear_rest(-1), _ear_rest(1))

    return img
