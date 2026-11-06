"""Persistent settings and daily stats."""
import copy
import datetime
import json
import os

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "desktop-cat")
DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "desktop-cat")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
STATS_PATH = os.path.join(DATA_DIR, "stats.json")
PETS_PATH = os.path.join(DATA_DIR, "pets.json")

DEFAULT_CATS = [
    {"name": "Mochi", "color": "ginger", "enabled": True},
    {"name": "Luna", "color": "black", "enabled": True},
]

DEFAULTS = {
    # cats (coat: ginger | grey | black | cream | tuxedo)
    "cats": DEFAULT_CATS,
    "size": 1.1,
    "activity": "normal",       # lazy | normal | hyper
    "stay_put": False,
    "hide_fullscreen": False,
    "sounds": True,
    "toy_ball": True,
    "toy_box": True,
    "butterflies": False,
    "battery_saver": True,      # lower frame rate on battery / power-saver (cats stay active)
    "battery_off_pct": 20,      # cats nap (turn off) when on battery at or below this %, 0 = never
    # focus / pomodoro
    "focus_min": 25,
    "short_break_min": 5,
    "long_break_min": 15,
    "sessions_before_long": 4,
    "auto_start_breaks": True,
    "auto_start_focus": False,
    "calm_during_focus": True,
    "show_timer": True,
    "goal": "",
    # wellbeing reminders (minutes, 0 = off)
    "hydrate_min": 45,
    "stretch_min": 60,
    "eyes_min": 0,
    # distraction guard
    "distraction_guard": True,
    "distraction_keywords": "youtube, reddit, instagram, netflix, tiktok, facebook, twitch, twitter",
    "notifications": True,
    "bedtime_nudge": True,
    "bedtime_hour": 23,
    # treats: free daily allowance + reward per completed focus session
    "daily_treats": 10,
    "treats_per_session": 3,
}


def load():
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    for k, v in data.items():
        if k not in DEFAULTS or k == "cats":
            continue
        d = DEFAULTS[k]
        if type(v) is type(d) or (isinstance(d, float) and isinstance(v, int) and not isinstance(v, bool)):
            cfg[k] = v
    cats = data.get("cats")
    if isinstance(cats, list):
        for i, c in enumerate(cats[:len(cfg["cats"])]):
            if isinstance(c, dict):
                for key in ("name", "color", "enabled"):
                    if key in c and type(c[key]) is type(cfg["cats"][i][key]):
                        cfg["cats"][i][key] = c[key]
    # migrate the single-cat config from v1
    if isinstance(data.get("name"), str):
        cfg["cats"][0]["name"] = data["name"]
    if isinstance(data.get("color"), str):
        cfg["cats"][0]["color"] = data["color"]
    cfg["cats"][0]["enabled"] = True
    return cfg


def save(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


class Stats:
    def __init__(self):
        self.data = {}
        try:
            with open(STATS_PATH) as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def today(self):
        key = datetime.date.today().isoformat()
        return self.data.setdefault(key, {"sessions": 0, "focus_seconds": 0.0})

    def save(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = STATS_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f)
            os.replace(tmp, STATS_PATH)
        except OSError:
            pass


class PetData:
    """Per-cat bond (affection, hunger, pet/treat counts) + the treat jar."""

    def __init__(self):
        try:
            with open(PETS_PATH) as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("cats", {})
        self.data.setdefault("jar", 0)
        self.data.setdefault("jar_day", "")

    def bond(self, idx):
        b = self.data["cats"].setdefault(str(idx), {})
        for k, v in (("affection", 50.0), ("hunger", 20.0), ("pets", 0), ("treats", 0)):
            b.setdefault(k, v)
        return b

    def refill(self, daily):
        today = datetime.date.today().isoformat()
        if self.data["jar_day"] != today:
            self.data["jar_day"] = today
            self.data["jar"] = max(self.data["jar"], daily)

    @property
    def jar(self):
        return self.data["jar"]

    def add(self, n):
        self.data["jar"] = max(0, self.data["jar"] + n)

    def save(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = PETS_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f)
            os.replace(tmp, PETS_PATH)
        except OSError:
            pass
