"""动画模式接口：模式只描述"每个图标这一刻该长什么样"，不亲自碰窗口。

两套引擎（这是关键设计）：

    ENGINE_OVERLAY   原位层。可以缩放、压扁、回弹，但**不许位移**——
                     图标永远待在自己的格子里。观感是"原位果冻"，
                     不可能跑偏、不可能错位，最保守最稳。

    ENGINE_TAKEOVER  接管层。副本允许位移、聚拢、绕圈、拼人形，
                     所以可以做"散开再聚拢"这类整版排版动画。
                     但**仍然一个字节都不写 explorer 的图标坐标**：
                     移动的是我们自己的 overlay 窗口，不是
                     SysListView32 里的 item。退出时副本归位 1:1，
                     再把真图标放回来，所以随时 Ctrl+C 都不会打乱桌面。

两档都走同一套"预绘制 → 隐藏真图标 → 归位 → 显示真图标"的无感切换；
差别只在于这一档允不允许位移。模式通过 engine 字段声明自己属于哪一档。
"""
from __future__ import annotations

from dataclasses import dataclass

ENGINE_OVERLAY = "overlay"
ENGINE_TAKEOVER = "takeover"

ENGINES = (ENGINE_OVERLAY, ENGINE_TAKEOVER)


@dataclass(frozen=True)
class Transform:
    """一个图标在当前帧的形变。

    sx/sy   本体缩放（sx>1 拉宽、sy<1 压扁 = 果冻落地）
    dx/dy   相对格子中心的位移（像素）。overlay 引擎强制为 0。
    alpha   不透明度 0..1（takeover 引擎的淡入淡出用）
    """

    sx: float = 1.0
    sy: float = 1.0
    dx: float = 0.0
    dy: float = 0.0
    alpha: float = 1.0

    def is_rest(self, eps=1e-3):
        """是否已经完全归位（可以用来判断"可以安全撤副本了"）。"""
        return (abs(self.sx - 1.0) < eps and abs(self.sy - 1.0) < eps
                and abs(self.dx) < eps and abs(self.dy) < eps
                and self.alpha > 0.999)

    def clamp(self, engine, max_w=1.0, max_h=1.0):
        """按引擎规整：overlay 引擎不许位移，缩放夹在画布预留范围内。"""
        sx = min(max(self.sx, 1.0 - max_h), max_w)
        sy = min(max(self.sy, 1.0 - max_h), 1.0 + max_h)
        if engine == ENGINE_OVERLAY:
            return Transform(sx, sy, 0.0, 0.0, 1.0)
        return Transform(sx, sy, self.dx, self.dy, min(max(self.alpha, 0.0),
                                                       1.0))

    def blended(self, k):
        """从 1:1 静止插值到这个形变（k=0 静止，k=1 完全到位）。

        模式切换时用它做过渡，避免换模式那一帧图标突然跳一下。
        """
        if k >= 1.0:
            return self
        k = max(0.0, k)
        return Transform(sx=1.0 + (self.sx - 1.0) * k,
                         sy=1.0 + (self.sy - 1.0) * k,
                         dx=self.dx * k,
                         dy=self.dy * k,
                         alpha=1.0 - (1.0 - self.alpha) * k)


class Mode:
    """动画模式基类。

    子类至少覆盖 name/title/engine 和 tick()。tick 返回
    {图标唯一 key: Transform}；没出现的 key 视为静止。
    """

    name = ""
    title = ""
    engine = ENGINE_OVERLAY
    #: 自动轮换时停留多久（秒）；None = 不参与自动轮换（如"两年半"跳完一轮）
    dwell_s = 10.0

    def attach(self, ctx):
        """切到这个模式时调用一次。"""

    def detach(self):
        """离开这个模式时调用一次。"""

    def tick(self, ctx, dt):
        raise NotImplementedError

    def wants_exit(self, ctx):
        """takeover 模式可以自己要求下场（例如"两年半"跳完一轮）。"""
        return False


class ModeContext:
    """模式能看到的全部东西（只读视图，模式不该回写）。"""

    def __init__(self, icons, bands, bass, presence, jelly, screen, now):
        self.icons = icons          # [(key, DesktopIcon)]
        self.bands = bands          # 64 段 AGC 后的频段
        self.bass = bass
        self.presence = presence
        self.jelly = jelly          # JellyState（律动类模式共用）
        self.screen = screen        # (w, h)
        self.now = now

    def center(self, icon):
        left, top, right, bottom = icon.rect
        return (left + right) / 2.0, (top + bottom) / 2.0
