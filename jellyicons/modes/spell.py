"""拼字：把整屏图标排成一句话。

做法不是手工排坐标 —— 那样每换一个字都要重新量。这里用 PIL 把字
渲染成一张掩膜，再在笔画上均匀取 N 个点（N = 图标数），按 x 排序
分给图标。于是"字"是真的用图标当像素拼出来的，换字只换掩膜。
takeover 引擎（图标要离开自己的格子）。
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from ..shell_icons import load_font
from .base import ENGINE_TAKEOVER, Mode, Transform
from .util import approach

# 每 DWELL 秒换一个。太短看不清，太长又闷。
_WORDS = ("JELLY", "Q", "LOVE", "666", "HI!", "弹", "爱", "梦")
_DWELL = 6.0
_FADE = 0.45        # 换字时的飞行动画时长比例


class SpellMode(Mode):
    name = "spell"
    title = "拼字"
    engine = ENGINE_TAKEOVER
    dwell_s = 12.0

    def __init__(self):
        self._t = 0.0
        self._engage = 0.0
        self._word_i = 0
        self._cache_key = None
        self._points = []
        self._font = None

    def _font_for(self, px):
        if self._font is None or getattr(self._font, "size", None) != px:
            self._font = load_font(px)
        return self._font

    def _build(self, count, screen):
        """把当前字渲染成 count 个目标点（屏幕坐标）。"""
        w, h = screen
        word = _WORDS[self._word_i % len(_WORDS)]
        # 字号先粗估再量，保证字宽落在屏幕的 55%~80%
        px = max(24, int(min(w, h) * 0.34))
        for _ in range(6):
            font = self._font_for(px)
            box = font.getbbox(word)
            tw = max(1, box[2] - box[0])
            if tw >= w * 0.62 or px <= 24:
                break
            px = int(px * min(1.6, (w * 0.70) / tw))
        font = self._font_for(px)
        box = font.getbbox(word)
        tw = max(1, box[2] - box[0])
        th = max(1, box[3] - box[1])
        img = Image.new("L", (tw + 8, th + 8), 0)
        ImageDraw.Draw(img).text((4 - box[0], 4 - box[1]), word, 255, font=font)
        raw = img.load()
        pts = []
        for yy in range(img.height):
            for xx in range(img.width):
                if raw[xx, yy] > 110:
                    pts.append((xx - 4, yy - 4))
        if not pts:
            return []
        # 均匀抽 count 个，保留笔画形状（行优先扫描 → 笔画分布天然均匀）
        step = max(1, len(pts) // max(1, count))
        picked = pts[::step][:count]
        while len(picked) < count:
            picked.append(pts[len(picked) % len(pts)])
        # 居中
        ox = (w - tw) / 2.0
        oy = (h - th) / 2.0
        out = sorted(((ox + x, oy + y) for x, y in picked), key=lambda p: p[0])
        return out

    def detach(self):
        self._t = 0.0
        self._engage = 0.0
        self._word_i = 0
        self._cache_key = None
        self._points = []

    def tick(self, ctx, dt):
        self._t += dt
        active = 1.0 if ctx.presence >= 0.02 else 0.0
        self._engage = approach(self._engage, active, 2.0, dt)
        if self._engage < 0.02:
            return {}

        count = len(ctx.icons)
        if count == 0:
            return {}
        key = (count, ctx.screen, self._word_i)
        if key != self._cache_key:
            self._cache_key = key
            self._points = self._build(count, ctx.screen)
        if not self._points:
            return {}

        # 每 _DWELL 秒换下一个字
        if self._t >= _DWELL:
            self._t -= _DWELL
            self._word_i = (self._word_i + 1) % len(_WORDS)
            self._cache_key = None
        # 换字飞行：刚换完的那一小段用缓动压一下，避免瞬移
        prog = min(1.0, self._t / _FADE) if self._t < _FADE else 1.0
        ease = prog * prog * (3.0 - 2.0 * prog)

        bounce = 1.0 + 0.16 * ctx.bass
        out = {}
        icons = sorted(ctx.icons, key=lambda it: ctx.center(it[1])[0])
        for i, (ikey, icon) in enumerate(icons):
            tx, ty = self._points[i % len(self._points)]
            cx, cy = ctx.center(icon)
            dx = (tx - cx) * self._engage * ease
            dy = (ty - cy) * self._engage * ease
            sx = 1.0 + 0.06 * self._engage
            sy = 1.0 - 0.06 * self._engage * bounce
            out[ikey] = Transform(sx, sy, dx, dy)
        return out
