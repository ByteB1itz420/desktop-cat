"""Procedural, resolution-independent cat drawing with cairo.

Cat-local coordinates: origin at the feet (ground contact point), +x is the
direction the cat faces, y grows downward (so the cat lives at negative y).
One unit ~= one logical pixel at size 1.0.
"""
import math

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

OW = 1.6  # outline width
PI = math.pi

PALETTES = {
    "ginger": dict(coat=(0.99, 0.70, 0.40), dark=(0.91, 0.57, 0.29), stripe=(0.87, 0.48, 0.21),
                   belly=(1.0, 0.94, 0.84), outline=(0.36, 0.22, 0.15), ear=(1.0, 0.74, 0.74),
                   nose=(0.96, 0.50, 0.57), eye=(0.17, 0.12, 0.11), iris=None, tip=(0.87, 0.48, 0.21),
                   paw=None, muzzle=True),
    "grey": dict(coat=(0.71, 0.73, 0.79), dark=(0.58, 0.60, 0.67), stripe=(0.50, 0.52, 0.60),
                 belly=(0.95, 0.95, 0.97), outline=(0.22, 0.23, 0.29), ear=(1.0, 0.76, 0.80),
                 nose=(0.93, 0.56, 0.64), eye=(0.13, 0.13, 0.17), iris=None, tip=(0.50, 0.52, 0.60),
                 paw=None, muzzle=True),
    "black": dict(coat=(0.23, 0.23, 0.27), dark=(0.16, 0.16, 0.19), stripe=None,
                  belly=(0.30, 0.30, 0.35), outline=(0.06, 0.06, 0.08), ear=(0.80, 0.52, 0.60),
                  nose=(0.78, 0.45, 0.55), eye=(0.70, 0.88, 0.32), iris=True, tip=(0.16, 0.16, 0.19),
                  paw=None, muzzle=False),
    "cream": dict(coat=(1.0, 0.95, 0.87), dark=(0.92, 0.85, 0.75), stripe=None,
                  belly=(1.0, 1.0, 1.0), outline=(0.47, 0.38, 0.32), ear=(1.0, 0.76, 0.78),
                  nose=(0.96, 0.60, 0.65), eye=(0.20, 0.15, 0.14), iris=None, tip=(0.78, 0.64, 0.53),
                  paw=None, muzzle=True),
    "tuxedo": dict(coat=(0.20, 0.20, 0.24), dark=(0.14, 0.14, 0.17), stripe=None,
                   belly=(0.97, 0.97, 0.98), outline=(0.06, 0.06, 0.08), ear=(0.85, 0.55, 0.62),
                   nose=(0.90, 0.55, 0.62), eye=(0.95, 0.80, 0.30), iris=True, tip=(0.97, 0.97, 0.98),
                   paw=(0.97, 0.97, 0.98), muzzle=True),
}


def rgb(cr, c, a=1.0):
    cr.set_source_rgba(c[0], c[1], c[2], a)


def ellipse_path(cr, cx, cy, rx, ry, angle=0.0):
    cr.save()
    cr.translate(cx, cy)
    if angle:
        cr.rotate(angle)
    cr.scale(max(rx, 0.01), max(ry, 0.01))
    cr.new_sub_path()
    cr.arc(0, 0, 1, 0, 2 * PI)
    cr.restore()


def blob(cr, P, cx, cy, rx, ry, angle=0.0, fill=None, ow=OW):
    cr.new_path()
    ellipse_path(cr, cx, cy, rx, ry, angle)
    rgb(cr, fill or P["coat"])
    cr.fill_preserve()
    rgb(cr, P["outline"])
    cr.set_line_width(ow)
    cr.stroke()


def _path(cr, pts, curve):
    cr.new_path()
    cr.move_to(*pts[0])
    if curve and len(pts) == 4:
        cr.curve_to(*pts[1], *pts[2], *pts[3])
    else:
        for p in pts[1:]:
            cr.line_to(*p)


def limb(cr, P, pts, w, color, curve=False, ow=OW):
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    _path(cr, pts, curve)
    rgb(cr, P["outline"])
    cr.set_line_width(w + 2 * ow)
    cr.stroke()
    _path(cr, pts, curve)
    rgb(cr, color)
    cr.set_line_width(w)
    cr.stroke()


def bez(p0, p1, p2, p3, u):
    v = 1 - u
    return (v ** 3 * p0[0] + 3 * v * v * u * p1[0] + 3 * v * u * u * p2[0] + u ** 3 * p3[0],
            v ** 3 * p0[1] + 3 * v * v * u * p1[1] + 3 * v * u * u * p2[1] + u ** 3 * p3[1])


def tail(cr, P, p0, p1, p2, p3, w=5.4):
    """Tail with a darker (or lighter) tip, drawn as a thick outlined bezier."""
    limb(cr, P, [p0, p1, p2, p3], w, P["coat"], curve=True)
    pts = [bez(p0, p1, p2, p3, 0.80 + 0.2 * i / 5) for i in range(6)]
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.new_path()
    cr.move_to(*pts[0])
    for p in pts[1:]:
        cr.line_to(*p)
    rgb(cr, P["tip"])
    cr.set_line_width(w)
    cr.stroke()


