"""律动：壁纸原味。

逐行移植自 Dance Doll 壁纸的 processPulse / updateScale，
和 v1.5 之前 app.py 里的算法完全一致，只是改成"模式"。
"""
from __future__ import annotations

from .base import ENGINE_OVERLAY, Mode, Transform


class JellyMode(Mode):
    name = "jelly"
    title = "律动"
    engine = ENGINE_OVERLAY
    dwell_s = 10.0

    def tick(self, ctx, dt):
        out = {}
        for key, _icon in ctx.icons:
            out[key] = Transform(ctx.jelly.scaleX, ctx.jelly.scaleY)
        return out
