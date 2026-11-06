"""Pomodoro timer + wellbeing reminders."""
import time

from .config import Stats

MODE_ICON = {"focus": "🍅", "short": "☕", "long": "🛋️"}
MODE_NAME = {"focus": "Focus", "short": "Short break", "long": "Long break"}


class Focus:
    def __init__(self, cfg):
        self.cfg = cfg
        self.mode = "idle"          # idle | focus | short | long
        self.paused = False
        self.remaining = 0.0
        self.total = 1.0
        self.cycle = 0
        self.stats = Stats()
        self._save_in = 30.0
        now = time.monotonic()
        self.last = {"hydrate": now, "stretch": now, "eyes": now}

    @property
    def active(self):
        return self.mode != "idle"

    @property
    def focusing(self):
        return self.mode == "focus" and not self.paused

    def minutes_for(self, mode):
        return {"focus": self.cfg["focus_min"], "short": self.cfg["short_break_min"],
                "long": self.cfg["long_break_min"]}[mode]

    def start(self, mode):
        self.mode = mode
        self.paused = False
        self.total = max(1, self.minutes_for(mode)) * 60.0
        self.remaining = self.total

    def stop(self):
        self.mode = "idle"
        self.paused = False
        self.stats.save()

    def toggle_pause(self):
        if self.active:
            self.paused = not self.paused

    def skip(self):
        if self.active:
            self.remaining = 0.0

    def reset_reminders(self):
        now = time.monotonic()
        for k in self.last:
            self.last[k] = now

    def tick(self, dt, user_present=True):
        ev = []
        if self.active and not self.paused:
            self.remaining -= dt
            if self.mode == "focus":
                self.stats.today()["focus_seconds"] += dt
            if self.remaining <= 0:
                if self.mode == "focus":
                    self.cycle += 1
                    self.stats.today()["sessions"] += 1
                    nxt = "long" if self.cycle % max(1, self.cfg["sessions_before_long"]) == 0 else "short"
                    ev.append(("focus_done", nxt))
                    if self.cfg["auto_start_breaks"]:
                        self.start(nxt)
                    else:
                        self.mode = "idle"
                else:
                    ev.append(("break_done", None))
                    if self.cfg["auto_start_focus"]:
                        self.start("focus")
                    else:
                        self.mode = "idle"
                self.stats.save()
        self._save_in -= dt
        if self._save_in <= 0:
            self._save_in = 30.0
            self.stats.save()

        now = time.monotonic()
        if not user_present or self.mode in ("short", "long"):
            # don't nag while away or on a break; restart the clocks
            for k in self.last:
                self.last[k] = max(self.last[k], now - 60)
            return ev
        for key, cfgkey in (("hydrate", "hydrate_min"), ("stretch", "stretch_min"), ("eyes", "eyes_min")):
            mins = self.cfg.get(cfgkey, 0)
            if mins and now - self.last[key] >= mins * 60:
                self.last[key] = now
                ev.append((key, None))
        return ev

    def label(self):
        if not self.active:
            return None
        r = max(0, int(self.remaining + 0.999))
        icon = "⏸" if self.paused else MODE_ICON[self.mode]
        return f"{icon} {r // 60:02d}:{r % 60:02d}"

    def progress(self):
        return 1.0 - max(0.0, self.remaining) / self.total if self.active else None

    def today_text(self):
        d = self.stats.today()
        m = int(d["focus_seconds"] // 60)
        return f"Today: {d['sessions']} session{'s' if d['sessions'] != 1 else ''} · {m // 60}h {m % 60:02d}m focused"
