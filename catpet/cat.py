"""The cat's brain: physics, state machine, behaviour choices and social play."""
import math
import random

GRAVITY = 2400.0
ACTIVITY = {"lazy": 0.6, "normal": 1.0, "hyper": 1.6}

PET_LINES = ["purrr~ 💕", "mrrp! 😽", "more pets pls", "prrrrrr…", "(=^･ω･^=)", "hehe that tickles", "right there!! 😻"]
WAKE_LINES = ["mrrp…?", "*yaaawn*", "5 more minutes…", "huh? 😪"]
IDLE_LINES = ["meow", "mrow?", "🐾", "nya~", "…", "*stares*"]
THROW_LINES = ["mrrOW!", "wheee!", "hey!! 😾", "I'm ok!"]
DRAG_LINES = ["put me down!", "hewwo?", "mrrp?!", "where are we going"]
TREAT_LINES = ["nom nom nom 🐟", "*crunch crunch*", "yummy! 😻", "best treat ever!!"]
TAIL_LINES = ["hey! not the tail 😾", "hssss! 😾", "the tail is off limits"]
HUNGRY_LINES = ["hungry… 🐟?", "*stares at you* treat?", "mrrrow (feed me)", "my bowl is empty 😿"]

# states in which a cat is idle enough to be invited to play
IDLE_STATES = ("sit", "loaf", "groom", "walk", "yawn", "stretch", "slowblink", "land", "knead")
# states in which a cat stays put (butterflies may land on it)
STILL_STATES = ("sit", "loaf", "sleep", "inbox", "slowblink", "groom", "knead")
# head position (cat units) per pose, for butterflies perching
HEAD = {"sit": (6, -64), "loaf": (15, -42), "sleep": (12, -30), "stand": (21, -56),
        "stretch": (27, -34), "scratch": (9, -76), "jump": (24, -56), "dangle": (0, -76)}


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def weighted(opts):
    opts = [(w, v) for w, v in opts if w > 0]
    total = sum(w for w, _ in opts)
    r = random.random() * total
    for w, v in opts:
        r -= w
        if r <= 0:
            return v
    return opts[-1][1]


class Platform:
    __slots__ = ("id", "x0", "x1", "y")

    def __init__(self, pid, x0, x1, y):
        self.id, self.x0, self.x1, self.y = pid, x0, x1, y


class World:
    """One monitor's worth of space: the floor, window tops, and who's in it."""

    def __init__(self, name="main"):
        self.name = name
        self.platforms = {}
        self.cursor = None
        self.cursor_still = 0.0
        self.hidden = False
        self.neighbors = {"left": None, "right": None}
        self.cats = []
        self.toys = []
        self.butterflies = []
        self.set_size(1440, 900)

    def set_size(self, w, h):
        self.W, self.H = w, h
        self.platforms["floor"] = Platform("floor", 0, w, h)

    def set_windows(self, plats):
        floor = self.platforms["floor"]
        self.platforms = {"floor": floor}
        for p in plats:
            self.platforms[p.id] = p

    def floor(self):
        return self.platforms["floor"]

    def platform_under(self, px, py):
        best = None
        for p in self.platforms.values():
            if p.x0 <= px <= p.x1 and p.y >= py - 5:
                if best is None or p.y < best.y:
                    best = p
        return best