def paw(cr, P, x, y=0.0, color=None):
    blob(cr, P, x + 1.2, y - 2.5, 4.3, 2.7, fill=color or P.get("paw") or P["coat"], ow=1.3)


def leg(cr, P, hip, foot, far=False, w=6.3):
    col = P["dark"] if far else P["coat"]
    if P.get("paw") and not far:
        col = P["coat"]
    limb(cr, P, [hip, (foot[0], foot[1] - 3.0)], w, col)
    paw(cr, P, foot[0], foot[1], color=(P["dark"] if far and not P.get("paw") else None))


def stripes_on(cr, P, shape, lines, w=2.6):
    """Clip to an ellipse shape (cx, cy, rx, ry, angle) and draw tabby stripes."""
    if not P.get("stripe"):
        return
    cr.save()
    cr.new_path()
    ellipse_path(cr, *shape)
    cr.clip()
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    rgb(cr, P["stripe"])
    cr.set_line_width(w)
    for (a, b) in lines:
        cr.new_path()
        cr.move_to(*a)
        cr.line_to(*b)
        cr.stroke()
    cr.restore()


def belly_on(cr, P, shape, bshape):
    cr.save()
    cr.new_path()
    ellipse_path(cr, *shape)
    cr.clip()
    cr.new_path()
    ellipse_path(cr, *bshape)
    rgb(cr, P["belly"])
    cr.fill()
    cr.restore()
    # re-stroke outline over belly edge
    cr.new_path()
    ellipse_path(cr, *shape)
    rgb(cr, P["outline"])
    cr.set_line_width(OW)
    cr.stroke()


# ----------------------------------------------------------------- head ----

def eye(cr, P, x, y, r, state, look, side):
    lx, ly = look
    if state in ("open", "wide", "angry", "half"):
        big = state == "wide"
        ew, eh = (0.19 * r, 0.25 * r) if big else (0.165 * r, 0.215 * r)
        cr.new_path()
        ellipse_path(cr, x, y, ew, eh)
        rgb(cr, P["eye"])
        cr.fill()
        if P.get("iris"):
            cr.new_path()
            ellipse_path(cr, x + lx * 0.04 * r, y + ly * 0.03 * r, ew * (0.62 if big else 0.42), eh * 0.92)
            rgb(cr, (0.05, 0.05, 0.06))
            cr.fill()
        # glints
        cr.new_path()
        cr.arc(x + 0.05 * r + lx * 0.04 * r, y - 0.08 * r + ly * 0.03 * r, 0.068 * r, 0, 2 * PI)
        cr.set_source_rgba(1, 1, 1, 0.95)
        cr.fill()
        cr.new_path()
        cr.arc(x - 0.05 * r + lx * 0.03 * r, y + 0.09 * r, 0.032 * r, 0, 2 * PI)
        cr.fill()
        if state == "half":
            cr.save()
            cr.rectangle(x - ew - 2, y - eh - 2, 2 * ew + 4, eh + 1.5)
            cr.clip()
            cr.new_path()
            ellipse_path(cr, x, y, ew + 0.6, eh + 0.6)
            rgb(cr, P["coat"])
            cr.fill()
            cr.restore()
            cr.new_path()
            cr.move_to(x - ew - 0.5, y - 0.3)
            cr.line_to(x + ew + 0.5, y - 0.3)
            rgb(cr, P["outline"])
            cr.set_line_width(0.07 * r)
            cr.stroke()
        if state == "angry":
            cr.new_path()
            cr.move_to(x - side * 0.22 * r, y - 0.36 * r)
            cr.line_to(x + side * 0.14 * r, y - 0.24 * r)
            rgb(cr, P["outline"])
            cr.set_line_width(0.075 * r)
            cr.stroke()
        return
    cr.new_path()
    rgb(cr, P["outline"] if P["coat"][0] > 0.4 else (0.9, 0.9, 0.9))
    cr.set_line_width(0.075 * r)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    if state == "closed":       # sleepy u-shape
        cr.move_to(x - 0.16 * r, y)
        cr.curve_to(x - 0.08 * r, y + 0.11 * r, x + 0.08 * r, y + 0.11 * r, x + 0.16 * r, y)
    elif state == "happy":      # ^ ^
        cr.move_to(x - 0.16 * r, y + 0.05 * r)
        cr.curve_to(x - 0.08 * r, y - 0.13 * r, x + 0.08 * r, y - 0.13 * r, x + 0.16 * r, y + 0.05 * r)
    else:                       # blink
        cr.move_to(x - 0.15 * r, y + 0.02 * r)
        cr.line_to(x + 0.15 * r, y + 0.02 * r)
    cr.stroke()


