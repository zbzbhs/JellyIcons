"""星环：层层旋转，随节奏舒展。

图标按半径分到几层圆环，各层反向旋转；低频来时整圈向外舒展一下。
takeover 引擎（要位移）。
"""
from __future__ import annotations

import math

from .base import ENGINE_TAKEOVER, Mode, Transform
from .util import approach, clamp

RINGS = 3


class RingMode(Mode):
    name = "ring"
    title = "星环"
    engine = ENGINE_TAKEOVER
    dwell_s = 10.0

    def __init__(self):
        self._t = 0.0
        self._engage = 0.0
        self._open = 0.0

    def detach(self):
        self._t = 0.0
        self._engage = 0.0
        self._open = 0.0

    def tick(self, ctx, dt):
        self._t += dt
        active = 1.0 if ctx.presence >= 0.02 else 0.0
        self._engage = approach(self._engage, active, 2.0, dt)
        self._open = approach(self._open, min(1.0, ctx.bass * 1.3), 6.0, dt)

        w, h = ctx.screen
        cx, cy = w / 2.0, h / 2.0
        base_r = min(w, h) * 0.14
        gap = min(w, h) * 0.115 * (1.0 + 0.12 * self._open)
        total = max(1, len(ctx.icons))
        per_ring = max(1, (total + RINGS - 1) // RINGS)

        out = {}
        for pos, (key, icon) in enumerate(ctx.icons):
            ring = min(RINGS - 1, pos // per_ring)
            slot = pos % per_ring
            count = min(per_ring, total - ring * per_ring) or 1
            # 奇偶层反向转，层次感更强
            direction = 1.0 if ring % 2 == 0 else -1.0
            speed = direction * (0.34 - 0.07 * ring)
            ang = (2.0 * math.pi * slot / count
                   + self._t * speed + ring * 0.55)
            radius = base_r + gap * ring
            radius *= (1.0 + 0.06 * self._open)
            tx = cx + math.cos(ang) * radius
            ty = cy + math.sin(ang) * radius * 0.82
            ix, iy = ctx.center(icon)
            dx = (tx - ix) * self._engage
            dy = (ty - iy) * self._engage
            amp = clamp(self._open, 0.0, 1.0)
            out[key] = Transform(1.0 + amp * 0.07, 1.0 - amp * 0.07, dx, dy)
        return out
