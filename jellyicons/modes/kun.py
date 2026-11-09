"""两年半：图标拼成小人，运球、绕肩、抛球、左右靠。

一整轮 LOOP_S 秒跳完（自动轮换模式下跳完就换下一个，对应壁纸里
"两年半完整跳完一轮"）。桌面有腾讯会议图标时，用它当放大后的头部。

takeover 引擎（要位移）。
"""
from __future__ import annotations

import math

from .base import ENGINE_TAKEOVER, Mode, Transform
from .util import approach, lerp

LOOP_S = 12.0

# 阶段切分（归一化时间）
_P_DRIBBLE = 0.34      # 运球
_P_SHOULDER = 0.52     # 绕肩
_P_THROW = 0.70        # 抛出
_P_LEAN = 0.86         # 左右靠
# 剩下到 1.0 收势回位

_HEAD_HINTS = ("腾讯会议", "Tencent Meeting", "wemeet")


class KunMode(Mode):
    name = "kun"
    title = "两年半"
    engine = ENGINE_TAKEOVER
    dwell_s = None          # 不按 10 秒切，跳完一轮才切

    def __init__(self):
        self._t = 0.0
        self._engage = 0.0

    def detach(self):
        self._t = 0.0
        self._engage = 0.0

    # ---- 小人骨架（相对锚点的偏移，单位 = 一个图标边长） ----
    @staticmethod
    def _slots():
        return {
            "head": (0.0, -2.30),
            "torso_a": (0.0, -1.25),
            "torso_b": (0.0, -0.35),
            "arm_l": (-0.95, -1.35),
            "arm_r": (0.95, -1.35),
            "leg_l": (-0.52, 0.70),
            "leg_r": (0.52, 0.70),
        }

    def _pick_head(self, icons):
        for index, (_key, icon) in enumerate(icons):
            lowered = icon.name.lower()
            for hint in _HEAD_HINTS:
                if hint.lower() in lowered:
                    return index
        return None

    def _ball_path(self, p, body_bob):
        """球在"小人坐标系"里的位置（单位 = 图标边长），随时间推进。"""
        # 运球：右下侧上下拍
        if p < _P_DRIBBLE:
            q = p / _P_DRIBBLE
            bounce = abs(math.sin(q * math.pi * 3.0))
            return (1.15, 1.55 - 0.75 * bounce + body_bob)
        # 绕肩：从右下弧线越过肩到左上
        if p < _P_SHOULDER:
            q = (p - _P_DRIBBLE) / (_P_SHOULDER - _P_DRIBBLE)
            ang = math.pi * (0.5 - 1.15 * q)
            rad = 1.25
            return (math.cos(ang) * rad, -1.35 + math.sin(ang) * rad * 0.75
                    + body_bob)
        # 抛出：向右上抛，再落回
        if p < _P_THROW:
            q = (p - _P_SHOULDER) / (_P_THROW - _P_SHOULDER)
            x = lerp(-0.55, 1.65, q)
            y = -0.30 - 2.55 * math.sin(q * math.pi)
            return (x, y + body_bob)
        # 左右靠：球抱在左侧，身体左右倾
        if p < _P_LEAN:
            q = (p - _P_THROW) / (_P_LEAN - _P_THROW)
            return (lerp(1.65, -0.75, q), 0.55 + body_bob)
        q = (p - _P_LEAN) / (1.0 - _P_LEAN)
        return (lerp(-0.75, 1.15, q), 1.55 + body_bob)

    def _sway(self, p):
        """身体左右倾（弧度），左右靠阶段最明显。"""
        if p < _P_THROW:
            return math.sin(p * math.pi * 6.0) * 0.05
        if p < _P_LEAN:
            return 0.10 * math.sin((p - _P_THROW) * math.pi * 4.0)
        q = (p - _P_LEAN) / max(1e-6, 1.0 - _P_LEAN)
        return 0.22 * math.sin(q * math.pi * 2.0)

    def tick(self, ctx, dt):
        self._t += dt
        self._engage = approach(self._engage, 1.0, 3.0, dt)
        loop = self._t % LOOP_S
        p = loop / LOOP_S

        icons = ctx.icons
        total = len(icons)
        if total == 0:
            return {}
        side = 64.0
        w, h = ctx.screen
        cx, cy = w / 2.0, h / 2.0
        # 小人整体略偏上，给脚留空间
        ax, ay = cx, cy - side * 0.25

        slots = self._slots()
        order = ["head", "torso_a", "torso_b", "arm_l", "arm_r",
                 "leg_l", "leg_r"]
        head_index = self._pick_head(icons)
        if head_index is not None:
            # 腾讯会议图标当头部：从普通顺序里摘出来，专门放 head 槽
            ordered = [head_index] + [i for i in range(total)
                                      if i != head_index]
        else:
            ordered = list(range(total))

        sway = self._sway(p)
        cos_s, sin_s = math.cos(sway), math.sin(sway)
        body_bob = 0.06 * math.sin(p * math.pi * 12.0)
        ball = self._ball_path(p, body_bob)

        out = {}
        placed = 0
        for pos in ordered:
            key, icon = icons[pos]
            ix, iy = ctx.center(icon)
            if placed < len(order):
                slot = order[placed]
                sx0, sy0 = slots[slot]
                is_head = (slot == "head")
                # 绕自身锚点旋转
                rx = sx0 * cos_s - sy0 * sin_s
                ry = sx0 * sin_s + sy0 * cos_s
                if is_head:
                    scale = 1.35 if head_index is not None else 1.0
                    rx *= scale
                    ry *= scale
                tx = ax + rx * side
                ty = ay + ry * side + body_bob * side * 0.4
                amp = 0.0
                if slot in ("leg_l", "leg_r"):
                    amp = 0.05 * abs(math.sin(p * math.pi * 12.0))
                out[key] = Transform(1.0 + amp, 1.0 - amp,
                                     (tx - ix) * self._engage,
                                     (ty - iy) * self._engage)
                placed += 1
                continue

            # 剩下的当观众 / 篮球：第一个当球，其余在下方轻微起伏
            if placed == len(order):
                tx = ax + ball[0] * side
                ty = ay + ball[1] * side
                out[key] = Transform(1.06, 0.94,
                                     (tx - ix) * self._engage,
                                     (ty - iy) * self._engage)
                placed += 1
                continue

            index = placed - len(order) - 1
            cols = max(1, int(math.sqrt(max(1, total - len(order) - 1))))
            col = index % cols
            row = index // cols
            spread = side * 1.5
            tx = cx + (col - (cols - 1) / 2.0) * spread
            ty = h - side * (1.2 + row * 1.1)
            bob = 0.10 * math.sin(p * math.pi * 8.0 + index * 0.9)
            out[key] = Transform(1.0 + bob * 0.4, 1.0 - bob * 0.5,
                                 (tx - ix) * self._engage,
                                 (ty - iy) * self._engage)
            placed += 1
        return out

    def wants_exit(self, ctx):
        """一轮跳完就交给下一个模式（自动轮换时）。"""
        return self._t >= LOOP_S