def head(cr, P, cx, cy, r, a, tilt=0.0, eyes=None, mouth=None, ear_flat=0.0):
    eyes = eyes or a.get("eyes", "open")
    mouth = mouth or a.get("mouth", "w")
    look = a.get("look", (0.0, 0.0))
    lx, ly = look
    cr.save()
    cr.translate(cx, cy)
    cr.rotate(tilt + a.get("head_tilt", 0.0))
    fx = 0.12 * r + lx * 0.10 * r
    fy = ly * 0.07 * r
    ear_flat = max(ear_flat, a.get("ear_flat", 0.0))
    tw = a.get("ear_twitch", 0.0)

    # ears
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    for side in (-1, 1):
        twitch = tw if side == -1 else 0.0
        tip = (side * (0.80 * r + ear_flat * 0.25 * r) + fx * 0.3, -1.20 * r + ear_flat * 0.42 * r + twitch * 0.14 * r)
        outer = (side * 1.04 * r, -0.28 * r)
        inner = (side * 0.16 * r + fx * 0.2, -0.86 * r)
        cr.new_path()
        cr.move_to(*outer)
        cr.line_to(*tip)
        cr.line_to(*inner)
        cr.close_path()
        rgb(cr, P["coat"])
        cr.fill_preserve()
        rgb(cr, P["outline"])
        cr.set_line_width(OW)
        cr.stroke()
        c = ((outer[0] + tip[0] + inner[0]) / 3, (outer[1] + tip[1] + inner[1]) / 3 + 0.08 * r)
        k = 0.55
        cr.new_path()
        for i, p in enumerate((outer, tip, inner)):
            q = (c[0] + (p[0] - c[0]) * k, c[1] + (p[1] - c[1]) * k)
            (cr.move_to if i == 0 else cr.line_to)(*q)
        cr.close_path()
        rgb(cr, P["ear"])
        cr.fill()

    # head shape
    blob(cr, P, 0, 0, 1.14 * r, 0.97 * r)
    stripes_on(cr, P, (0, 0, 1.14 * r, 0.97 * r, 0),
               [((-0.30 * r + fx * 0.4, -1.0 * r), (-0.22 * r + fx * 0.4, -0.62 * r)),
                ((0.0 + fx * 0.4, -1.05 * r), (0.0 + fx * 0.4, -0.58 * r)),
                ((0.30 * r + fx * 0.4, -1.0 * r), (0.22 * r + fx * 0.4, -0.62 * r)),
                ((-1.2 * r, 0.05 * r), (-0.85 * r, 0.1 * r)),
                ((1.2 * r, 0.05 * r), (0.85 * r, 0.1 * r))],
               w=0.11 * r)

    if P.get("muzzle"):
        cr.new_path()
        ellipse_path(cr, fx, 0.36 * r + fy, 0.40 * r, 0.27 * r)
        rgb(cr, P["belly"], 0.95)
        cr.fill()

    # blush
    blush = a.get("blush", 0.45)
    if blush > 0:
        for side in (-1, 1):
            cr.new_path()
            ellipse_path(cr, fx + side * 0.66 * r, 0.24 * r + fy, 0.16 * r, 0.095 * r)
            cr.set_source_rgba(1.0, 0.50, 0.58, 0.55 * blush)
            cr.fill()

    for side in (-1, 1):
        eye(cr, P, fx + side * 0.43 * r, -0.04 * r + fy, r, eyes, look, side)

    # nose
    nx, ny = fx, 0.22 * r + fy
    cr.new_path()
    cr.move_to(nx - 0.085 * r, ny - 0.03 * r)
    cr.line_to(nx + 0.085 * r, ny - 0.03 * r)
    cr.line_to(nx, ny + 0.06 * r)
    cr.close_path()
    rgb(cr, P["nose"])
    cr.set_line_width(0.05 * r)
    cr.fill_preserve()
    cr.stroke()

    # mouth
    my = ny + 0.06 * r
    rgb(cr, P["outline"])
    cr.set_line_width(0.055 * r)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    if mouth in ("open", "yawn", "chew"):
        amt = a.get("mouth_open", 1.0)
        rx, ry = (0.17 * r, 0.22 * r) if mouth == "yawn" else (0.11 * r, 0.10 * r)
        ry *= max(0.25, amt)
        cr.new_path()
        ellipse_path(cr, nx, my + ry + 0.02 * r, rx, ry)
        cr.set_source_rgb(0.55, 0.16, 0.22)
        cr.fill_preserve()
        rgb(cr, P["outline"])
        cr.stroke()
        cr.new_path()
        ellipse_path(cr, nx, my + 1.6 * ry + 0.02 * r, rx * 0.6, ry * 0.42)
        cr.set_source_rgb(1.0, 0.55, 0.62)
        cr.fill()
    else:
        cr.new_path()
        cr.move_to(nx, my - 0.01 * r)
        cr.line_to(nx, my + 0.04 * r)
        cr.move_to(nx - 0.17 * r, my + 0.07 * r)
        cr.curve_to(nx - 0.13 * r, my + 0.15 * r, nx - 0.02 * r, my + 0.14 * r, nx, my + 0.04 * r)
        cr.curve_to(nx + 0.02 * r, my + 0.14 * r, nx + 0.13 * r, my + 0.15 * r, nx + 0.17 * r, my + 0.07 * r)
        cr.stroke()
        if mouth == "tongue":
            cr.new_path()
            ellipse_path(cr, nx + 0.03 * r, my + 0.15 * r, 0.06 * r, 0.075 * r)
            cr.set_source_rgb(1.0, 0.52, 0.60)
            cr.fill_preserve()
            rgb(cr, P["outline"])
            cr.set_line_width(0.035 * r)
            cr.stroke()

    # whiskers
    rgb(cr, P["outline"] if P["coat"][0] > 0.4 else (0.85, 0.85, 0.85), 0.55)
    cr.set_line_width(0.035 * r)
    for side in (-1, 1):
        for k in (-1, 1):
            cr.new_path()
            cr.move_to(fx + side * 0.52 * r, ny + 0.06 * r + k * 0.05 * r)
            cr.line_to(fx + side * 1.42 * r, ny + 0.02 * r + k * 0.16 * r)
            cr.stroke()
    cr.restore()