class Cat:
    def __init__(self, idx, world, cfg, sound=None, bond=None):
        self.idx = idx
        self.w = world
        self.cfg = cfg
        self.sound = sound
        self.bond = bond if bond is not None else {"affection": 50.0, "hunger": 20.0, "pets": 0, "treats": 0}
        self.peers = []
        self.t = 0.0
        self.x = world.W * random.uniform(0.25, 0.75)
        self.y = 140.0
        self.vx, self.vy = random.choice((-1, 1)) * 120.0, 0.0
        self.pid = "floor"
        self.ref = None
        self.facing = random.choice((-1, 1))
        self.state = "fall"
        self.st = 0.0
        self.dur = 0.0
        self.queue = []
        self.energy = random.uniform(0.7, 0.95)
        self.phase = 0.0
        self.prev_x = self.x
        self.vel_x = 0.0
        self.target_x = None
        self.speed_mul = 1.0
        self.jump = None
        self.squash = 0.0
        self.blink_in = random.uniform(1.5, 4)
        self.blink = 0.0
        self.twitch_in = 3.0
        self.twitch = 0.0
        self.look = (0.0, 0.0)
        self.particles = []
        self.bubble = None          # [text, until, started]
        self.play_until = 0.0
        self.calm = False           # set by app during focus sessions
        self.on_break = False
        self.night = False
        self.emit_t = 0.0
        self.sleep_reason = None
        # social / toys
        self.target = None
        self.partner = None
        self.gap = 0.0
        self.tries = 0
        self.tussle_lead = False
        self.cloud = 0.0
        self.booped = False
        self.box = None
        self.inbox_sleep = False
        self.want_box_sleep = False
        self.pet_times = []
        self.social_cool = random.uniform(15, 30)
        self.flag = False
        self.hungry_nag = 120.0

    # ------------------------------------------------------------ helpers --
    @property
    def profile(self):
        cats = self.cfg.get("cats") or []
        return cats[self.idx] if self.idx < len(cats) else {"name": "Cat", "color": "ginger"}

    @property
    def name(self):
        return self.profile.get("name") or "Cat"

    @property
    def color(self):
        return self.profile.get("color") or "ginger"

    @property
    def s(self):
        return float(self.cfg.get("size", 1.1))

    @property
    def act(self):
        return ACTIVITY.get(self.cfg.get("activity", "normal"), 1.0)

    @property
    def max_up(self):
        return 520.0 * min(1.3, self.s)

    @property
    def max_dx(self):
        return 650.0

    @property
    def airborne(self):
        return self.state in ("jump", "fall", "dragged")

    @property
    def asleep(self):
        return self.state == "sleep" or (self.state == "inbox" and self.inbox_sleep)

    @property
    def affection(self):
        return self.bond["affection"]

    def love(self, amount):
        self.bond["affection"] = clamp(self.bond["affection"] + amount, 0.0, 100.0)

    def platform(self):
        return self.w.platforms.get(self.pid) or self.w.platforms["floor"]

    def say(self, text, dur=3.0, sound=None):
        self.bubble = [text, self.t + dur, self.t]
        if sound and self.sound:
            self.sound.play(sound, voice=self.idx)

    def emit(self, kind, n=1, **kw):
        for _ in range(n):
            p = {"kind": kind, "x": self.x + random.uniform(-14, 14) * self.s,
                 "y": self.y - random.uniform(45, 62) * self.s,
                 "vx": random.uniform(-18, 18), "vy": random.uniform(-55, -35),
                 "life": 1.6, "max": 1.6, "size": 8 * self.s, "rot": random.uniform(0, 6)}
            p.update(kw)
            self.particles.append(p)

    def friend(self):
        for c in self.peers:
            if c is not self and c.w is self.w:
                return c
        return None

    def far_friend(self):
        for c in self.peers:
            if c is not self and c.w is not self.w:
                return c
        return None

    def dir_to(self, world):
        for d, nb in self.w.neighbors.items():
            if nb is world:
                return d
        return None

    def head_top(self):
        pose = self.pose_name() or "sit"
        hx, hy = HEAD.get(pose, (6, -64))
        return self.x + hx * self.facing * self.s, self.y + hy * self.s

    def bbox(self):
        s = self.s
        if self.state == "dragged":
            return (self.x - 40 * s, self.y - 95 * s, 80 * s, 115 * s)
        if self.state == "tussle":
            return (self.cloud - 70 * s, self.y - 90 * s, 140 * s, 98 * s)
        return (self.x - 62 * s, self.y - 84 * s, 124 * s, 94 * s)

    def hit_box(self):
        s = self.s
        if self.state == "dragged":
            return (self.x - 22 * s, self.y - 72 * s, 44 * s, 76 * s)
        if self.state == "tussle":
            return (self.cloud - 40 * s, self.y - 60 * s, 80 * s, 62 * s)
        pose = self.pose_name()
        top = {"sleep": 34, "loaf": 44, "stretch": 50, "scratch": 78}.get(pose, 66) * s
        if self.state == "inbox":
            top = (44 if self.inbox_sleep else 64) * s
        return (self.x - 32 * s, self.y - top, 64 * s, top + 3)

    def hit(self, px, py):
        x, y, w, h = self.hit_box()
        return x <= px <= x + w and y <= py <= y + h

    def body_part(self, px, py):
        """Which part of the cat is under the pointer: head | back | tail."""
        x, y, w, h = self.hit_box()
        rel = (px - self.x) * self.facing
        if py < y + h * 0.45 or rel > 8 * self.s:
            return "head"
        if rel < -18 * self.s:
            return "tail"
        return "back"

    # --------------------------------------------------- step scheduling --
    def set_state(self, st, dur=0.0):
        self.state = st
        self.st = 0.0
        self.dur = dur
        self.flag = False

    def interrupt(self, steps):
        if self.box is not None and self.state == "inbox":
            self.leave_box(then=steps)
            return
        self.queue = list(steps)
        if not self.airborne:
            self.next()

    def next(self):
        if self.queue:
            self.run_step(self.queue.pop(0))
        else:
            self.decide()

    def run_step(self, step):
        kind = step[0]
        s = self.s
        if kind in ("walk", "run"):
            self.target_x = step[1]
            self.speed_mul = step[2] if len(step) > 2 else 1.0
            self.set_state(kind)
        elif kind == "jump":
            self.begin_jump(step[1], step[2], step[3] if len(step) > 3 else None)
        elif kind == "face":
            self.facing = step[1]
            self.next()
        elif kind == "face_to":
            tg = step[1]
            if tg is not None and abs(tg.x - self.x) > 2:
                self.facing = 1 if tg.x > self.x else -1
            self.next()
        elif kind == "say":
            self.say(step[1], step[2] if len(step) > 2 else 3.0, step[3] if len(step) > 3 else None)
            self.next()
        elif kind == "chase":
            self.set_state("chase")
        elif kind == "approach":
            self.target, self.gap = step[1], step[2]
            self.tries = step[4] if len(step) > 4 else 0
            self.set_state("approach", step[3])
        elif kind in ("pursue", "hunt"):
            self.target = step[1]
            self.set_state(kind, step[2])
        elif kind == "boop":
            self.partner = step[2]
            self.booped = False
            self.set_state("boop", step[1])
        elif kind == "ready":
            self.set_state("ready", step[1])
        elif kind == "tussle_start":
            self.start_tussle(step[1])
        elif kind == "allogroom":
            p = step[2]
            if (p.w is self.w and abs(p.x - self.x) < 55 * s and not p.airborne and p.box is None
                    and not p.asleep and p.state not in ("tussle",)):
                p.queue = [("sit", 2.0)]
                p.set_state("petted", step[1])
                p.say("prrr… 💕", 2.0, "purr")
                self.partner = p
                self.facing = 1 if p.x > self.x else -1
                self.set_state("allogroom", step[1])
            else:
                self.next()
        elif kind == "cuddle_down":
            self.emit("heart", 2)
            self.love(2)
            self.sleep_reason = None
            self.set_state("sleep", step[1])
        elif kind == "enter_box":
            self.enter_box(step[1])
        elif kind == "bat":
            ball = step[1]
            if ball.w is self.w and ball.grounded and abs(ball.x - self.x) < 36 * s:
                self.facing = 1 if ball.x >= self.x else -1
                ball.kick(self.facing * random.uniform(260, 600), -random.uniform(120, 420))
                self.set_state("swipe", 0.45)
            else:
                self.next()
        elif kind == "eat_treat":
            tr = step[1]
            if tr.w is self.w and not tr.eaten and tr.grounded and abs(tr.x - self.x) < 40 * s:
                tr.eaten = True
                self.facing = 1 if tr.x >= self.x else -1
                self.say(random.choice(TREAT_LINES), 2.6, "meow")
                self.bond["hunger"] = max(0.0, self.bond["hunger"] - 40)
                self.bond["treats"] += 1
                self.love(4)
                self.energy = min(1.0, self.energy + 0.15)
                self.set_state("eat", 2.6)
                for c in self.peers:   # the other cat missed out
                    if c is not self and c.target is tr:
                        c.target = None
                        c.queue = [("say", random.choice(["hey! that was mine 😿", "no fair!!", "…😾"]), 2.0), ("sit", 2.0)]
                        if not c.airborne:
                            c.next()
            else:
                self.next()
        elif kind == "cross":
            self.cross(step[1])
        else:
            if kind == "sleep":
                self.sleep_reason = step[2] if len(step) > 2 else None
            self.set_state(kind, step[1] if len(step) > 1 else 1.5)

    def abort(self):
        self.queue = []
        self.target = None
        self.set_state("sit", random.uniform(1.0, 2.0))

    # ---------------------------------------------------------- planning --
    def reachable(self):
        cur = self.platform()
        out = []
        for p in self.w.platforms.values():
            if p.id == cur.id or p.x1 - p.x0 < 60:
                continue
            tx = random.uniform(p.x0 + 30, p.x1 - 30)
            if self.travel(p, tx, check=True):
                out.append((p, tx))
        return out

    def travel(self, p, tx, check=False):
        cur = self.platform()
        tx = clamp(tx, p.x0 + 20, p.x1 - 20)
        if p.id == cur.id or (abs(p.y - cur.y) < 4 and (p.x0 - 30 <= cur.x1 and cur.x0 <= p.x1 + 30)):
            return True if check else [("run" if abs(tx - self.x) > 380 else "walk", tx)]
        up = cur.y - p.y
        if up > self.max_up:
            return None
        if up < -40 and cur.x0 - 10 <= tx <= cur.x1 + 10 and p.id == "floor":
            left, right = cur.x0 - 45, cur.x1 + 45
            cands = [v for v in (left, right) if 20 < v < self.w.W - 20]
            if cands:
                tx = min(cands, key=lambda v: abs(v - self.x))
        lx = clamp(tx, cur.x0 + 18, cur.x1 - 18)
        if abs(tx - lx) > self.max_dx:
            return None
        if check:
            return True
        steps = []
        if abs(lx - self.x) > 8:
            steps.append(("walk" if abs(lx - self.x) < 300 else "run", lx))
        steps += [("face", 1 if tx >= lx else -1), ("crouch", 0.45), ("jump", p.id, tx)]
        return steps

    def plan_sleep(self, nap=False, reason=None):
        cur = self.platform()
        dur = random.uniform(25, 60) if nap else random.uniform(70, 200)
        stay = self.cfg.get("stay_put")
        f = self.friend()
        if not stay and f is not None and f.state == "sleep" and f.box is None and random.random() < 0.6:
            if self.travel(f.platform(), f.x, check=True):
                self.queue = [("approach", f, 36 * self.s, 10.0, 0), ("face", f.facing), ("cuddle_down", dur)]
                self.next()
                return
        boxes = [b for b in self.w.toys if b.kind == "box" and b.occupant is None and b.grounded]
        if not stay and boxes and random.random() < 0.3:
            self.want_box_sleep = True
            self.plan_box(boxes[0])
            return
        options = [(cur, random.uniform(cur.x0 + 40, max(cur.x0 + 41, cur.x1 - 40)))]
        if not stay:
            options += self.reachable()
        if len(options) > 1 and random.random() < 0.55:
            p, tx = random.choice(options[1:])
        else:
            p, tx = options[0]
        steps = (None if stay else self.travel(p, tx)) or []
        if random.random() < 0.45:
            steps.append(("knead", random.uniform(2.0, 3.5)))
        steps += [("yawn", 1.2), ("sleep", dur, reason)]
        self.queue = steps
        self.next()

    def plan_box(self, box):
        self.queue = [("approach", box, 0.0, 9.0, 0), ("enter_box", box)]
        self.next()

    def plan_ball(self, ball):
        steps = []
        for _ in range(random.randint(1, 3)):
            steps += [("approach", ball, 16 * self.s, 6.0, 0), ("bat", ball)]
        self.queue = steps + [("sit", 2.0)]
        self.next()

    def plan_treat(self, treat):
        self.target = treat
        self.queue = [("approach", treat, 12 * self.s, 9.0, 0), ("eat_treat", treat)]
        if self.box is not None:
            self.leave_box(then=self.queue)
            return
        if self.asleep:
            self.say("!! treat?! 🐟", 1.5, "meow")
        if not self.airborne:
            self.next()

    def plan_visit(self, d):
        nb = self.w.neighbors.get(d)
        if nb is None or self.airborne:
            return False
        W = self.w.W
        edge = 3 if d == "left" else W - 3
        steps = []
        if self.pid != "floor":
            steps = self.travel(self.w.floor(), edge + (80 if d == "left" else -80))
            if not steps:
                return False
        steps += [("run", edge), ("cross", d)]
        self.interrupt(steps)
        return True

    def cross(self, d):
        nb = self.w.neighbors.get(d)
        if nb is None:
            self.next()
            return
        self.w = nb
        self.particles = []
        self.pid = "floor"
        self.ref = None
        self.y = nb.H
        self.x = nb.W - 3 if d == "left" else 3
        self.facing = -1 if d == "left" else 1
        inward = self.x + self.facing * random.uniform(120, 350)
        self.queue = [("run", clamp(inward, 30, nb.W - 30))] + self.queue
        f = self.friend()
        if f is not None:
            self.queue.append(("say", f"hi {f.name}! 😸", 2.0, "meow"))
        self.queue.append(("sit", 2.0))
        self.next()

    def start_social(self, kind=None):
        f = self.friend()
        if (f is None or self.airborne or f.airborne or self.box is not None or f.box is not None
                or f.state in ("dragged", "tussle", "eat", "approach") or self.cfg.get("stay_put")):
            return False
        if kind is None:
            if f.asleep:
                if self.energy < 0.5:
                    kind = "cuddle"
                elif random.random() < 0.3:
                    kind = "boop"
                else:
                    return False
            elif not (f.state in IDLE_STATES and f.t >= f.social_cool):
                return False
            else:
                opts = [(2.0, "boop"), (2.2, "chase"), (1.6, "tussle"), (1.2, "groom")]
                if self.energy < 0.45 and f.energy < 0.55:
                    opts.append((2.0, "cuddle"))
                kind = weighted(opts)
        if f.pid != self.pid and not self.travel(f.platform(), f.x, check=True):
            return False
        s = self.s
        self.social_cool = self.t + random.uniform(35, 70)
        f.social_cool = f.t + random.uniform(25, 50)
        if kind == "boop":
            self.queue = [("approach", f, 25 * s, 8.0, 0), ("boop", 3.0, f)]
            if not f.asleep:
                f.queue = [("face_to", self), ("boop", 7.0, self)]
                f.next()
        elif kind == "chase":
            cur = f.platform()
            if cur.x1 - cur.x0 < 250:
                return self.start_social("boop")
            pts = [random.uniform(cur.x0 + 30, cur.x1 - 30) for _ in range(3)]
            f.queue = [("say", "catch me! 😼", 1.8)] + [("run", x, 1.2) for x in pts] + [("sit", 2.0)]
            f.next()
            self.say("hehe 😈", 1.5)
            self.queue = [("pursue", f, 8.0)]
        elif kind == "tussle":
            self.queue = [("approach", f, 22 * s, 7.0, 0), ("tussle_start", f)]
            f.queue = [("face_to", self), ("ready", 7.0)]
            f.next()
        elif kind == "groom":
            self.queue = [("approach", f, 26 * s, 8.0, 0), ("face_to", f), ("allogroom", 3.2, f), ("sit", 2.0)]
            f.queue = [("face_to", self), ("sit", 9.0)]
            f.next()
        elif kind == "cuddle":
            dur = random.uniform(80, 180)
            self.queue = [("approach", f, 36 * s, 10.0, 0), ("face", f.facing), ("yawn", 1.0), ("cuddle_down", dur)]
            if not f.asleep:
                f.queue = [("yawn", 1.2), ("sleep", dur + 15)]
                f.next()
        self.next()
        return True

    def start_tussle(self, p):
        if (p.w is not self.w or p.airborne or p.box is not None or abs(p.y - self.y) > 10
                or abs(p.x - self.x) > 80 * self.s):
            self.next()
            return
        cx = (self.x + p.x) / 2
        for c, lead in ((self, True), (p, False)):
            c.queue = []
            c.jump = None
            c.tussle_lead = lead
            c.cloud = cx
            c.partner = p if lead else self
            c.x = cx
            c.set_state("tussle", 2.6)
        self.say("!!! 💥", 1.0, "meow")

    def decide(self):
        w = self.w
        cur = self.platform()
        calm = self.calm
        stay = self.cfg.get("stay_put", False)
        act = self.act
        self.target = None
        if self.play_until > self.t and not stay:
            self.set_state("chase")
            return
        if self.energy < 0.15 or (calm and self.energy < 0.6 and random.random() < 0.3):
            self.plan_sleep(nap=self.energy > 0.3)
            return
        opts = [(4.0 if calm else 3.0, "sit"), (1.8 if calm else 1.0, "loaf"), (1.0, "groom"),
                (0.5, "stretch"), (0.3 + (1 - self.energy), "yawn"), (0.25, "meow"), (0.35, "knead")]
        if not stay:
            brk = 2.0 if self.on_break else 1.0
            opts += [((0.6 if calm else 3.0) * act * brk, "walk"),
                     ((0.3 if calm else 2.2) * act * brk, "jump"),
                     ((0.0 if calm else 0.4) * act * brk, "zoomies"),
                     ((0.0 if calm else 0.22) * act, "spin")]
            if w.cursor and not calm:
                opts.append(((0.8 + self.affection / 100) * act, "curious"))
            f = self.friend()
            if f is not None and self.t >= self.social_cool:
                opts.append(((0.5 if calm else 2.4) * act * brk, "social"))
            ff = self.far_friend()
            if ff is not None and not calm and self.dir_to(ff.w):
                opts.append((0.35 * act, "visit_friend"))
            if any(t.kind == "ball" for t in w.toys) and not calm:
                opts.append((1.3 * act * brk, "ball"))
            if any(t.kind == "box" and t.occupant is None and t.grounded for t in w.toys):
                opts += [(1.2, "box"), (0.35, "scratch")]
            if w.butterflies and not calm:
                opts.append((5.0, "hunt"))
        if self.energy < 0.55 or self.night:
            opts.append((0.8 if not self.night else 1.5, "nap"))
        c = weighted(opts)
        s = self.s
        if c == "sit":
            self.run_step(("sit", random.uniform(3, 8) / math.sqrt(act)))
        elif c == "loaf":
            self.run_step(("loaf", random.uniform(6, 14)))
        elif c == "groom":
            self.run_step(("groom", random.uniform(2.5, 4.5)))
        elif c == "stretch":
            self.run_step(("stretch", 1.8))
        elif c == "yawn":
            self.run_step(("yawn", 1.3))
        elif c == "knead":
            self.run_step(("knead", random.uniform(3, 5)))
        elif c == "spin":
            self.say(random.choice(["?!", "my tail!!", "*spins*"]), 1.4)
            self.run_step(("spin", 2.4))
        elif c == "meow":
            line = random.choice(HUNGRY_LINES) if self.bond["hunger"] > 70 else random.choice(IDLE_LINES)
            self.say(line, 2.2, "meow")
            self.run_step(("sit", random.uniform(2, 4)))
        elif c == "nap":
            self.plan_sleep(nap=True)
        elif c == "walk":
            x = random.uniform(cur.x0 + 30, max(cur.x0 + 31, cur.x1 - 30))
            if abs(x - self.x) < 50:
                self.run_step(("sit", 2.0))
            else:
                self.interrupt([("walk", x), ("sit", random.uniform(1.5, 4))])
        elif c == "jump":
            r = self.reachable()
            if r:
                p, tx = random.choice(r)
                self.interrupt(self.travel(p, tx) + [("sit", random.uniform(2, 4))])
            elif cur.x1 - cur.x0 > 200:
                tx = clamp(self.x + random.choice((-1, 1)) * random.uniform(80, 200), cur.x0 + 30, cur.x1 - 30)
                self.facing = 1 if tx > self.x else -1
                self.interrupt([("crouch", 0.4), ("jump", cur.id, tx), ("sit", 2.5)])
            else:
                self.run_step(("sit", 3.0))
        elif c == "zoomies":
            pts = [random.uniform(cur.x0 + 30, max(cur.x0 + 31, cur.x1 - 30)) for _ in range(3)]
            self.say("!!! ⚡", 1.2)
            self.interrupt([("run", x, 1.5) for x in pts] + [("sit", 2.5)])
        elif c == "curious":
            cx, cy = w.cursor
            target = w.platform_under(cx, cy)
            steps = self.travel(target, cx + random.uniform(-40, 40)) if target else None
            if steps:
                self.interrupt(steps + [("sit", random.uniform(3, 6))])
            else:
                self.run_step(("sit", 3.0))
        elif c == "social":
            if not self.start_social():
                self.run_step(("sit", 2.0))
        elif c == "visit_friend":
            if not self.plan_visit(self.dir_to(self.far_friend().w)):
                self.run_step(("sit", 2.0))
        elif c == "ball":
            self.plan_ball(random.choice([t for t in w.toys if t.kind == "ball"]))
        elif c == "box":
            self.plan_box(random.choice([t for t in w.toys if t.kind == "box" and t.occupant is None]))
        elif c == "scratch":
            b = random.choice([t for t in w.toys if t.kind == "box"])
            self.interrupt([("approach", b, 36 * s, 8.0, 0), ("face_to", b), ("scratch", 3.0), ("sit", 2.0)])
        elif c == "hunt":
            self.say("👀", 1.2)
            self.run_step(("hunt", w.butterflies[0], 12.0))

    # ------------------------------------------------------------- jumps --
    def begin_jump(self, pid, tx, h=None, ty=None, box=None):
        p = self.w.platforms.get(pid) if pid is not None else None
        if p is None and box is None:
            self.next()
            return
        x0, y0 = self.x, self.y
        y1 = ty if ty is not None else p.y
        D = y0 - y1
        if h is None:
            h = 28 * self.s + max(0.0, D) * 0.55 + abs(tx - x0) * 0.07
        dist = math.hypot(tx - x0, y1 - y0)
        T = 0.38 + dist / 1500.0 + max(0.0, D) / 2000.0
        self.jump = dict(x0=x0, y0=y0, x1=tx, y1=y1, h=h, T=T, pid=pid, box=box)
        if abs(tx - x0) > 3:
            self.facing = 1 if tx > x0 else -1
        self.set_state("jump")

    def land(self, p, impact=0.0):
        self.y = p.y
        self.pid = p.id
        self.ref = (p.x0, p.x1 - p.x0)
        self.vx = self.vy = 0.0
        self.squash = clamp(impact / 4000.0, 0.08, 0.28)
        self.jump = None
        if impact > 1700:
            self.say(random.choice(THROW_LINES), 2.0, "meow")
            self.emit("star", 3, vy=-40, life=1.0, max=1.0)
            self.love(-1)
        self.set_state("land", 0.22)

    def start_fall(self, vx=0.0, vy=0.0):
        if self.box is not None:
            self.box.occupant = None
            self.box = None
        self.vx, self.vy = vx, vy
        self.jump = None
        self.set_state("fall")

    def drop_into(self, world):
        """Teleport into another world (monitor added/removed): fall in from the top."""
        self.w = world
        self.particles = []
        self.queue = []
        self.x = clamp(self.x, 40, world.W - 40)
        self.y = 100.0
        self.start_fall(0, 0)

    # --------------------------------------------------------------- box --
    def enter_box(self, box):
        s = self.s
        if box.occupant is None and box.w is self.w and box.grounded and abs(box.x - self.x) < 34 * s:
            self.begin_jump(None, box.x, 34 * s, ty=box.y - 3 * s, box=box)
        else:
            self.want_box_sleep = False
            self.next()

    def leave_box(self, then=None):
        b = self.box
        self.box = None
        if b is not None:
            b.occupant = None
        self.inbox_sleep = False
        if b is None or not b.grounded:
            self.queue = list(then or [])
            self.start_fall()
            return
        p = self.w.platforms.get(b.pid) or self.w.floor()
        self.pid = p.id
        tx = clamp(b.x + random.choice((-1, 1)) * 55 * self.s, p.x0 + 20, p.x1 - 20)
        self.queue = [("jump", p.id, tx, 34 * self.s)] + list(then or [("sit", 2.0)])
        self.next()

    # ------------------------------------------------------- interaction --
    def pet(self, part="head"):
        if self.state in ("dragged", "jump", "fall", "tussle"):
            return
        self.bond["pets"] += 1
        if self.state == "inbox":
            if self.inbox_sleep:
                self.inbox_sleep = False
                self.say(random.choice(WAKE_LINES), 2.0)
            else:
                self.say(random.choice(PET_LINES), 2.0, "purr")
            self.emit("heart", 2)
            self.love(1.5)
            return
        if self.asleep:
            self.wake(gentle=True)
            return
        if part == "tail" and random.random() < 0.6:
            self.say(random.choice(TAIL_LINES), 2.2, "meow")
            self.love(-2)
            self.queue = [("sit", 1.5)]
            self.set_state("annoyed", 1.4)
            return
        now = self.t
        self.pet_times = [p for p in self.pet_times if now - p < 20] + [now]
        limit = 6 + int(self.affection / 25)        # a bonded cat tolerates more pets
        if len(self.pet_times) >= limit:
            self.pet_times = []
            cur = self.platform()
            away = clamp(self.x - self.facing * random.uniform(150, 300), cur.x0 + 30, cur.x1 - 30)
            self.say("ok that's enough!! 😾", 2.5, "meow")
            self.queue = [("walk", away), ("groom", 3.0)]
            self.set_state("annoyed", 1.4)
            return
        if self.state != "petted":
            self.say(random.choice(PET_LINES), 2.5, "purr")
        self.love(2.5 if part == "head" else 1.5)
        self.queue = [("knead", 2.5)] if len(self.pet_times) == 3 else []
        self.set_state("petted", 2.8)
        self.energy = min(1.0, self.energy + 0.02)

    def boop(self):
        """double click: happy hop + meow"""
        if self.airborne or self.box is not None:
            return
        if self.asleep:
            self.wake()
            return
        cur = self.platform()
        self.say("mrrp! ✨", 1.8, "meow")
        self.emit("star", 3)
        self.love(1)
        self.queue = []
        self.interrupt([("crouch", 0.18), ("jump", cur.id, self.x, 60 * self.s), ("sit", 2.0)])

    def wake(self, gentle=False):
        self.say(random.choice(WAKE_LINES), 2.5)
        if self.box is not None:
            self.inbox_sleep = False
            self.st = max(0.0, self.dur - 3.0)
            return
        self.queue = []
        self.interrupt([("stretch", 1.6), ("yawn", 1.2), ("sit", 2.0)] if not gentle else
                       [("yawn", 1.2), ("petted", 2.0)])

    def welcome(self):
        cur = self.platform()
        steps = [("say", random.choice(["welcome back! 😸", "you're back!! 💕", "missed you~"]), 3.0, "meow")]
        if self.w.cursor and not self.cfg.get("stay_put"):
            steps.append(("walk", clamp(self.w.cursor[0], cur.x0 + 20, cur.x1 - 20)))
        steps.append(("petted", 1.5))
        if self.asleep:
            steps = [("stretch", 1.4)] + steps
        self.interrupt(steps)

    def drag_start(self):
        if self.box is not None:
            self.box.occupant = None
            self.box = None
            self.inbox_sleep = False
        self.queue = []
        self.jump = None
        self.target = None
        self.set_state("dragged")
        self.say(random.choice(DRAG_LINES), 2.0, "meow")

    def drag_to(self, px, py):
        self.x = clamp(px, 10, self.w.W - 10)
        self.y = py + 60 * self.s

    def release(self, vx, vy):
        self.start_fall(clamp(vx, -2200, 2200), clamp(vy, -2200, 2200))

    def play(self, seconds=30):
        if self.box is not None:
            self.leave_box()
        self.play_until = self.t + seconds
        self.say("ooh, a toy?! 🧶", 2.0, "meow")
        self.queue = []
        if not self.airborne:
            self.set_state("chase")

    def sleep_now(self):
        if self.box is not None:
            self.inbox_sleep = True
            self.st = 0.0
            self.dur = max(self.dur, 120.0)
            return
        self.queue = []
        if not self.airborne:
            self.interrupt([("yawn", 1.0), ("sleep", random.uniform(120, 300))])

    def alert(self, text, sound="meow"):
        """Grumpy reminder (distractions)."""
        if self.state == "dragged":
            return
        self.say(text, 5.0, sound)
        self.interrupt([("alert", 4.0), ("sit", 2.0)])

    def notice(self, text, action="sit", dur=4.0, sound="meow"):
        """Friendly reminder: wake up, show a message, maybe do an action."""
        self.say(text, 6.0, sound)
        if self.state in ("dragged", "tussle"):
            return
        self.interrupt([(action, dur), ("sit", 2.0)])

    def celebrate(self, text=None):
        if text:
            self.say(text, 6.0, "meow")
        if self.state in ("dragged", "tussle"):
            return
        self.interrupt([("celebrate", 2.2), ("petted", 1.5)])

    # ------------------------------------------------------------ update --
    def update(self, dt):
        self.t += dt
        self.st += dt
        w = self.w
        s = self.s

        # needs
        if self.asleep:
            self.energy = min(1.0, self.energy + dt / 150.0)
        else:
            drain = (1.6 if self.state in ("run", "chase", "pursue", "hunt") else 1.0) * (1.5 if self.night else 1.0)
            self.energy = max(0.0, self.energy - dt / (700.0 * self.act ** 0.5) * drain)
        self.bond["hunger"] = min(100.0, self.bond["hunger"] + dt / 110.0)   # ~3h from full to starving
        self.bond["affection"] = max(0.0, self.bond["affection"] - dt / 1800.0)
        self.hungry_nag -= dt
        if (self.bond["hunger"] > 75 and self.hungry_nag <= 0 and not self.calm
                and self.state in ("sit", "loaf", "walk")):
            self.hungry_nag = random.uniform(240, 480)
            self.say(random.choice(HUNGRY_LINES), 3.0, "meow")

        # blink / ear twitch
        self.blink_in -= dt
        if self.blink_in <= 0:
            self.blink = 0.13
            self.blink_in = random.uniform(2.0, 5.5)
        self.blink = max(0.0, self.blink - dt)
        self.twitch_in -= dt
        if self.twitch_in <= 0:
            self.twitch = 0.18
            self.twitch_in = random.uniform(2.5, 8)
        self.twitch = max(0.0, self.twitch - dt)
        self.squash = max(0.0, self.squash - dt * 1.2)

        # look at the most interesting thing: a butterfly, the other cat playing, or the cursor
        tl = (0.0, 0.0)
        if not self.asleep:
            hx, hy = self.x, self.y - 45 * s
            focus = None
            if w.butterflies:
                b = min(w.butterflies, key=lambda b: abs(b.x - self.x))
                if b.perch is self:
                    tl = (0.0, -1.0)
                elif abs(b.x - self.x) < 450:
                    focus = (b.x, b.y)
            if focus is None and w.cursor:
                if math.hypot(w.cursor[0] - hx, w.cursor[1] - hy) < 600:
                    focus = w.cursor
            if focus is not None:
                tl = (clamp((focus[0] - hx) / 220, -1, 1) * self.facing, clamp((focus[1] - hy) / 220, -1, 1))
        k = min(1.0, dt * 6)
        self.look = (self.look[0] + (tl[0] - self.look[0]) * k, self.look[1] + (tl[1] - self.look[1]) * k)

        # stand on (and ride along with) the current platform
        if not self.airborne and self.state != "inbox":
            p = w.platforms.get(self.pid)
            if p is None:
                self.start_fall(0, 0)
            else:
                if self.ref and abs((p.x1 - p.x0) - self.ref[1]) < 2 and p.x0 != self.ref[0]:
                    self.x += p.x0 - self.ref[0]
                    if self.state == "tussle":
                        self.cloud += p.x0 - self.ref[0]
                self.ref = (p.x0, p.x1 - p.x0)
                self.y = p.y
                if not (p.x0 - 12 <= self.x <= p.x1 + 12) and self.state not in ("walk", "run", "chase", "approach", "pursue", "hunt"):
                    self.start_fall(0, 0)

        self.prev_x = self.x
        getattr(self, "u_" + self.state, self.u_timed)(dt)
        if dt > 0:
            self.vel_x = self.vel_x * 0.7 + 0.3 * (self.x - self.prev_x) / dt
        if abs(self.vel_x) > 12 and self.state not in ("jump", "fall", "dragged"):
            self.phase += dt * (15 if abs(self.vel_x) > 130 else 8.5)

        # particles
        for p in self.particles:
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["life"] -= dt
        self.particles = [p for p in self.particles if p["life"] > 0]
        if self.bubble and self.t > self.bubble[1]:
            self.bubble = None

    def u_timed(self, dt):
        st = self.state
        if st == "petted":
            self.emit_t -= dt
            if self.emit_t <= 0:
                self.emit("heart", vy=-50)
                self.emit_t = 0.3
        elif st == "eat":
            self.emit_t -= dt
            if self.emit_t <= 0:
                self.emit("text", text="nom", size=10 * self.s, vy=-40, life=0.9, max=0.9)
                self.emit_t = 0.7
        elif st == "celebrate":
            self.emit_t -= dt
            if self.emit_t <= 0:
                self.emit("star", 2, vy=-70)
                self.emit("heart", vy=-60)
                self.emit_t = 0.25
        elif st == "knead":
            if not self.flag:
                self.flag = True
                if self.sound:
                    self.sound.play("purr", voice=self.idx)
            self.emit_t -= dt
            if self.emit_t <= 0:
                self.emit("heart", vy=-40, size=6 * self.s)
                self.emit_t = 0.9
        elif st == "scratch":
            self.emit_t -= dt
            if self.emit_t <= 0:
                self.emit("text", text="scritch", size=8 * self.s, x=self.x + self.facing * 24 * self.s,
                          y=self.y - 50 * self.s, vy=-30, life=0.7, max=0.7)
                self.emit_t = 0.6
        elif st == "slowblink":
            if not self.flag and self.st > self.dur * 0.5:
                self.flag = True
                self.emit("heart", vy=-35)
                self.love(1)
        elif st in ("alert", "annoyed"):
            if self.w.cursor:
                self.facing = 1 if self.w.cursor[0] >= self.x else -1
        elif st == "ready":
            p = self.partner
            if p is not None and p.w is self.w:
                self.facing = 1 if p.x >= self.x else -1
        if self.st >= self.dur:
            self.next()

    def u_sit(self, dt):
        w = self.w
        if w.cursor and not self.cfg.get("stay_put"):
            cx, cy = w.cursor
            dx = cx - self.x
            if abs(dx) > 70 and (dx > 0) != (self.facing > 0) and random.random() < dt * 0.6:
                self.facing = 1 if dx > 0 else -1
            up = self.y - cy
            # slow blink ("I love you" in cat) when you hover nearby, still
            if (w.cursor_still > 2.5 and math.hypot(dx, up - 40 * self.s) < 260 and self.st > 1.0
                    and random.random() < dt * 0.35):
                self.queue.insert(0, ("sit", 2.0))
                self.set_state("slowblink", 1.8)
                return
            if (not self.calm and abs(dx) < 130 * self.s and 25 < up < 170 * self.s
                    and self.st > 1.0 and random.random() < dt * 0.5 * self.act):
                cur = self.platform()
                tx = clamp(cx, cur.x0 + 15, cur.x1 - 15)
                self.facing = 1 if dx >= 0 else -1
                self.say("!", 0.8)
                self.interrupt([("crouch", 0.35), ("jump", cur.id, tx, up + 10), ("sit", 2.0)])
                return
        if self.st >= self.dur:
            self.next()

    u_loaf = u_sit

    def _zzz(self, dt, dy=30):
        self.emit_t -= dt
        if self.emit_t <= 0:
            s = self.s
            self.particles.append({"kind": "z", "x": self.x + 10 * s * self.facing, "y": self.y - dy * s,
                                   "vx": 12 * self.facing, "vy": -18, "life": 2.4, "max": 2.4,
                                   "size": random.uniform(10, 15) * s})
            self.emit_t = 1.3

    def u_sleep(self, dt):
        self._zzz(dt)
        if self.st >= self.dur:
            if self.sleep_reason == "focus":
                self.st = 0.0
                return
            self.wake()

    def u_inbox(self, dt):
        b = self.box
        if b is None or b.w is not self.w:
            self.box = None
            self.start_fall()
            return
        self.x = b.x
        self.y = b.y - 3 * self.s
        if self.inbox_sleep:
            self._zzz(dt, dy=40)
        if self.st >= self.dur:
            if b.dragged or not b.grounded:
                return
            self.leave_box()

    def _move_toward(self, dt, speed):
        dx = self.target_x - self.x
        step = speed * dt
        if abs(dx) <= step:
            self.x = self.target_x
            return True
        self.facing = 1 if dx > 0 else -1
        self.x += self.facing * step
        cur = self.platform()
        if not (cur.x0 - 2 <= self.x <= cur.x1 + 2):
            for q in self.w.platforms.values():
                if q.id != cur.id and abs(q.y - cur.y) < 4 and q.x0 - 30 <= self.x <= q.x1 + 30:
                    self.pid = q.id
                    self.ref = (q.x0, q.x1 - q.x0)
                    return False
            self.x = clamp(self.x, cur.x0, cur.x1)
            return True
        return False

    def u_walk(self, dt):
        if self._move_toward(dt, 58 * self.s * self.speed_mul):
            self.next()

    def u_run(self, dt):
        if self._move_toward(dt, 220 * self.s * self.speed_mul):
            self.next()

    def u_crouch(self, dt):
        if self.st >= self.dur:
            self.next()

    u_land = u_crouch

    def u_spin(self, dt):
        self.facing = 1 if int(self.st / 0.2) % 2 == 0 else -1
        if self.st >= self.dur:
            self.emit("star", 3, vy=-50)
            if random.random() < 0.5:
                self.say("dizzy… 😵‍💫", 1.8)
            self.next()

    @staticmethod
    def target_pid(tg):
        if isinstance(tg, Cat):
            if tg.airborne:
                return None
            return tg.box.pid if tg.box is not None else tg.pid
        return tg.pid if getattr(tg, "grounded", False) else None

    def u_approach(self, dt):
        tg = self.target
        if tg is None or tg.w is not self.w or self.st > self.dur or getattr(tg, "eaten", False):
            self.abort()
            return
        tp = self.target_pid(tg)
        if tp is None:
            return  # target in the air: wait for it to land
        cur = self.platform()
        p = self.w.platforms.get(tp)
        if p is None:
            self.abort()
            return
        if tp != cur.id and not (abs(p.y - cur.y) < 4 and p.x0 - 30 <= cur.x1 and cur.x0 <= p.x1 + 30):
            steps = self.travel(p, tg.x) if self.tries < 2 else None
            if not steps:
                self.abort()
                return
            self.queue = steps + [("approach", tg, self.gap, max(2.0, self.dur - self.st), self.tries + 1)] + self.queue
            self.next()
            return
        side = 1 if self.x >= tg.x else -1
        gx = clamp(tg.x + side * self.gap, cur.x0 + 5, cur.x1 - 5)
        if abs(gx - self.x) < 5:
            if abs(tg.x - self.x) > 2:
                self.facing = 1 if tg.x > self.x else -1
            self.next()
            return
        self.target_x = gx
        fast = abs(gx - self.x) > 200 or getattr(tg, "kind", "") == "treat"
        self._move_toward(dt, (220 if fast else 75) * self.s)

    def u_pursue(self, dt):
        tg = self.target
        if tg is None or tg.w is not self.w or self.st > self.dur or tg.airborne or tg.pid != self.pid:
            self.say(random.choice(["aww 😿", "too fast!", "next time…"]), 1.8)
            self.abort()
            return
        dx = tg.x - self.x
        if abs(dx) < 30 * self.s and self.st > 0.8:
            self.start_tussle(tg)
            return
        self.target_x = tg.x
        self._move_toward(dt, 265 * self.s)

    def u_hunt(self, dt):
        bf = self.target
        if bf is None or bf.gone or bf.w is not self.w or self.st > self.dur:
            self.abort()
            return
        cur = self.platform()
        tx = clamp(bf.x, cur.x0 + 15, cur.x1 - 15)
        dx = tx - self.x
        up = self.y - bf.y
        if abs(dx) > 25:
            self.target_x = tx
            self._move_toward(dt, (200 if abs(dx) > 120 else 70) * self.s)
        else:
            self.facing = 1 if bf.x >= self.x else -1
            if 25 < up < 230 * self.s and self.st > 0.8 and random.random() < dt * 2.0:
                bf.startle()
                left = max(1.0, self.dur - self.st)
                self.queue = [("crouch", 0.3), ("jump", cur.id, tx, up + 8), ("hunt", bf, left)]
                self.next()

    def u_chase(self, dt):
        w = self.w
        if self.t > self.play_until or not w.cursor:
            self.play_until = 0.0
            self.say("that was fun! 😸", 2.5, "purr")
            self.love(3)
            self.run_step(("sit", 3.0))
            return
        cx, cy = w.cursor
        cur = self.platform()
        under = w.platform_under(cx, cy)
        if under and under.id != cur.id and self.st > 0.5 and abs(under.y - cur.y) > 30:
            steps = self.travel(under, cx)
            if steps:
                self.interrupt(steps)
                return
        tx = clamp(cx, cur.x0 + 15, cur.x1 - 15)
        dx = tx - self.x
        if abs(dx) > 30:
            self.facing = 1 if dx > 0 else -1
            self.x += self.facing * min(abs(dx), 260 * self.s * dt)
            self.x = clamp(self.x, cur.x0, cur.x1)
        else:
            up = self.y - cy
            if self.st > 0.6 and 20 < up < 260:
                self.queue = [("crouch", 0.25), ("jump", cur.id, tx, up + 10), ("chase",)]
                self.next()

    def u_boop(self, dt):
        p = self.partner
        if p is not None and p.w is self.w:
            if abs(p.x - self.x) > 2:
                self.facing = 1 if p.x > self.x else -1
            if not self.booped and abs(p.x - self.x) < 44 * self.s and abs(p.y - self.y) < 10:
                self.booped = True
                p.booped = True
                if p.asleep:
                    p.wake(gentle=True)
                mx = (self.x + p.x) / 2
                self.particles.append({"kind": "heart", "x": mx, "y": self.y - 40 * self.s, "vx": 0, "vy": -30,
                                       "life": 1.8, "max": 1.8, "size": 11 * self.s})
                self.say("*boop* 💕", 1.8)
                self.love(1)
                p.love(1)
                self.dur = min(self.dur, self.st + 1.5)
                if p.state == "boop":
                    p.dur = min(p.dur, p.st + 1.5)
        if self.st >= self.dur:
            self.next()

    def u_tussle(self, dt):
        if self.tussle_lead:
            self.emit_t -= dt
            if self.emit_t <= 0:
                self.particles.append({"kind": "star", "x": self.cloud + random.uniform(-40, 40) * self.s,
                                       "y": self.y - random.uniform(30, 65) * self.s, "vx": random.uniform(-40, 40),
                                       "vy": -40, "life": 0.6, "max": 0.6, "size": 6 * self.s, "rot": 0})
                self.emit_t = 0.15
        if self.st >= self.dur:
            cur = self.platform()
            d = -1 if self.tussle_lead else 1
            tx = clamp(self.cloud + d * 65 * self.s, cur.x0 + 20, cur.x1 - 20)
            self.x = self.cloud + d * 6 * self.s
            self.queue = [("jump", self.pid, tx, 26 * self.s), ("face", -d), ("sit", random.uniform(2, 4))]
            if self.tussle_lead and random.random() < 0.7:
                self.queue.insert(2, ("say", random.choice(["rematch? 😼", "I won!", "hehe 😹", "good fight"]), 2.0))
            self.love(1)
            self.next()

    def u_jump(self, dt):
        j = self.jump
        if not j:
            self.start_fall()
            return
        u = self.st / j["T"]
        if u >= 1.0:
            vy = (j["y1"] - j["y0"]) / j["T"] + 4 * j["h"] / j["T"]
            self.x = j["x1"]
            box = j.get("box")
            if box is not None:
                self.jump = None
                if box.occupant is None and box.w is self.w and box.grounded and abs(box.x - self.x) < 30 * self.s:
                    self.box = box
                    box.occupant = self
                    self.inbox_sleep = self.want_box_sleep or self.energy < 0.3
                    self.want_box_sleep = False
                    self.squash = 0.15
                    if not self.inbox_sleep and random.random() < 0.5:
                        self.say("if I fits, I sits 📦", 2.5)
                    self.set_state("inbox", random.uniform(70, 160) if self.inbox_sleep else random.uniform(8, 20))
                else:
                    self.y = j["y1"]
                    self.start_fall(0, 0)
                return
            p = self.w.platforms.get(j["pid"])
            if p and p.x0 - 10 <= j["x1"] <= p.x1 + 10 and abs(p.y - j["y1"]) < 40:
                self.land(p, impact=vy)
            else:
                self.y = j["y1"]
                self.start_fall((j["x1"] - j["x0"]) / j["T"] * 0.5, vy * 0.3)
            return
        if j.get("box") is not None:
            b = j["box"]
            j["x1"], j["y1"] = b.x, b.y - 3 * self.s
        self.x = j["x0"] + (j["x1"] - j["x0"]) * u
        self.y = j["y0"] + (j["y1"] - j["y0"]) * u - 4 * j["h"] * u * (1 - u)
        self.vy = (j["y1"] - j["y0"]) / j["T"] - 4 * j["h"] * (1 - 2 * u) / j["T"]

    def u_fall(self, dt):
        w = self.w
        prev = self.y
        self.vy += GRAVITY * dt
        self.vx *= (1 - 0.5 * dt)
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.x < 25:
            self.x, self.vx = 25, abs(self.vx) * 0.5
        elif self.x > w.W - 25:
            self.x, self.vx = w.W - 25, -abs(self.vx) * 0.5
        top = 90 * self.s
        if self.y < top:
            self.y, self.vy = top, abs(self.vy) * 0.3
        if self.vy > 0:
            best = None
            for p in w.platforms.values():
                if prev <= p.y + 0.5 and self.y >= p.y and p.x0 <= self.x <= p.x1:
                    if best is None or p.y < best.y:
                        best = p
            if best:
                self.land(best, impact=self.vy)
                return
        if self.y > w.H:
            self.land(w.platforms["floor"], impact=self.vy)

    def u_dragged(self, dt):
        pass

    # ----------------------------------------------------------- drawing --
    def pose_name(self):
        st = self.state
        if st in ("walk", "run", "crouch", "land", "chase", "approach", "pursue", "hunt", "ready", "boop", "spin"):
            return "stand"
        if st in ("jump", "fall"):
            return "jump"
        if st == "dragged":
            return "dangle"
        if st == "sleep":
            return "sleep"
        if st in ("loaf", "knead"):
            return "loaf"
        if st == "stretch":
            return "stretch"
        if st == "scratch":
            return "scratch"
        if st == "tussle":
            return None
        if st == "inbox":
            return "loaf" if self.inbox_sleep else "sit"
        return "sit"

    def render_sig(self):
        """A coarse fingerprint of how the cat looks right now; redraw only when it changes."""
        pose, a, yoff = self.draw_params()
        q = []
        for k in sorted(a):
            if k == "t":
                continue
            v = a[k]
            if isinstance(v, float):
                q.append(round(v, 1))
            elif isinstance(v, tuple):
                q.append(tuple(round(x, 1) for x in v))
            else:
                q.append(v)
        timed = pose in ("scratch", "dangle", "jump") or self.state in ("tussle", "knead") or a.get("wiggle")
        return (pose, round(self.x), round(self.y + yoff), self.facing, round(self.squash, 2), self.color,
                self.s, tuple(q), round(self.t * 15) if timed else 0,
                round(self.cloud) if self.state == "tussle" else 0)

    def draw_params(self):
        st = self.state
        t = self.t
        a = {"t": t, "look": self.look, "tail": math.sin(t * 1.4 + self.idx) * 0.6 + math.sin(t * 3.7) * 0.25,
             "breathe": math.sin(t * 2.2 + self.idx), "ear_twitch": 1.0 if self.twitch > 0 else 0.0,
             "blush": 0.35 + self.affection / 250.0, "eyes": "open", "mouth": "w"}
        pose = self.pose_name()
        yoff = 0.0
        moving = abs(self.vel_x) > 12 or st == "spin"
        if pose == "stand":
            a["moving"] = moving
            a["run"] = abs(self.vel_x) > 130 or st == "spin"
            a["phase"] = self.phase
        if st in ("crouch", "ready") or (st in ("hunt", "chase") and not moving):
            a["crouch"] = 1.0
            a["wiggle"] = True
            a["eyes"] = "wide"
        if st == "boop":
            a["crouch"] = 0.3
            if self.booped:
                a["eyes"] = "happy"
                a["blush"] = 1.0
        if st == "land":
            a["crouch"] = 0.5
        if st in ("jump", "fall"):
            a["vy"] = self.vy
        if st == "dragged":
            a["eyes"] = "wide" if self.st < 1.2 else "open"
            a["mouth"] = "open" if self.st < 0.8 else "w"
            a["swing"] = 0.0
        if st == "sleep" or (st == "inbox" and self.inbox_sleep):
            a["eyes"] = "closed"
        if st in ("petted", "knead"):
            a["eyes"] = "happy" if st == "petted" else "closed"
            a["blush"] = 1.0
            a["head_tilt"] = math.sin(t * 3) * 0.08
            a["tail"] = math.sin(t * 5) * 0.9
            a["knead"] = st == "knead"
        if st == "groom":
            a["paw_up"] = math.sin(t * 7)
            a["eyes"] = "closed"
            a["mouth"] = "tongue"
            a["tilt"] = -0.12
        if st == "allogroom":
            a["eyes"] = "closed"
            a["mouth"] = "tongue"
            a["tilt"] = 0.22 + math.sin(t * 6) * 0.06
        if st == "swipe":
            a["paw_up"] = 1.0
            a["eyes"] = "wide"
        if st == "yawn":
            a["eyes"] = "closed"
            a["mouth"] = "yawn"
            a["mouth_open"] = math.sin(min(1.0, self.st / max(self.dur, 0.1)) * math.pi)
        if st == "stretch":
            a["eyes"] = "happy"
            a["mouth"] = "yawn"
        if st == "eat":
            a["eyes"] = "happy"
            a["mouth"] = "chew"
            a["mouth_open"] = 0.4 + 0.6 * abs(math.sin(t * 9))
            a["blush"] = 0.9
            a["head_tilt"] = 0.25
        if st in ("alert", "annoyed"):
            a["eyes"] = "angry"
            a["ear_flat"] = 0.6
            a["tail"] = math.sin(t * 9) * 1.0
            a["mouth"] = "open" if self.st < 0.6 else "w"
        if st == "celebrate":
            a["eyes"] = "happy"
            a["blush"] = 1.0
            yoff = -abs(math.sin(self.st * 7)) * 16 * self.s
            a["tail"] = math.sin(t * 8)
        if st == "slowblink":
            u = self.st / max(self.dur, 0.1)
            a["eyes"] = "closed" if 0.3 < u < 0.7 else "half"
            a["blush"] = 0.9
        if st == "scratch":
            a["eyes"] = "happy"
        if st in ("sit", "loaf") and self.energy < 0.25:
            a["eyes"] = "half"
        if a["eyes"] in ("open", "half") and self.blink > 0:
            a["eyes"] = "blink"
        if self.bubble and t - self.bubble[2] < 0.45 and a["mouth"] == "w" and not self.asleep:
            a["mouth"] = "open"
            a["mouth_open"] = math.sin((t - self.bubble[2]) / 0.45 * math.pi)
        return pose, a, yoff
