#!/usr/bin/env python3
"""Render every pose / palette to a PNG sheet (handy for tweaking the art)."""
import sys
import cairo
from catpet import render

out = sys.argv[1] if len(sys.argv) > 1 else "preview.png"
poses = [
    ("stand", {}), ("stand", {"moving": True, "phase": 1.0}), ("stand", {"moving": True, "run": True, "phase": 2.2}),
    ("stand", {"crouch": 1.0, "wiggle": True}), ("sit", {}), ("sit", {"eyes": "happy", "blush": 1.0}),
    ("sit", {"paw_up": 0.5, "eyes": "closed", "mouth": "tongue", "tilt": -0.12}), ("sit", {"mouth": "yawn", "eyes": "closed"}),
    ("sit", {"eyes": "angry", "mouth": "open", "ear_flat": 0.7}), ("sit", {"eyes": "half"}), ("loaf", {}), ("sleep", {}),
    ("jump", {"vy": -500}), ("jump", {"vy": 600}), ("dangle", {"eyes": "wide", "mouth": "open"}), ("stretch", {"eyes": "happy", "mouth": "yawn"}),
]
palettes = list(render.PALETTES)
S = 2.0
cw, ch = 140 * S, 110 * S
surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(cw * len(poses) / 2), int(ch * 2 * len(palettes)))
cr = cairo.Context(surf)
cr.set_source_rgb(0.86, 0.89, 0.93)
cr.paint()
for pi_, pal in enumerate(palettes):
    for i, (pose, extra) in enumerate(poses):
        col, row = i % (len(poses) // 2), i // (len(poses) // 2) + pi_ * 2
        x, y = col * cw + cw / 2, row * ch + ch - 14 * S
        cr.set_source_rgb(0.7, 0.72, 0.76)
        cr.rectangle(col * cw + 10, y, cw - 20, 2)
        cr.fill()
        a = {"t": 0.3, "look": (0.3, 0.1), "tail": 0.3}
        a.update(extra)
        render.draw_cat(cr, render.PALETTES[pal], pose, x, y, S * 1.2, 1, a)
render.draw_particles(cr, [{"kind": "heart", "x": 60, "y": 30, "size": 9, "life": 1, "max": 1},
                           {"kind": "z", "x": 90, "y": 30, "size": 16, "life": 1, "max": 1}])
surf.write_to_png(out)
print(out)
