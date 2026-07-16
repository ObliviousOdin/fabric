"""Bobbin v3 "The Spoolkin" — the set's exemplar character.

Bobbin is no longer a spool with a face: it is a small porcelain-cream
gumdrop critter that WEARS a spool — top flange as a flat cap (axle hole,
gold rim stitches), a violet band of wound thread hugging its middle like a
cozy jumper, the body flaring into a cream skirt-hem (the bottom flange),
stubby mitten nubs, rounded navy feet — and a springy thread AHOGE curling
from the cap's axle hole. The ahoge is Bobbin's soul: it perks, streams,
wilts, and curls into question marks, carrying emotion in every row. A
second loose end exits the wrap as a thread tail, Bobbin's tool arm.

Built to the research-driven redesign brief: infant-schema face low on the
head, one signature gag per row, cap that lags and floats at motion apexes
("gap of sky"), a high-drama unravel on failed, and loops that land back on
frame 0.
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
    sparkle,
    strand,
    sweat_drop,
    tear,
)

NAME = "Bobbin"
SLUG = "bobbin"
DESCRIPTION = "A porcelain spoolkin with a thread ahoge and a cozy wound-thread jumper."

V = RAMPS["violet"]
N = RAMPS["navy"]
C = RAMPS["cream"]
G = RAMPS["gold"]

# Rest-pose landmarks (half-res px). Cap top y=38, foot bottoms y=100.
CAP_W, CAP_H = 36, 8
CAP_TOP = 38
CROWN_Y = 44  # body starts under the cap
WRAP_TOP, WRAP_BOT = 68, 88
HEM_BOT = 96  # feet fill 95..100


def _widths(y: float) -> float:
    """Gumdrop silhouette half-width at rest-pose *y* (no waist pinch)."""
    pts = [(42.0, 14.0), (52.0, 17.0), (68.0, 19.0), (78.0, 20.0), (88.0, 21.0), (93.0, 22.0), (96.0, 20.0)]
    if y <= pts[0][0]:
        return pts[0][1]
    for (y0, w0), (y1, w1) in zip(pts, pts[1:]):
        if y <= y1:
            f = ease_in_out((y - y0) / (y1 - y0))
            return w0 + (w1 - w0) * f
    return pts[-1][1]


class Pose:
    """Per-frame body transform: lift (dy<0 = airborne), squash, lean."""

    def __init__(self, dy: float = 0.0, squash: float = 1.0, lean: float = 0.0, wrap_h: float = WRAP_BOT - WRAP_TOP):
        self.dy = dy
        self.squash = squash
        self.lean = lean
        self.wrap_h = wrap_h

    def map_y(self, y: float) -> float:
        """Map a rest-pose y to the posed y (anchored at the hem bottom)."""
        return HEM_BOT + self.dy - (HEM_BOT - y) / self.squash

    def width(self, y_rest: float) -> float:
        return _widths(y_rest) * self.squash

    # Landmark helpers (posed coordinates).
    @property
    def crown(self) -> float:
        return self.map_y(CROWN_Y)

    @property
    def cap_top(self) -> float:
        return self.map_y(CAP_TOP)

    @property
    def wrap_top(self) -> float:
        return self.map_y(WRAP_BOT - self.wrap_h)

    @property
    def wrap_bot(self) -> float:
        return self.map_y(WRAP_BOT)

    @property
    def hem_bot(self) -> float:
        return self.map_y(HEM_BOT)


def _silhouette(img, p: Pose, *, feet_phase: float | None = None, cap_float: float = 0.0, cap_dx: float = 0.0, arms: bool = True):
    """Pre-outline color mass: body, hem, feet, mitts, and the floating cap."""
    d = ImageDraw.Draw(img)
    cx = CX + p.lean

    # Feet: rounded navy pads, planted at the (possibly lifted) ground line.
    if feet_phase is None:
        lifts = (0.0, 0.0)
    else:
        step = math.sin(2 * math.pi * feet_phase)
        lifts = (max(0.0, step) * 3, max(0.0, -step) * 3)
    ground = GROUND + min(p.dy, 0)
    for side, lift in zip((-1, 1), lifts):
        fx = cx + side * 9
        d.rounded_rectangle((fx - 4, ground - 5 - lift, fx + 4, ground - lift), radius=2, fill=N[1])

    # Gumdrop body: per-row spans following the width curve.
    y = p.crown
    while y <= p.hem_bot:
        y_rest = HEM_BOT - (HEM_BOT + p.dy - y) * p.squash
        w = p.width(y_rest)
        d.line((cx - w, y, cx + w, y), fill=C[3])
        y += 1.0
    # Rounded crown dome above the crown line, tucked under the cap.
    dome_w = p.width(46.0)
    d.ellipse((cx - dome_w, p.cap_top + CAP_H / 2, cx + dome_w, p.crown + 8), fill=C[3])

    # Mitten nubs just above the wrap.
    if arms:
        ay = p.map_y(65.0)
        aw = p.width(66.0)
        for side in (-1, 1):
            axx = cx + side * (aw + 1)
            d.rounded_rectangle((axx - 2, ay, axx + 2, ay + 6), radius=2, fill=C[3])

    # The cap — a separate mass so it can lag, tilt, and float (gap of sky).
    cap_y = p.cap_top - cap_float
    d.ellipse(
        (cx + cap_dx - CAP_W / 2, cap_y, cx + cap_dx + CAP_W / 2, cap_y + CAP_H),
        fill=C[2],
    )
    return cap_y


def _shade(img, p: Pose, cap_y: float, *, cap_dx: float = 0.0, wind_phase: float = 0.0, gold_glint: bool = False, progress: float | None = None):
    """Post-outline detail pass: body ramps, wrap bands, cap face, stitches."""
    d = ImageDraw.Draw(img)
    cx = CX + p.lean

    # Body shading: warm light high-left crescent, cool shadow low-right,
    # C[1] rim inside the hem bottom. The lit crown IS the face plate.
    dome_w = p.width(48.0)
    d.arc((cx - dome_w + 1, p.crown - 6, cx + dome_w - 3, p.crown + 14), 150, 250, fill=C[4])
    shadow_top = p.map_y(60.0)
    dither_shade(img, (cx + p.width(70.0) - 5, shadow_top, cx + p.width(88.0) + 1, p.hem_bot - 1), C[2], phase=1)
    d.line((cx - p.width(95.0) + 2, p.hem_bot - 1, cx + p.width(95.0) - 2, p.hem_bot - 1), fill=C[1])
    d.line((cx - p.width(94.0) + 2, p.hem_bot - 2, cx + p.width(94.0) - 2, p.hem_bot - 2), fill=C[2])

    # Wound-thread wrap: banded violet jumper with a lit left column and a
    # deep right/bottom rim. Bands scroll with wind_phase.
    top, bot = p.wrap_top, p.wrap_bot
    wleft = cx - p.width(78.0) + 1
    wright = cx + p.width(78.0) - 1
    d.rectangle((wleft, top, wright, bot), fill=V[2])
    yy = top + (wind_phase % 1.0) * 3
    row = 0
    while yy < bot:
        d.line((wleft, yy, wright, yy), fill=V[1] if row % 2 == 0 else V[3])
        yy += 3
        row += 1
    dither_shade(img, (wleft, top, wleft + 4, bot), V[4])
    d.line((wright, top + 1, wright, bot), fill=V[0])
    d.line((wleft, bot, wright, bot), fill=V[0])
    if progress is not None:  # working gag: a gold stitch rides a band row
        px = wleft + 2 + (wright - wleft - 4) * progress
        py = top + 4 + 3 * (int(progress * 6) % 4)
        put(img, px, py, G[2])
        put(img, px + 1, py, G[3])

    # Cap detail: top face, highlight arc, underside shadow + forehead cast,
    # ink-ringed axle hole with navy core, five gold rim stitches.
    ccx = cx + cap_dx
    d.ellipse((ccx - CAP_W / 2 + 2, cap_y + 1, ccx + CAP_W / 2 - 2, cap_y + CAP_H - 2), fill=C[3])
    d.arc((ccx - CAP_W / 2 + 3, cap_y + 1, ccx + CAP_W / 2 - 5, cap_y + CAP_H - 3), 150, 280, fill=C[4])
    d.arc((ccx - CAP_W / 2, cap_y, ccx + CAP_W / 2, cap_y + CAP_H), 20, 130, fill=C[0])
    d.line((cx - 9, p.crown + 1, cx + 9, p.crown + 1), fill=C[1])  # cast shadow on brow
    d.ellipse((ccx - 3, cap_y + 1, ccx + 3, cap_y + 4), outline=INK, fill=N[0])
    for k, sx in enumerate((-14, -7, 0, 7, 14)):
        color = G[4] if (gold_glint and k == 2) else G[2]
        put(img, ccx + sx, cap_y + CAP_H - 1, color)


def _face(img, p: Pose, *, mood="open", look=(0, 0), mouth_mood="smile", cheeks=False):
    cx = CX + p.lean
    ey = p.map_y(52.0)
    anime_eye_lg(img, int(cx - 9), int(ey), mood=mood, look=look)
    anime_eye_lg(img, int(cx + 6), int(ey), mood=mood, look=look)
    mouth(img, int(cx), int(ey + 9), mouth_mood)
    if cheeks:
        blush(img, int(cx - 13), int(ey + 6))
        blush(img, int(cx + 11), int(ey + 6))


def _ahoge(img, p: Pose, cap_y: float, pose: str, t: float, *, cap_dx: float = 0.0):
    """The soul strand: rooted at the axle hole, pose per row."""
    cx = CX + p.lean + cap_dx
    root = (cx, cap_y + 1)
    if pose == "perk":  # fully vertical, proud
        pts = [(cx, cap_y - 4), (cx + 1, cap_y - 8), (cx, cap_y - 12)]
    elif pose == "rest":
        sway = follow(t, 0.15, 2)
        pts = [(cx + 1, cap_y - 4), (cx + 2 + sway, cap_y - 8), (cx - 1 + sway, cap_y - 11)]
    elif pose == "flick":  # idle life-beat: tip snaps up
        pts = [(cx + 1, cap_y - 4), (cx + 2, cap_y - 9), (cx + 3, cap_y - 13)]
    elif pose == "stream":  # running: streams straight back
        whip = follow(t * 2, 0.2, 3)
        pts = [(cx - 5, cap_y - 2), (cx - 10, cap_y - 3 + whip / 2), (cx - 14, cap_y - 1 + whip)]
    elif pose == "flat":  # jump anticipation: flattened sideways
        pts = [(cx + 4, cap_y - 1), (cx + 8, cap_y), (cx + 11, cap_y + 1)]
    elif pose == "down":  # airborne: streams downward
        pts = [(cx + 3, cap_y - 2), (cx + 5, cap_y + 3), (cx + 6, cap_y + 8)]
    elif pose == "wilt":  # failed: draped over the cap edge
        droop = min(1.0, t * 3)
        pts = [
            (cx + 3, cap_y - 3 + 3 * droop),
            (cx + 7, cap_y - 2 + 5 * droop),
            (cx + 10, cap_y + 6 * droop),
        ]
    elif pose == "hook":  # waiting: curls into a question mark
        f = ease_in_out(min(1.0, t * 3))
        wob = 1 if (int(t * 6) % 2 == 0 and t > 0.4) else 0
        pts = [
            (cx + 2, cap_y - 5),
            (cx + 4 + 2 * f, cap_y - 9 - f),
            (cx + 2 + 2 * f + wob, cap_y - 12 - 2 * f),
            (cx - 1 + f, cap_y - 10 - 2 * f),
        ]
        strand(img, [root, *pts], V[2], thick=True)
        strand(img, [root, *pts], V[1])
        put(img, pts[-1][0], pts[-1][1], C[4])
        put(img, cx + 2, cap_y - 6, V[1])  # the question dot
        return
    elif pose == "whip":  # working: counter-whips the tail orbit
        whip = follow(t, 0.2, 3)
        pts = [(cx - whip, cap_y - 5), (cx - 2 * whip, cap_y - 9), (cx - whip, cap_y - 12)]
    else:
        pts = [(cx, cap_y - 6), (cx, cap_y - 10)]
    strand(img, [root, pts[0]], V[2], thick=True)
    strand(img, pts, V[1])
    put(img, pts[-1][0], pts[-1][1], C[4])


def _tail(img, p: Pose, pts, *, tip=True):
    """Thread tail exiting the wrap low-right, Bobbin's tool arm."""
    cx = CX + p.lean
    anchor = (cx + p.width(80.0) - 1, p.map_y(80.0))
    strand(img, [anchor, *pts], V[1])
    if tip and pts:
        put(img, pts[-1][0], pts[-1][1], C[4])


