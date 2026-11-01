"""Process-wide single-instance guard for JellyIcons."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL

DEFAULT_MUTEX_NAME = r"Local\\JellyIcons.SingleInstance"
_ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    """命名互斥体守卫。

    名字可传：单测必须用独立名字，否则会撞上用户正在跑的实例
    （那不是 bug，是互斥体按设计生效）。
    """

    def __init__(self, name: str = DEFAULT_MUTEX_NAME) -> None:
        self._name = name
        self._handle = None

    def acquire(self) -> bool:
        if self._handle:
            return True
        handle = _kernel32.CreateMutexW(None, False, self._name)
        if not handle:
            # 拿不到句柄就别拦着用户启动
            return True
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            _kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = None
