# -*- coding: utf-8 -*-
"""PIDL / Shell 资源释放回归：反复枚举不能持续涨内存。

之前 enum_desktop_items 返回的 PIDL 从不释放，每 5 秒一次的双击目标
刷新 + 每次图标重载都在漏；这里用进程私有内存增长做粗粒度回归。
"""
import ctypes
import sys
import unittest
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jellyicons import shell_icons  # noqa: E402
from jellyicons import click_open  # noqa: E402

_psapi = ctypes.WinDLL("psapi", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _private_bytes():
    _psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_PROCESS_MEMORY_COUNTERS),
        wintypes.DWORD]
    _psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    counters = _PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    if not _psapi.GetProcessMemoryInfo(_kernel32.GetCurrentProcess(),
                                       ctypes.byref(counters),
                                       counters.cb):
        raise OSError("GetProcessMemoryInfo 失败")
    return counters.PagefileUsage


class PidlReleaseTests(unittest.TestCase):
    def test_enum_releases_pidls(self):
        """反复枚举 40 次，内存增长必须远小于"每次泄漏 36 个 PIDL"。"""
        shell_icons.enum_desktop_items()      # 预热 COM / 缓存
        base = _private_bytes()
        for _ in range(40):
            items = shell_icons.enum_desktop_items()
            self.assertGreater(len(items), 0)
            # 调用方负责释放 —— 这里模拟 build_icon_cache 的做法
            for _name, rel in items:
                ctypes.windll.ole32.CoTaskMemFree(ctypes.c_void_p(rel))
        grown = _private_bytes() - base
        self.assertLess(grown, 4 * 1024 * 1024,
                        "枚举 PIDL 疑似泄漏：增长 %d 字节" % grown)

    def test_pidl_map_releases(self):
        click_open._desktop_pidl_map()        # 预热
        base = _private_bytes()
        for _ in range(20):
            mapping = click_open._desktop_pidl_map()
            self.assertTrue(mapping)
        grown = _private_bytes() - base
        self.assertLess(grown, 4 * 1024 * 1024,
                        "双击目标映射疑似泄漏：增长 %d 字节" % grown)

    def test_pidl_map_returns_strings(self):
        """缓存里必须是解析后的字符串，不能留着 PIDL 指针。"""
        mapping = click_open._desktop_pidl_map()
        self.assertTrue(mapping)
        for key, value in mapping.items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(value, str)
            self.assertTrue(value)

    def test_key_suffix_restored(self):
        """重名 key（name#1）解析时必须还原成显示名再查表。"""
        watcher = click_open.DoubleClickWatcher(lambda x, y: None)
        watcher._stamp = 1e18                 # 别真去枚举
        watcher._pidl_cache = {"记事本": "C:\\Windows\\notepad.exe"}
        self.assertEqual(watcher._resolve("记事本#1", 0.0),
                         "C:\\Windows\\notepad.exe")

    def test_ambiguous_stem_not_guessed(self):
        """去扩展名后有多个候选时不能瞎猜，宁可打不开。"""
        watcher = click_open.DoubleClickWatcher(lambda x, y: None)
        watcher._stamp = 1e18
        watcher._pidl_cache = {"a.txt": "X", "a.md": "Y"}
        self.assertIsNone(watcher._resolve("a", 0.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
