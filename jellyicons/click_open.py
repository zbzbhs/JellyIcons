# -*- coding: utf-8 -*-
"""双击 overlay 副本 → 打开对应真实桌面项。

为什么不让 overlay 窗口自己接收鼠标：
    要让窗口收到 WM_LBUTTONDOWN 就必须去掉 WS_EX_TRANSPARENT，而那样
    桌面图标的拖动/删除/框选/右键会全部被我们的窗口吃掉 —— 这正是旧版
    本踩过的坑，架构上不能退回去。

所以走只读轮询：GetAsyncKeyState(VK_LBUTTON) 取按下沿 + GetCursorPos
取位置 + GetDoubleClickTime/GetSystemMetrics(SM_CXDOUBLECLK) 判双击，
命中某个 overlay 的图标格子就打开对应项。全程不装钩子、不抢输入。

打开方式（实测取舍）：
    ShellExecuteExW + SEE_MASK_INVOKEIDLIST + lpIDList 在本机返回
    ERROR_CANCELLED(1223)，不可用。改用
    SHGetNameFromIDList(SIGDN_DESKTOPABSOLUTEPARSING) 把 PIDL 转成
    "::{GUID}"（虚拟项，如此电脑/回收站）或 "D:\\path"（文件系统项），
    再 ShellExecuteW("open", name) —— 两种都实测能解析出正确字符串，
    且 ShellExecuteW 本身已实测可用。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from . import shell_icons
from .logutil import get_logger

log = get_logger()

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)

VK_LBUTTON = 0x01
SM_CXDOUBLECLK = 36
SM_CYDOUBLECLK = 37
SW_SHOWNORMAL = 1
COINIT_APARTMENTTHREADED = 0x2
SIGDN_DESKTOPABSOLUTEPARSING = 0x80028000

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetDoubleClickTime.argtypes = []
user32.GetDoubleClickTime.restype = wintypes.UINT
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

shell32.SHGetNameFromIDList.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
shell32.SHGetNameFromIDList.restype = ctypes.c_long
shell32.ILCombine.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
shell32.ILCombine.restype = ctypes.c_void_p
shell32.ShellExecuteW.argtypes = [
    wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.LPCWSTR, ctypes.c_int]
shell32.ShellExecuteW.restype = ctypes.c_void_p
ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]


def pidl_to_name(absolute_pidl):
    """绝对 PIDL → "::{GUID}" 或 "D:\\path"；失败返回 None。"""
    if not absolute_pidl:
        return None
    out = ctypes.c_void_p()
    hr = shell32.SHGetNameFromIDList(
        ctypes.c_void_p(absolute_pidl), SIGDN_DESKTOPABSOLUTEPARSING,
        ctypes.byref(out))
    if hr < 0 or not out.value:
        return None
    try:
        return ctypes.wstring_at(out)
    finally:
        ole32.CoTaskMemFree(out)


def open_name(name) -> bool:
    """按解析名打开（虚拟项与文件系统项通用）。"""
    if not name:
        return False
    try:
        ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    except Exception:
        pass
    # ShellExecuteW 返回值 > 32 才算成功
    ret = shell32.ShellExecuteW(None, "open", name, None, None, SW_SHOWNORMAL)
    ok = int(ret or 0) > 32
    if not ok:
        log.warning("[open] ShellExecuteW 失败 ret=%s err=%r",
                    ret, ctypes.get_last_error())
    return ok


def open_pidl(absolute_pidl) -> bool:
    return open_name(pidl_to_name(absolute_pidl))


def _desktop_pidl_map():
    """{显示名: 解析后的字符串}；PIDL 只在函数内短暂存在并全部释放。"""
    items = []
    desk = None
    try:
        shell_icons._ensure_com()
        desk = shell_icons._desktop_abs_pidl()
        items = shell_icons.enum_desktop_items()
        out = {}
        for name, rel in items:
            absolute = shell32.ILCombine(ctypes.c_void_p(desk),
                                         ctypes.c_void_p(rel))
            try:
                if absolute and name not in out:
                    resolved = pidl_to_name(absolute)
                    if resolved:
                        out[name] = resolved
            finally:
                if absolute:
                    ole32.CoTaskMemFree(ctypes.c_void_p(absolute))
        return out
    except Exception as exc:
        log.warning("[open] 枚举桌面项失败: %r", exc)
        return {}
    finally:
        for _name, rel in items:
            ole32.CoTaskMemFree(ctypes.c_void_p(rel))
        if desk:
            ole32.CoTaskMemFree(ctypes.c_void_p(desk))


class DoubleClickWatcher(object):
    """只读轮询双击。hit_test(x, y) -> 显示名 或 None。"""

    PIDL_REFRESH_S = 5.0

    def __init__(self, hit_test):
        self._hit_test = hit_test
        self._down = False
        self._last_t = 0.0
        self._last_pos = (0, 0)
        self._name_cache = {}      # 显示名 -> 解析名
        self._pidl_cache = {}
        self._stamp = 0.0
        self.enabled = True
        self.opened = []           # 测试/日志用：已打开的项名

    # ---- 解析名缓存（桌面增删项时按 5 秒节奏刷新）----

    def _resolve(self, name, now):
        # hit_test 返回的是唯一 key（重名项为 name#2），解析前先还原显示名
        display = name
        if "#" in name:
            head, _sep, tail = name.rpartition("#")
            if head and tail.isdigit():
                display = head
        if now - self._stamp > self.PIDL_REFRESH_S:
            self._pidl_cache = _desktop_pidl_map()
            self._name_cache = {}
            self._stamp = now
        if display in self._name_cache:
            return self._name_cache[display]
        pidl = self._pidl_cache.get(display)
        if pidl is None:
            # UIA 名与 Shell 名可能差扩展名，做一次宽松匹配；重名不猜
            stem = display.rsplit(".", 1)[0]
            matches = [(key, value) for key, value in self._pidl_cache.items()
                       if key.rsplit(".", 1)[0] == stem]
            if len(matches) == 1:
                pidl = matches[0][1]
        if pidl is None:
            return None
        resolved = pidl
        if resolved:
            self._name_cache[display] = resolved
        return resolved

    def poll(self, now):
        """每帧调用。返回被双击打开的项名（没发生则 None）。"""
        if not self.enabled:
            return None
        down = bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        if not down:
            self._down = False
            return None
        if self._down:            # 按住不放，不算新的一次点击
            return None
        self._down = True

        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return None
        x, y = int(point.x), int(point.y)

        interval = user32.GetDoubleClickTime() / 1000.0
        slack_x = max(2, user32.GetSystemMetrics(SM_CXDOUBLECLK) // 2)
        slack_y = max(2, user32.GetSystemMetrics(SM_CYDOUBLECLK) // 2)
        last_x, last_y = self._last_pos
        is_double = (now - self._last_t <= interval
                     and abs(x - last_x) <= slack_x
                     and abs(y - last_y) <= slack_y)
        self._last_t = now
        self._last_pos = (x, y)
        if not is_double:
            return None

        name = self._hit_test(x, y)
        if not name:
            return None
        self._last_t = 0.0        # 防止三击重复触发
        resolved = self._resolve(name, now)
        if resolved is None:
            log.info("[open] 找不到桌面项: %s", name)
            return None
        if open_name(resolved):
            log.info("[open] 双击打开: %s -> %s", name, resolved)
            self.opened.append(name)
            return name
        return None