# ---------------------------------------------------------------- poses ----

def pose_stand(cr, P, a):
    t = a["t"]
    ph = a.get("phase", 0.0)
    moving = a.get("moving", False)
    run = a.get("run", False)
    crouch = a.get("crouch", 0.0)
    sway = a.get("tail", 0.0)
    bob = abs(math.sin(ph)) * (2.2 if run else 1.4) if moving else 0.0
    by = -24 + crouch * 7 - bob
    stride = 9.0 if run else 6.5

    def foot(off):
        if not moving:
            return 0.0, 0.0
        s = math.sin(ph + off)
        return s * stride, -max(0.0, math.cos(ph + off)) * (4.0 if run else 2.6)

    wig = math.sin(t * 22) * 1.6 * crouch if a.get("wiggle") else 0.0
    # far legs
    for hx, off in ((-10.0 + wig, 0.0), (15.0, PI)):
        dx, lift = foot(off)
        leg(cr, P, (hx, by + 7), (hx + dx, lift), far=True)
    # tail
    if run:
        tail(cr, P, (-19, by - 2), (-30, by - 4), (-38, by - 9 + sway * 3), (-47, by - 12 + sway * 5))
    else:
        tail(cr, P, (-19, by - 3), (-31, by - 5), (-34 + sway * 3, by - 22), (-28 + sway * 8, by - 33))
    # body
    shape = (wig * 0.3, by, 22, 12.5, 0.0)
    blob(cr, P, *shape[:4])
    belly_on(cr, P, shape, (3, by + 7, 15, 6.5, 0.0))
    stripes_on(cr, P, shape, [((x, by - 14), (x + 2.5, by - 4)) for x in (-12, -5, 2)])
    # near legs
    for hx, off in ((-13.0 + wig, PI), (12.0, 0.0)):
        dx, lift = foot(off)
        leg(cr, P, (hx, by + 7), (hx + dx, lift))
    head(cr, P, 21, by - 12 + crouch * 4, 12.5, a, tilt=0.05 if run else 0.0)


def pose_sit(cr, P, a):
    br = a.get("breathe", 0.0)
    flick = a.get("tail", 0.0)
    paw_up = a.get("paw_up", None)
    # far front leg
    leg(cr, P, (10, -22), (10.5, 0), far=True, w=5.8)
    # haunch
    blob(cr, P, -7, -9.5, 13.5, 9.5)
    stripes_on(cr, P, (-7, -9.5, 13.5, 9.5, 0), [((-12, -19), (-9, -11)), ((-5, -19), (-3, -12))])
    # body (chest leans forward)
    shape = (0, -21 - br * 0.4, 11.5, 16.5 + br * 0.4, 0.2)
    blob(cr, P, *shape)
    belly_on(cr, P, shape, (6.5, -19, 6.0, 11.5, 0.2))
    stripes_on(cr, P, shape, [((-12, -30), (-6, -28)), ((-12, -22), (-6, -21))])
    # tail curled around the front on the floor
    tail(cr, P, (-18, -4), (-28, 0.5), (-10, 1.0), (14 + flick * 2.5, -3.0 - abs(flick) * 4.0), w=5.2)
    # near front leg (maybe raised for grooming / batting)
    if paw_up is not None:
        k = paw_up
        leg(cr, P, (5, -24), (11 + 3 * k, -31 - 3 * k), w=6.0)
    else:
        leg(cr, P, (5, -22), (5.5, 0), w=6.2)
    head(cr, P, 6, -41 - br * 0.7, 13, a, tilt=a.get("tilt", 0.0))


def pose_loaf(cr, P, a):
    br = a.get("breathe", 0.0)
    flick = a.get("tail", 0.0)
    shape = (-2, -12 - br * 0.4, 21, 12 + br * 0.4, 0.0)
    blob(cr, P, *shape)
    stripes_on(cr, P, shape, [((x, -26), (x + 2, -16)) for x in (-14, -7, 0)])
    tail(cr, P, (-20, -5), (-26, 2), (-6, 2), (12 + flick * 2, -2.0), w=5.0)
    if a.get("knead"):
        k = math.sin(a["t"] * 7)
        leg(cr, P, (8, -10), (15, -max(0.0, k) * 4), far=True, w=5.6)
        leg(cr, P, (11, -10), (19, -max(0.0, -k) * 4), w=5.8)
    else:
        blob(cr, P, 15, -2.8, 5.2, 3.0, fill=P.get("paw") or P["coat"], ow=1.3)
        blob(cr, P, 9, -2.6, 5.0, 2.8, fill=P.get("paw") or P["coat"], ow=1.3)
    head(cr, P, 15, -23 - br * 0.6, 12.5, a, tilt=a.get("tilt", 0.0))