def draw(state: str, i: int, n: int):
    img = canvas()
    t = i / n
    ph = 2 * math.pi * t

    if state == "idle":
        breath = math.sin(ph)
        p = Pose(dy=-max(0.0, breath), squash=1.0 + 0.02 * breath)
        cap_y = _silhouette(img, p)
        img = auto_outline(img)
        _shade(img, p, cap_y, gold_glint=(i == 2))
        _ahoge(img, p, cap_y, "flick" if i == 2 else "rest", t)
        drift = follow(t, 0.15, 4)
        _tail(img, p, [(CX + 24, p.map_y(84.0) + drift / 2), (CX + 28, p.map_y(88.0) + drift)])
        _face(img, p, mood="closed" if i == n - 1 else "open", mouth_mood="smile", cheeks=True)

    elif state == "running-right":
        bounce = ease_out(abs(math.sin(2 * ph)))
        p = Pose(dy=-4 * bounce, squash=1.0 + 0.07 * (1 - bounce), lean=3)
        cap_lag = 1.0 if bounce > 0.8 else 0.0  # cap floats at the apex
        cap_y = _silhouette(img, p, feet_phase=t * 2, cap_float=cap_lag)
        img = auto_outline(img)
        _shade(img, p, cap_y)
        _ahoge(img, p, cap_y, "stream", t)
        whip = follow(t * 2, 0.35, 3)
        _tail(img, p, [(CX - 14, p.map_y(78.0) - whip), (CX - 22, p.map_y(80.0) + whip)])
        if i in (2, 6):  # max-velocity smear
            sy = int(p.map_y(70.0))
            for k in range(3):
                put(img, CX - 20 - k, sy + k, C[2])
        motion_ticks(img, CX - 20, int(p.map_y(64.0)), 1)
        _face(img, p, mood="focused", look=(1, 0), mouth_mood="line")

    elif state == "waving":
        dip = 1.0 if i == 0 else 0.0
        p = Pose(dy=dip)
        cap_y = _silhouette(img, p)
        img = auto_outline(img)
        _shade(img, p, cap_y)
        _ahoge(img, p, cap_y, "perk", t)
        # The thread tail is the flag arm: anticipation low, overshoot apex.
        sweep = (0.0, 0.75, 1.0, 0.55)[i]
        ang = math.pi * (0.05 + 0.75 * sweep)
        ax, ay = CX + 20, p.map_y(70.0)
        tipx = ax + 16 * math.cos(ang)
        tipy = ay - 20 * math.sin(ang) + (2 if i == 2 else 0)
        _tail(img, p, [(ax, ay - 10 * sweep), (tipx, tipy)])
        if i == 2:
            sparkle(img, int(tipx) + 2, int(tipy) - 2, small=True)
        _face(img, p, mood="happy", mouth_mood="open", cheeks=True)

    elif state == "jumping":
        # Symmetric arc peaked at the middle frame: f0 crouch, f1 rise,
        # f2 apex (hat float + sparkle), f3 descend, f4 landing squash.
        arc = math.sin(math.pi * i / (n - 1))
        if i == 0:
            p = Pose(squash=1.22)
            cap_y = _silhouette(img, p, cap_float=-1)  # pressed onto brows
        elif i == n - 1:
            p = Pose(squash=1.12)
            cap_y = _silhouette(img, p, cap_float=-1)
        else:
            p = Pose(dy=-14 * arc, squash=1.0 - 0.06 * arc)
            cap_y = _silhouette(img, p, cap_float=2 * arc)  # hat float gag
        img = auto_outline(img)
        _shade(img, p, cap_y)
        _ahoge(img, p, cap_y, "flat" if i in (0, n - 1) else "down", t)
        _tail(img, p, [(CX + 24, p.map_y(86.0) + 6 * arc), (CX + 26, p.map_y(90.0) + 9 * arc)])
        if i == 2:
            sparkle(img, CX - 26, int(p.cap_top) + 2)
            sparkle(img, CX + 27, int(p.crown) + 4, small=True)
        happy = i != 0
        _face(img, p, mood="happy" if happy else "focused", mouth_mood="open" if happy else "line", cheeks=happy)

    elif state == "failed":
        settle = ease_in_out(min(1.0, i / 3))  # slump-in over f0..f3, then hold
        sulk = 0.5 * math.sin(ph)
        wrap_h = 20 - 6 * settle  # the wrap unravels away
        p = Pose(dy=4 * settle + max(0.0, sulk), squash=1.0 + 0.14 * settle, wrap_h=wrap_h)
        cap_y = _silhouette(img, p, cap_dx=2 * settle)
        img = auto_outline(img)
        _shade(img, p, cap_y, cap_dx=2 * settle)
        _ahoge(img, p, cap_y, "wilt", t if i != 5 else t + 0.05, cap_dx=2 * settle)
        # The unravelled thread piles up beside the hem as sagging loops.
        loops = int(1 + 2 * settle)
        base_y = p.hem_bot + 1
        for k in range(loops):
            x0 = CX + 14 + k * 7 - 4 * k
            sag = 4 + k * 2 + math.sin(ph + k)
            strand(img, [(x0, base_y - 2), (x0 + 5, base_y - 2 + sag / 2), (x0 + 10, base_y - 2)], V[1])
        if i >= 3:
            tear(img, CX + 12, p.map_y(58.0) + (i - 3))
        sweat_drop(img, CX + CAP_W // 2 + 6, cap_y + 5 + 5 * t)
        _face(img, p, mood="sad", look=(0, 1), mouth_mood="wobble")

    elif state == "waiting":
        p = Pose(dy=-max(0.0, math.sin(ph)) * 0.7)
        cap_y = _silhouette(img, p)
        img = auto_outline(img)
        _shade(img, p, cap_y)
        _ahoge(img, p, cap_y, "hook", t)
        # Tail patience-tap: lifts on f1, taps on f2.
        tap = 2 if i == 1 else 0
        _tail(img, p, [(CX + 24, p.map_y(88.0) - tap), (CX + 27, p.map_y(92.0) - tap)])
        attention_dot(img, CX, cap_y - 8 + bob(t, 1.5), t=t)
        look = (0, -1) if (i // 2) % 2 == 0 else (-1, -1)
        _face(img, p, mood="closed" if i == n - 1 else "open", look=look, mouth_mood="line")

    elif state == "running":  # working in place: winding the day's thread
        beat = abs(math.sin(ph * 1.5))
        p = Pose(dy=-2.5 * beat, squash=1.0 + 0.05 * (1 - beat))
        rattle = 1 if i % 2 == 0 else -1
        cap_y = _silhouette(img, p, cap_dx=rattle)
        img = auto_outline(img)
        _shade(img, p, cap_y, cap_dx=rattle, wind_phase=t * 3, progress=(t * 2) % 1.0)
        _ahoge(img, p, cap_y, "whip", t, cap_dx=rattle)
        ang = ph * 2
        r = p.width(78.0) + 8
        wx, wy = CX + r * math.cos(ang), p.map_y(78.0) + 7 * math.sin(ang)
        _tail(img, p, [((CX + p.width(80.0) + wx) / 2, (p.map_y(80.0) + wy) / 2 - 3), (wx, wy)])
        _face(img, p, mood="focused", look=(1 if math.cos(ang) > 0 else -1, 0), mouth_mood="line")

    elif state == "review":
        nod = i == n - 1
        p = Pose(dy=1.0 if nod else 0.0)
        cap_y = _silhouette(img, p, cap_float=-1 if nod else 0)
        img = auto_outline(img)
        _shade(img, p, cap_y)
        _ahoge(img, p, cap_y, "rest", t)
        # A taut cream reading thread: left mitten pinch, tail holds right.
        line_y = p.map_y(62.0)
        strand(img, [(CX - 22, line_y + 2), (CX - 18, line_y), (CX + 18, line_y), (CX + 22, line_y + 2)], C[3])
        _tail(img, p, [(CX + 24, p.map_y(72.0)), (CX + 22, line_y + 2)], tip=False)
        scan = ease_in_out(min(1.0, t * (n / (n - 1.5))))
        sx = CX - 12 + 24 * scan
        put(img, sx, line_y, G[2])
        put(img, sx, line_y - 1, G[3])
        if nod:
            _face(img, p, mood="happy", mouth_mood="smile", cheeks=True)
        else:
            look_x = max(-1, min(1, int(round((sx - CX) / 6))))
            _face(img, p, mood="focused", look=(look_x, 1), mouth_mood="line")

    else:  # pragma: no cover
        p = Pose()
        cap_y = _silhouette(img, p)
        img = auto_outline(img)
        _shade(img, p, cap_y)
        _ahoge(img, p, cap_y, "rest", t)
        _face(img, p)

    return img
