"""多米诺：从左上角开始，一整排图标依次"倒下再弹起"。

关键是**延迟按列传播**，不是同时动 —— 那一眼就能看出是骨牌在推。
每块牌倒下时挤压成宽扁（sx 大、sy 小），起来时反向过冲一点。
overlay 引擎：不位移，所以绝不会碰到邻居。
"""
from __future__ import annotations

import math

from .base import ENGINE_OVERLAY, Mode, Transform
from .util import approach, clamp

_LAP_S = 5.2             # 一轮推完的时长
_COL_DELAY = 0.085       # 每列延迟（秒）
_ROW_DELAY = 0.035       # 每行微延迟，让波前是斜的
_TIP = 0.55              # 单块牌倒下的持续时间（秒）


class DominoMode(Mode):
    name = "domino"
    title = "多米诺"
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
        active = 1.0 if ctx.presence >= 0.02 else 0.0
        self._engage = approach(self._engage, active, 2.4, dt)
        if self._engage < 0.02:
            return {}
        self._energy = approach(self._energy, min(1.0, ctx.bass * 1.3), 5.0, dt)

        # 列/行序号：用图标的屏幕坐标分桶（图标尺寸随 DPI 变，不能写死）
        cols = {}
        rows = {}
        for ikey, icon in ctx.icons:
            cx, cy = ctx.center(icon)
            cols[ikey] = int(cx // 100)
            rows[ikey] = int(cy // 100)
        base_col = min(cols.values()) if cols else 0
        base_row = min(rows.values()) if rows else 0

        amp = 0.30 * self._engage * (0.5 + 0.5 * self._energy)
        out = {}
        for ikey, _icon in ctx.icons:
            delay = ((cols[ikey] - base_col) * _COL_DELAY
                     + (rows[ikey] - base_row) * _ROW_DELAY)
            # 每轮从 0 开始推，delay 决定这块牌什么时候倒
            phase = (self._t % _LAP_S) - delay
            if phase < 0:
                continue
            p = phase / _TIP
            if p >= 2.0:
                continue
            # p ∈ [0,1)：倒下；p ∈ [1,2)：弹回
            if p < 1.0:
                k = math.sin(p * math.pi) ** 0.6
            else:
                k = -math.sin((p - 1.0) * math.pi) * 0.35
            k = clamp(k, -0.4, 1.0) * amp
            out[ikey] = Transform(1.0 + k, 1.0 - k * 1.5)
        return out
