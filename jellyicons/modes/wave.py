"""海浪：波峰错开，起伏传递。

图标按屏幕 x 排成波列，每个有固定相位差，所以一眼看过去是一道
从左往右推的浪。纵向位移为主，最像"整片桌面在呼吸"。
takeover 引擎（要位移）。
"""
from __future__ import annotations

import math

from .base import ENGINE_TAKEOVER, Mode, Transform
from .util import approach


class WaveMode(Mode):
    name = "wave"
    title = "海浪"
    engine = ENGINE_TAKEOVER
    dwell_s = 10.0

    def __init__(self):
        self._t = 0.0
        self._engage = 0.0
        self._energy = 0.0

    def detach(self):
        self._t = 0.0
        self._engage = 0.0
        self._energy = 0.0

    def tick(self, ctx, dt):
        self._t += dt
        active = 1.0 if ctx.presence >= 0.02 else 0.0
        self._engage = approach(self._engage, active, 1.8, dt)
        # 整体浪高由低频能量缓慢驱动，不要每帧抖
        self._energy = approach(self._energy,
                                min(1.0, ctx.bass * 1.2), 4.0, dt)

        w, _h = ctx.screen
        span = max(1.0, w)
        amp = 26.0 * self._engage * (0.35 + 0.65 * self._energy)
        out = {}
        for key, icon in ctx.icons:
            ix, iy = ctx.center(icon)
            phase = (ix / span) * math.pi * 2.2
            travel = math.sin(self._t * 2.1 - phase)
            bob = travel * amp
            # 浪峰处横向略撑开、浪谷处压扁
            peak = (travel + 1.0) * 0.5
            sx = 1.0 + 0.05 * peak * self._engage
            sy = 1.0 - 0.06 * peak * self._engage
            out[key] = Transform(sx, sy, 0.0, bob)
        return out
