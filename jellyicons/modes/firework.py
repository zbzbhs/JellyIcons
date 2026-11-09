"""烟花：重拍绽放，轻轻收回。

每个图标有自己的相位延迟（按到屏幕中心的距离排），
所以一次重拍会从中心向外扩散成涟漪，再各自弹性收回。
纯缩放，overlay 引擎可跑。
"""
from __future__ import annotations

import math

from .base import ENGINE_OVERLAY, Mode, Transform
from .util import approach


class FireworkMode(Mode):
    name = "firework"
    title = "烟花"
    engine = ENGINE_OVERLAY
    dwell_s = 10.0

    def __init__(self):
        self._last_bass = 0.0
        self._burst = 0.0
        self._spread = 0.0

    def tick(self, ctx, dt):
        # 重拍检测：bass 相对上一帧明显跳升
        jump = ctx.bass - self._last_bass
        self._last_bass = ctx.bass
        if jump > 0.12 and ctx.presence >= 0.02:
            self._burst = min(1.0, self._burst + 0.55 + jump)
            self._spread = 0.0
        # 爆发能量按固定半衰衰减
        self._burst *= math.exp(-4.2 * dt)
        self._spread = approach(self._spread, 1.0, 2.6, dt)

        w, h = ctx.screen
        cx, cy = w / 2.0, h / 2.0
        max_d = math.hypot(cx, cy) or 1.0
        out = {}
        for key, icon in ctx.icons:
            ix, iy = ctx.center(icon)
            dist = math.hypot(ix - cx, iy - cy) / max_d      # 0 中心 .. 1 角落
            delay = dist * 0.22                              # 涟漪从中心往外传
            local = max(0.0, self._burst - delay)
            amp = local * (0.5 + 0.5 * self._spread)
            sx = 1.0 + amp * 0.11
            sy = 1.0 - amp * 0.09
            out[key] = Transform(sx, sy)
        return out
