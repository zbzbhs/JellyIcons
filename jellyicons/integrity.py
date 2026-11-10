# -*- coding: utf-8 -*-
"""进程完整性级别（Integrity Level）检测。

为什么需要它：桌面图标列表由 explorer.exe（Medium 完整性）拥有。
Windows 的 UIPI 不允许低完整性进程读取高完整性进程的 UI Automation 子树，
于是 UI Automation 会"看得见桌面列表、但读不到任何子项"，
表现就是「启动后毫无效果」。

实测：可执行文件如果带 `Mandatory Label\\Low` 标签（例如位于被沙箱标记的
工作区目录里），Windows 启动它时会强制进程降到 Low。把同一个文件复制到
不带标签的目录（如 %LOCALAPPDATA%）后即恢复为父进程的 Medium。
低完整性进程无法自行提权，所以只能在启动前选对解释器。
"""
import ctypes
from ctypes import POINTER, byref
from ctypes import wintypes as W

_k = ctypes.WinDLL("kernel32", use_last_error=True)
_adv = ctypes.WinDLL("advapi32", use_last_error=True)

_k.GetCurrentProcess.restype = W.HANDLE
_k.GetCurrentProcess.argtypes = []
_k.OpenProcess.restype = W.HANDLE
_k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
_k.CloseHandle.restype = W.BOOL
_k.CloseHandle.argtypes = [W.HANDLE]
_adv.OpenProcessToken.restype = W.BOOL
_adv.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, POINTER(W.HANDLE)]
_adv.GetTokenInformation.restype = W.BOOL
_adv.GetTokenInformation.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                     W.DWORD, POINTER(W.DWORD)]
_adv.GetSidSubAuthorityCount.restype = POINTER(ctypes.c_ubyte)
_adv.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
_adv.GetSidSubAuthority.restype = POINTER(W.DWORD)
_adv.GetSidSubAuthority.argtypes = [ctypes.c_void_p, W.DWORD]
_adv.ConvertSidToStringSidW.restype = W.BOOL
_adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                       POINTER(ctypes.c_wchar_p)]

TOKEN_QUERY = 0x0008
TOKEN_ADJUST_DEFAULT = 0x0080
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TokenIntegrityLevel = 25

IL_UNTRUSTED = 0x0000
IL_LOW = 0x1000
IL_MEDIUM = 0x2000
IL_MEDIUM_PLUS = 0x2100
IL_HIGH = 0x3000
IL_SYSTEM = 0x4000

NAMES = {
    IL_UNTRUSTED: "Untrusted",
    IL_LOW: "Low",
    IL_MEDIUM: "Medium",
    IL_MEDIUM_PLUS: "Medium-Plus",
    IL_HIGH: "High",
    IL_SYSTEM: "System",
}


def integrity_of(pid=None):
    """返回 (rid, sid_string)。pid 为 None 表示当前进程。

    失败时返回 (None, 原因字符串)，不抛异常。
    """
    if pid is None:
        h = _k.GetCurrentProcess()
        own = False
        if not h:
            return None, "GetCurrentProcess 失败"
    else:
        h = _k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        own = True
        if not h:
            return None, "OpenProcess(%d) err=%d" % (
                pid, ctypes.get_last_error())
    tok = W.HANDLE()
    try:
        if not _adv.OpenProcessToken(h, TOKEN_QUERY, byref(tok)):
            return None, "OpenProcessToken err=%d" % ctypes.get_last_error()
        need = W.DWORD(0)
        _adv.GetTokenInformation(tok, TokenIntegrityLevel, None, 0,
                                 byref(need))
        size = need.value or 64
        buf = ctypes.create_string_buffer(size)
        if not _adv.GetTokenInformation(tok, TokenIntegrityLevel, buf, size,
                                        byref(need)):
            return None, "GetTokenInformation err=%d" % ctypes.get_last_error()
        sid = ctypes.cast(buf, POINTER(ctypes.c_void_p))[0]
        cnt = _adv.GetSidSubAuthorityCount(sid)[0]
        rid = _adv.GetSidSubAuthority(sid, cnt - 1)[0]
        s = ctypes.c_wchar_p()
        _adv.ConvertSidToStringSidW(sid, byref(s))
        return rid, (s.value or "")
    finally:
        if tok:
            _k.CloseHandle(tok)
        if own:
            _k.CloseHandle(h)


def current_integrity():
    """当前进程的 (rid, 名称)。"""
    rid, sid = integrity_of()
    return rid, NAMES.get(rid, str(sid))


def can_read_desktop():
    """当前完整性是否足以通过 UI Automation 读取桌面图标。

    桌面由 explorer（Medium）拥有，低完整性读不到子项。
    """
    rid, _ = current_integrity()
    return rid is not None and rid >= IL_MEDIUM


def describe():
    rid, name = current_integrity()
    if rid is None:
        return "未知（读取失败）"
    return name
