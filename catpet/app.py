"""Transparent, click-through overlays (wlr layer-shell), one per monitor, hosting the cats."""
import datetime
import glob
import math
import os
import random
import shutil
import socket
import subprocess
import sys
import time

import json

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell
except (ValueError, ImportError):
    GtkLayerShell = None
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import config, render  # noqa: E402
from .cat import Cat, Platform, World, clamp  # noqa: E402
from .focus import MODE_NAME, Focus  # noqa: E402
from .hypr import Hypr  # noqa: E402
from .menu import CatMenu  # noqa: E402
from .settings_ui import GoalDialog, SettingsWindow  # noqa: E402
from .sound import Sound  # noqa: E402
from .toys import Ball, Box, Butterfly, Treat  # noqa: E402

AWAY_AFTER = 300.0  # seconds without cursor movement = user is away
RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
CONTROL_SOCK = os.path.join(RUNTIME_DIR, "desktop-cat.sock")
# lives in tmpfs: survives app restarts within a session, wiped at logout / reboot
SESSION_STATE = os.path.join(RUNTIME_DIR, "desktop-cat-state.json")


def rect_union(rects):
    rects = [r for r in rects if r]
    if not rects:
        return None
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    return (x0, y0, x1 - x0, y1 - y0)


def irect(r, pad=4):
    x, y, w, h = r
    return (int(math.floor(x)) - pad, int(math.floor(y)) - pad, int(math.ceil(w)) + 2 * pad, int(math.ceil(h)) + 2 * pad)


def inside(r, x, y):
    return r is not None and r[0] <= x <= r[0] + r[2] and r[1] <= y <= r[1] + r[3]


MOTION_STATES = {"run", "jump", "fall", "dragged", "chase", "pursue", "hunt", "tussle", "spin", "celebrate"}
SLOW_STATES = {"walk", "approach", "crouch", "ready", "land", "swipe"}
GENTLE_STATES = {"petted", "eat", "knead", "groom", "allogroom", "scratch", "yawn", "stretch", "slowblink",
                 "alert", "annoyed", "boop"}
# frame interval (ms) per activity tier: (on AC, on battery / power-saver)
FRAME_MS = {"motion": (33, 40), "slow": (50, 55), "gentle": (66, 80), "idle": (125, 166), "off": (1000, 1000)}


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def power_state():
    """(on_battery, battery_percent or None, power_saver_profile)"""
    saver = _read("/sys/firmware/acpi/platform_profile") in ("low-power", "quiet", "cool")
    ac = None
    for p in glob.glob("/sys/class/power_supply/*/online"):
        if _read(p) == "1":
            ac = True
        elif ac is None:
            ac = False
    pct, discharging = None, False
    for bat in glob.glob("/sys/class/power_supply/BAT*"):
        cap = _read(os.path.join(bat, "capacity"))
        if cap and cap.isdigit():
            pct = int(cap)
        if _read(os.path.join(bat, "status")) == "Discharging":
            discharging = True
    on_battery = discharging or ac is False
    return on_battery, pct, saver


def cat_screen(app, cat):
    return next((sc for sc in app.screens.values() if sc.world is cat.w), None)


class Overlay(Gtk.Window):
    def __init__(self, app, screen, gdk_monitor):
        super().__init__()
        self.app = app
        self.screen_ = screen
        self.set_app_paintable(True)
        self.set_decorated(False)
        vis = self.get_screen().get_rgba_visual()
        if vis:
            self.set_visual(vis)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "desktop-cat")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        try:
            GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        except AttributeError:
            GtkLayerShell.set_keyboard_interactivity(self, False)
        if gdk_monitor is not None:
            GtkLayerShell.set_monitor(self, gdk_monitor)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK
                        | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.connect("draw", lambda _w, cr: app.draw(screen, cr))
        self.connect("size-allocate", lambda _w, al: screen.world.set_size(al.width, al.height))
        self.connect("button-press-event", lambda _w, ev: app.on_press(screen, ev))
        self.connect("button-release-event", lambda _w, ev: app.on_release(screen, ev))
        self.connect("motion-notify-event", lambda _w, ev: app.on_motion(screen, ev))
        self.connect("scroll-event", lambda _w, ev: app.on_scroll(screen, ev))
        self.connect("realize", lambda *_: app.update_input(screen, force=True))


class Screen:
    """One monitor: its world (floor + window tops) and its overlay window."""

    def __init__(self, app, mon, gdk_mon):
        self.name = mon["name"]
        self.update_geom(mon)
        self.world = World(self.name)
        self.world.set_size(*self.lsize)
        self.prev = []
        self.cache = {}
        self.input_rects = None
        self.hud = {}
        self.overlay = Overlay(app, self, gdk_mon)
        self.overlay.show_all()

    def update_geom(self, mon):
        self.id = mon.get("id")
        self.ox, self.oy = mon.get("x", 0), mon.get("y", 0)
        sc = mon.get("scale") or 1.0
        w, h = mon.get("width", 1920), mon.get("height", 1080)
        if mon.get("transform", 0) % 2 == 1:
            w, h = h, w
        self.lsize = (int(round(w / sc)), int(round(h / sc)))
        self.mon = mon


