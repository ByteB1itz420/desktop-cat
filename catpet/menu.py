"""A cute menu drawn inside the overlay (works with touchpads; no GTK popup grabs needed)."""
import gi

gi.require_version("PangoCairo", "1.0")
from gi.repository import PangoCairo  # noqa: E402

from . import render  # noqa: E402

W = 270
ROW = 28
SEP = 9
HEAD = 50
PAD = 8


class CatMenu:
    def __init__(self, app, sc, cat, page="main"):
        self.app, self.sc, self.cat = app, sc, cat
        self.page = page
        self.hover = -1
        self.away = 0.0
        self.rows = []
        self.layout = []
        self.rect = None
        self.rebuild()

    def rebuild(self):
        self.rows = self.app.menu_rows(self.page, self.cat)
        h = HEAD + sum(SEP if r["kind"] == "sep" else ROW for r in self.rows) + PAD
        w = self.sc.world
        c = self.cat
        s = c.s
        x = c.x + 42 * s if c.x + 42 * s + W < w.W - 6 else c.x - 42 * s - W
        x = max(6, min(w.W - W - 6, x))
        y = max(6, min(w.H - h - 6, c.y - h + 20))
        self.rect = (x, y, W, h)
        self.layout = []
        yy = y + HEAD
        for i, r in enumerate(self.rows):
            rh = SEP if r["kind"] == "sep" else ROW
            self.layout.append((yy, yy + rh, i))
            yy += rh

    def row_at(self, px, py):
        x, y, w, h = self.rect
        if not (x <= px <= x + w):
            return -1
        for y0, y1, i in self.layout:
            if y0 <= py < y1 and self.rows[i]["kind"] not in ("sep", "info"):
                return i
        return -1

    def sig(self):
        return (self.page, self.hover, tuple(r["label"] for r in self.rows), tuple(round(v) for v in self.rect),
                self.app.focus.label())

    def draw(self, cr):
        x, y, w, h = self.rect
        # shadow + card
        render.rounded_rect(cr, x + 2, y + 4, w, h, 14)
        cr.set_source_rgba(0, 0, 0, 0.22)
        cr.fill()
        render.rounded_rect(cr, x, y, w, h, 14)
        cr.set_source_rgba(1.0, 0.985, 0.965, 0.98)
        cr.fill_preserve()
        cr.set_source_rgba(0.32, 0.23, 0.20, 1)
        cr.set_line_width(1.6)
        cr.stroke()
        # header
        c = self.cat
        lay = render.make_layout(cr, f"🐱 {c.name}", 15, True)
        lay.set_alignment(0)
        cr.move_to(x + 14, y + 7)
        cr.set_source_rgb(0.24, 0.17, 0.16)
        PangoCairo.show_layout(cr, lay)
        sub = render.make_layout(cr, self.app.mood_line(c), 11, False)
        sub.set_alignment(0)
        cr.move_to(x + 14, y + 28)
        cr.set_source_rgb(0.45, 0.36, 0.33)
        PangoCairo.show_layout(cr, sub)
        cr.move_to(x + 10, y + HEAD - 3)
        cr.line_to(x + w - 10, y + HEAD - 3)
        cr.set_source_rgba(0.32, 0.23, 0.20, 0.25)
        cr.set_line_width(1)
        cr.stroke()
        # rows
        for (y0, y1, i) in self.layout:
            r = self.rows[i]
            kind = r["kind"]
            if kind == "sep":
                cr.move_to(x + 14, (y0 + y1) / 2)
                cr.line_to(x + w - 14, (y0 + y1) / 2)
                cr.set_source_rgba(0.32, 0.23, 0.20, 0.18)
                cr.stroke()
                continue
            if i == self.hover:
                render.rounded_rect(cr, x + 6, y0 + 1, w - 12, y1 - y0 - 2, 8)
                cr.set_source_rgba(1.0, 0.80, 0.70, 0.75)
                cr.fill()
            info = kind == "info"
            lay = render.make_layout(cr, r["label"], 11.5 if info else 13, not info)
            lay.set_alignment(0)
            _ink, log = lay.get_pixel_extents()
            cr.move_to(x + 14, y0 + (y1 - y0 - log.height) / 2)
            if info:
                cr.set_source_rgb(0.50, 0.42, 0.40)
            else:
                cr.set_source_rgb(0.24, 0.17, 0.16)
            PangoCairo.show_layout(cr, lay)
            right = None
            if kind == "nav" and not r["label"].startswith("‹"):
                right = "›"
            elif kind == "check":
                right = "✅" if r.get("on") else "⬜"
            if right:
                rl = render.make_layout(cr, right, 13, True)
                _ink, lg = rl.get_pixel_extents()
                cr.move_to(x + w - 16 - lg.width, y0 + (y1 - y0 - lg.height) / 2)
                cr.set_source_rgb(0.45, 0.36, 0.33)
                PangoCairo.show_layout(cr, rl)
