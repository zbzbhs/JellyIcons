"""弹球：一颗球在屏幕上弹来弹去，撞到谁谁被撞歪。

物理很朴素（匀速 + 边界反弹 + 一次碰撞给个冲量），但观感很好：
球自己的图标会放大成"球"，沿途图标被撞出一个凹陷再弹回。
takeover 引擎（球要真的在屏幕上跑）。
"""
from __future__ import annotations

import math

from .base import ENGINE_TAKEOVER, Mode, Transform
from .util import approach, clamp

_SPEED = 420.0          # 像素/秒（1800px 屏横穿约 6 秒）
_HIT_R = 1.9            # 撞击半径 = 图标边长 × 该值
_IMPULSE = 46.0         # 撞击给的最大位移


class BallMode(Mode):
    name = "ball"
    title = "弹球"
    engine = ENGINE_TAKEOVER
    dwell_s = 12.0

    def __init__(self):
        self._x = None
        self._y = None
        self._vx = 1.0
        self._vy = 0.62
        self._engage = 0.0
        self._hits = {}          # key -> 剩余冲量 0..1

    def detach(self):
        self._x = self._y = None
        self._engage = 0.0
        self._hits.clear()

    def _step_ball(self, ctx, dt):
        w, h = ctx.screen
        if self._x is None:
            self._x, self._y = w * 0.5, h * 0.42
        n = math.hypot(self._vx, self._vy) or 1.0
        self._vx, self._vy = self._vx / n, self._vy / n
        self._x += self._vx * _SPEED * dt
        self._y += self._vy * _SPEED * dt
        # 边界反弹（留 6% 余量，避免贴着窗口边看不见）
        mx, my = w * 0.06, h * 0.06
        if self._x < mx:
            self._x = mx + (mx - self._x)
            self._vx = abs(self._vx)
        elif self._x > w - mx:
            self._x = (w - mx) - (self._x - (w - mx))
            self._vx = -abs(self._vx)
        if self._y < my:
            self._y = my + (my - self._y)
            self._vy = abs(self._vy)
        elif self._y > h - my:
            self._y = (h - my) - (self._y - (h - my))
            self._vy = -abs(self._vy)

    def tick(self, ctx, dt):
        active = 1.0 if ctx.presence >= 0.02 else 0.0
        self._engage = approach(self._engage, active, 2.2, dt)
        if self._engage < 0.02:
            return {}
        if dt <= 0:
            return {}

        self._step_ball(ctx, dt)
        bx, by = self._x or 0.0, self._y or 0.0

        # 找离球最近的图标当"球本体"
        nearest, best = None, 1e18
        for ikey, icon in ctx.icons:
            cx, cy = ctx.center(icon)
            d = (cx - bx) ** 2 + (cy - by) ** 2
            if d < best:
                best, nearest = d, ikey

        out = {}
        for ikey, icon in ctx.icons:
            cx, cy = ctx.center(icon)
            dxs, dys = cx - bx, cy - by
            dist = math.hypot(dxs, dys) or 1.0
            if ikey == nearest:
                # 球本体：放大 + 轻微压扁，跟着速度方向拉长
                sx = 1.0 + 0.30 * self._engage
                sy = 1.0 + 0.30 * self._engage
                out[ikey] = Transform(sx, sy, 0.0, 0.0)
                continue
            # 被撞：距离小于撞击半径就吃一个冲量
            r = _HIT_R * max(8, icon.width)
            if dist < r:
                want = 1.0 - dist / r
                if want > self._hits.get(ikey, 0.0):
                    self._hits[ikey] = want
            power = self._hits.get(ikey, 0.0)
            if power <= 0.001:
                continue
            self._hits[ikey] = max(0.0, power - dt * 1.7)   # 1/1.7s 内衰减完
            push = _IMPULSE * power * self._engage
            sx = 1.0 + 0.16 * power * self._engage
            sy = 1.0 - 0.20 * power * self._engage
            out[ikey] = Transform(sx, sy,
                                  (-dxs / dist) * push, (-dys / dist) * push)
        return {k: Transform(t.sx, t.sy,
                             clamp(t.dx, -160.0, 160.0),
                             clamp(t.dy, -160.0, 160.0))
                for k, t in out.items()}