def pose_sleep(cr, P, a):
    b = a.get("breathe", 0.0)
    ry = 11.0 + b * 0.8
    shape = (-3, -ry, 24, ry, 0.0)
    blob(cr, P, *shape)
    belly_on(cr, P, shape, (8, -2, 12, 5, 0.0))
    stripes_on(cr, P, shape, [((x, -ry * 2), (x + 3, -ry)) for x in (-18, -10, -2)])
    tail(cr, P, (-25, -6), (-28, 4), (6, 3.5), (21, -2.8), w=5.2)
    blob(cr, P, 19, -3.0, 5.2, 3.0, fill=P.get("paw") or P["coat"], ow=1.3)
    head(cr, P, 12, -11.5 - b * 0.5, 11.5, a, tilt=0.28, eyes="closed", mouth="w", ear_flat=0.15)


def pose_jump(cr, P, a):
    vy = a.get("vy", 0.0)
    ang = max(-0.45, min(0.5, vy / 1100.0))
    falling = vy > 120
    cr.save()
    cr.translate(0, -22)
    cr.rotate(ang)
    cr.translate(0, 22)
    leg(cr, P, (-11, -21), (-27, -13), far=True)
    if falling:
        leg(cr, P, (15, -21), (23, -4), far=True)
    else:
        leg(cr, P, (15, -24), (31, -29), far=True)
    tail(cr, P, (-20, -26), (-32, -28), (-40, -31), (-49, -36 + math.sin(a["t"] * 9) * 3))
    shape = (0, -24, 24, 11, 0.0)
    blob(cr, P, *shape[:4])
    belly_on(cr, P, shape, (3, -17, 16, 6, 0.0))
    stripes_on(cr, P, shape, [((x, -36), (x + 2.5, -27)) for x in (-12, -5, 2)])
    leg(cr, P, (-14, -20), (-31, -9))
    if falling:
        leg(cr, P, (12, -20), (20, -1))
    else:
        leg(cr, P, (12, -23), (30, -23))
    head(cr, P, 24, -35, 12.5, a, eyes=a.get("eyes") if a.get("eyes") != "open" else ("wide" if falling else "open"))
    cr.restore()


def pose_dangle(cr, P, a):
    t = a["t"]
    sw = math.sin(t * 2.4) * 0.10 + a.get("swing", 0.0)
    cr.save()
    cr.translate(0, -62)
    cr.rotate(sw)
    cr.translate(0, 62)
    k = math.sin(t * 5)
    tail(cr, P, (0, -14), (1, -2), (-6, 6), (-3 + math.sin(t * 3) * 7, 13), w=5.0)
    leg(cr, P, (-6, -16), (-7 - k, 1), far=True, w=5.8)
    leg(cr, P, (6, -16), (7 + k, 1), w=5.8)
    shape = (0, -29, 11.5, 17.5, 0.0)
    blob(cr, P, *shape[:4])
    belly_on(cr, P, shape, (0, -26, 7, 12, 0.0))
    leg(cr, P, (-6, -40), (-7, -27 + k), w=5.6)
    leg(cr, P, (6, -40), (7, -27 - k), w=5.6)
    head(cr, P, 0, -51, 13.5, dict(a, look=(0.0, 0.2)), tilt=0.0)
    cr.restore()


def pose_stretch(cr, P, a):
    sway = a.get("tail", 0.0)
    leg(cr, P, (-11, -24), (-10, 0), far=True)
    leg(cr, P, (12, -11), (27, 0), far=True)
    tail(cr, P, (-20, -29), (-26, -42), (-19, -54), (-26 + sway * 5, -63))
    shape = (-1, -20, 22, 10, 0.32)
    blob(cr, P, *shape)
    belly_on(cr, P, shape, (3, -13, 15, 5, 0.32))
    stripes_on(cr, P, shape, [((x, -38 + (x + 10) * 0.3), (x + 3, -24 + (x + 10) * 0.3)) for x in (-14, -6, 2)])
    leg(cr, P, (-15, -23), (-15, 0))
    leg(cr, P, (9, -10), (23, 0))
    head(cr, P, 27, -14, 12, a, tilt=-0.15)


def pose_scratch(cr, P, a):
    """Up on hind legs, scratching at something in front."""
    k = math.sin(a["t"] * 12)
    sway = a.get("tail", 0.0)
    tail(cr, P, (-13, -6), (-25, -2), (-33, -6 + sway * 2), (-40, -15 + sway * 4), w=5.2)
    leg(cr, P, (-4, -14), (-1, 0), far=True)
    leg(cr, P, (7, -42), (21, -55 - k * 3), far=True, w=5.6)
    blob(cr, P, -6, -10, 12, 9)
    shape = (1, -31, 10.5, 18, 0.45)
    blob(cr, P, *shape)
    belly_on(cr, P, shape, (6, -30, 5.5, 12, 0.45))
    stripes_on(cr, P, shape, [((-12, -38), (-5, -36)), ((-10, -28), (-3, -27))])
    leg(cr, P, (-2, -14), (2, 0))
    head(cr, P, 9, -55, 12.5, a, tilt=-0.1)
    leg(cr, P, (5, -40), (20, -48 + k * 3), w=5.8)


