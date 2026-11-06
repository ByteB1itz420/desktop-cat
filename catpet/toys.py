"""Things the cats play with: a yarn ball, a cardboard box and butterflies."""
import math
import random

from .cat import GRAVITY, STILL_STATES, clamp


class Toy:
    kind = "toy"

    def __init__(self, world, x, s=1.1):
        self.w = world
        self.x = x
        self.y = 120.0
        self.vx = self.vy = 0.0
        self.pid = "floor"
        self.ref = None
        self.grounded = False
        self.dragged = False
        self.s = s
        self.hold_dy = 0.0

    @property
    def airborne(self):
        return not self.grounded

    def drag_start(self):
        self.dragged = True
        self.grounded = False

    def drag_to(self, px, py):
        self.x = clamp(px, 10, self.w.W - 10)
        self.y = py + self.hold_dy

    def release(self, vx, vy):
        self.dragged = False
        self.vx, self.vy = clamp(vx * 0.8, -1800, 1800), clamp(vy * 0.8, -1800, 1800)

    def drop_into(self, world):
        self.w = world
        self.x = clamp(self.x, 40, world.W - 40)
        self.y = 100.0
        self.grounded = False
        self.dragged = False
        self.vx = self.vy = 0.0

    def physics(self, dt, bounce=0.0, roll=False, margin=12):
        if self.dragged:
            return
        w = self.w
        if self.grounded:
            p = w.platforms.get(self.pid)
            if p is None or not (p.x0 - 2 <= self.x <= p.x1 + 2):
                self.grounded = False
                self.vy = 0.0
            else:
                if self.ref and abs((p.x1 - p.x0) - self.ref[1]) < 2:
                    self.x += p.x0 - self.ref[0]
                self.ref = (p.x0, p.x1 - p.x0)
                self.y = p.y
                if roll and self.vx:
                    self.x += self.vx * dt
                    self.vx *= max(0.0, 1 - 1.5 * dt)
                    if abs(self.vx) < 4:
                        self.vx = 0.0
                    if self.x < margin or self.x > w.W - margin:
                        self.x = clamp(self.x, margin, w.W - margin)
                        self.vx = -self.vx * 0.6
                return
        prev = self.y
        self.vy += GRAVITY * dt
        self.vx *= (1 - 0.3 * dt)
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.x < margin or self.x > w.W - margin:
            self.x = clamp(self.x, margin, w.W - margin)
            self.vx = -self.vx * 0.6
        if self.y < 40:
            self.y, self.vy = 40, abs(self.vy) * 0.3
        if self.vy > 0:
            best = None
            for p in w.platforms.values():
                if prev <= p.y + 0.5 and self.y >= p.y and p.x0 <= self.x <= p.x1:
                    if best is None or p.y < best.y:
                        best = p
            if best is None and self.y > w.H:
                best = w.platforms["floor"]
            if best:
                self.y = best.y
                if bounce and self.vy > 260:
                    self.vy = -self.vy * bounce
                    self.vx *= 0.85
                else:
                    self.vy = 0.0
                    self.grounded = True
                    self.pid = best.id
                    self.ref = (best.x0, best.x1 - best.x0)


class Ball(Toy):
    kind = "ball"

    def __init__(self, world, x, s=1.1):
        super().__init__(world, x, s)
        self.rot = 0.0

    @property
    def r(self):
        return 9.0 * self.s

    def drag_start(self):
        super().drag_start()
        self.hold_dy = self.r

    def kick(self, vx, vy):
        self.grounded = False
        self.vx, self.vy = vx, vy

    def update(self, dt):
        self.physics(dt, bounce=0.45, roll=True, margin=self.r)
        self.rot += self.vx * dt / max(self.r, 1)

    def bbox(self):
        r = self.r
        return (self.x - r * 4.2, self.y - 2 * r - 4, r * 8.4, 2 * r + 8)

    def hit_box(self):
        r = self.r
        return (self.x - r - 3, self.y - 2 * r - 3, 2 * r + 6, 2 * r + 6)


class Box(Toy):
    kind = "box"

    def __init__(self, world, x, s=1.1):
        super().__init__(world, x, s)
        self.occupant = None

    @property
    def size(self):
        return 56 * self.s, 32 * self.s

    def drag_start(self):
        super().drag_start()
        self.hold_dy = self.size[1] / 2

    def update(self, dt):
        self.physics(dt, bounce=0.0, roll=False, margin=self.size[0] / 2)

    def bbox(self):
        w, h = self.size
        return (self.x - w / 2 - 16 * self.s, self.y - h - 22 * self.s, w + 32 * self.s, h + 26 * self.s)

    def hit_box(self):
        w, h = self.size
        return (self.x - w / 2, self.y - h - 10 * self.s, w, h + 10 * self.s)


