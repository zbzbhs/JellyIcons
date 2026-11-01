# -*- coding: utf-8 -*-
"""用 Shell API 取桌面项的 256px 图标位图（带真实 alpha）。

已实测：SHGetDesktopFolder + EnumObjects 能拿到 52 个桌面项 PIDL；
SHCreateItemFromIDList(IID_IShellItemImageFactory) + GetImage(SIIGBF_BIGGERSIZEOK)
能拿到干净的 256x256 RGBA。
"""
import ctypes
from ctypes import POINTER, byref, c_void_p, c_int, c_uint, c_long, c_ubyte, c_uint32

from PIL import Image, ImageDraw, ImageFont

u = ctypes.windll.user32
sh = ctypes.windll.shell32
ole = ctypes.windll.ole32
shlw = ctypes.windll.shlwapi
gdi = ctypes.windll.gdi32


class GUID(ctypes.Structure):
    _fields_ = [("D1", c_uint), ("D2", ctypes.c_ushort), ("D3", ctypes.c_ushort),
                ("D4", c_ubyte * 8)]


class STRRET(ctypes.Structure):
    _fields_ = [("uType", c_uint), ("pOleStr", c_void_p), ("uOffset", c_uint),
                ("cStr", ctypes.c_char * 260)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", c_long), ("cy", c_long)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", c_uint), ("biWidth", c_long), ("biHeight", c_long),
                ("biPlanes", ctypes.c_ushort), ("biBitCount", ctypes.c_ushort),
                ("biCompression", c_uint), ("biSizeImage", c_uint),
                ("biXPelsPerMeter", c_long), ("biYPelsPerMeter", c_long),
                ("biClrUsed", c_uint), ("biClrImportant", c_uint)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", c_uint * 3)]


IID_IShellItemImageFactory = GUID(
    0xBCC18B79, 0xBA16, 0x442F, (c_ubyte * 8)(0x80, 0xC4, 0x8A, 0x59, 0xC3, 0x0C, 0x46, 0x3B))

SIIGBF_RESIZETOFIT = 0x00
SIIGBF_BIGGERSIZEOK = 0x01
SIIGBF_ICONONLY = 0x04
SIIGBF_THUMBNAILONLY = 0x08
SIIGBF_ICONBACKGROUND = 0x80

CSIDL_DESKTOP = 0
SHCONTF_FOLDERS = 0x20
SHCONTF_NONFOLDERS = 0x40
SHGDN_INFOLDER = 0x1

_CoInit = False


def _ensure_com():
    global _CoInit
    if not _CoInit:
        ole.CoInitialize(None)
        _CoInit = True


def _vcall(ptr, idx, restype, argtypes, *args):
    vt = ctypes.cast(ptr, POINTER(c_void_p))[0]
    fnaddr = ctypes.cast(vt, POINTER(c_void_p))[idx]
    proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    return proto(fnaddr)(ptr, *args)


def _free_pidl(pidl):
    if pidl:
        ole.CoTaskMemFree(c_void_p(pidl))


def _release_com(ptr):
    if ptr:
        _vcall(ptr, 2, c_uint32, [])


def enum_desktop_items():
    """返回 [(display_name, absolute_pidl_ptr)]。

    PIDL 是 COM 分配的所有权资源，不再遗留到进程退出。调用方对每个
    返回的指针负责 CoTaskMemFree；遍历失败也会释放枚举器和已返回项。
    """
    _ensure_com()
    p_desk = c_void_p()
    hr = sh.SHGetDesktopFolder(byref(p_desk))
    if hr != 0:
        raise OSError("SHGetDesktopFolder 0x%08X" % (hr & 0xFFFFFFFF))
    p_enum = c_void_p()
    out = []
    try:
        hr = _vcall(p_desk, 4, c_long, [c_void_p, c_uint, POINTER(c_void_p)],
                    None, SHCONTF_FOLDERS | SHCONTF_NONFOLDERS, byref(p_enum))
        if hr != 0:
            raise OSError("EnumObjects 0x%08X" % (hr & 0xFFFFFFFF))
        try:
            while True:
                rg = c_void_p()
                fetched = c_uint()
                hr = _vcall(p_enum, 3, c_long,
                            [c_uint, POINTER(c_void_p), POINTER(c_uint)],
                            1, byref(rg), byref(fetched))
                if hr != 0 or not fetched.value or not rg.value:
                    break
                sr = STRRET()
                name = ""
                try:
                    if _vcall(p_desk, 11, c_long,
                              [c_void_p, c_uint, POINTER(STRRET)],
                              c_void_p(rg.value), SHGDN_INFOLDER,
                              byref(sr)) == 0:
                        b = ctypes.create_unicode_buffer(512)
                        shlw.StrRetToBufW(byref(sr), c_void_p(rg.value), b, 512)
                        name = b.value
                finally:
                    if sr.uType == 0 and sr.pOleStr:
                        ole.CoTaskMemFree(sr.pOleStr)
                out.append((name, rg.value))
        finally:
            _release_com(p_enum)
    except Exception:
        for _name, ptr in out:
            ole.CoTaskMemFree(c_void_p(ptr))
        raise
    finally:
        _release_com(p_desk)
    return out


