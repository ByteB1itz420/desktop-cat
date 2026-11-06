"""Procedurally synthesised meow / purr / chime (no asset files needed)."""
import math
import os
import random
import shutil
import struct
import subprocess
import time
import wave

CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "desktop-cat")
RATE = 22050
VERSION = 3


def _write(path, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32000)) for s in samples))


def _meow(pitch=1.0, dur=0.55, vol=0.32):
    n = int(RATE * dur)
    out = []
    ph = 0.0
    for i in range(n):
        u = i / n
        f0 = pitch * (480 + 330 * math.sin(math.pi * min(1.0, u * 1.25)) ** 1.3 - 120 * u)
        ph += 2 * math.pi * f0 / RATE
        formant = 2100 - 1200 * u            # "mee" -> "ow"
        s = 0.0
        for k in range(1, 9):
            amp = math.exp(-((k * f0 - formant) / 650.0) ** 2) + 0.35 / k
            s += amp * math.sin(k * ph)
        env = min(1.0, u / 0.06) * (1 - u) ** 1.4
        out.append(s * env * vol * 0.45)
    return out


def _purr(dur=1.4, vol=0.5):
    n = int(RATE * dur)
    out = []
    lp = 0.0
    for i in range(n):
        u = i / n
        noise = random.uniform(-1, 1)
        lp += (noise - lp) * 0.05
        am = 0.5 + 0.5 * math.sin(2 * math.pi * 26 * i / RATE) ** 2
        breath = 0.6 + 0.4 * math.sin(2 * math.pi * 0.9 * i / RATE)
        env = min(1.0, u / 0.1) * min(1.0, (1 - u) / 0.2)
        out.append(lp * 3.5 * am * breath * env * vol)
    return out


def _chime(vol=0.3):
    n = int(RATE * 1.1)
    out = []
    for i in range(n):
        tt = i / RATE
        s = 0.0
        for j, f in enumerate((880, 1108.7, 1318.5)):
            t0 = j * 0.12
            if tt >= t0:
                s += math.sin(2 * math.pi * f * (tt - t0)) * math.exp(-(tt - t0) * 4.0)
        out.append(s * vol / 2)
    return out


class Sound:
    def __init__(self, cfg):
        self.cfg = cfg
        self.player = shutil.which("paplay") or shutil.which("pw-play") or shutil.which("aplay")
        self.files = {}
        self._last = 0.0
        try:
            os.makedirs(CACHE, exist_ok=True)
            gen = {"meow": lambda: _meow(1.0), "meow2": lambda: _meow(1.18, 0.4),
                   "meow3": lambda: _meow(0.9, 0.7), "meow4": lambda: _meow(1.32, 0.35),
                   "meow5": lambda: _meow(1.22, 0.55), "purr": _purr, "chime": _chime}
            for name, fn in gen.items():
                p = os.path.join(CACHE, f"{name}_v{VERSION}.wav")
                if not os.path.exists(p):
                    _write(p, fn())
                self.files[name] = p
        except OSError:
            self.files = {}

    VOICES = [("meow", "meow3"), ("meow2", "meow4", "meow5")]

    def play(self, name, voice=0):
        if not self.cfg.get("sounds") or not self.player:
            return
        now = time.monotonic()
        if now - self._last < 0.6:
            return
        self._last = now
        if name == "meow":
            name = random.choice(self.VOICES[voice % len(self.VOICES)])
        p = self.files.get(name)
        if p:
            try:
                subprocess.Popen([self.player, p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass
