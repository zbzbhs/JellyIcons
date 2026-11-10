# -*- coding: utf-8 -*-
"""控制面板（自绘 UI）。

为什么不用原生控件：
    原生 Tk 控件在深色主题下很难做统一质感（ttk 主题只管得了部分状态，
    下拉列表还得单独走 option 数据库）。这里改成"整块用 Pillow 画、贴到
    一个 Canvas 上"，所有圆角、渐变、状态色都由我们自己的像素决定，视觉
    上完全一致；交互靠 Canvas 的鼠标事件 + 自建命中表实现。

设计约束（延续整个项目的原则）：
    - 面板只"发命令"，绝不直接碰 overlay 窗口或桌面。所有状态归 App 主
      循环所有：面板通过 `app.post()` 提交意图、通过 `app.snapshot()` 读
      只读快照。跨线程只共享一个 Queue 和一份不可变 dict。
    - 面板跑在独立线程（Tk 不允许跨线程访问），主线程继续按 FPS 渲染。
      面板崩了、关掉、Tk 初始化失败，都不影响动画 —— 这条路径永远可选。
    - 窗口无边框（overrideredirect）+ 颜色键透明：圆角以外的像素直接透出
      桌面，没有直角白底。拖动由标题栏区域自己实现。
"""
from __future__ import annotations

import os
import threading

from .logutil import get_logger

log = get_logger()

# ---------------------------------------------------------------- 视觉常量

BG_TOP = (17, 20, 26)
BG_BOTTOM = (23, 27, 35)
SURFACE = (29, 34, 45)
SURFACE_HI = (38, 45, 59)
BORDER = (46, 55, 71)
TEXT = (231, 236, 245)
DIM = (139, 149, 168)
FAINT = (96, 105, 122)
ACCENT = (75, 214, 160)
ACCENT_DIM = (30, 104, 78)
WARN = (242, 181, 68)
DANGER = (232, 106, 106)
KEY = "#ff00ff"          # 颜色键：这个颜色会被 Windows 当成"完全透明"

PAD = 16
WIDTH = 424
RADIUS = 16

POLL_MS = 33             # 面板刷新 ~30fps，主循环是 60fps，够看

_FONT_CANDIDATES = (
    (r"C:\Windows\Fonts\msyh.ttc", 0),
    (r"C:\Windows\Fonts\msyhl.ttc", 0),
    (r"C:\Windows\Fonts\segoeui.ttf", 0),
    (r"C:\Windows\Fonts\simhei.ttf", 0),
)

_font_cache: dict = {}


def _font(size: int, bold: bool = False):
    """拿到一个 PIL 字体对象（带缓存）。找不到任何中文字体时退回默认位图字体。"""
    key = (size, bold)
    hit = _font_cache.get(key)
    if hit is not None:
        return hit
    from PIL import ImageFont

    path = None
    if bold:
        for cand in (r"C:\Windows\Fonts\msyhbd.ttc",
                     r"C:\Windows\Fonts\msyh.ttc",
                     r"C:\Windows\Fonts\segoeuib.ttf"):
            if os.path.exists(cand):
                path = cand
                break
    if path is None:
        for cand, idx in _FONT_CANDIDATES:
            if os.path.exists(cand):
                path = cand
                break
    try:
        font = (ImageFont.truetype(path, size, index=0) if path
                else ImageFont.load_default())
    except Exception:
        font = ImageFont.load_default()
    _font_cache[key] = font
    return font


def _rr(draw, box, radius, fill=None, outline=None, width=1):
    """圆角矩形。PIL 的 rounded_rectangle 半径会被自动夹到合法范围。"""
    draw.rounded_rectangle(box, radius=radius, fill=fill,
                           outline=outline, width=width)


_bg_cache: dict = {}


