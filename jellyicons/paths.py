# -*- coding: utf-8 -*-
"""运行期路径：源码运行与打包成 exe 后必须都能用。

两套路径语义完全不同：

  源码运行            打包成单文件 exe
  ------------------  ------------------------------------------------
  代码目录 = 项目根   代码被解到临时目录 %TEMP%\\_MEIxxxx（只读、退出即删）
  数据可写            数据不能写进 _MEIxxxx

所以：
  - **只读资源**（图标位图、默认配置）走 `resource_dir()`，源码下是项目根，
    exe 下是 `sys._MEIPASS`。
  - **可写数据**（日志、心跳、comtypes 代码缓存）走 `data_dir()`：源码下是
    项目根（保持历史行为，老用户升级无感），exe 下是 exe 所在目录；exe 目录
    不可写（装在 Program Files）时退到 %LOCALAPPDATA%\\JellyIcons。

comtypes 生成的代码缓存必须可写：`comtypes.client` 导入时会 makedirs 一个
gen 目录，指到只读的 _MEIPASS 会直接 ImportError。
"""
from __future__ import annotations

import os
import sys


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包出来的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> str:
    """只读资源目录（exe 内是解包临时目录）。"""
    if is_frozen():
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return base
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _exe_dir() -> str:
    return os.path.dirname(os.path.abspath(sys.executable))


def _writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write-test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.unlink(probe)
        return True
    except Exception:
        return False


_data_dir_cache = None


def data_dir() -> str:
    """可写数据目录（日志、心跳、代码缓存）。"""
    global _data_dir_cache
    if _data_dir_cache:
        return _data_dir_cache
    if not is_frozen():
        _data_dir_cache = resource_dir()
        return _data_dir_cache

    candidates = [
        _exe_dir(),
        os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                     "JellyIcons"),
    ]
    for cand in candidates:
        if _writable(cand):
            _data_dir_cache = cand
            return cand
    _data_dir_cache = os.environ.get("TEMP") or os.getcwd()
    return _data_dir_cache


def data_path(*parts: str) -> str:
    return os.path.join(data_dir(), *parts)


def cache_dir() -> str:
    """comtypes 生成代码的缓存目录（必须可写）。"""
    path = data_path(".cache", "comtypes")
    os.makedirs(path, exist_ok=True)
    return path
