# -*- coding: utf-8 -*-
"""控制面板：设备选择、8 个模式、自动轮换、实时波形、开始/停止。

设计约束（延续整个项目的原则）：
  - 面板只是"发命令"，绝不直接碰 overlay 窗口或桌面 —— 所有状态都归
    App 主循环拥有，面板通过 queue 提交意图、通过只读快照显示现状。
    跨线程只共享两个东西：一个 Queue 和一份不可变快照。
  - 面板跑在自己的线程里（Tk 不允许跨线程访问），主线程继续 60fps 渲染。
    面板崩了、关掉、甚至 Tk 初始化失败，都不影响动画 —— 这条路径必须
    永远可选。
"""
from __future__ import annotations

import threading

from .logutil import get_logger

log = get_logger()

BG = "#12141a"
FG = "#e8ecf4"
DIM = "#8b93a7"
ACCENT = "#4bd6a0"
ACTIVE = "#2a6b52"
WAVE_BG = "#0b0d12"
WAVE_FG = "#4bd6a0"
WAVE_PEAK = "#f2b544"

POLL_MS = 33


class ControlPanel:
    """一个独立线程里的 Tk 面板。"""

    def __init__(self, app):
        self.app = app
        self._thread = None
        self._stop = threading.Event()
        self._root = None
        self._canvas = None
        self._mode_buttons = {}
        self._device_box = None
        self._auto_var = None
        self._status = None
        self._bar_heights = None

    # ---- 生命周期 ----

    def start(self):
        if self._thread is not None:
            return False
        self._thread = threading.Thread(target=self._run, name="panel",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()

    # ---- 线程内部 ----

    def _run(self):
        try:
            import tkinter as tk
            from tkinter import ttk
        except Exception as exc:
            log.warning("[panel] 无法加载 tkinter（%r），以无面板模式运行", exc)
            return
        try:
            root = tk.Tk()
        except Exception as exc:
            log.warning("[panel] Tk 初始化失败（%r），以无面板模式运行", exc)
            return

        self._root = root
        root.title("JellyIcons")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        # 深色下拉框：clam 主题默认是浅灰，白字会看不清。fieldbackground
        # 管输入区、background 管箭头按钮，按下拉列表还要走 option 数据库
        # （那是 Listbox，不受 ttk.Style 管）。
        style.configure("TCombobox", fieldbackground="#1b1f29",
                        background="#1b1f29", foreground=FG,
                        arrowcolor=FG, bordercolor="#2a3040",
                        lightcolor="#2a3040", darkcolor="#2a3040",
                        selectbackground="#1b1f29", selectforeground=FG)
        style.map("TCombobox",
                  fieldbackground=[("readonly", "#1b1f29"),
                                   ("focus", "#1b1f29")],
                  foreground=[("readonly", FG)],
                  selectbackground=[("readonly", "#1b1f29")],
                  selectforeground=[("readonly", FG)])
        root.option_add("*TCombobox*Listbox.background", "#1b1f29")
        root.option_add("*TCombobox*Listbox.foreground", FG)
        root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        root.option_add("*TCombobox*Listbox.selectForeground", "#0b0d12")

        self._build_header(root, tk, ttk)
        self._build_wave(root, tk)
        self._build_modes(root, tk)
        self._build_footer(root, tk, ttk)

        log.info("[panel] 控制面板已打开")
        try:
            self._tick()
            root.mainloop()
        except Exception as exc:
            log.warning("[panel] 面板异常退出: %r", exc)
        finally:
            try:
                root.destroy()
            except Exception:
                pass
            self._root = None
            log.info("[panel] 控制面板已关闭")

    def _build_header(self, root, tk, ttk):
        bar = tk.Frame(root, bg=BG, padx=12, pady=10)
        bar.pack(fill="x")
        tk.Label(bar, text="音频输出", bg=BG, fg=DIM,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        devices = getattr(self.app, "devices", None) or []
        names = [d["name"] for d in devices] or ["（未检测到 loopback 设备）"]
        self._device_box = ttk.Combobox(bar, values=names, width=42,
                                        state="readonly")
        self._device_box.pack(fill="x", pady=(4, 0))
        idx = 0
        for i, d in enumerate(devices):
            if d.get("default"):
                idx = i
                break
        if devices:
            self._device_box.current(idx)
        self._device_box.bind("<<ComboboxSelected>>", self._on_device)

    def _build_wave(self, root, tk):
        wrap = tk.Frame(root, bg=BG, padx=12)
        wrap.pack(fill="x")
        self._canvas = tk.Canvas(wrap, width=352, height=76, bg=WAVE_BG,
                                 highlightthickness=0, bd=0)
        self._canvas.pack()
        self._bar_heights = [0] * 64

    def _build_modes(self, root, tk):
        wrap = tk.Frame(root, bg=BG, padx=12, pady=10)
        wrap.pack(fill="x")
        modes = getattr(self.app, "mode_list", None) or []
        cols = 4
        for i, (name, title, engine) in enumerate(modes):
            b = tk.Button(
                wrap, text=title, width=8, bd=0, relief="flat",
                bg="#1b1f29", fg=FG, activebackground=ACTIVE,
                activeforeground=FG,
                font=("Microsoft YaHei UI", 9),
                command=lambda n=name: self.app.post(
                    {"type": "select_mode", "name": n}))
            b.grid(row=i // cols, column=i % cols, padx=3, pady=3,
                   sticky="ew")
            b._engine = engine
            self._mode_buttons[name] = b
        for c in range(cols):
            wrap.grid_columnconfigure(c, weight=1)

    def _build_footer(self, root, tk, ttk):
        bar = tk.Frame(root, bg=BG, padx=12, pady=8)
        bar.pack(fill="x")
        self._auto_var = tk.BooleanVar(
            value=bool(getattr(self.app, "auto_switch", True)))
        cb = tk.Checkbutton(
            bar, text="自动轮换", variable=self._auto_var, bg=BG, fg=FG,
            selectcolor="#1b1f29", activebackground=BG,
            activeforeground=FG, bd=0, highlightthickness=0,
            font=("Microsoft YaHei UI", 9),
            command=self._on_auto)
        cb.pack(side="left")

        tk.Button(bar, text="停止", width=7, bd=0, bg="#3a2230", fg="#ff9aa8",
                  activebackground="#4a2a3a", activeforeground="#ff9aa8",
                  font=("Microsoft YaHei UI", 9),
                  command=lambda: self.app.post({"type": "quit"})
                  ).pack(side="right")

        self._status = tk.Label(root, text="", bg=BG, fg=DIM, anchor="w",
                                padx=12, pady=6,
                                font=("Microsoft YaHei UI", 8))
        self._status.pack(fill="x")

        hint = "   ".join(getattr(self.app, "hotkey_hints", None) or [])
        tk.Label(root, text=hint, bg=BG, fg="#5d6478", anchor="w", padx=12,
                 pady=10, font=("Microsoft YaHei UI", 8),
                 wraplength=352, justify="left").pack(fill="x")

    # ---- 事件 ----

    def _on_close(self):
        self.app.post({"type": "quit"})
        self.stop()
        if self._root is not None:
            try:
                self._root.quit()
            except Exception:
                pass

    def _on_device(self, _evt=None):
        i = self._device_box.current()
        devices = getattr(self.app, "devices", None) or []
        if 0 <= i < len(devices):
            self.app.post({"type": "device", "index": devices[i]["index"]})

    def _on_auto(self):
        self.app.post({"type": "set_auto", "value": bool(self._auto_var.get())})

    # ---- 每帧刷新（面板线程） ----

    def _tick(self):
        if self._stop.is_set() or self._root is None:
            return
        snap = self.app.snapshot()
        if snap is not None:
            self._draw_wave(snap)
            self._refresh_modes(snap)
            self._status.configure(text=self._status_text(snap))
        self._root.after(POLL_MS, self._tick)

    def _draw_wave(self, snap):
        c = self._canvas
        if c is None:
            return
        bands = snap.get("bands") or ()
        n = min(64, len(bands))
        x0, w = 4, 5
        gap = 1
        h = 76
        c.delete("all")
        for i in range(n):
            v = max(0.0, min(1.0, float(bands[i]) * float(snap.get("gain", 1.0))))
            bh = int(v * (h - 8))
            if bh <= self._bar_heights[i] and bh == 0:
                continue
            self._bar_heights[i] = bh
            x = x0 + i * (w + gap)
            colour = WAVE_PEAK if v > 0.86 else WAVE_FG
            c.create_rectangle(x, h - 4 - bh, x + w, h - 4,
                               fill=colour, width=0)

    def _refresh_modes(self, snap):
        cur = snap.get("mode")
        for name, btn in self._mode_buttons.items():
            active = (name == cur)
            try:
                btn.configure(bg=ACTIVE if active else "#1b1f29",
                              fg=FG if active else "#b9c0d0")
            except Exception:
                pass

    @staticmethod
    def _status_text(snap):
        return ("%s · %s · %d 个图标 · %s · fps %.0f"
                % (snap.get("mode_title", "?"),
                   "接管" if snap.get("engine") == "takeover" else "原位",
                   snap.get("icons", 0),
                   "音乐中" if snap.get("hidden") else "待机",
                   snap.get("fps", 0.0)))
