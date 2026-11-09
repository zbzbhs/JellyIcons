# -*- coding: utf-8 -*-
"""全局热键：RegisterHotKey + 独立消息线程。

为什么要单独写这个而不是用钩子：
    全局低级钩子（WH_KEYBOARD_LL）会把回调塞进系统输入队列，Python 的
    GIL 一旦被渲染抢走，整个系统的键盘鼠标都会卡住 —— 早期版本真的把
    用户鼠标卡死过。RegisterHotKey 是系统自己匹配组合键，我们只在按下
    时收到一条消息，零风险。

热键默认：
    Ctrl+Alt+F9    退出
    Ctrl+Alt+Right 下一个模式
    Ctrl+Alt+Left  上一个模式
    Ctrl+Alt+Space 开始/暂停自动轮换

注册失败（被别的程序占了）只记日志，不影响主功能。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading

from .logutil import get_logger

log = get_logger()

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

VK_F9 = 0x78
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_SPACE = 0x20

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_uint,
                                  ctypes.c_uint]
user32.RegisterHotKey.restype = wt.BOOL
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wt.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND,
                               ctypes.c_uint, ctypes.c_uint]
user32.GetMessageW.restype = wt.BOOL
user32.PostThreadMessageW.argtypes = [wt.DWORD, ctypes.c_uint,
                                      wt.WPARAM, wt.LPARAM]
user32.PostThreadMessageW.restype = wt.BOOL

#: 默认热键表：id -> (修饰键, 虚拟键, 动作名, 人类可读)
DEFAULT_BINDINGS = (
    (1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_F9, "quit",
     "Ctrl+Alt+F9  退出"),
    (2, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_RIGHT, "next",
     "Ctrl+Alt+→   下一个模式"),
    (3, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_LEFT, "prev",
     "Ctrl+Alt+←   上一个模式"),
    (4, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_SPACE, "toggle_auto",
     "Ctrl+Alt+Space  自动轮换开关"),
)


class HotkeyListener:
    """在后台线程里跑一个消息循环，把热键翻译成回调。"""

    def __init__(self, bindings=None):
        self.bindings = tuple(bindings or DEFAULT_BINDINGS)
        self._actions = {}
        self._thread = None
        self._thread_id = None
        self._registered = []
        self._ready = threading.Event()

    def bind(self, action, callback):
        self._actions[action] = callback

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="hotkeys",
                                        daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def _run(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        for hid, mods, vk, action, human in self.bindings:
            if user32.RegisterHotKey(None, hid, mods, vk):
                self._registered.append(hid)
            else:
                log.info("[hotkey] %s 注册失败（可能被其他程序占用）", human)
        self._ready.set()
        if self._registered:
            log.info("[hotkey] 已注册 %d 个热键", len(self._registered))

        msg = wt.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):
                break
            if msg.message == WM_HOTKEY:
                action = None
                for hid, mods, vk, act, human in self.bindings:
                    if hid == msg.wParam:
                        action = act
                        break
                if action is not None:
                    cb = self._actions.get(action)
                    if cb is not None:
                        try:
                            cb()
                        except Exception as exc:
                            log.warning("[hotkey] %s 回调异常: %r", action, exc)
        self._unregister()

    def _unregister(self):
        for hid in self._registered:
            try:
                user32.UnregisterHotKey(None, hid)
            except Exception:
                pass
        self._registered = []

    def stop(self):
        if self._thread_id is not None:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def describe(self):
        return [human for _hid, _m, _v, _a, human in self.bindings]