POSES = {
    "scratch": pose_scratch,
    "stand": pose_stand,
    "sit": pose_sit,
    "loaf": pose_loaf,
    "sleep": pose_sleep,
    "jump": pose_jump,
    "dangle": pose_dangle,
    "stretch": pose_stretch,
}

# approximate top of the drawing (ears) per pose, in cat units (negative y)
POSE_TOP = {"scratch": -80, "stand": -64, "sit": -70, "loaf": -48, "sleep": -38, "jump": -62, "dangle": -80, "stretch": -66}


def draw_cat(cr, P, pose, x, y, scale, facing, a, squash=0.0):
    cr.save()
    cr.translate(x, y)
    cr.scale(scale * facing * (1 + squash), scale * (1 - squash))
    POSES[pose](cr, P, a)
    cr.restore()


# -------------------------------------------------------------- effects ----

def heart(cr, x, y, size, alpha=1.0):
    cr.new_path()
    cr.move_to(x, y + size * 0.55)
    cr.curve_to(x - size * 1.1, y - size * 0.15, x - size * 0.55, y - size * 1.0, x, y - size * 0.35)
    cr.curve_to(x + size * 0.55, y - size * 1.0, x + size * 1.1, y - size * 0.15, x, y + size * 0.55)
    cr.close_path()
    cr.set_source_rgba(1.0, 0.42, 0.58, alpha)
    cr.fill_preserve()
    cr.set_source_rgba(0.55, 0.12, 0.25, alpha)
    cr.set_line_width(1.2)
    cr.stroke()


def star(cr, x, y, size, alpha=1.0, rot=0.0):
    cr.new_path()
    for i in range(10):
        r = size if i % 2 == 0 else size * 0.45
        ang = rot + i * PI / 5 - PI / 2
        (cr.move_to if i == 0 else cr.line_to)(x + r * math.cos(ang), y + r * math.sin(ang))
    cr.close_path()
    cr.set_source_rgba(1.0, 0.85, 0.3, alpha)
    cr.fill_preserve()
    cr.set_source_rgba(0.6, 0.4, 0.1, alpha)
    cr.set_line_width(1.0)
    cr.stroke()


def zzz(cr, x, y, size, alpha=1.0):
    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(size)
    cr.move_to(x, y)
    cr.text_path("z")
    cr.set_source_rgba(1, 1, 1, alpha)
    cr.fill_preserve()
    cr.set_source_rgba(0.25, 0.25, 0.4, alpha)
    cr.set_line_width(1.2)
    cr.stroke()


def draw_particles(cr, particles):
    for p in particles:
        alpha = max(0.0, min(1.0, p["life"] / p["max"] * 1.5))
        kind = p["kind"]
        if kind == "heart":
            heart(cr, p["x"], p["y"], p["size"], alpha)
        elif kind == "star":
            star(cr, p["x"], p["y"], p["size"], alpha, p.get("rot", 0.0))
        elif kind == "z":
            zzz(cr, p["x"], p["y"], p["size"], alpha)
        elif kind == "text":
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(p["size"])
            cr.move_to(p["x"], p["y"])
            cr.text_path(p["text"])
            cr.set_source_rgba(1, 1, 1, alpha)
            cr.fill_preserve()
            cr.set_source_rgba(0.3, 0.2, 0.2, alpha)
            cr.set_line_width(1.0)
            cr.stroke()


_measure_cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4))


def make_layout(cr, text, px=13, bold=True, max_w=None):
    lay = PangoCairo.create_layout(cr)
    fd = Pango.FontDescription.from_string("Sans Bold" if bold else "Sans")
    fd.set_absolute_size(px * Pango.SCALE)
    lay.set_font_description(fd)
    if max_w:
        lay.set_width(int(max_w * Pango.SCALE))
        lay.set_wrap(Pango.WrapMode.WORD_CHAR)
    lay.set_alignment(Pango.Alignment.CENTER)
    lay.set_text(text, -1)
    return lay


def measure(text, px=13, bold=True, max_w=None):
    lay = make_layout(_measure_cr, text, px, bold, max_w)
    _ink, log = lay.get_pixel_extents()
    return log.width, log.height


def rounded_rect(cr, x, y, w, h, r):
    cr.new_path()
    cr.arc(x + w - r, y + r, r, -PI / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, PI / 2)
    cr.arc(x + r, y + h - r, r, PI / 2, PI)
    cr.arc(x + r, y + r, r, PI, 3 * PI / 2)
    cr.close_path()


