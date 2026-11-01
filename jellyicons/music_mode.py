# -*- coding: utf-8 -*-
"""音乐模式：检测到音乐时隐藏真实桌面图标，音乐停止后恢复。

实现方式：ShowWindow(SysListView32, SW_HIDE/SW_SHOW)。

为什么这样做是干净且足够安全的：
  1. Windows 自带的"右键桌面 → 查看 → 显示桌面图标"开关本质上就是
     explorer 隐藏同一个 SysListView32 窗口——我们做的事与系统开关
     逐像素一致，只是触发时机交给音乐检测。
  2. 只改窗口可见性（SWP/ShowWindow），不改 GWL_STYLE、不改 exstyle、
     不写注册表、不碰 FFlags（旧工程事故的根源全部避开）。
  3. explorer 重启后窗口句柄变化：状态机每次动作前重查句柄，
     查不到就放弃隐藏并保持恢复态。
  4. 强杀自愈：退出路径（finally / atexit / 异常）全部恢复；
     进程被 taskkill /F 时由独立看门狗子进程恢复（见 watchdog.py）。
  5. 用户手动勾掉"显示桌面图标"（HideIcons=1）时不抢：启动时如果
     图标本来就被用户隐藏，音乐模式禁用，绝不代用户做决定。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from .logutil import get_logger

log = get_logger()

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [
    wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
]
user32.FindWindowExW.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL

SW_HIDE = 0
SW_SHOW = 5

# 状态
STATE_INIT = "init"          # 尚未决定（音乐模式待命）
STATE_SHOWN = "shown"        # 真实图标可见（正常模式）
STATE_HIDDEN = "hidden"      # 真实图标被我们隐藏（音乐模式中）
HIDE_RETRY_S = 0.5


def find_listview_hwnd() -> int:
    """Progman→[WorkerW]→SHELLDLL_DefView→SysListView32，找不到返回 0。

    每次调用重查：explorer 重启后句柄会变，缓存句柄会操作到死句柄。
    """
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        return 0
    defview = user32.FindWindowExW(progman, 0, "SHELLDLL_DefView", None)
    if not defview:
        worker = user32.FindWindowExW(progman, 0, "WorkerW", None)
        while worker:
            defview = user32.FindWindowExW(
                worker, 0, "SHELLDLL_DefView", None)
            if defview:
                break
            worker = user32.FindWindowExW(
                progman, worker, "WorkerW", None)
    if not defview:
        return 0
    return user32.FindWindowExW(defview, 0, "SysListView32", None) or 0


class MusicMode:
    """音乐检测滞回 + 图标隐藏/恢复的状态机。

    用法：主循环每帧调 feed(presence, now)，再用 mode 属性决定 overlay
    是否接管文字标签绘制等。

    注意：feed 的入参是 ActivityDetector 给出的 **presence**（0..1，
    已过 attack/release 包络 + 逐频段 AGC），不是裸 bass。包络把节拍
    之间的空档填平了，所以阈值可以取得很低而不会误触发。
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.state = STATE_INIT
        self._above_since: float | None = None
        self._below_since: float | None = None
        self._hide_succeeded = False   # 本次会话是否成功隐藏过
        self._recover_failed_logged = False
        self._last_hide_attempt = float("-inf")

    # ---- 检测 ----

    def feed(self, presence: float, now: float,
             allow_exit: bool = True, before_enter=None) -> str:
        """输入当前音乐活动度与时间戳，返回期望状态 STATE_*。

        allow_exit=False 时只允许进入隐藏、不允许退出。主循环用它做
        "等缩放回落到 1.0 再切回真图标"的闸门——否则形变还没归位就
        把真图标显示出来，会看到一下跳变。

        before_enter：隐藏真图标**之前**执行的回调。主循环用它先把副本
        按 1:1 画满屏幕，再让 explorer 的图标消失——顺序反了会看到桌面
        整块空一帧（这就是"连贯"的关键）。
        """
        if not self.enabled:
            self.state = STATE_SHOWN
            return STATE_SHOWN
        if presence >= MUSIC_ON_THRESHOLD:
            if self._above_since is None:
                self._above_since = now
            if (now - self._above_since >= MUSIC_ON_HOLD_S
                    and self.state != STATE_HIDDEN
                    and now - self._last_hide_attempt >= HIDE_RETRY_S):
                self._last_hide_attempt = now
                if before_enter is not None:
                    try:
                        ready = before_enter()
                    except Exception as exc:
                        log.warning("[music] 副本预绘制失败，保留真实图标: %r", exc)
                        ready = False
                    if ready is False:
                        return self.state
                self._enter_hidden()
        else:
            self._above_since = None
            if self.state == STATE_INIT:
                # 启动时没到开阈值：直接落到 shown。卡在 init 会让
                # 主循环的 at_rest 判断和日志都看不出真实状态。
                self.state = STATE_SHOWN
        if presence <= MUSIC_OFF_THRESHOLD:
            if self._below_since is None:
                self._below_since = now
            if (allow_exit and now - self._below_since >= MUSIC_OFF_HOLD_S
                    and self.state == STATE_HIDDEN):
                self._exit_hidden()
        else:
            self._below_since = None
        return self.state

    # ---- 状态迁移 ----

    def _enter_hidden(self) -> bool:
        hwnd = find_listview_hwnd()
        if not hwnd:
            log.warning("[music] 找不到桌面 ListView，放弃隐藏"
                        "（explorer 正在重启？）")
            return False
        user32.ShowWindow(hwnd, SW_HIDE)
        if not user32.IsWindowVisible(hwnd):
            self.state = STATE_HIDDEN
            self._hide_succeeded = True
            self._below_since = None
            log.info("[music] 音乐开始 → 真实图标已隐藏")
            return True
        log.warning("[music] ShowWindow(SW_HIDE) 失败，保持显示")
        return False

    def _exit_hidden(self):
        ok = self._show_listview()
        if ok:
            self.state = STATE_SHOWN
            self._above_since = None
            log.info("[music] 音乐停止 → 真实图标已恢复")
        else:
            if not self._recover_failed_logged:
                log.error("[music] 恢复失败！将每帧重试；"
                          "若仍未恢复请手动右键桌面→查看→显示桌面图标")
                self._recover_failed_logged = True

    def _show_listview(self) -> bool:
        """恢复显示；explorer 重启后句柄变化也能找回。"""
        hwnd = find_listview_hwnd()
        if not hwnd:
            return False
        if user32.IsWindowVisible(hwnd):
            return True  # 已经可见（用户手动恢复了或 explorer 重建了）
        user32.ShowWindow(hwnd, SW_SHOW)
        return bool(user32.IsWindowVisible(hwnd))

    # ---- 生命周期 ----

    def restore(self) -> bool:
        """恢复真实图标并返回结果。失败时保留所有权，供看门狗继续接管。"""
        if not self._hide_succeeded:
            return True
        try:
            if self._show_listview():
                self._hide_succeeded = False
                self.state = STATE_SHOWN
                log.info("[music] 退出：真实图标已恢复")
                return True
        except Exception as exc:
            log.error("[music] 退出恢复异常: %r", exc)
        log.error("[music] 真实图标尚未恢复，保留心跳由看门狗继续处理")
        return False


from .config import (  # noqa: E402  (放底部避免循环导入期 config 常量未就绪)
    MUSIC_ON_THRESHOLD,
    MUSIC_ON_HOLD_S,
    MUSIC_OFF_THRESHOLD,
    MUSIC_OFF_HOLD_S,
)