def _desktop_abs_pidl():
    p = c_void_p()
    hr = sh.SHGetSpecialFolderLocation(None, CSIDL_DESKTOP, byref(p))
    if hr != 0:
        raise OSError("SHGetSpecialFolderLocation 0x%08X" % (hr & 0xFFFFFFFF))
    return p.value


def _hbitmap_to_image(hbm, size):
    # 显式声明类型，避免句柄被当 32 位 int（icon_capture 会改 gdi.* 的 argtypes）
    gdi.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                              ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.c_uint]
    gdi.GetDIBits.restype = ctypes.c_int
    gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.SelectObject.restype = ctypes.c_void_p
    gdi.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi.DeleteObject.restype = ctypes.c_int
    gdi.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi.DeleteDC.restype = ctypes.c_int

    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = size
    bi.bmiHeader.biHeight = -size
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0

    buf = ctypes.create_string_buffer(size * size * 4)
    hdc = gdi.CreateCompatibleDC(None)
    old = gdi.SelectObject(hdc, hbm)
    got = gdi.GetDIBits(hdc, hbm, 0, size, buf, byref(bi), 0)
    gdi.SelectObject(hdc, old)
    gdi.DeleteDC(hdc)
    gdi.DeleteObject(hbm)
    if not got:
        return None
    return Image.frombuffer("RGBA", (size, size), buf, "raw", "BGRA", 0, 1).copy()


def get_icon_image(abs_pidl, size=256, flags=None):
    """取绝对 PIDL 的图标位图（RGBA）。失败返回 None。"""
    _ensure_com()
    if flags is None:
        flags = SIIGBF_BIGGERSIZEOK | SIIGBF_ICONONLY
    psi = c_void_p()
    hr = sh.SHCreateItemFromIDList(c_void_p(abs_pidl), byref(IID_IShellItemImageFactory),
                                   byref(psi))
    if hr != 0 or not psi.value:
        return None
    hbm = c_void_p()
    hr = _vcall(psi, 3, c_long, [SIZE, c_int, POINTER(c_void_p)],
                SIZE(size, size), flags, byref(hbm))
    _vcall(psi, 2, c_uint32, [])  # Release
    if hr != 0 or not hbm.value:
        return None
    return _hbitmap_to_image(hbm, size)


def build_icon_cache(size=256):
    """{显示名: RGBA Image}，同名项以 name#1/name#2 保留各自位图。"""
    _ensure_com()
    desk = _desktop_abs_pidl()
    sh.ILCombine.argtypes = [c_void_p, c_void_p]
    sh.ILCombine.restype = c_void_p
    cache = {}
    try:
        for name, rel in enum_desktop_items():
            ab = None
            try:
                ab = sh.ILCombine(c_void_p(desk), c_void_p(rel))
                if not ab:
                    continue
                img = get_icon_image(ab, size)
                if img is not None:
                    key = name
                    n = 1
                    while key in cache:
                        key = "%s#%d" % (name, n)
                        n += 1
                    cache[key] = img
            finally:
                if ab:
                    ole.CoTaskMemFree(c_void_p(ab))
                ole.CoTaskMemFree(c_void_p(rel))
    finally:
        ole.CoTaskMemFree(c_void_p(desk))
    return cache