def draw_bubble(cr, rect, tail_x, down, text, alpha=1.0):
    x, y, w, h = rect
    r = 10
    tx = max(x + r + 8, min(x + w - r - 8, tail_x))
    cr.new_path()
    cr.move_to(x + r, y)
    if not down:
        cr.line_to(tx - 7, y)
        cr.line_to(tx, y - 9)
        cr.line_to(tx + 7, y)
    cr.line_to(x + w - r, y)
    cr.arc(x + w - r, y + r, r, -PI / 2, 0)
    cr.line_to(x + w, y + h - r)
    cr.arc(x + w - r, y + h - r, r, 0, PI / 2)
    if down:
        cr.line_to(tx + 7, y + h)
        cr.line_to(tx, y + h + 9)
        cr.line_to(tx - 7, y + h)
    cr.line_to(x + r, y + h)
    cr.arc(x + r, y + h - r, r, PI / 2, PI)
    cr.line_to(x, y + r)
    cr.arc(x + r, y + r, r, PI, 3 * PI / 2)
    cr.close_path()
    cr.set_source_rgba(1, 0.99, 0.97, 0.97 * alpha)
    cr.fill_preserve()
    cr.set_source_rgba(0.30, 0.22, 0.20, alpha)
    cr.set_line_width(1.6)
    cr.stroke()
    lay = make_layout(cr, text, 13, True, w - 20)
    _ink, log = lay.get_pixel_extents()
    cr.move_to(x + 10, y + (h - log.height) / 2)
    cr.set_source_rgba(0.24, 0.17, 0.16, alpha)
    PangoCairo.show_layout(cr, lay)


BADGE_COLORS = {
    "focus": (0.95, 0.38, 0.36),
    "short": (0.30, 0.70, 0.52),
    "long": (0.28, 0.55, 0.85),
    "paused": (0.55, 0.55, 0.60),
}


def draw_badge(cr, rect, text, kind, progress=None):
    x, y, w, h = rect
    c = BADGE_COLORS.get(kind, BADGE_COLORS["paused"])
    rounded_rect(cr, x, y, w, h, h / 2)
    cr.set_source_rgba(c[0], c[1], c[2], 0.95)
    cr.fill_preserve()
    cr.set_source_rgba(c[0] * 0.5, c[1] * 0.5, c[2] * 0.5, 1)
    cr.set_line_width(1.4)
    cr.stroke()
    if progress is not None:
        cr.save()
        rounded_rect(cr, x + 3, y + h - 5, w - 6, 3, 1.5)
        cr.set_source_rgba(1, 1, 1, 0.25)
        cr.fill()
        rounded_rect(cr, x + 3, y + h - 5, max(3, (w - 6) * progress), 3, 1.5)
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.fill()
        cr.restore()
    lay = make_layout(cr, text, 12, True)
    _ink, log = lay.get_pixel_extents()
    cr.move_to(x + (w - log.width) / 2, y + (h - log.height) / 2 - (1 if progress is not None else 0))
    cr.set_source_rgb(1, 1, 1)
    PangoCairo.show_layout(cr, lay)


# ------------------------------------------------------------------ toys ----

BOX = (0.84, 0.64, 0.42)
BOX_DARK = (0.66, 0.47, 0.28)
BOX_LINE = (0.40, 0.27, 0.15)


def _poly(cr, pts, fill, line=BOX_LINE, lw=1.5):
    cr.new_path()
    cr.move_to(*pts[0])
    for p in pts[1:]:
        cr.line_to(*p)
    cr.close_path()
    rgb(cr, fill)
    cr.fill_preserve()
    rgb(cr, line)
    cr.set_line_width(lw)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.stroke()


def draw_box_back(cr, x, y, s):
    w, h = 56 * s, 32 * s
    top = y - h
    for side in (-1, 1):
        bx = x + side * w / 2
        _poly(cr, [(bx, top), (bx + side * 13 * s, top - 15 * s), (bx - side * 15 * s, top - 18 * s),
                   (bx - side * 25 * s, top)], BOX)
    _poly(cr, [(x - w / 2, top), (x - w / 2 + 6 * s, top - 7 * s), (x + w / 2 - 6 * s, top - 7 * s), (x + w / 2, top)],
          (0.42, 0.29, 0.17))


def draw_box_front(cr, x, y, s):
    w, h = 56 * s, 32 * s
    x0, top = x - w / 2, y - h
    rounded_rect(cr, x0, top, w, h, 2.5 * s)
    rgb(cr, BOX)
    cr.fill_preserve()
    rgb(cr, BOX_LINE)
    cr.set_line_width(1.6)
    cr.stroke()
    cr.rectangle(x0 + w * 0.80, top + 1, w * 0.2 - 1, h - 2)
    rgb(cr, BOX_DARK, 0.35)
    cr.fill()
    cr.rectangle(x - 4.5 * s, top + 0.8, 9 * s, h * 0.42)
    cr.set_source_rgba(0.95, 0.87, 0.68, 0.95)
    cr.fill()
    heart(cr, x0 + 12 * s, top + h * 0.62, 4 * s, 0.85)


def draw_ball(cr, x, y, r, rot):
    cx, cy = x, y - r
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.new_path()
    cr.move_to(cx - r * 0.3, cy + r * 0.9)
    cr.curve_to(cx - r * 1.4, y + 1, cx - r * 2.2, y - 4, cx - r * 3.3, y - 1)
    cr.set_source_rgb(0.93, 0.36, 0.47)
    cr.set_line_width(1.6)
    cr.stroke()
    cr.new_path()
    cr.arc(cx, cy, r, 0, 2 * PI)
    cr.set_source_rgb(0.93, 0.36, 0.47)
    cr.fill_preserve()
    cr.save()
    cr.clip()
    cr.set_line_width(1.3)
    cr.set_source_rgba(1.0, 0.68, 0.74, 0.95)
    for k in range(4):
        cr.save()
        cr.translate(cx, cy)
        cr.rotate(rot + k * PI / 4)
        cr.scale(1.0, 0.35 + 0.16 * k)
        cr.new_path()
        cr.arc(0, 0, r * 0.95, 0, PI)
        cr.restore()
        cr.stroke()
    cr.restore()
    cr.new_path()
    cr.arc(cx, cy, r, 0, 2 * PI)
    cr.set_source_rgb(0.45, 0.12, 0.20)
    cr.set_line_width(1.4)
    cr.stroke()