class App:
    def __init__(self):
        self.cfg = config.load()
        self.hypr = Hypr()
        self.sound = Sound(self.cfg)
        self.focus = Focus(self.cfg)
        self.pets = config.PetData()
        self.pets.refill(self.cfg["daily_treats"])
        self.screens = {}
        self.cats = []
        self.toys = []
        self.butterflies = []
        self.started = False
        self.snooze_until = 0.0
        self.press = None
        self.stroke = []
        self.cursor_moved = time.monotonic()
        self.cursor_screen = None
        self.away = False
        self.last_tick = time.monotonic()
        self.poll = {"cursor": 0.0, "windows": 0.0, "guard": 0.0, "power": 0.0, "save": 30.0}
        self.guard_cooldown = 0.0
        self.next_bf = time.monotonic() + random.uniform(60, 180)
        self.next_bed = 0.0
        self.low_power = False
        self.on_battery = False
        self.battery_pct = None
        self.battery_off = False
        self.frame_ms = 16
        self.settings_win = None
        self.menu = None
        self._measure_cache = {}

        self.sync_screens(self.hypr.monitors())
        if not self.screens:
            self._fallback_screen()
        self.sync_cats()
        self.sync_toys()
        restored = self.restore_session()
        self.started = True
        self._timer = GLib.timeout_add(self.frame_ms, self.tick)
        if not restored:
            GLib.timeout_add(1400, self._greet)   # only on a fresh login / boot
        self._start_control()

    def _greet(self):
        names = " & ".join(c.name for c in self.cats)
        if self.cats:
            self.cats[0].say(f"hi! we're {names} 🐾" if len(self.cats) > 1 else f"hi! I'm {names} 🐾", 3.5, "meow")
        return False

    # ------------------------------------------------------------ screens --
    def _fallback_screen(self):
        disp = Gdk.Display.get_default()
        gm = disp.get_monitor(0)
        g = gm.get_geometry()
        mon = {"name": "default", "id": 0, "x": g.x, "y": g.y, "width": g.width, "height": g.height, "scale": 1}
        self.screens["default"] = Screen(self, mon, gm)

    def primary(self):
        for sc in self.screens.values():
            if sc.name.startswith("eDP"):
                return sc
        return next(iter(self.screens.values()), None)

    def sync_screens(self, mons):
        if not mons:
            return
        mons = [m for m in mons if not m.get("disabled")]
        names = {m["name"] for m in mons}
        changed = False
        for name in list(self.screens):
            if name not in names and name != "default":
                sc = self.screens.pop(name)
                sc.overlay.destroy()
                changed = True
        disp = Gdk.Display.get_default()
        gmons = [disp.get_monitor(i) for i in range(disp.get_n_monitors())]
        for m in mons:
            sc = self.screens.get(m["name"])
            if sc is not None:
                sc.update_geom(m)
                continue
            gm = next((g for g in gmons if g.get_geometry().x == m["x"] and g.get_geometry().y == m["y"]), None)
            if gm is None:
                gm = next((g for g in gmons if g.get_model() and g.get_model() == m.get("model")), None)
            if gm is None and len(gmons) == 1 and len(mons) == 1:
                gm = gmons[0]
            if gm is None:
                continue  # GTK hasn't seen this output yet; retry on the next poll
            sc = Screen(self, m, gm)
            self.screens[m["name"]] = sc
            changed = True
            if self.started:
                self.on_screen_added(sc)
        if changed:
            self.link_neighbors()
            self.rehome()

    def link_neighbors(self):
        scs = list(self.screens.values())
        for a in scs:
            a.world.neighbors = {"left": None, "right": None}
            for b in scs:
                if b is a:
                    continue
                if not (b.oy < a.oy + a.lsize[1] and a.oy < b.oy + b.lsize[1]):
                    continue
                if abs(b.ox + b.lsize[0] - a.ox) <= 4:
                    a.world.neighbors["left"] = b.world
                if abs(a.ox + a.lsize[0] - b.ox) <= 4:
                    a.world.neighbors["right"] = b.world

    def worlds(self):
        return [sc.world for sc in self.screens.values()]

    def home_world(self, idx):
        prim = self.primary()
        if idx == 0 or prim is None:
            return prim.world if prim else None
        others = [sc for sc in self.screens.values() if sc is not prim]
        return others[0].world if others else prim.world

    def rehome(self):
        """Anything living on a monitor that disappeared drops onto a remaining one."""
        worlds = self.worlds()
        if not worlds:
            return
        prim = self.primary().world
        for c in self.cats:
            if c.w not in worlds:
                c.drop_into(self.home_world(c.idx))
                c.say("whoa! 🙀", 1.5)
        for t in list(self.toys):
            if t.w not in worlds:
                if t.kind == "treat":
                    self.toys.remove(t)
                else:
                    t.drop_into(prim)
        self.butterflies = [b for b in self.butterflies if b.w in worlds]

    def on_screen_added(self, sc):
        if len(self.cats) < 2:
            return
        c = self.cats[1]
        if c.w is sc.world or c.w is not self.cats[0].w:
            return
        d = c.dir_to(sc.world)
        c.say("ooh, a new screen! 🖥️", 2.5, "meow")
        if not (d and c.plan_visit(d)):
            c.drop_into(sc.world)

    # ------------------------------------------------------- cats & toys --
    def sync_cats(self):
        want = [i for i, p in enumerate(self.cfg["cats"]) if i == 0 or p.get("enabled", True)]
        have = {c.idx: c for c in self.cats}
        for i in want:
            if i not in have:
                w = self.home_world(i)
                c = Cat(i, w, self.cfg, self.sound, bond=self.pets.bond(i))
                others = [o for o in self.cats if o.w is w]
                if others:
                    c.x = clamp(others[0].x + random.choice((-1, 1)) * random.uniform(150, 350), 60, w.W - 60)
                self.cats.append(c)
        for c in list(self.cats):
            if c.idx not in want:
                if c.box is not None:
                    c.box.occupant = None
                self.cats.remove(c)
        self.cats.sort(key=lambda c: c.idx)
        for c in self.cats:
            c.peers = self.cats

    def sync_toys(self):
        prim = self.primary()
        if prim is None:
            return
        s = float(self.cfg["size"])
        for kind, key, cls in (("ball", "toy_ball", Ball), ("box", "toy_box", Box)):
            have = [t for t in self.toys if t.kind == kind]
            if self.cfg[key] and not have:
                w = prim.world
                x = random.uniform(w.W * (0.15 if kind == "box" else 0.4), w.W * (0.35 if kind == "box" else 0.8))
                self.toys.append(cls(w, x, s))
            elif not self.cfg[key]:
                for t in have:
                    if getattr(t, "occupant", None) is not None:
                        t.occupant.start_fall()
                    self.toys.remove(t)
        for t in self.toys:
            t.s = s

    def toss_treat(self, near=None):
        self.pets.refill(self.cfg["daily_treats"])
        speaker = near or self.speaker()
        if speaker is None:
            return
        if self.pets.jar <= 0:
            speaker.say("the treat jar is empty 😿\nfinish a focus session to earn more!", 4.0, "meow")
            return
        self.pets.add(-1)
        self.pets.save()
        w = speaker.w
        if w.cursor and near is None:
            x, y = w.cursor
        else:
            x, y = speaker.x + speaker.facing * random.uniform(60, 140), speaker.y - 160
        x = clamp(x, 20, w.W - 20)
        self.toys.append(Treat(w, x, max(40, y), float(self.cfg["size"])))

    def assign_treats(self):
        for tr in [t for t in self.toys if t.kind == "treat"]:
            if tr.eaten:
                self.toys.remove(tr)
                continue
            if not tr.grounded or tr.dragged:
                continue
            claim = tr.claimed_by
            if claim is not None and (claim.target is not tr or claim.w is not tr.w):
                tr.claimed_by = None
                tr.retry = getattr(tr, "retry", 0) + 1
            if tr.claimed_by is None and getattr(tr, "retry", 0) < 4:
                cands = [c for c in self.cats if c.w is tr.w and c.state not in ("dragged", "tussle", "eat")
                         and not c.airborne and not isinstance(c.target, Treat)]
                cands.sort(key=lambda c: abs(c.x - tr.x) + abs(c.y - tr.y))
                if cands:
                    tr.claimed_by = cands[0]
                    cands[0].plan_treat(tr)
                    if len(cands) > 1 and random.random() < 0.5:   # a race!
                        cands[1].plan_treat(tr)
            if tr.age > 240:
                self.toys.remove(tr)

    def speaker(self):
        """The cat on the screen you're using does the talking."""
        if self.cursor_screen is not None:
            here = [c for c in self.cats if c.w is self.cursor_screen.world]
            if here:
                return here[0]
        return self.cats[0] if self.cats else None

    # -------------------------------------------------------------- polling --
    def poll_cursor(self, now):
        c = self.hypr.cursor()
        if c is None:
            return
        gx, gy = c
        if self.cursor_screen is not None and self.cursor_screen.world.cursor is not None:
            ow = self.cursor_screen
            lc = ow.world.cursor
            if abs(gx - ow.ox - lc[0]) + abs(gy - ow.oy - lc[1]) > 1:
                self.cursor_moved = now
        self.cursor_screen = None
        for sc in self.screens.values():
            lx, ly = gx - sc.ox, gy - sc.oy
            if 0 <= lx < sc.world.W and 0 <= ly < sc.world.H:
                sc.world.cursor = (lx, ly)
                self.cursor_screen = sc
            else:
                sc.world.cursor = None
            sc.world.cursor_still = (now - self.cursor_moved) if sc.world.cursor else 0.0

    def poll_windows(self, mons):
        clients = self.hypr.clients()
        s = float(self.cfg["size"])
        for sc in self.screens.values():
            mon = next((m for m in mons if m.get("name") == sc.name), None)
            if mon is None:
                continue
            ws = {mon["activeWorkspace"]["id"]}
            if mon.get("specialWorkspace", {}).get("id"):
                ws.add(mon["specialWorkspace"]["id"])
            plats = []
            fullscreen = False
            for c in clients:
                if not c.get("mapped", True) or c.get("hidden"):
                    continue
                if c["workspace"]["id"] not in ws and not c.get("pinned"):
                    continue
                if c.get("monitor") != mon["id"]:
                    continue
                if c.get("fullscreen") and c["workspace"]["id"] == mon["activeWorkspace"]["id"]:
                    fullscreen = True
                x0 = c["at"][0] - sc.ox
                y = c["at"][1] - sc.oy
                x1 = x0 + c["size"][0]
                x0, x1 = max(8, x0), min(sc.world.W - 8, x1)
                if y < 78 * s or x1 - x0 < 70 or y > sc.world.H - 40:
                    continue
                plats.append(Platform(c.get("address", str(len(plats))), x0, x1, y))
            sc.world.set_windows(plats)
            sc.world.hidden = fullscreen and self.cfg["hide_fullscreen"]

    def check_distraction(self):
        if not (self.cfg["distraction_guard"] and self.focus.focusing):
            return
        w = self.hypr.active_window()
        if not w:
            return
        hay = f"{w.get('title', '')} {w.get('class', '')}".lower()
        words = [k.strip().lower() for k in self.cfg["distraction_keywords"].split(",") if k.strip()]
        hit = next((k for k in words if k in hay), None)
        if hit and time.monotonic() > self.guard_cooldown:
            self.guard_cooldown = time.monotonic() + 75
            sp = self.speaker()
            goal = self.cfg.get("goal")
            msg = f"hey! {hit}?? 😾\nback to: {goal}" if goal else f"hey! {hit}?? 😾\nwe're focusing!"
            sp.alert(msg)
            self.notify("Psst… you're focusing 🍅", f"{sp.name} caught you on {hit}.")

    def is_night(self):
        h = datetime.datetime.now().hour
        b = self.cfg["bedtime_hour"]
        return h >= b or h < 5

    # -------------------------------------------------------------- main loop --
    def tick(self):
        now = time.monotonic()
        dt = min(0.13, now - self.last_tick)
        self.last_tick = now
        if now >= self.poll["power"]:
            self.poll["power"] = now + 20.0
            self._update_power()
        if self.battery_off:
            self._set_interval(FRAME_MS["off"][0])
            return True
        if self.hypr.ok:
            if now >= self.poll["cursor"]:
                self.poll["cursor"] = now + (0.1 if self.low_power else 0.05)
                self.poll_cursor(now)
            if now >= self.poll["windows"]:
                self.poll["windows"] = now + (0.8 if self.low_power else 0.4)
                mons = self.hypr.monitors()
                self.sync_screens(mons)
                self.poll_windows(mons)
            if now >= self.poll["guard"]:
                self.poll["guard"] = now + 3.0
                self.check_distraction()
        away = now - self.cursor_moved > AWAY_AFTER
        if away and not self.away and not self.focus.focusing:
            for c in self.cats:
                if not c.asleep:
                    c.sleep_now()
        if not away and self.away:
            self.focus.reset_reminders()
            sp = self.speaker()
            if sp:
                sp.welcome()
        self.away = away

        night = self.is_night()
        if self.cfg["bedtime_nudge"] and night and not away and now >= self.next_bed:
            self.next_bed = now + 45 * 60
            if self.started and now - self.cursor_moved < 30:
                sp = self.speaker()
                if sp:
                    sp.notice("it's getting late… 🌙\nbed soon?", "yawn", 1.5)
        for c in self.cats:
            c.calm = self.focus.focusing and self.cfg["calm_during_focus"]
            c.on_break = self.focus.mode in ("short", "long")
            c.night = night
        for kind, arg in self.focus.tick(dt, user_present=not away):
            self.handle_event(kind, arg)

        # who lives where
        for w in self.worlds():
            w.cats = [c for c in self.cats if c.w is w]
            w.toys = [t for t in self.toys if t.w is w]
            w.butterflies = [b for b in self.butterflies if b.w is w]
        for c in self.cats:
            c.update(dt)
        for t in self.toys:
            t.update(dt)
        for b in self.butterflies:
            b.update(dt)
        self.butterflies = [b for b in self.butterflies if not b.gone]
        self.assign_treats()
        pr = self.press
        if pr and not pr["drag"] and isinstance(pr["obj"], Cat) and now - pr["t0"] > 0.55:
            self.open_menu(pr["sc"], pr["obj"])          # press-and-hold = menu (touchpad friendly)
        m = self.menu
        if m is not None:
            cur = m.sc.world.cursor
            x, y, w_, h_ = m.rect
            near = cur is not None and (x - 50 <= cur[0] <= x + w_ + 50 and y - 50 <= cur[1] <= y + h_ + 50
                                        or m.cat.hit(*cur))
            m.away = 0.0 if near else m.away + dt
            if m.away > 2.5 or m.cat not in self.cats or m.cat.w is not m.sc.world:
                self.close_menu()
            elif m.page == "focus" and self.focus.active:
                m.rebuild()
        if now >= self.next_bf:
            self.next_bf = now + random.uniform(150, 420)
            if self.cfg["butterflies"] and not self.butterflies and not self.focus.focusing:
                ws = [w for w in self.worlds() if not w.hidden]
                if ws:
                    self.butterflies.append(Butterfly(random.choice(ws)))

        self.poll["save"] -= dt
        if self.poll["save"] <= 0:
            self.poll["save"] = 15.0
            self.save_session()
            self.pets.save()

        snoozed = now < self.snooze_until
        for sc in self.screens.values():
            self.compute_hud(sc)
            self.queue_redraw(sc, snoozed)
            self.update_input(sc, snoozed=snoozed)
        tier = "off" if snoozed else self.activity_tier(now)
        self._set_interval(FRAME_MS[tier][1 if self.low_power else 0])
        return True

    def activity_tier(self, now):
        """Only animate fast when something is actually moving: saves lots of battery."""
        if self.press is not None:
            return "motion"
        tier = "gentle" if self.menu is not None else "idle"
        for c in self.cats:
            if c.w.hidden:
                continue
            if c.state in MOTION_STATES or abs(c.vel_x) > 140:
                return "motion"
            if c.state in SLOW_STATES or abs(c.vel_x) > 5 or c.squash > 0:
                tier = "slow"
                continue
            if tier != "slow" and (c.state in GENTLE_STATES or any(p["kind"] != "z" for p in c.particles)
                    or (c.bubble and (c.t - c.bubble[2] < 0.3 or c.bubble[1] - c.t < 0.5))):
                tier = "gentle"
        if self.butterflies:
            return "motion"
        for t in self.toys:
            if t.dragged or not t.grounded or abs(t.vx) > 1:
                return "motion"
        if tier == "slow":
            return tier
        if tier == "idle" and now - self.cursor_moved < 0.8:
            tier = "gentle"   # eyes follow the cursor
        return tier

    def _set_interval(self, ms):
        if ms != self.frame_ms:
            self.frame_ms = ms
            GLib.source_remove(self._timer)
            self._timer = GLib.timeout_add(ms, self.tick)

    def _update_power(self):
        on_bat, pct, saver = power_state()
        self.on_battery, self.battery_pct = on_bat, pct
        self.low_power = bool(self.cfg["battery_saver"]) and (on_bat or saver)
        cutoff = int(self.cfg.get("battery_off_pct", 0))
        should_off = bool(cutoff) and on_bat and pct is not None and pct <= cutoff
        if should_off and not self.battery_off:
            self.battery_off = True
            sp = self.speaker()
            if sp:
                sp.say(f"battery at {pct}%… 🔋\nwe'll nap until you plug in", 4.0, "meow")
            self.notify("Desktop Cat is napping 🔋", f"Battery is at {pct}%. The cats will be back when you charge.")
            self.save_all()
            GLib.timeout_add(3500, self._battery_hide)
        elif self.battery_off and (not on_bat or (pct is not None and pct > cutoff + 3) or not cutoff):
            self.battery_off = False
            self.last_tick = time.monotonic()
            for sc in self.screens.values():
                sc.overlay.queue_draw()
                self.update_input(sc, force=True)
            sp = self.speaker()
            if sp:
                sp.celebrate("yay, power! ⚡ we're back")

    def _battery_hide(self):
        if self.battery_off:
            for sc in self.screens.values():
                sc.prev = []
                sc.overlay.queue_draw()
                sc.input_rects = ()
                sc.overlay.input_shape_combine_region(cairo.Region())
        return False

    def handle_event(self, kind, arg):
        sp = self.speaker()
        if sp is None:
            return
        if kind == "focus_done":
            self.sound.play("chime")
            n = self.cfg["treats_per_session"]
            self.pets.add(n)
            self.pets.save()
            nxt = MODE_NAME[arg].lower()
            sp.celebrate(f"session done! 🎉 +{n} treats 🐟\n{nxt} time ☕")
            for c in self.cats:
                if c is not sp:
                    c.celebrate("🎉")
            self.notify("Focus session complete 🎉", f"You earned {n} treats for {' & '.join(c.name for c in self.cats)}! Take a {nxt}.")
        elif kind == "break_done":
            self.sound.play("chime")
            if self.focus.mode == "focus":
                sp.notice("break's over! back to it 💪", "sit", 3.0)
            else:
                sp.notice("break's over! ready? 💪\n(right-click me)", "sit", 3.0)
            self.notify("Break's over ☕", f"{sp.name} is ready to focus again.")
        elif kind == "hydrate":
            sp.notice("drink some water! 💧", "sit", 4.0)
            self.notify("Hydration break 💧", f"{sp.name} reminds you to drink some water.")
        elif kind == "stretch":
            for c in self.cats:
                c.notice("stretch with me! 🙆" if c is sp else "🙆", "stretch", 3.0)
            self.notify("Stretch break 🙆", "Stand up, roll your shoulders, fix your posture.")
        elif kind == "eyes":
            sp.notice("rest your eyes 👀\nlook far away for 20s", "loaf", 6.0)
            self.notify("Eye rest 👀", "Look at something 20 feet away for 20 seconds.")

    def notify(self, title, body):
        if not self.cfg["notifications"] or not shutil.which("notify-send"):
            return
        try:
            subprocess.Popen(["notify-send", "-a", "Desktop Cat", "-i", "face-smile", title, body],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    # -------------------------------------------------------------- layout --
    def _measure(self, text, max_w=None, px=13):
        key = (text, max_w, px)
        if key not in self._measure_cache:
            if len(self._measure_cache) > 96:
                self._measure_cache.clear()
            self._measure_cache[key] = render.measure(text, px, True, max_w)
        return self._measure_cache[key]

    def compute_hud(self, sc):
        w = sc.world
        hud = {}
        owner = self.speaker() if (self.cfg["show_timer"] and self.focus.active) else None
        for cat in w.cats:
            s = cat.s
            pose, _a, yoff = cat.draw_params()
            top = cat.y + yoff + render.POSE_TOP.get(pose or "sit", -70) * s
            if cat.state == "inbox":
                top -= 4 * s
            badge = bubble = None
            y = top - 4
            if cat is owner:
                label = self.focus.label()
                tw, th = self._measure(label, px=12)
                bw, bh = tw + 22, th + 10
                bx = max(4, min(w.W - bw - 4, cat.x - bw / 2))
                by = y - bh
                if by < 4:
                    by = cat.y + 6 if cat.y + 6 + bh < w.H else 4
                badge = (bx, by, bw, bh)
                y = min(y, by) - 2
            if cat.bubble:
                text = cat.bubble[0]
                tw, th = self._measure(text, max_w=220)
                bw, bh = min(240, tw + 22), th + 16
                bx = max(4, min(w.W - bw - 4, cat.x - bw / 2))
                by = y - bh - 12
                down = True
                if by < 4:
                    by = cat.y + 14
                    down = False
                    if badge and badge[1] > cat.y:
                        by = badge[1] + badge[3] + 12
                age = cat.t - cat.bubble[2]
                remain = cat.bubble[1] - cat.t
                alpha = max(0.0, min(1.0, age / 0.15, remain / 0.3))
                bubble = ((bx, by, bw, bh), down, text, alpha)
            hud[cat] = (badge, bubble)
        sc.hud = hud

    def queue_redraw(self, sc, snoozed=False):
        """Invalidate only what visibly changed since the last frame."""
        w = sc.world
        cur = {}
        if not (w.hidden or snoozed or self.battery_off):
            for c in w.cats:
                cur[("cat", id(c))] = (c.render_sig(), c.bbox())
                if c.particles:
                    sig = tuple((p["kind"], int(p["x"] / 2), int(p["y"] / 2), int(p["life"] * 6)) for p in c.particles)
                    rect = rect_union([(p["x"] - p["size"] * 2.5, p["y"] - p["size"] * 2.5,
                                        p["size"] * 5 + 50, p["size"] * 5) for p in c.particles])
                    cur[("fx", id(c))] = (sig, rect)
            for t in w.toys:
                occ = t.occupant.render_sig() if getattr(t, "occupant", None) is not None else None
                cur[("toy", id(t))] = ((round(t.x), round(t.y), round(getattr(t, "rot", 0.0), 1), occ), t.bbox())
            for b in w.butterflies:
                cur[("bf", id(b))] = ((round(b.x), round(b.y), round(b.t * 12)), b.bbox())
            for cat, (badge, bubble) in sc.hud.items():
                if badge:
                    sig = (tuple(round(v) for v in badge), self.focus.label(), self.focus.paused,
                           round(self.focus.progress() or 0, 2))
                    cur[("badge", id(cat))] = (sig, badge)
                if bubble:
                    r = bubble[0]
                    cur[("bubble", id(cat))] = ((tuple(round(v) for v in r), bubble[2], round(bubble[3], 1), round(cat.x)),
                                                (r[0], r[1] - 10, r[2], r[3] + 20))
        if self.menu is not None and self.menu.sc is sc:
            cur[("menu",)] = (self.menu.sig(), self.menu.rect)
        for key, (sig, rect) in cur.items():
            old = sc.cache.get(key)
            if old is None or old[0] != sig:
                sc.overlay.queue_draw_area(*irect(rect, pad=6))
                if old is not None and old[1] != rect:
                    sc.overlay.queue_draw_area(*irect(old[1], pad=6))
        for key, (sig, rect) in sc.cache.items():
            if key not in cur:
                sc.overlay.queue_draw_area(*irect(rect, pad=6))
        sc.cache = cur

    def update_input(self, sc, force=False, snoozed=False):
        w = sc.world
        if w.hidden or snoozed:
            rects = ()
        elif self.press and self.press.get("drag") and self.press["sc"] is sc:
            rects = ((0, 0, w.W, w.H),)
        else:
            rs = [c.hit_box() for c in w.cats] + [t.hit_box() for t in w.toys] + [b.hit_box() for b in w.butterflies]
            for badge, bubble in sc.hud.values():
                if badge:
                    rs.append(badge)
                if bubble:
                    rs.append(bubble[0])
            if self.menu is not None and self.menu.sc is sc:
                rs.append(self.menu.rect)
            rects = tuple(irect(r, pad=1) for r in rs)
        if rects == sc.input_rects and not force:
            return
        sc.input_rects = rects
        region = cairo.Region([cairo.RectangleInt(*r) for r in rects]) if rects else cairo.Region()
        sc.overlay.input_shape_combine_region(region)

    # ----------------------------------------------------------------- draw --
    def palette(self, cat):
        return render.PALETTES.get(cat.color, render.PALETTES["ginger"])

    def draw_cat(self, cr, cat):
        pose, a, yoff = cat.draw_params()
        if cat.state == "tussle":
            if cat.tussle_lead and cat.partner is not None:
                render.draw_cloud(cr, cat.cloud, cat.y, cat.s, cat.t, self.palette(cat), self.palette(cat.partner))
            return
        if pose is None:
            return
        if not cat.airborne and cat.state != "inbox":
            cr.new_path()
            render.ellipse_path(cr, cat.x, cat.y - 1, 26 * cat.s, 3.2 * cat.s)
            cr.set_source_rgba(0, 0, 0, 0.16)
            cr.fill()
        render.draw_cat(cr, self.palette(cat), pose, cat.x, cat.y + yoff, cat.s, cat.facing, a, cat.squash)

    def draw(self, sc, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        w = sc.world
        if w.hidden or self.battery_off or time.monotonic() < self.snooze_until:
            return True
        s = float(self.cfg["size"])
        clips = [(r.x, r.y, r.width, r.height) for r in cr.copy_clip_rectangle_list()] or [(0, 0, w.W, w.H)]

        def vis(r):
            return r is not None and any(r[0] < c[0] + c[2] and c[0] < r[0] + r[2] + 12 and
                                         r[1] < c[1] + c[3] and c[1] < r[1] + r[3] + 12 for c in clips)
        boxes = [t for t in w.toys if t.kind == "box" and vis(t.bbox())]
        for b in boxes:
            cr.new_path()
            render.ellipse_path(cr, b.x, b.y - 1, 32 * s, 3.5 * s)
            cr.set_source_rgba(0, 0, 0, 0.14)
            cr.fill()
            render.draw_box_back(cr, b.x, b.y, s)
            if b.occupant is not None and b.occupant.w is w:
                self.draw_cat(cr, b.occupant)
            render.draw_box_front(cr, b.x, b.y, s)
        for c in w.cats:
            if c.state != "inbox" and vis(c.bbox()):
                self.draw_cat(cr, c)
        for t in w.toys:
            if not vis(t.bbox()):
                continue
            if t.kind == "ball":
                render.draw_ball(cr, t.x, t.y, t.r, t.rot)
            elif t.kind == "treat":
                render.draw_treat(cr, t.x, t.y, s, t.rot)
        for b in w.butterflies:
            render.draw_butterfly(cr, b.x, b.y, b.t, b.color, b.perched)
        for c in w.cats:
            render.draw_particles(cr, c.particles)
        for cat, (badge, bubble) in sc.hud.items():
            if bubble and not vis(bubble[0]):
                bubble = None
            if badge and not vis(badge):
                badge = None
            if badge:
                kind = "paused" if self.focus.paused else self.focus.mode
                render.draw_badge(cr, badge, self.focus.label(), kind, self.focus.progress())
            if bubble:
                rect, down, text, alpha = bubble
                render.draw_bubble(cr, rect, cat.x, down, text, alpha)
        if self.menu is not None and self.menu.sc is sc and vis(self.menu.rect):
            self.menu.draw(cr)
        return True

    # ---------------------------------------------------------------- input --
    def pick(self, sc, x, y):
        w = sc.world
        for b in w.butterflies:
            if inside(b.hit_box(), x, y):
                return b
        for t in w.toys:
            if t.kind == "treat" and inside(t.hit_box(), x, y):
                return t
        for c in reversed(w.cats):
            if c.hit(x, y):
                return c
        for t in w.toys:
            if inside(t.hit_box(), x, y):
                return t
        return None

    def on_press(self, sc, ev):
        self._set_interval(FRAME_MS["motion"][1 if self.low_power else 0])
        x, y = ev.x, ev.y
        m = self.menu
        if m is not None and m.sc is sc and inside(m.rect, x, y):
            if ev.type == Gdk.EventType.BUTTON_PRESS and ev.button in (1, 3):
                self.menu_click(x, y)
            return True
        if m is not None:
            self.close_menu()
        obj = self.pick(sc, x, y)
        if ev.button == 3:
            cat = obj if isinstance(obj, Cat) else (sc.world.cats[0] if sc.world.cats else self.speaker())
            if cat is not None:
                self.open_menu(cat_screen(self, cat) or sc, cat)
            return True
        if ev.button == 2:
            near = obj if isinstance(obj, Cat) else None
            self.toss_treat(near=near)
            return True
        if ev.button != 1:
            return False
        if ev.type == Gdk.EventType._2BUTTON_PRESS:
            self.press = None
            if isinstance(obj, Cat):
                obj.boop()
            return True
        if ev.type != Gdk.EventType.BUTTON_PRESS:
            return True
        for cat, (badge, bubble) in sc.hud.items():
            if inside(badge, x, y):
                self.focus.toggle_pause()
                cat.say("paused ⏸" if self.focus.paused else "let's go! 🍅", 1.8)
                return True
            if bubble and inside(bubble[0], x, y) and obj is None:
                cat.bubble = None
                return True
        if isinstance(obj, Butterfly):
            obj.startle()
            return True
        if obj is not None:
            self.press = {"obj": obj, "sc": sc, "x": x, "y": y, "drag": False, "t0": time.monotonic(),
                          "samples": [(time.monotonic(), x, y)]}
        return True

    def on_motion(self, sc, ev):
        x, y = ev.x, ev.y
        now = time.monotonic()
        self.cursor_moved = now
        m = self.menu
        if m is not None and m.sc is sc and inside(m.rect, x, y):
            h = m.row_at(x, y)
            if h != m.hover:
                m.hover = h
                sc.overlay.queue_draw_area(*irect(m.rect, 6))
            m.away = 0.0
            return True
        pr = self.press
        if pr and pr["sc"] is sc:
            if not pr["drag"] and math.hypot(x - pr["x"], y - pr["y"]) > 7:
                pr["drag"] = True
                pr["obj"].drag_start()
                self.update_input(sc, force=True)
            if pr["drag"]:
                pr["obj"].drag_to(x, y)
                pr["samples"].append((now, x, y))
                pr["samples"] = [s for s in pr["samples"] if now - s[0] < 0.1]
                return True
        # stroking: wiggle the pointer over a cat to pet it
        for c in sc.world.cats:
            if c.hit(x, y):
                self.stroke.append((now, x, y))
                self.stroke = [s for s in self.stroke if now - s[0] < 1.2]
                dist = sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(self.stroke, self.stroke[1:]))
                if dist > 260 and not c.asleep:
                    self.stroke = []
                    c.pet(c.body_part(x, y))
                break
        return True

    def on_release(self, sc, ev):
        if ev.button != 1:
            return False
        pr = self.press
        self.press = None
        if pr is None:
            return True
        obj = pr["obj"]
        if pr["drag"]:
            vx = vy = 0.0
            smp = pr["samples"]
            if len(smp) >= 2 and smp[-1][0] - smp[0][0] > 0.005:
                vx = (smp[-1][1] - smp[0][1]) / (smp[-1][0] - smp[0][0])
                vy = (smp[-1][2] - smp[0][2]) / (smp[-1][0] - smp[0][0])
            obj.release(vx, vy)
            self.update_input(sc, force=True)
            return True
        if isinstance(obj, Cat):
            obj.pet(obj.body_part(ev.x, ev.y))
        elif obj.kind == "ball":
            obj.kick(random.choice((-1, 1)) * random.uniform(150, 350), -random.uniform(350, 550))
        elif obj.kind == "box":
            if obj.occupant is not None:
                obj.occupant.pet()
            else:
                free = [c for c in sc.world.cats if not c.airborne and c.state not in ("tussle", "eat")]
                if free:
                    c = min(free, key=lambda c: abs(c.x - obj.x))
                    c.say("a box?! 📦", 1.5)
                    c.queue = []
                    c.plan_box(obj)
        return True

    def on_scroll(self, sc, ev):
        for c in sc.world.cats:
            if c.hit(ev.x, ev.y):
                c.pet(c.body_part(ev.x, ev.y))
                break
        return True

    # ---------------------------------------------------------------- menu --
    # ---------------------------------------------------------------- menu --
    def mood_line(self, cat):
        b = cat.bond
        mood = ("😴 sleeping" if cat.asleep else "😿 hungry" if b["hunger"] > 75
                else "😸 energetic" if cat.energy > 0.6 else "🙂 content" if cat.energy > 0.3 else "🥱 sleepy")
        h = int(round(cat.affection / 20))
        return f"{mood}   bond {'❤' * h}{'♡' * (5 - h)}"

    def open_menu(self, sc, cat, page="main"):
        self.menu = CatMenu(self, sc, cat, page)
        self.press = None

    def close_menu(self):
        self.menu = None

    def menu_rows(self, page, cat):
        rows = []

        def item(label, act):
            rows.append({"label": label, "kind": "item", "act": act})

        def nav(label, to):
            rows.append({"label": label, "kind": "nav", "act": to})

        def info(label):
            rows.append({"label": label, "kind": "info"})

        def sep():
            rows.append({"label": "", "kind": "sep"})

        def check(label, get, set_):
            rows.append({"label": label, "kind": "check", "on": bool(get()), "act": lambda: set_(not get())})

        def cfg_check(label, key, after=None):
            def set_(v):
                self.cfg[key] = v
                config.save(self.cfg)
                if after:
                    after()
            check(label, lambda: self.cfg[key], set_)

        f = self.focus
        if page == "main":
            if f.active:
                info(f"{f.label()}  {MODE_NAME[f.mode]}")
                item("▶  Resume timer" if f.paused else "⏸  Pause timer", f.toggle_pause)
            else:
                item(f"🍅  Start focus ({self.cfg['focus_min']} min)", lambda: self.start_mode("focus"))
            nav("📋  Focus & productivity", "focus")
            sep()
            self.pets.refill(self.cfg["daily_treats"])
            item(f"🐟  Give a treat  ({self.pets.jar} left)", lambda: self.toss_treat(near=cat))
            item(f"🧶  Play with {cat.name}", lambda: cat.play(30))
            fr, ff = cat.friend(), cat.far_friend()
            if fr is not None:
                item(f"🐾  Play with {fr.name}",
                     lambda: cat.start_social(random.choice(["chase", "tussle", "boop"])) or cat.say("not now 😼", 1.5))
            elif ff is not None and cat.dir_to(ff.w):
                item(f"🐾  Go visit {ff.name}", lambda: cat.plan_visit(cat.dir_to(ff.w)))
            boxes = [t for t in cat.w.toys if t.kind == "box" and t.occupant is None]
            if boxes and cat.box is None:
                item("📦  Hop in the box", lambda: (setattr(cat, "queue", []), cat.plan_box(boxes[0])))
            item("☀️  Wake up" if cat.asleep else "💤  Take a nap", cat.wake if cat.asleep else cat.sleep_now)
            for d, label in (("left", "⬅️  Go to the left screen"), ("right", "➡️  Go to the right screen")):
                if cat.w.neighbors.get(d) is not None:
                    item(label, lambda d=d: cat.plan_visit(d) or cat.drop_into(cat.w.neighbors[d]))
            sep()
            muted = not self.cfg["sounds"]
            item("🔊  Unmute cats" if muted else "🔇  Mute cats", lambda: self.set_muted(not muted, cat))
            nav("🎛️  Toggles", "toggles")
            item("🙈  Hide for 30 minutes", self.snooze)
            item("⚙️  Settings…", self.open_settings)
            item("👋  Quit until next login", self.quit)
            item("✖  Close menu", lambda: None)
        elif page == "focus":
            nav("‹  Back", "main")
            if f.active:
                info(f"{f.label()}  —  {MODE_NAME[f.mode]}")
                item("▶  Resume" if f.paused else "⏸  Pause", f.toggle_pause)
                item("⏭  Skip to next", f.skip)
                item("⏹  Stop timer", self.stop_timer)
            else:
                info("no timer running")
                item(f"🍅  Start focus ({self.cfg['focus_min']} min)", lambda: self.start_mode("focus"))
                item("🎯  Set goal & focus…", self.open_goal)
                item(f"☕  Short break ({self.cfg['short_break_min']} min)", lambda: self.start_mode("short"))
                item(f"🛋️  Long break ({self.cfg['long_break_min']} min)", lambda: self.start_mode("long"))
            sep()
            info(f.today_text())
            if self.cfg.get("goal"):
                info(f"🎯 {self.cfg['goal'][:34]}")
            cfg_check("🛡️  Distraction guard", "distraction_guard")
            cfg_check("🤫  Calm cats while focusing", "calm_during_focus")
            cfg_check("⏱️  Timer above cat", "show_timer")
            if self.battery_pct is not None:
                cut = self.cfg.get("battery_off_pct", 0)
                info(f"🔋 {self.battery_pct}%{' on battery' if self.on_battery else ' charging'}"
                     + (f" · nap below {cut}%" if cut else ""))
            item("⚙️  More settings (reminders…)", self.open_settings)
        elif page == "toggles":
            nav("‹  Back", "main")
            cfg_check("📌  Stay in one spot", "stay_put")
            cfg_check("🧶  Yarn ball", "toy_ball", self.sync_toys)
            cfg_check("📦  Cardboard box", "toy_box", self.sync_toys)

            def set_second(v):
                self.cfg["cats"][1]["enabled"] = v
                config.save(self.cfg)
                self.sync_cats()
            check(f"🐈‍⬛  {self.cfg['cats'][1]['name']} (second cat)", lambda: self.cfg["cats"][1]["enabled"], set_second)
            cfg_check("🖥️  Hide over fullscreen apps", "hide_fullscreen")
            cfg_check("🔋  Battery saver", "battery_saver")
        return rows

    def menu_click(self, px, py):
        m = self.menu
        i = m.row_at(px, py)
        if i < 0:
            return
        r = m.rows[i]
        if r["kind"] == "nav":
            m.page = r["act"]
            m.hover = -1
            m.rebuild()
        elif r["kind"] == "check":
            r["act"]()
            m.rebuild()
        else:
            self.close_menu()
            r["act"]()

    def set_muted(self, muted, cat=None):
        self.cfg["sounds"] = not muted
        config.save(self.cfg)
        if cat is not None:
            cat.say("shh… 🤫" if muted else "meow! 🔊", 1.5, None if muted else "meow")

    def snooze(self):
        self.snooze_until = time.monotonic() + 30 * 60
        for sc in self.screens.values():
            sc.overlay.queue_draw()

    def start_mode(self, mode):
        self.focus.start(mode)
        sp = self.speaker()
        goal = self.cfg.get("goal")
        if mode == "focus":
            msg = f"let's focus! 🎯\n{goal}" if goal else "let's focus! 🎯\nwe'll keep quiet."
            sp.notice(msg, "sit", 2.5)
        else:
            sp.notice("break time! ☕ stretch, sip, relax", "stretch", 2.0)

    def stop_timer(self):
        self.focus.stop()
        self.speaker().say("timer stopped", 2.0)

    def open_goal(self):
        def done(start):
            if start:
                self.start_mode("focus")
        d = GoalDialog(self.cfg, done)
        d.show_all()
        d.present()

    def open_settings(self):
        if self.settings_win:
            self.settings_win.present()
            return

        def saved():
            self.sync_cats()
            self.sync_toys()
            self.speaker().say("got it! 😺", 2.0)
            for sc in self.screens.values():
                sc.overlay.queue_draw()

        self.settings_win = SettingsWindow(self.cfg, saved)
        self.settings_win.connect("destroy", lambda *_: setattr(self, "settings_win", None))
        self.settings_win.show_all()
        self.settings_win.present()

    def quit(self):
        self.save_all()
        for c in self.cats:
            c.say("bye bye! 👋", 1.0)
        GLib.timeout_add(700, self._really_quit)

    def _really_quit(self):
        if os.environ.get("INVOCATION_ID") and shutil.which("systemctl"):
            # running as the always-on service: stop it so systemd doesn't restart us
            subprocess.Popen(["systemctl", "--user", "stop", "desktop-cat.service"])
        Gtk.main_quit()
        return False

    def save_all(self):
        self.pets.save()
        self.focus.stats.save()
        self.save_session()

    def save_session(self):
        """Remember where everyone is, so a restart doesn't look like a respawn."""
        data = {"cats": {}, "toys": {}}
        for c in self.cats:
            data["cats"][str(c.idx)] = {"world": c.w.name, "x": c.x, "y": c.y, "pid": c.pid, "facing": c.facing,
                                        "energy": c.energy, "asleep": c.asleep and c.box is None}
        for t in self.toys:
            if t.kind in ("ball", "box"):
                data["toys"][t.kind] = {"world": t.w.name, "x": t.x, "y": t.y, "pid": t.pid}
        f = self.focus
        if f.active:
            data["focus"] = {"mode": f.mode, "remaining": f.remaining, "total": f.total, "paused": f.paused,
                             "cycle": f.cycle}
        try:
            tmp = SESSION_STATE + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(data, fh)
            os.replace(tmp, SESSION_STATE)
        except OSError:
            pass

    def restore_session(self):
        try:
            with open(SESSION_STATE) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return False
        worlds = {sc.world.name: sc.world for sc in self.screens.values()}
        for c in self.cats:
            d = data.get("cats", {}).get(str(c.idx))
            if not d:
                continue
            w = worlds.get(d["world"], c.w)
            c.w = w
            c.x = clamp(d["x"], 20, w.W - 20)
            c.y = min(d["y"], w.H)
            c.pid = d.get("pid", "floor")
            c.facing = d.get("facing", 1)
            c.energy = d.get("energy", c.energy)
            c.vx = c.vy = 0.0
            if d.get("asleep"):
                c.run_step(("sleep", random.uniform(40, 120)))
            else:
                c.set_state("sit", random.uniform(2, 5))
        for t in self.toys:
            d = data.get("toys", {}).get(t.kind)
            if d:
                t.w = worlds.get(d["world"], t.w)
                t.x, t.y, t.pid = clamp(d["x"], 20, t.w.W - 20), min(d["y"], t.w.H), d.get("pid", "floor")
                t.grounded = True
        fd = data.get("focus")
        if fd:
            f = self.focus
            f.mode, f.remaining, f.total, f.paused, f.cycle = fd["mode"], fd["remaining"], fd["total"], fd["paused"], fd["cycle"]
        return True

    # ------------------------------------------------------- control socket --
    def _start_control(self):
        """`desktop-cat treat|pet|play|focus|pause|stop|hide|show` from a keybind or script."""
        try:
            if os.path.exists(CONTROL_SOCK):
                os.unlink(CONTROL_SOCK)
            self._ctl = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            self._ctl.bind(CONTROL_SOCK)
            self._ctl.setblocking(False)
            GLib.io_add_watch(self._ctl.fileno(), GLib.IO_IN, self._on_control)
        except OSError as e:
            print(f"control socket unavailable: {e}", file=sys.stderr)

    def _on_control(self, *_):
        try:
            cmd = self._ctl.recv(256).decode().strip().lower()
        except OSError:
            return True
        sp = self.speaker()
        if sp is None:
            return True
        if cmd == "treat":
            self.toss_treat()
        elif cmd == "pet":
            sp.pet()
        elif cmd == "play":
            sp.play(30)
        elif cmd == "focus":
            self.start_mode("focus") if not self.focus.active else None
        elif cmd == "pause":
            self.focus.toggle_pause()
        elif cmd == "stop":
            self.stop_timer()
        elif cmd == "hide":
            self.snooze()
        elif cmd == "show":
            self.snooze_until = 0.0
        elif cmd == "menu":
            self.open_menu(cat_screen(self, sp), sp)
        return True


def main():
    if GtkLayerShell is None or not GtkLayerShell.is_supported():
        msg = ("Desktop Cat needs gtk-layer-shell on a wlroots/Hyprland Wayland session.\n"
               "Install it with:  sudo pacman -S gtk-layer-shell")
        print(msg, file=sys.stderr)
        if shutil.which("notify-send"):
            subprocess.call(["notify-send", "Desktop Cat", msg])
        sys.exit(1)
    import signal
    app = App()

    def stop(*_):
        app.save_all()
        Gtk.main_quit()
        return False
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, stop)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, stop)
    Gtk.main()


if __name__ == "__main__":
    main()
