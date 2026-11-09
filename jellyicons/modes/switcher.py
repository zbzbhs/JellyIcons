"""模式切换器：手动选模式 + 自动轮换 + 引擎变化上报。

它只负责"现在该由哪个模式说话"，不碰窗口也不碰真图标；
引擎变化（overlay <-> takeover）由 app 主循环按 needs_prime 处理。
"""
from __future__ import annotations

import sys

from . import ALL_MODES, BY_NAME, create

DEFAULT_ORDER = tuple(cls.name for cls in ALL_MODES)

# 切换时的过渡时长：新模式在这段时间内从"静止"淡入到自己的形变，
# 避免换模式那一帧图标突然跳一下。
BLEND_S = 0.20

# 音乐停下后的归位时长：takeover 模式此刻图标还在半路（聚拢/绕圈），
# 必须先平滑滑回原位，才能把真图标放回来 —— 否则会看到图标"跳回去"。
WIND_DOWN_S = 0.35


class ModeSwitcher:
    def __init__(self, order=None, start=None, auto=True):
        self.order = tuple(order or DEFAULT_ORDER)
        if not self.order:
            self.order = DEFAULT_ORDER
        first = start if start in BY_NAME else self.order[0]
        self._mode = create(first)
        self._index = self.order.index(self._mode.name)
        self.auto = bool(auto)
        self._elapsed = 0.0
        self._blend = 0.0
        self._wind = WIND_DOWN_S
        #: 引擎刚刚发生变化 -> app 需要重新预绘制/恢复真图标
        self.needs_prime = True
        self._prev_engine = None

    # ---- 查询 ----

    @property
    def mode(self):
        return self._mode

    @property
    def name(self):
        return self._mode.name

    @property
    def title(self):
        return self._mode.title

    @property
    def engine(self):
        return self._mode.engine

    def order_titles(self):
        return [(name, BY_NAME[name].title) for name in self.order
                if name in BY_NAME]

    # ---- 控制 ----

    def select(self, name):
        """手动切到某个模式；返回是否真的换了。"""
        if name not in BY_NAME:
            raise KeyError("未知模式: %r（可用: %s）"
                           % (name, ", ".join(sorted(BY_NAME))))
        if name == self._mode.name:
            return False
        self._switch(name)
        return True

    def next(self):
        """切到下一个模式（自动轮换和快捷键都走这里）。"""
        if len(self.order) < 2:
            return False
        self._index = (self._index + 1) % len(self.order)
        self._switch(self.order[self._index])
        return True

    def prev(self):
        if len(self.order) < 2:
            return False
        self._index = (self._index - 1) % len(self.order)
        self._switch(self.order[self._index])
        return True

    def set_auto(self, flag):
        self.auto = bool(flag)

    def restart(self):
        """音乐重新开始时调用：让当前模式从第 0 帧重新起跳。"""
        name = self._mode.name
        try:
            self._mode.detach()
        except Exception:
            pass
        self._mode = create(name)
        self._elapsed = 0.0
        self._blend = 0.0
        self._wind = WIND_DOWN_S
        self.needs_prime = True

    def _switch(self, name):
        engine_changed = BY_NAME[name].engine != self._mode.engine
        try:
            self._mode.detach()
        except Exception:
            pass
        self._mode = create(name)
        self._elapsed = 0.0
        self._blend = 0.0
        self._wind = WIND_DOWN_S
        if engine_changed:
            self.needs_prime = True
        # 同一引擎也会换形变，保留 needs_prime 让 app 重绘一帧
        self.needs_prime = True

    # ---- 每帧 ----

    def tick(self, ctx, dt, active=True):
        """返回 (transforms, engine, blend)。

        active=False（没音乐）时先走一段"归位"过渡：把当前形变按
        WIND_DOWN_S 平滑缩回 1:1，再交给 app 去显示真图标。音乐一停就
        立刻归位会看到图标"跳"回原位；完全不归位则永远退不出音乐模式。
        """
        if active and self.auto and dt > 0:
            self._elapsed += dt
            dwell = self._mode.dwell_s
            if dwell is not None:
                if self._elapsed >= dwell:
                    self.next()
            elif self._mode.wants_exit(ctx):
                # 例如"两年半"跳完一整轮：留在原地等下一个自动周期太浪费
                self.next()

        try:
            transforms = self._mode.tick(ctx, dt)
        except Exception as exc:
            # 单个模式的 bug 绝不能拖垮整个程序：退回静止，并跳过这个模式
            self._failures = getattr(self, "_failures", 0) + 1
            sys.stderr.write("[mode] %s tick 异常（第 %d 次）: %r\n"
                             % (self._mode.name, self._failures, exc))
            transforms = {}
            if self._failures >= 3:
                self._failures = 0
                self.next()
        engine = self._mode.engine

        # 模式切换过渡：前 BLEND_S 秒把形变从 1:1 拉到位，避免突跳
        self._blend = min(1.0, self._blend + dt / BLEND_S) if dt > 0 else 1.0
        k = self._blend

        # 音乐停了：按下坡时长把形变一路收回到 1:1
        if active:
            self._wind = WIND_DOWN_S
        else:
            self._wind = max(0.0, self._wind - dt)
            k = min(k, self._wind / WIND_DOWN_S)

        if k < 1.0:
            transforms = {
                key: tf.blended(k) for key, tf in transforms.items()
            }
        return transforms, engine, k