def draw_treat(cr, x, y, s, rot=0.0):
    """A little fish-shaped cookie."""
    cr.save()
    cr.translate(x, y - 4 * s)
    cr.rotate(rot)
    cr.scale(s, s)
    cr.new_path()
    cr.move_to(-8, 0)
    cr.curve_to(-4, -6, 5, -6, 7, 0)
    cr.curve_to(5, 6, -4, 6, -8, 0)
    cr.close_path()
    cr.move_to(-7, 0)
    cr.line_to(-12, -4)
    cr.line_to(-12, 4)
    cr.close_path()
    cr.set_source_rgb(0.99, 0.62, 0.45)
    cr.fill_preserve()
    cr.set_source_rgb(0.55, 0.25, 0.15)
    cr.set_line_width(1.1)
    cr.stroke()
    cr.new_path()
    cr.arc(3.5, -1.2, 1.1, 0, 2 * PI)
    cr.fill()
    cr.restore()


def draw_butterfly(cr, x, y, t, color, perched=False):
    flap = abs(math.sin(t * (5 if perched else 15)))
    fw = 0.25 + 0.75 * flap
    cr.save()
    cr.translate(x, y)
    for side in (-1, 1):
        for (ox, oy, rx, ry, ang) in ((6.5, -3.5, 6.5, 5.5, 0.5), (4.5, 3.5, 4.5, 3.8, -0.4)):
            cr.new_path()
            ellipse_path(cr, side * ox * fw, oy, rx * fw + 0.6, ry, side * ang)
            cr.set_source_rgba(color[0], color[1], color[2], 0.95)
            cr.fill_preserve()
            cr.set_source_rgba(0.25, 0.2, 0.3, 0.9)
            cr.set_line_width(1.0)
            cr.stroke()
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_source_rgb(0.22, 0.18, 0.25)
    cr.set_line_width(2.2)
    cr.new_path()
    cr.move_to(0, -5)
    cr.line_to(0, 6)
    cr.stroke()
    cr.set_line_width(0.9)
    for side in (-1, 1):
        cr.new_path()
        cr.move_to(0, -5)
        cr.curve_to(side * 1, -9, side * 3, -10, side * 4, -11)
        cr.stroke()
    cr.restore()


def draw_cloud(cr, x, y, s, t, P1, P2):
    """Cartoon play-fight dust cloud with paws and tails flailing out of it."""
    cx, cy = x, y - 26 * s
    for i, (P, a0) in enumerate(((P1, 0.3), (P2, 2.0), (P1, 3.9), (P2, 5.2), (P1, 1.2), (P2, 4.4))):
        ang = a0 + math.sin(t * 9 + i * 1.7) * 0.7 + t * 2.2 * (1 if i % 2 else -1)
        r1 = (40 + 6 * math.sin(t * 14 + i)) * s
        p0 = (cx + math.cos(ang) * 12 * s, cy + math.sin(ang) * 10 * s)
        p1 = (cx + math.cos(ang) * r1, cy + math.sin(ang) * r1 * 0.75)
        if i < 4:
            limb(cr, P, [p0, p1], 6 * s, P["coat"], ow=1.5)
            blob(cr, P, p1[0], p1[1], 4.2 * s, 3.2 * s, angle=ang, fill=P.get("paw") or P["coat"], ow=1.3)
        else:
            mid = (cx + math.cos(ang + 0.6) * r1 * 0.7, cy + math.sin(ang + 0.6) * r1 * 0.6)
            limb(cr, P, [p0, mid, mid, p1], 5 * s, P["coat"], curve=True, ow=1.5)
    puffs = []
    for i in range(9):
        a = i / 9 * 2 * PI + math.sin(t * 6 + i) * 0.2
        rr = (22 + 4 * math.sin(t * 11 + i * 2)) * s
        puffs.append((cx + math.cos(a) * rr * 0.95, cy + math.sin(a) * rr * 0.62, (14 + 3 * math.sin(t * 13 + i)) * s))
    puffs.append((cx, cy, 20 * s))
    for (px, py, pr) in puffs:
        cr.new_path()
        cr.arc(px, py, pr, 0, 2 * PI)
        cr.set_source_rgb(0.40, 0.36, 0.34)
        cr.set_line_width(3.2)
        cr.stroke()
    for (px, py, pr) in puffs:
        cr.new_path()
        cr.arc(px, py, pr, 0, 2 * PI)
        cr.set_source_rgb(0.97, 0.95, 0.91)
        cr.fill()
    for i in range(3):
        a = t * 3 + i * 2.1
        star(cr, cx + math.cos(a) * 14 * s, cy + math.sin(a) * 8 * s, 4.5 * s, 0.9, a)
