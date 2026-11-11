"""呼吸：整块桌面像一张被掀动的布，缓慢的同心圆从中心扩散。

和其它模式比它**几乎没有位移**，只有很轻的缩放与明暗呼吸，
适合长时间挂着当背景（不抢注意力，也不烧 CPU）。
overlay 引擎。
"""
from __future__ import annotations

import math

from .base import ENGINE_OVERLAY, Mode, Transform
from .util import approach, clamp

_PERIOD_S = 7.4          # 一次呼吸的周期


class BreathMode(Mode):
    name = "breath"
    title = "呼吸"
    engine = ENGINE_OVERLAY
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
        # 这一档故意用更软的起落：presence 小一点就开始，安静的曲子也能看到
        active = 1.0 if ctx.presence >= 0.01 else 0.0
        self._engage = approach(self._engage, active, 1.2, dt)
        if self._engage < 0.02:
            return {}
        self._energy = approach(self._energy, min(1.0, ctx.bass * 1.1), 2.5, dt)

        w, h = ctx.screen
        cx0, cy0 = w * 0.5, h * 0.5
        diag = max(1.0, math.hypot(w, h))
        phase = self._t / _PERIOD_S * math.tau

        out = {}
        for ikey, icon in ctx.icons:
            cx, cy = ctx.center(icon)
            # 距离中心越远，相位越落后 → 同心圆从中心往外扩
            d = math.hypot(cx - cx0, cy - cy0) / diag
            wave = math.sin(phase - d * math.pi * 2.0)
            k = wave * self._engage * (0.45 + 0.55 * self._energy)
            sx = 1.0 + 0.045 * k
            sy = 1.0 - 0.055 * k
            # overlay 引擎会把 dx/dy 清零，这里传 0 保持契约清晰：
            # "布面"的起伏全靠同心圆的缩放相位差表达，不靠位移。
            out[ikey] = Transform(clamp(sx, 0.9, 1.12), clamp(sy, 0.88, 1.06),
                                  0.0, 0.0)
        return out
