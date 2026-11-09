"""音浪：八个频段，各跳各的。

每个图标绑一个频段（按图标索引均匀摊到 8 个子带），
子带能量高就压得更狠。纯缩放，不位移 —— 可以用 overlay 引擎跑。
"""
from __future__ import annotations

from .. import config
from .base import ENGINE_OVERLAY, Mode, Transform
from .util import clamp

SUB_BANDS = 8


class BandsMode(Mode):
    name = "bands"
    title = "音浪"
    engine = ENGINE_OVERLAY
    dwell_s = 10.0

    def __init__(self):
        self._levels = [0.0] * SUB_BANDS

    def _band_index(self, position, total):
        if total <= 1:
            return 0
        idx = int(position * SUB_BANDS / total)
        return clamp(idx, 0, SUB_BANDS - 1)

    def tick(self, ctx, dt):
        bands = ctx.bands or []
        # 64 段摊到 8 个子带，取每个子带的峰值（比均值更抓节拍）
        per = max(1, len(bands) // SUB_BANDS)
        targets = []
        for i in range(SUB_BANDS):
            chunk = bands[i * per:(i + 1) * per]
            targets.append(max(chunk) if chunk else 0.0)
        # 上升快、回落慢，看起来才像"跳"
        for i, target in enumerate(targets):
            cur = self._levels[i]
            rate = 26.0 if target > cur else 5.0
            self._levels[i] = target + (cur - target) * pow(2.718281828,
                                                           -rate * dt)
        out = {}
        total = len(ctx.icons)
        for pos, (key, _icon) in enumerate(ctx.icons):
            level = self._levels[self._band_index(pos, total)]
            amp = min(1.0, level * config.AGC_TO_VOL * 18.0)
            sx = 1.0 + amp * 0.10
            sy = 1.0 - amp * 0.14
            out[key] = Transform(sx, sy)
        return out
