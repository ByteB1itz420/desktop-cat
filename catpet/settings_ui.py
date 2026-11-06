"""Settings window (a small fixed-size GTK window, which Hyprland floats)."""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from . import config  # noqa: E402
from .render import PALETTES  # noqa: E402


def cfg_get(cfg, key):
    node = cfg
    for part in key.split("."):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def cfg_set(cfg, key, value):
    parts = key.split(".")
    node = cfg
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    node[parts[-1]] = value


class SettingsWindow(Gtk.Window):
    def __init__(self, cfg, on_save):
        super().__init__(title="Desktop Cat — Settings")
        self.cfg = cfg
        self.on_save = on_save
        self.set_resizable(False)
        self.set_border_width(14)
        self.widgets = {}

        nb = Gtk.Notebook()
        nb.append_page(self._page([
            ("Focus session (min)", "focus_min", "spin", (1, 180)),
            ("Short break (min)", "short_break_min", "spin", (1, 60)),
            ("Long break (min)", "long_break_min", "spin", (1, 90)),
            ("Sessions before long break", "sessions_before_long", "spin", (1, 12)),
            ("Auto-start breaks", "auto_start_breaks", "switch", None),
            ("Auto-start next focus", "auto_start_focus", "switch", None),
            ("Cat stays calm during focus", "calm_during_focus", "switch", None),
            ("Show timer above cat", "show_timer", "switch", None),
            ("Current goal", "goal", "entry", None),
        ]), Gtk.Label(label="🍅 Focus"))
        nb.append_page(self._page([
            ("Hydration reminder (min, 0=off)", "hydrate_min", "spin", (0, 240)),
            ("Stretch / posture (min, 0=off)", "stretch_min", "spin", (0, 240)),
            ("20-20-20 eye rest (min, 0=off)", "eyes_min", "spin", (0, 120)),
            ("Bedtime nudge", "bedtime_nudge", "switch", None),
            ("Bedtime (hour, 0-23)", "bedtime_hour", "spin", (0, 23)),
            ("Desktop notifications", "notifications", "switch", None),
            ("Distraction guard (during focus)", "distraction_guard", "switch", None),
            ("Distracting sites/apps (comma-sep.)", "distraction_keywords", "entry", None),
        ]), Gtk.Label(label="💧 Wellbeing"))
        nb.append_page(self._page([
            ("Cat 1 name", "cats.0.name", "entry", None),
            ("Cat 1 coat", "cats.0.color", "combo", list(PALETTES)),
            ("Second cat", "cats.1.enabled", "switch", None),
            ("Cat 2 name", "cats.1.name", "entry", None),
            ("Cat 2 coat", "cats.1.color", "combo", list(PALETTES)),
            ("Size", "size", "scale", (0.6, 2.2)),
            ("Energy", "activity", "combo", ["lazy", "normal", "hyper"]),
            ("Stay in one spot", "stay_put", "switch", None),
            ("Meows & purrs", "sounds", "switch", None),
        ]), Gtk.Label(label="🐱 Cats"))
        nb.append_page(self._page([
            ("Yarn ball", "toy_ball", "switch", None),
            ("Cardboard box", "toy_box", "switch", None),
            ("Free treats per day", "daily_treats", "spin", (0, 100)),
            ("Bonus treats per focus session", "treats_per_session", "spin", (0, 20)),
            ("Hide when an app is fullscreen", "hide_fullscreen", "switch", None),
            ("Save battery (lower FPS on battery)", "battery_saver", "switch", None),
            ("Turn off below battery % (0 = never)", "battery_off_pct", "spin", (0, 90)),
        ]), Gtk.Label(label="🧶 Toys & treats"))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.pack_start(nb, True, True, 0)
        btns = Gtk.Box(spacing=8)
        btns.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.destroy())
        save = Gtk.Button(label="Save")
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", self._save)
        btns.pack_start(cancel, False, False, 0)
        btns.pack_start(save, False, False, 0)
        box.pack_start(btns, False, False, 0)
        self.add(box)
        self.set_size_request(460, -1)

    def _page(self, rows):
        g = Gtk.Grid(column_spacing=18, row_spacing=10, margin=12)
        for i, (label, key, kind, extra) in enumerate(rows):
            lab = Gtk.Label(label=label, xalign=0)
            g.attach(lab, 0, i, 1, 1)
            v = cfg_get(self.cfg, key)
            if kind == "spin":
                w = Gtk.SpinButton.new_with_range(extra[0], extra[1], 1)
                w.set_value(v)
            elif kind == "switch":
                w = Gtk.Switch(active=bool(v), halign=Gtk.Align.END)
            elif kind == "entry":
                w = Gtk.Entry(text=v, hexpand=True)
                w.set_width_chars(24)
            elif kind == "combo":
                w = Gtk.ComboBoxText()
                for opt in extra:
                    w.append(opt, opt.capitalize())
                w.set_active_id(v)
            else:  # scale
                w = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, extra[0], extra[1], 0.1)
                w.set_value(v)
                w.set_hexpand(True)
            g.attach(w, 1, i, 1, 1)
            self.widgets[key] = (kind, w)
        return g

    def _save(self, *_):
        for key, (kind, w) in self.widgets.items():
            if kind == "spin":
                v = int(w.get_value())
            elif kind == "switch":
                v = w.get_active()
            elif kind == "entry":
                v = w.get_text().strip() or cfg_get(self.cfg, key)
            elif kind == "combo":
                v = w.get_active_id() or cfg_get(self.cfg, key)
            else:
                v = round(float(w.get_value()), 2)
            cfg_set(self.cfg, key, v)
        config.save(self.cfg)
        self.on_save()
        self.destroy()


class GoalDialog(Gtk.Window):
    def __init__(self, cfg, on_done):
        super().__init__(title="Focus goal")
        self.set_resizable(False)
        self.set_border_width(14)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.pack_start(Gtk.Label(label="What are you working on? 🎯", xalign=0), False, False, 0)
        self.entry = Gtk.Entry(text=cfg.get("goal", ""))
        self.entry.set_width_chars(36)
        self.entry.connect("activate", self._ok)
        box.pack_start(self.entry, False, False, 0)
        self.start = Gtk.CheckButton(label="Start a focus session now", active=True)
        box.pack_start(self.start, False, False, 0)
        ok = Gtk.Button(label="Let's go")
        ok.connect("clicked", self._ok)
        ok.set_halign(Gtk.Align.END)
        box.pack_start(ok, False, False, 0)
        self.add(box)
        self.cfg = cfg
        self.on_done = on_done

    def _ok(self, *_):
        self.cfg["goal"] = self.entry.get_text().strip()
        config.save(self.cfg)
        self.on_done(self.start.get_active())
        self.destroy()
