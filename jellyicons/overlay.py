"""Application-owned, layered, click-through overlay windows.

Only windows created by this module are positioned, shown or destroyed.
No shell window handles are accepted or modified.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PIL import Image

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
ULW_ALPHA = 2
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1
SW_SHOWNOACTIVATE = 4
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
SWP_NOSENDCHANGING = 0x0400

HWND = wintypes.HWND
LPVOID = ctypes.c_void_p
LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, wintypes.UINT, WPARAM, LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


def _types() -> None:
    user32.DefWindowProcW.argtypes = [HWND, wintypes.UINT, WPARAM, LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        HWND, wintypes.HMENU, wintypes.HINSTANCE, LPVOID]
    user32.CreateWindowExW.restype = HWND
    user32.UpdateLayeredWindow.argtypes = [HWND, wintypes.HDC, ctypes.POINTER(POINT),
        ctypes.POINTER(SIZE), wintypes.HDC, ctypes.POINTER(POINT), wintypes.COLORREF,
        ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
    user32.UpdateLayeredWindow.restype = wintypes.BOOL
    user32.GetDC.argtypes = [HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [HWND, wintypes.HDC]
    user32.DestroyWindow.argtypes = [HWND]
    user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
    user32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.GetWindowLongW.argtypes = [HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO),
        wintypes.UINT, ctypes.POINTER(LPVOID), wintypes.HANDLE, wintypes.DWORD]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE


_types()
_DefWindowProc = user32.DefWindowProcW


@WNDPROC
def _window_proc(hwnd, message, wparam, lparam):
    if message == WM_NCHITTEST:
        return HTTRANSPARENT
    return _DefWindowProc(hwnd, message, wparam, lparam)


_window_class_registered = False


def _register_class() -> None:
    global _window_class_registered
    if _window_class_registered:
        return
    instance = kernel32.GetModuleHandleW(None)
    window_class = WNDCLASSW()
    window_class.lpfnWndProc = _window_proc
    window_class.hInstance = instance
    window_class.lpszClassName = "JellyIconsOverlay"
    if not user32.RegisterClassW(ctypes.byref(window_class)):
        error = ctypes.get_last_error()
        if error != 1410:  # class already exists
            raise ctypes.WinError(error)
    _window_class_registered = True


class OverlayWindow:
    """A non-activating top-level window that never consumes mouse input."""

    def __init__(self) -> None:
        _register_class()
        self.hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT,
            "JellyIconsOverlay", "", WS_POPUP, 0, 0, 1, 1,
            None, None, kernel32.GetModuleHandleW(None), None,
        )
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self._screen_dc = user32.GetDC(None)
        self._memory_dc = gdi32.CreateCompatibleDC(self._screen_dc)
        self._bitmap = None
        self._old_bitmap = None
        self._pixels = None
        self._buffer_size = (0, 0)
        self._closed = False

    def _ensure_buffer(self, width: int, height: int) -> None:
        if self._buffer_size == (width, height):
            return
        if self._bitmap:
            if self._old_bitmap:
                gdi32.SelectObject(self._memory_dc, self._old_bitmap)
            gdi32.DeleteObject(self._bitmap)
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        pixels = LPVOID()
        self._bitmap = gdi32.CreateDIBSection(
            self._memory_dc, ctypes.byref(info), 0, ctypes.byref(pixels), None, 0)
        if not self._bitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        self._old_bitmap = gdi32.SelectObject(self._memory_dc, self._bitmap)
        self._pixels = pixels
        self._buffer_size = (width, height)

    def draw(self, image: Image.Image, x: int, y: int) -> None:
        """Draw an RGBA image at physical screen coordinates."""
        if self._closed:
            return
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        width, height = image.size
        self._ensure_buffer(width, height)
        # UpdateLayeredWindow requires premultiplied alpha.
        pixels = image.tobytes("raw", "BGRA")
        ctypes.memmove(self._pixels, pixels, len(pixels))
        destination = POINT(int(x), int(y))
        size = SIZE(width, height)
        source = POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        if not user32.UpdateLayeredWindow(
                self.hwnd, self._screen_dc, ctypes.byref(destination), ctypes.byref(size),
                self._memory_dc, ctypes.byref(source), 0, ctypes.byref(blend), ULW_ALPHA):
            raise ctypes.WinError(ctypes.get_last_error())
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)

    def move(self, x: int, y: int) -> None:
        user32.SetWindowPos(self.hwnd, None, int(x), int(y), 0, 0,
                            SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_NOSENDCHANGING)

    def hide(self) -> None:
        """隐藏本窗口本身（不是销毁）。用于"非音乐模式时不挡任何东西"。"""
        if self._closed or not self.hwnd:
            return
        user32.ShowWindow(self.hwnd, 0)   # SW_HIDE

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._bitmap:
            if self._old_bitmap:
                gdi32.SelectObject(self._memory_dc, self._old_bitmap)
            gdi32.DeleteObject(self._bitmap)
            self._bitmap = None
        if self._memory_dc:
            gdi32.DeleteDC(self._memory_dc)
            self._memory_dc = None
        if self._screen_dc:
            user32.ReleaseDC(None, self._screen_dc)
            self._screen_dc = None
        user32.DestroyWindow(self.hwnd)
        self.hwnd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
