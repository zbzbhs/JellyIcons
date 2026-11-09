"""心动：沿爱心轨迹流动，一张一弛。

图标按心形参数方程派位置，整体随节拍做一次"收缩—舒张"。
takeover 引擎（要位移）。
"""
from __future__ import annotations

import math

from .base import ENGINE_TAKEOVER, Mode, Transform
from .util import approach, clamp


class HeartMode(Mode):
    name = "heart"
    title = "心动"
    engine = ENGINE_TAKEOVER
    dwell_s = 10.0

    def __init__(self):
        self._t = 0.0
        self._beat = 0.0
        self._engage = 0.0

    def detach(self):
        self._t = 0.0
        self._beat = 0.0
        self._engage = 0.0

    @staticmethod
    def _heart(theta):
        """经典心形曲线，归一化到 [-1,1]。"""
        x = 16.0 * math.sin(theta) ** 3
        y = -(13.0 * math.cos(theta) - 5.0 * math.cos(2 * theta)
              - 2.0 * math.cos(3 * theta) - math.cos(4 * theta))
        return x / 17.0, y / 17.0

    def tick(self, ctx, dt):
        self._t += dt
        active = 1.0 if ctx.presence >= 0.02 else 0.0
        self._engage = approach(self._engage, active, 2.4, dt)
        # 心跳：低频驱动的一次收缩
        self._beat = approach(self._beat, min(1.0, ctx.bass * 1.4), 14.0, dt)
        self._beat *= math.exp(-3.4 * dt)

        w, h = ctx.screen
        cx, cy = w / 2.0, h / 2.0
        scale = min(w, h) * 0.30 * (1.0 + 0.05 * self._beat)
        total = max(1, len(ctx.icons))
        out = {}
        for pos, (key, icon) in enumerate(ctx.icons):
            ix, iy = ctx.center(icon)
            theta = 2.0 * math.pi * pos / total + self._t * 0.28
            hx, hy = self._heart(theta)
            tx, ty = cx + hx * scale, cy + hy * scale * 0.92
            dx = (tx - ix) * self._engage
            dy = (ty - iy) * self._engage
            pulse = clamp(self._beat, 0.0, 1.0)
            out[key] = Transform(1.0 + pulse * 0.10, 1.0 - pulse * 0.10,
                                 dx, dy)
        return out