# ---------------------------------------------------------------- 文字渲染

def load_font(px):
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhl.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, px)
        except Exception:
            continue
    return ImageFont.load_default()


class _LOGFONTW(ctypes.Structure):
    _fields_ = [
        ("lfHeight", ctypes.c_long),
        ("lfWidth", ctypes.c_long),
        ("lfEscapement", ctypes.c_long),
        ("lfOrientation", ctypes.c_long),
        ("lfWeight", ctypes.c_long),
        ("lfItalic", ctypes.c_byte),
        ("lfUnderline", ctypes.c_byte),
        ("lfStrikeOut", ctypes.c_byte),
        ("lfCharSet", ctypes.c_byte),
        ("lfOutPrecision", ctypes.c_byte),
        ("lfClipPrecision", ctypes.c_byte),
        ("lfQuality", ctypes.c_byte),
        ("lfPitchAndFamily", ctypes.c_byte),
        ("lfFaceName", ctypes.c_wchar * 32),
    ]


SPI_GETICONTITLELOGFONT = 0x001F


def system_icon_font(fallback_px=15):
    """读系统"图标标题字体"（SystemParametersInfoW SPI_GETICONTITLELOGFONT）。

    这样我们画的文字和 explorer 画的桌面标签同字体同字号，
    切换瞬间不会有"字变了"的观感差异。返回 (font, px)。
    失败时退回 load_font(fallback_px)，返回 (font, fallback_px)。
    """
    try:
        lf = _LOGFONTW()
        user32 = ctypes.windll.user32
        user32.SystemParametersInfoW.argtypes = [
            ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        user32.SystemParametersInfoW.restype = ctypes.c_int
        ok = user32.SystemParametersInfoW(
            SPI_GETICONTITLELOGFONT, ctypes.sizeof(lf),
            ctypes.byref(lf), 0)
        if ok:
            face = (lf.lfFaceName or "").strip()
            # lfHeight 为负 = 字符高度（不含内部行距），取绝对值
            px = abs(int(lf.lfHeight)) or fallback_px
            px = max(9, min(48, px))
            if face:
                for path in (r"C:\\Windows\\Fonts\\msyh.ttc",
                             r"C:\\Windows\\Fonts\\msyhl.ttc",
                             r"C:\\Windows\\Fonts\\simhei.ttf"):
                    try:
                        font = ImageFont.truetype(path, px)
                        # 用系统给的族名优先；PIL 不认族名时上面的文件仍可用
                        try:
                            named = ImageFont.truetype(face, px)
                            if named is not None:
                                font = named
                        except Exception:
                            pass
                        return font, px
                    except Exception:
                        continue
    except Exception:
        pass
    return load_font(fallback_px), fallback_px


def wrap_label(text, font, max_width, max_lines=2):
    """按像素宽度折行，最多 max_lines 行，超出加省略号。"""
    if not text:
        return []
    lines = []
    cur = ""
    for ch_ in text:
        trial = cur + ch_
        if font.getlength(trial) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = ch_
            if len(lines) >= max_lines:
                break
    if len(lines) < max_lines and cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    # 省略号处理
    if lines:
        joined = "".join(lines)
        if len(joined) < len(text):
            last = lines[-1]
            while last and font.getlength(last + "…") > max_width:
                last = last[:-1]
            lines[-1] = last + "…"
    return lines


def render_label(text, font, max_width, max_lines=2, color=(255, 255, 255)):
    """把文字渲染成带黑描边的 RGBA 图（桌面图标那种白字黑边）。

    宽度按实际最长行自适应，不是固定 max_width —— 真图标的文字框就是紧贴文字的
    （回收站 58px、Microsoft Edge 86px），固定宽度会让高亮框和文字错位。
    """
    lines = wrap_label(text, font, max_width, max_lines)
    if not lines:
        return None
    line_h = int(font.size * 1.28) + 2
    # 按实际最长行决定宽度
    text_w = int(max(font.getlength(l) for l in lines)) if lines else 0
    width = max(1, text_w) + 8
    height = line_h * len(lines) + 8
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        wpx = font.getlength(line)
        x = (width - wpx) / 2.0
        y = 4 + i * line_h
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0, 210))
        draw.text((x, y), line, font=font, fill=color + (255,))
    return img
