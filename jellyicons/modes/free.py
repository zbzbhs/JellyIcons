"""自由：图标沿弧线汇聚到中央，随鼓点向外弹开、弹性收回，顺时针流动。

takeover 引擎：音乐期间真图标隐藏，副本自己排版（不动 explorer 的坐标）。
"""
from __future__ import annotations

import math

from .base import ENGINE_TAKEOVER, Mode, Transform
from .util import approach, clamp


class FreeMode(Mode):
    name = "free"
    title = "自由"
    engine = ENGINE_TAKEOVER
    dwell_s = 10.0

    def __init__(self):
        self._t = 0.0
        self._pull = 0.0        # 汇聚程度 0..1
        self._kick = 0.0        # 鼓点外弹能量

    def detach(self):
        self._t = 0.0
        self._pull = 0.0
        self._kick = 0.0

    def tick(self, ctx, dt):
        self._t += dt
        # 目标汇聚度：跟着 presence 走，有音乐就聚起来
        target = 0.62 if ctx.presence >= 0.02 else 0.0
        self._pull = approach(self._pull, target, 2.2, dt)
        # 鼓点把图标再往外送一下
        self._kick *= math.exp(-5.0 * dt)
        if ctx.presence >= 0.02 and ctx.bass > 0.25:
            self._kick = min(1.0, self._kick + ctx.bass * 0.30)

        w, h = ctx.screen
        cx, cy = w / 2.0, h / 2.0
        max_r = math.hypot(cx, cy) or 1.0
        out = {}
        for pos, (key, icon) in enumerate(ctx.icons):
            ix, iy = ctx.center(icon)
            vx, vy = ix - cx, iy - cy
            r = math.hypot(vx, vy)
            if r < 1e-6:
                ang = 0.0
            else:
                ang = math.atan2(vy, vx)
            # 每个图标转速不同 → 一开始整齐，后来慢慢散成一条流动的带
            speed = 0.10 + 0.06 * ((pos * 7) % 5)
            ang += speed * self._t * self._pull
            # 汇聚：半径往内收；kick：往外弹
            shrink = 1.0 - 0.42 * self._pull
            push = self._kick * 0.10 * max_r * 0.02
            nr = clamp(r * shrink + push, 0.0, max_r)
            nx, ny = cx + math.cos(ang) * nr, cy + math.sin(ang) * nr
            dx = (nx - ix) * self._pull
            dy = (ny - iy) * self._pull
            # 频谱决定压扁多少（低频段到大图标）
            band = ctx.bands[(pos * 3) % len(ctx.bands)] if ctx.bands else 0.0
            amp = min(1.0, band * 0.5)
            out[key] = Transform(1.0 + amp * 0.06, 1.0 - amp * 0.08, dx, dy)
        return out