class Treat(Toy):
    """A fish-shaped treat. Falls, lands, and gets eaten by the fastest cat."""
    kind = "treat"

    def __init__(self, world, x, y, s=1.1):
        super().__init__(world, x, s)
        self.y = y
        self.vx = random.uniform(-60, 60)
        self.vy = -random.uniform(50, 200)
        self.eaten = False
        self.claimed_by = None
        self.age = 0.0
        self.rot = random.uniform(-0.4, 0.4)

    def drag_start(self):
        super().drag_start()
        self.claimed_by = None
        self.hold_dy = 4 * self.s

    def update(self, dt):
        self.age += dt
        self.physics(dt, bounce=0.3, roll=False, margin=8)
        if not self.grounded:
            self.rot += dt * 6

    def bbox(self):
        s = self.s
        return (self.x - 14 * s, self.y - 14 * s, 28 * s, 16 * s)

    def hit_box(self):
        s = self.s
        return (self.x - 11 * s, self.y - 11 * s, 22 * s, 13 * s)


BUTTERFLY_COLORS =[(1.0, 0.72, 0.30), (0.62, 0.78, 1.0), (1.0, 0.60, 0.80), (0.70, 0.92, 0.62), (0.85, 0.70, 1.0)]


class Butterfly:
    kind = "butterfly"

    def __init__(self, world):
        self.w = world
        self.side = random.choice((-1, 1))
        self.x = -20.0 if self.side > 0 else world.W + 20.0
        self.y = random.uniform(world.H * 0.35, world.H * 0.75)
        self.vx = self.vy = 0.0
        self.t = random.uniform(0, 10)
        self.life = random.uniform(35, 55)
        self.target = None
        self.retarget = 0.0
        self.color = random.choice(BUTTERFLY_COLORS)
        self.perch = None
        self.perch_t = 0.0
        self.perch_cd = 6.0
        self.flee = 0.0
        self.gone = False

    @property
    def perched(self):
        return self.perch is not None

    def startle(self):
        self.perch = None
        self.flee = 1.4
        self.perch_cd = 8.0
        self.target = (self.x + random.uniform(-200, 200), self.y - random.uniform(150, 260))

    def update(self, dt):
        self.t += dt
        self.life -= dt
        self.perch_cd -= dt
        w = self.w
        if self.perch is not None:
            c = self.perch
            if c.w is not w or c.state not in STILL_STATES or self.perch_t <= 0:
                self.startle()
            else:
                self.perch_t -= dt
                self.x, self.y = c.head_top()
                self.y -= 3
                return
        if self.life <= 0:
            self.target = (self.x + self.side * 300, -80)
            if self.y < -40 or self.x < -60 or self.x > w.W + 60:
                self.gone = True
        elif self.flee > 0:
            self.flee -= dt
        else:
            self.retarget -= dt
            arrived = isinstance(self.target, tuple) and math.hypot(self.target[0] - self.x, self.target[1] - self.y) < 20
            if self.target is None or self.retarget <= 0 or arrived:
                self.retarget = random.uniform(1.5, 3.5)
                still = [c for c in w.cats if c.state in STILL_STATES]
                if still and self.perch_cd <= 0 and random.random() < 0.35:
                    self.target = random.choice(still)
                else:
                    self.target = (random.uniform(60, w.W - 60), random.uniform(w.H * 0.3, w.H - 50))
        tgt = self.target
        if tgt is not None and not isinstance(tgt, tuple):
            cat = tgt
            if cat.w is not w or cat.state not in STILL_STATES:
                self.target = None
                tgt = (self.x, self.y)
            else:
                hx, hy = cat.head_top()
                if math.hypot(hx - self.x, hy - self.y) < 8:
                    self.perch = cat
                    self.perch_t = random.uniform(4, 8)
                    self.target = None
                    return
                tgt = (hx, hy)
        if tgt is None:
            tgt = (self.x, self.y)
        dx, dy = tgt[0] - self.x, tgt[1] - self.y
        d = math.hypot(dx, dy) or 1
        speed = 190 if self.flee > 0 else 85
        dvx, dvy = dx / d * speed, dy / d * speed
        self.vx += (dvx - self.vx) * min(1, dt * 2.5)
        self.vy += (dvy - self.vy) * min(1, dt * 2.5)
        self.x += self.vx * dt
        self.y += self.vy * dt + math.sin(self.t * 7) * 28 * dt

    def bbox(self):
        return (self.x - 16, self.y - 16, 32, 32)

    def hit_box(self):
        return (self.x - 12, self.y - 12, 24, 24)