def _paint_bg(size):
    """竖向渐变底：从上到下一点点变亮，避免大块纯色的塑料感。

    逐像素循环在 Python 里很贵（424×578 就是 24 万次），而面板每秒重画
    30 次 —— 所以按尺寸缓存，尺寸不变时直接复用同一张底图。
    """
    from PIL import Image

    w, h = size
    hit = _bg_cache.get((w, h))
    if hit is not None:
        return hit.copy()
    img = Image.new("RGB", (w, h), BG_TOP)
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        # 轻微的纵向渐变 + 极弱的横向提亮，模拟环境光
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    if len(_bg_cache) > 8:
        _bg_cache.clear()
    _bg_cache[(w, h)] = img
    return img.copy()


class ControlPanel:
    """无边框自绘面板。对外只暴露 start() / stop()。"""

    # 布局（y 坐标都在 _layout() 里算，这里只是名义常量）
    HEADER_H = 46
    STATUS_H = 70
    WAVE_H = 92
    MODE_ROW_H = 60
    ROW_H = 42

    def __init__(self, app):
        self.app = app
        self._thread = None
        self._stop = threading.Event()
        self._root = None
        self._canvas = None
        self._photo = None
        self._item = None
        self._popup = None
        self._hits = []          # [(x0, y0, x1, y1, action)]
        self._hover = None
        self._collapsed = False
        self._drag = None
        self._peaks = [0.0] * 64
        self._last_bands = None
        self._device_open = False
        self._pinned = True
        self._fps_smooth = 0.0
        self._height = 0

    # ------------------------------------------------------------ 生命周期

    def start(self):
        if self._thread is not None:
            return False
        self._thread = threading.Thread(target=self._run, name="panel",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        root = self._root
        if root is not None:
            try:
                root.after(0, root.destroy)
            except Exception:
                pass

    # ------------------------------------------------------------ Tk 线程

    def _run(self):
        try:
            import tkinter as tk
        except Exception as exc:
            log.warning("[ui] 无法加载 tkinter（%r），以无面板模式运行", exc)
            return
        try:
            root = tk.Tk()
        except Exception as exc:
            log.warning("[ui] Tk 初始化失败（%r），以无面板模式运行", exc)
            return

        self._root = root
        root.overrideredirect(True)
        root.configure(bg=KEY)
        try:
            root.wm_attributes("-transparentcolor", KEY)
        except Exception:
            # 老系统/某些远程桌面拿不到颜色键，退化成一个圆角黑底窗口
            root.configure(bg="#11141a")
            log.info("[ui] 颜色键透明不可用，使用实心底色")
        try:
            root.wm_attributes("-topmost", True)
        except Exception:
            pass
        root.title("JellyIcons")

        canvas = tk.Canvas(root, highlightthickness=0, bd=0, bg=KEY,
                           width=WIDTH, height=10)
        canvas.pack(fill="both", expand=True)
        self._canvas = canvas

        canvas.bind("<Motion>", self._on_motion)
        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<Leave>", self._on_leave)
        canvas.bind("<MouseWheel>", lambda e: "break")
        root.bind("<Escape>", lambda e: self.app.post({"type": "quit"}))

        self._place_window()
        self._render()
        self._tick()
        try:
            root.mainloop()
        except Exception as exc:
            log.warning("[ui] 面板主循环异常退出: %r", exc)
        log.info("[ui] 面板已关闭")

    def _place_window(self):
        root = self._root
        if root is None:
            return
        # 默认贴屏幕右上角，离边缘留一点呼吸
        try:
            sw = root.winfo_screenwidth()
            x = max(0, sw - WIDTH - 28)
            y = 72
            root.geometry("+%d+%d" % (x, y))
        except Exception:
            pass

    # ------------------------------------------------------------ 绘制

    def _snap(self):
        try:
            return self.app.snapshot() or {}
        except Exception:
            return {}

    def _render(self):
        """按当前快照重画整块面板，并把可点区域记进 self._hits。"""
        from PIL import ImageDraw

        snap = self._snap()
        hits = []
        height = self._measure(snap)
        self._height = height

        img = _paint_bg((WIDTH, height))
        d = ImageDraw.Draw(img)

        # 圆角遮罩：面板以外涂成颜色键 → 屏幕上是完全透明
        from PIL import Image as _I
        mask = _I.new("L", (WIDTH * 2, height * 2), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, WIDTH * 2 - 1, height * 2 - 1], radius=RADIUS * 2, fill=255)
        mask = mask.resize((WIDTH, height), _I.LANCZOS)
        base = _I.new("RGB", (WIDTH, height), KEY)
        base.paste(img, (0, 0), mask)
        img = base
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, WIDTH - 1, height - 1], radius=RADIUS,
                            outline=BORDER, width=1)

        self._draw_sections(d, snap, hits)

        self._hits = hits
        self._blit(img, height)

    def _draw_sections(self, d, snap, hits):
        """按顺序画所有区块。折叠时只留标题栏。

        抽出来是为了让离线渲染（render_preview / 单测）和真实窗口走
        完全同一条绘制路径 —— 之前两边各写一份，折叠逻辑只改了一边，
        结果折叠后仍然画出整块面板、按钮全在窗口外面。
        """
        y = self._draw_header(d, snap, hits)
        if self._collapsed:
            return y
        y = self._draw_status(d, snap, y)
        y = self._draw_wave(d, snap, y)
        y = self._draw_modes(d, snap, y, hits)
        y = self._draw_switch(d, snap, y, hits)
        y = self._draw_device(d, snap, y, hits)
        return self._draw_footer(d, snap, y, hits)

    def _modes(self):
        """模式列表的单一来源：测量高度和真正绘制必须用同一份。"""
        try:
            return list(self.app.mode_list or [])
        except Exception:
            return []

    def _measure(self, snap):
        if self._collapsed:
            return self.HEADER_H + 8
        # 高度必须以真正要画的列表为准。之前这里读 snap["mode_count"]，
        # 而 _draw_modes 读 app.mode_list —— 两者不一致时（比如快照还是上一
        # 帧的 4 个模式、实际已经 8 个）底部按钮会被窗口裁掉。
        modes = self._modes()
        count = len(modes) if modes else int(snap.get("mode_count") or 8)
        rows = max(1, (count + 3) // 4)
        h = (8 + self.HEADER_H + 6 + self.STATUS_H + 10 + self.WAVE_H + 12
             + rows * self.MODE_ROW_H + (rows - 1) * 8 + 12
             + self.ROW_H + 8 + self.ROW_H + 10
             + 44 + 10 + 48)
        return h

    def _blit(self, img, height):
        from PIL import ImageTk

        canvas = self._canvas
        if canvas is None:
            return
        try:
            self._photo = ImageTk.PhotoImage(img)
            if self._item is None:
                self._item = canvas.create_image(0, 0, anchor="nw",
                                                 image=self._photo)
            else:
                canvas.itemconfig(self._item, image=self._photo)
            if int(canvas["height"]) != height:
                canvas.config(height=height)
                self._root.geometry("%dx%d" % (WIDTH, height))
        except Exception as exc:
            log.warning("[ui] 贴图失败: %r", exc)

    # ---- 各区块 ----

    def _draw_header(self, d, snap, hits):
        y = 8
        h = self.HEADER_H
        # 应用名 + 版本
        d.text((PAD + 2, y + h // 2), "JellyIcons", font=_font(16, True),
               fill=TEXT, anchor="lm")
        ver = snap.get("version") or ""
        if ver:
            d.text((PAD + 2 + 92, y + h // 2 + 1), "v" + str(ver),
                   font=_font(10), fill=FAINT, anchor="lm")

        # 右上三个小按钮：折叠 / 关闭
        by = y + h // 2
        bx = WIDTH - PAD - 14
        hits.append((bx - 12, by - 12, bx + 12, by + 12, "close"))
        self._icon_button(d, bx, by, "close",
                          DANGER if self._hover == "close" else DIM)

        bx2 = bx - 30
        # 折叠态的同一个按钮要报 "expand"，否则 _on_release 里点它会走
        # 反方向的分支（视觉上是展开图标，行为却是再折叠一次）。
        hits.append((bx2 - 12, by - 12, bx2 + 12, by + 12,
                     "collapse" if not self._collapsed else "expand"))
        self._icon_button(d, bx2, by, "collapse" if not self._collapsed
                          else "expand",
                          TEXT if self._hover in ("collapse", "expand") else DIM)

        # 折叠态：标题栏右侧显示一句状态，方便一眼看出在不在工作
        if self._collapsed:
            hidden = snap.get("hidden")
            txt = "音乐中 · 已接管" if hidden else "待机 · 原始图标"
            d.text((WIDTH - PAD - 74, by), txt, font=_font(11),
                   fill=ACCENT if hidden else DIM, anchor="rm")
        else:
            # 拖动提示：标题栏空白处可拖
            hits.append((PAD, y, WIDTH - PAD - 80, y + h, "drag"))
        return y + h

    def _icon_button(self, d, cx, cy, kind, color):
        r = 7
        if kind == "close":
            d.line([(cx - r, cy - r), (cx + r, cy + r)], fill=color, width=1)
            d.line([(cx - r, cy + r), (cx + r, cy - r)], fill=color, width=1)
        elif kind == "collapse":
            d.line([(cx - r, cy), (cx + r, cy)], fill=color, width=1)
        else:  # expand
            _rr(d, [cx - r - 1, cy - r + 1, cx + r + 1, cy + r - 1], 3,
                fill=None, outline=color, width=1)

    def _draw_status(self, d, snap, y):
        y += 6
        hidden = bool(snap.get("hidden"))
        engine = snap.get("engine") or "overlay"
        mode_title = snap.get("mode_title") or "律动"
        icons = int(snap.get("icons") or 0)
        audio_ok = bool(snap.get("audio_ok"))
        bass = float(snap.get("bass") or 0.0)

        box = [PAD, y, WIDTH - PAD, y + self.STATUS_H]
        _rr(d, box, 12, fill=SURFACE, outline=BORDER)

        # 状态点 + 状态词
        dot = ACCENT if hidden else FAINT
        d.ellipse([PAD + 16 - 4, y + 22 - 4, PAD + 16 + 4, y + 22 + 4],
                  fill=dot)
        state_txt = "音乐中" if hidden else "待机"
        d.text((PAD + 28, y + 22), state_txt, font=_font(15, True),
               fill=TEXT, anchor="lm")
        sub = "%s · %s" % (mode_title, "接管" if engine == "takeover"
                           else "原位")
        d.text((PAD + 16, y + 46), sub, font=_font(11), fill=DIM, anchor="lm")

        # 右侧三条小指标
        right = WIDTH - PAD - 14
        rows = [
            ("图标", str(icons), TEXT),
            ("FPS", "%.0f" % float(snap.get("fps") or 0), TEXT),
            ("音频", "OK" if audio_ok else "无", ACCENT if audio_ok else WARN),
        ]
        for i, (label, value, col) in enumerate(rows):
            cy = y + 18 + i * 18
            d.text((right, cy), value, font=_font(12, True), fill=col,
                   anchor="rm")
            d.text((right - 40, cy), label, font=_font(10), fill=FAINT,
                   anchor="rm")

        # 底部 2px 电平条：低频强度，直观看有没有在吃音乐
        bar_w = WIDTH - PAD * 2 - 32
        bx = PAD + 16
        byv = y + self.STATUS_H - 10
        d.rounded_rectangle([bx, byv, bx + bar_w, byv + 3], radius=2,
                            fill=(43, 50, 64))
        fillw = int(min(1.0, bass) * bar_w)
        if fillw > 1:
            d.rounded_rectangle([bx, byv, bx + fillw, byv + 3], radius=2,
                                fill=ACCENT if hidden else ACCENT_DIM)
        return y + self.STATUS_H

    def _draw_wave(self, d, snap, y):
        y += 10
        box = [PAD, y, WIDTH - PAD, y + self.WAVE_H]
        _rr(d, box, 12, fill=(12, 15, 21), outline=BORDER)

        bands = snap.get("bands") or []
        inner_x = PAD + 10
        inner_w = WIDTH - PAD * 2 - 20
        top = y + 10
        bottom = y + self.WAVE_H - 8
        mid = (top + bottom) / 2.0
        half = (bottom - top) / 2.0

        n = 64
        gap = 1.6
        bw = max(1.0, (inner_w - gap * (n - 1)) / n)
        vals = list(bands[:n]) + [0.0] * max(0, n - len(bands))
        for i in range(n):
            v = float(vals[i] or 0.0)
            v = max(0.0, min(1.0, v))
            # 峰值保持：掉得比上升慢，波形看起来才有"记忆"
            self._peaks[i] = max(v, self._peaks[i] - 0.012)
            h = max(1.0, v * half)
            x0 = inner_x + i * (bw + gap)
            x1 = x0 + bw
            # 上下对称，渐变靠两段色表现
            col = ACCENT if v > 0.55 else (58, 150, 190)
            d.rectangle([x0, mid - h, x1, mid + h], fill=col)
            ph = max(1.0, self._peaks[i] * half)
            d.rectangle([x0, mid - ph - 1, x1, mid - ph],
                        fill=(242, 181, 68))

        d.line([inner_x, mid, inner_x + inner_w, mid], fill=(32, 40, 52))
        if not bands:
            d.text((WIDTH / 2, mid), "等待音频", font=_font(11), fill=FAINT,
                   anchor="mm")
        return y + self.WAVE_H

    def _draw_modes(self, d, snap, y, hits):
        y += 12
        modes = self._modes()
        if not modes:
            return y
        current = snap.get("mode")
        cols = 4
        gap = 8
        cell_w = (WIDTH - PAD * 2 - gap * (cols - 1)) / cols
        cell_h = self.MODE_ROW_H
        for i, (name, title, engine) in enumerate(modes):
            r, c = divmod(i, cols)
            x0 = PAD + c * (cell_w + gap)
            y0 = y + r * (cell_h + gap)
            active = (name == current)
            key = "mode:" + name
            hover = self._hover == key
            fill = ACCENT_DIM if active else (
                SURFACE_HI if hover else SURFACE)
            _rr(d, [x0, y0, x0 + cell_w, y0 + cell_h], 10, fill=fill,
                outline=ACCENT if active else BORDER)
            cy = y0 + cell_h / 2
            d.text((x0 + cell_w / 2, cy - 7), title, font=_font(12, active),
                   fill=TEXT if active else (200, 208, 222), anchor="mm")
            tag = "接管" if engine == "takeover" else "原位"
            d.text((x0 + cell_w / 2, cy + 10), tag, font=_font(9),
                   fill=ACCENT if active else FAINT, anchor="mm")
            hits.append((x0, y0, x0 + cell_w, y0 + cell_h, key))
        rows = max(1, (len(modes) + cols - 1) // cols)
        return y + rows * cell_h + (rows - 1) * gap

    def _draw_switch(self, d, snap, y, hits):
        y += 12
        box = [PAD, y, WIDTH - PAD, y + self.ROW_H]
        _rr(d, box, 10, fill=SURFACE, outline=BORDER)
        cy = y + self.ROW_H / 2
        d.text((PAD + 14, cy), "自动轮换", font=_font(12), fill=TEXT,
               anchor="lm")
        d.text((PAD + 14 + 62, cy), "每 10 秒换一种", font=_font(10),
               fill=FAINT, anchor="lm")

        on = bool(snap.get("auto"))
        tw, th = 38, 20
        tx0 = WIDTH - PAD - 14 - tw
        ty0 = cy - th / 2
        _rr(d, [tx0, ty0, tx0 + tw, ty0 + th], th / 2,
            fill=ACCENT_DIM if on else (54, 62, 78))
        kx = tx0 + tw - th / 2 if on else tx0 + th / 2
        d.ellipse([kx - 7, cy - 7, kx + 7, cy + 7],
                  fill=ACCENT if on else (150, 160, 178))
        hits.append((tx0, ty0, tx0 + tw, ty0 + th, "auto"))
        return y + self.ROW_H

    def _draw_device(self, d, snap, y, hits):
        y += 8
        box = [PAD, y, WIDTH - PAD, y + self.ROW_H]
        _rr(d, box, 10, fill=SURFACE, outline=BORDER)
        cy = y + self.ROW_H / 2
        d.text((PAD + 14, cy), "音频输出", font=_font(12), fill=TEXT,
               anchor="lm")
        name = str(snap.get("device") or "默认设备")
        if len(name) > 22:
            name = name[:21] + "…"
        d.text((PAD + 78, cy), name, font=_font(11), fill=DIM, anchor="lm")
        # 下拉箭头
        ax = WIDTH - PAD - 18
        d.polygon([(ax - 5, cy - 2), (ax + 5, cy - 2), (ax, cy + 4)],
                  fill=DIM)
        hits.append((PAD, y, WIDTH - PAD, y + self.ROW_H, "device"))
        return y + self.ROW_H

    def _draw_footer(self, d, snap, y, hits):
        y += 10
        # 主按钮：停止
        btn = [PAD, y, WIDTH - PAD, y + 44]
        hover = self._hover == "quit"
        _rr(d, btn, 12, fill=(52, 40, 42) if not hover else (74, 52, 55),
            outline=(92, 62, 66))
        d.text((WIDTH / 2, y + 22), "停止并退出", font=_font(13, True),
               fill=(232, 150, 150), anchor="mm")
        hits.append((btn[0], btn[1], btn[2], btn[3], "quit"))

        y += 54
        hints = snap.get("hotkeys") or [
            "Ctrl+Alt+←/→ 切换模式", "Ctrl+Alt+Space 自动轮换",
            "Ctrl+Alt+F9 退出"]
        for i, line in enumerate(hints[:3]):
            d.text((PAD + 2, y + i * 13), line, font=_font(9), fill=FAINT,
                   anchor="la")
        return y + 26

    # ------------------------------------------------------------ 交互

    def _hit(self, x, y):
        for x0, y0, x1, y1, action in self._hits:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return action
        return None

    def _on_motion(self, event):
        action = self._hit(event.x, event.y)
        if action != self._hover:
            self._hover = action
            try:
                self._canvas.config(
                    cursor="hand2" if action and action != "drag" else
                    ("fleur" if action == "drag" else ""))
            except Exception:
                pass
            self._render()
        if self._drag is not None:
            dx = event.x_root - self._drag[0]
            dy = event.y_root - self._drag[1]
            try:
                self._root.geometry("+%d+%d" % (self._drag[2] + dx,
                                                self._drag[3] + dy))
            except Exception:
                pass

    def _on_leave(self, event):
        if self._hover is not None and self._drag is None:
            self._hover = None
            self._render()

    def _on_press(self, event):
        action = self._hit(event.x, event.y)
        if action == "drag":
            self._drag = (event.x_root, event.y_root,
                          self._root.winfo_x(), self._root.winfo_y())
            return
        self._drag = None

    def _on_release(self, event):
        dragged = self._drag is not None
        self._drag = None
        if dragged:
            return
        action = self._hit(event.x, event.y)
        if action is None:
            return
        if action == "quit":
            self.app.post({"type": "quit"})
        elif action == "collapse":
            self._collapsed = not self._collapsed
            self._render()
        elif action == "expand":
            self._collapsed = False
            self._render()
        elif action == "auto":
            self.app.post({"type": "toggle_auto"})
        elif action == "device":
            self._open_device_menu()
        elif action.startswith("mode:"):
            self.app.post({"type": "select_mode", "name": action[5:]})

    # ---- 设备下拉 ----

    def _open_device_menu(self):
        if self._popup is not None:
            self._close_popup()
            return
        try:
            import tkinter as tk
        except Exception:
            return
        devices = list(getattr(self.app, "devices", []) or [])
        if not devices:
            return
        from PIL import ImageDraw, ImageTk

        row_h = 34
        w = WIDTH - PAD * 2
        h = 10 + row_h * len(devices) + 6
        img = _paint_bg((w, h))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=10, fill=SURFACE,
                            outline=BORDER)
        for i, dev in enumerate(devices):
            y0 = 5 + i * row_h
            name = str(dev.get("name") or "设备")
            if len(name) > 26:
                name = name[:25] + "…"
            if dev.get("default"):
                name += "  默认"
            d.text((14, y0 + row_h / 2), name, font=_font(11), fill=TEXT,
                   anchor="lm")

        popup = tk.Toplevel(self._root)
        popup.overrideredirect(True)
        try:
            popup.wm_attributes("-topmost", True)
            popup.wm_attributes("-transparentcolor", KEY)
        except Exception:
            pass
        popup.configure(bg=KEY)
        canvas = tk.Canvas(popup, width=w, height=h, highlightthickness=0,
                           bd=0, bg=KEY)
        canvas.pack()
        photo = ImageTk.PhotoImage(img)
        canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas.image = photo

        try:
            rx = self._root.winfo_rootx() + PAD
            ry = self._root.winfo_rooty() + self._height - 120
            popup.geometry("+%d+%d" % (rx, ry))
        except Exception:
            pass

        def choose(event):
            idx = (event.y - 5) // row_h
            if 0 <= idx < len(devices):
                self.app.post({"type": "device",
                               "index": devices[idx].get("index")})
            self._close_popup()

        canvas.bind("<Button-1>", choose)
        canvas.bind("<Motion>", lambda e: canvas.config(cursor="hand2"))
        popup.bind("<FocusOut>", lambda e: self._close_popup())
        self._popup = popup
        self._device_open = True

    def _close_popup(self):
        popup, self._popup = self._popup, None
        self._device_open = False
        if popup is not None:
            try:
                popup.destroy()
            except Exception:
                pass

    # ------------------------------------------------------------ 刷新

    def _tick(self):
        if self._stop.is_set():
            try:
                self._root.destroy()
            except Exception:
                pass
            return
        try:
            self._render()
        except Exception as exc:
            log.warning("[ui] 刷新失败: %r", exc)
        try:
            self._root.after(POLL_MS, self._tick)
        except Exception:
            pass


# ------------------------------------------------------------------ 预览

def render_preview(path, snap=None, mode_list=None):
    """把面板画成一张 PNG（自检与文档用，不启动 Tk）。"""
    snap = dict(snap or {})
    _modes = list(mode_list or [])

    class _FakeApp:
        mode_list = _modes

        def snapshot(self):
            return snap

        def post(self, cmd):
            pass

    panel = ControlPanel(_FakeApp())
    panel._render_to_file = None
    from PIL import Image, ImageDraw

    height = panel._measure(snap)
    img = _paint_bg((WIDTH, height))
    d = ImageDraw.Draw(img)
    mask = Image.new("L", (WIDTH * 2, height * 2), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, WIDTH * 2 - 1, height * 2 - 1], radius=RADIUS * 2, fill=255)
    mask = mask.resize((WIDTH, height), Image.LANCZOS)
    base = Image.new("RGB", (WIDTH, height), (10, 12, 16))
    base.paste(img, (0, 0), mask)
    img = base
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, WIDTH - 1, height - 1], radius=RADIUS,
                        outline=BORDER, width=1)
    panel._draw_sections(d, snap, [])
    img.save(path)
    return path
