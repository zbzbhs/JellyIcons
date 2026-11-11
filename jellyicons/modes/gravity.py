"""鼠标引力 / 放大镜：鼠标附近的图标被吸过来、放大，远处的被推开。

两档感受靠一个参数切换：

    MODE_PULL   靠近的图标被拉向鼠标，尺寸变大（"引力"），
                鼠标一走开就弹回原位 —— 这个最像"果冻被手指按着"。
    MODE_LENS   不做位移，只按距离放大（"放大镜"）。

鼠标位置来自 `ctx.pointer`（app 每帧取一次 GetCursorPos）。
拿不到鼠标（沙箱/远端桌面）时 pointer 为 None，本模式自动降级成
"静止呼吸"，绝不抖。
"""
from __future__ import annotations

import math

from .base import ENGINE_TAKEOVER, Mode, Transform
from .util import approach, clamp

MODE_PULL = "pull"
MODE_LENS = "lens"

# 影响半径 = 图标边长 × 该值
_RADIUS = 3.4
# 引力最大位移（像素）
_PULL = 54.0


class GravityMode(Mode):
    name = "gravity"
    title = "鼠标引力"
    engine = ENGINE_TAKEOVER
    dwell_s = 10.0

    def __init__(self, style=MODE_PULL):
        self.style = style
        self._engage = 0.0
        # 每个图标一份平滑后的"受吸引程度"，避免鼠标跳变时图标瞬移
        self._pull = {}

    def detach(self):
        self._engage = 0.0
        self._pull.clear()

    def tick(self, ctx, dt):
        active = 1.0 if ctx.presence >= 0.02 else 0.0
        self._engage = approach(self._engage, active, 3.0, dt)
        if self._engage < 0.02:
            self._pull.clear()
            return {}

        px, py = ctx.pointer if ctx.pointer else (None, None)
        if px is None:
            # 没有鼠标位置：全部轻轻呼吸，保持"活着"的感觉
            out = {}
            breath = 1.0 + 0.03 * math.sin(ctx.now * 1.7) * self._engage
            for ikey, _icon in ctx.icons:
                out[ikey] = Transform(breath, 2.0 - breath)
            return out

        out = {}
        for ikey, icon in ctx.icons:
            cx, cy = ctx.center(icon)
            dxs, dys = px - cx, py - cy
            dist = math.hypot(dxs, dys) or 1.0
            r = _RADIUS * max(8, icon.width)
            near = clamp(1.0 - dist / r, 0.0, 1.0)
            near = near * near                       # 平方衰减，中心更集中
            smooth = approach(self._pull.get(ikey, 0.0), near, 14.0, dt)
            self._pull[ikey] = smooth
            k = smooth * self._engage
            if k < 0.004:
                continue
            if self.style == MODE_LENS:
                sx = 1.0 + 0.42 * k
                sy = 1.0 + 0.42 * k
                out[ikey] = Transform(sx, sy, 0.0, 0.0)
            else:
                pull = _PULL * k * k
                sx = 1.0 + 0.22 * k
                sy = 1.0 - 0.14 * k
                out[ikey] = Transform(
                    sx, sy,
                    clamp((dxs / dist) * pull, -_PULL, _PULL),
                    clamp((dys / dist) * pull, -_PULL, _PULL))
        return out


class LensMode(GravityMode):
    """放大镜：只放大不位移，观感更安静，适合当背景。"""

    name = "lens"
    title = "放大镜"
    dwell_s = 10.0

    def __init__(self):
        super().__init__(style=MODE_LENS)
