# -*- coding: utf-8 -*-
"""诊断模式：不动任何东西，只逐项报告链路健康状况。

用法：python run.py --diagnose [秒数]
输出到控制台和 JellyIcons.log。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import time

from jellyicons import config, shell_icons
from jellyicons.audio_engine import AudioEngine
from jellyicons.desktop_reader import DesktopReader, IntegrityError
from jellyicons.logutil import get_logger

log = get_logger()


def _integrity_level():
    """本进程完整性级别（Low=0x1000, Medium=0x2000, High=0x3000）。"""
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                             ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE

    TOKEN_QUERY = 0x0008
    TokenIntegrityLevel = 25
    h = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
                                     TOKEN_QUERY, ctypes.byref(h)):
        return "unknown"
    ln = wintypes.DWORD()
    advapi32.GetTokenInformation(h, TokenIntegrityLevel, None, 0,
                                 ctypes.byref(ln))
    buf = ctypes.create_string_buffer(ln.value or 8)
    if not advapi32.GetTokenInformation(h, TokenIntegrityLevel, buf,
                                        ln.value, ctypes.byref(ln)):
        return "unknown"
    # TOKEN_MANDATORY_LABEL { SID_AND_ATTRIBUTES { PSID, attrs } }
    sid = ctypes.cast(ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0],
                      ctypes.c_void_p)
    advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    count = advapi32.GetSidSubAuthorityCount(sid)[0]
    rid = advapi32.GetSidSubAuthority(sid, count - 1)[0]
    names = {0x1000: "Low", 0x2000: "Medium", 0x3000: "High"}
    return names.get(rid, hex(rid))


def _dump_window_chain():
    """Print the Progman/WorkerW → DefView → ListView handle chain."""
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.FindWindowW.restype = ctypes.c_void_p
        u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        u32.FindWindowExW.restype = ctypes.c_void_p
        u32.FindWindowExW.argtypes = [
            wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
        u32.IsWindowVisible.restype = wintypes.BOOL
        u32.IsWindowVisible.argtypes = [wintypes.HWND]
        u32.GetWindowTextLengthW.restype = ctypes.c_int
        u32.GetWindowTextLengthW.argtypes = [wintypes.HWND]

        def tag(h):
            if not h:
                return "NULL"
            vis = "visible" if u32.IsWindowVisible(h) else "hidden"
            return "0x%X(%s)" % (h & 0xFFFFFFFFFFFFFFFF, vis)

        progman = u32.FindWindowW("Progman", None)
        print("    window-chain: Progman=%s" % tag(progman))
        if progman:
            dv = u32.FindWindowExW(progman, 0, "SHELLDLL_DefView", None)
            print("    window-chain:   DefView=%s" % tag(dv))
            if dv:
                lv = u32.FindWindowExW(dv, 0, "SysListView32", None)
                print("    window-chain:     ListView=%s" % tag(lv))
            worker = u32.FindWindowExW(progman, 0, "WorkerW", None)
            while worker:
                print("    window-chain:   WorkerW=%s" % tag(worker))
                dv2 = u32.FindWindowExW(worker, 0, "SHELLDLL_DefView", None)
                if dv2:
                    print("    window-chain:     DefView=%s" % tag(dv2))
                    lv2 = u32.FindWindowExW(dv2, 0, "SysListView32", None)
                    print("    window-chain:       ListView=%s" % tag(lv2))
                worker = u32.FindWindowExW(progman, worker, "WorkerW", None)
    except Exception as exc:
        print("    window-chain dump failed: %r" % exc)


def run_diagnose(duration=None):
    if duration is None:
        duration = 8.0
    print("=" * 56)
    print("JellyIcons 诊断模式")
    print("=" * 56)

    # 1. 完整性
    lvl = _integrity_level()
    ok_uia = lvl in ("Medium", "High")
    print("[1] 进程完整性: %s  %s" % (
        lvl, "(UIA 可用)" if ok_uia else "(低完整性 → UIA 会被 UIPI 拦截！"
        "必须从正常桌面/cmd 启动，不能从沙箱/低完整性宿主启动)"))

    # 2. 音频
    eng = AudioEngine()
    if eng.open():
        levels = []
        t0 = time.time()
        print("[2] 音频 loopback: %s" % eng.device_name)
        print("    （%0.0f 秒内请播放音乐/敲一下桌面测试音）" % duration)
        while time.time() - t0 < duration:
            levels.append(eng.bass_level(config.BASS_BINS))
            time.sleep(0.05)
        peak = max(levels) if levels else 0.0
        print("    bass 峰值=%.3f  %s" % (
            peak, "OK（有信号）" if peak > 0.02 else
            "无信号 —— 检查：音乐在播放吗？输出设备对吗？"))
        eng.close()
    else:
        print("[2] 音频 loopback: 打开失败（无动画驱动，只会静止）")

    # 3. 图标位图
    try:
        cache = shell_icons.build_icon_cache(config.ICON_PIXMAP)
        print("[3] Shell 图标位图: %d 项  %s" % (
            len(cache), "OK" if cache else "失败：一个都没取到"))
    except Exception as exc:
        print("[3] Shell 图标位图: 异常 %r" % exc)
        cache = {}

    # 4. UIA 桌面布局
    snap = []
    try:
        reader = DesktopReader()
        snap = reader.snapshot()
        print("[4] UIA 桌面布局: %d 个图标  %s" % (
            len(snap), "OK" if snap else "空（UIPI 拦截或桌面真空）"))
        for icon in snap[:3]:
            print("    %s @ %s" % (icon.name, icon.rect))
    except IntegrityError as exc:
        print("[4] UIA 桌面布局: IntegrityError —— %s" % exc)
        _dump_window_chain()
    except Exception as exc:
        print("[4] UIA 桌面布局: 异常 %r" % exc)
        _dump_window_chain()

    # 5. 副本覆盖率（决定音乐模式敢不敢隐藏真图标）
    if cache and snap:
        from jellyicons.app import App
        entries = App._dedupe(snap)
        keys = [key for key, _icon in entries]
        missing = [key for key, icon in entries
                   if cache.get(key) is None and cache.get(icon.name) is None]
        covered = len(keys) - len(missing)
        print("[5] 副本覆盖率: %d/%d  %s" % (
            covered, len(keys),
            "OK（可以隐藏真图标）" if not missing
            else "不足 —— 音乐模式不会隐藏真图标（安全优先）"))
        if missing:
            print("    缺位图的桌面项:", missing[:8])
            print("    Shell 名例:", sorted(cache)[:8])
        dupes = [key for key in keys if "#" in key]
        if dupes:
            print("    重名项(已按序号区分):", dupes[:8])
    else:
        print("[5] 副本覆盖率: 跳过（前置项失败）")

    print("=" * 56)
    print("诊断结束。日志: %s" % os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "JellyIcons.log"))
    return 0
