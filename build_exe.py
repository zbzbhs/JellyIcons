# -*- coding: utf-8 -*-
"""把 JellyIcons 打成单文件 exe（PyInstaller）。

用法：
    .venv\\Scripts\\python.exe make_icon.py      # 先生成图标（改过才需要）
    .venv\\Scripts\\python.exe build_exe.py       # 打包
    .venv\\Scripts\\python.exe build_exe.py --console   # 带控制台的调试版

产物：dist\\JellyIcons.exe —— 复制到任何 Windows 10/11 x64 机器双击即可，
不需要装 Python、不需要 venv、不需要 pip。

几个必须显式处理的东西（少一个就打不开音频或读不到桌面）：
  * `_portaudiowpatch` 是**顶层** .pyd（不是 pyaudiowpatch 包内的 DLL），
    PyInstaller 的依赖分析看不到它 —— 必须 --hidden-import 或
    --collect-all pyaudiowpatch。
  * UIAutomationCore 走 comtypes 动态生成代码，运行时要能在可写目录
    生成 .py —— 已在 `jellyicons/paths.py` 里改到 data_dir()/.cache。
  * `sys.executable` 在 exe 里指向 exe 自己，看门狗改为 `--watchdog`
    自执行（见 `App._start_watchdog`）。
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "JellyIcons"
ICON = os.path.join(ROOT, "assets", "jellyicons.ico")
# 版本资源：填了它 exe 才有"文件说明/产品名/版本"，属性页不再是空白，
# 也是 Windows 判定可信度的一点点加分项（真正消掉 SmartScreen 需要
# 代码签名证书，那是另一回事）。
VERSION_FILE = os.path.join(ROOT, "version_info.txt")

# 明确要收进去的模块
HIDDEN = [
    "_portaudiowpatch",          # pyaudiowpatch 的 C 扩展（顶层）
    "pyaudiowpatch",
    "comtypes",
    "comtypes.client",
    "comtypes.stream",
    "comtypes.gen",
    "numpy",
    "PIL._tkinter_finder",
    "tkinter",
    "tkinter.ttk",
    "tkinter.font",
    "jellyicons.watchdog",       # exe --watchdog 自执行要用
]

# 明显用不到的大件，剔掉能省体积。
# 注意：标准库不能剔 —— comtypes 生成 UIAutomation 类型代码时会走
# importlib.metadata，而它会 import email；剔掉 email 就会在运行时炸
# ModuleNotFoundError。所以这里只排第三方大包。
EXCLUDE = [
    "matplotlib", "scipy", "pandas", "IPython", "notebook", "pytest",
    "lib2to3",
]


def _data_arg(src: str, dest: str) -> str:
    return "%s%s%s" % (src, os.pathsep, dest)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    console = "--console" in argv

    if not os.path.exists(ICON):
        print("[build] 缺少图标，先跑 make_icon.py")
        return 1

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",
        "--console" if console else "--windowed",
        "--name", NAME + ("-console" if console else ""),
        "--icon", ICON,
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build"),
        # 源码里用 `from diagnose import run_diagnose`（项目根在 sys.path 上）
        "--paths", ROOT,
        "--add-data", _data_arg(os.path.join(ROOT, "assets"), "assets"),
        "--add-data", _data_arg(os.path.join(ROOT, "README.md"), "."),
    ]
    for mod in HIDDEN:
        cmd += ["--hidden-import", mod]
    for mod in EXCLUDE:
        cmd += ["--exclude-module", mod]
    if os.path.exists(VERSION_FILE):
        cmd += ["--version-file", VERSION_FILE]
    cmd.append(os.path.join(ROOT, "run.py"))

    print("[build] %s" % " ".join(cmd))
    res = subprocess.run(cmd, cwd=ROOT)
    if res.returncode != 0:
        print("[build] PyInstaller 失败，退出码 %d" % res.returncode)
        return res.returncode

    exe = os.path.join(ROOT, "dist", NAME + ("-console" if console else "") + ".exe")
    if not os.path.exists(exe):
        print("[build] 没找到产物 %s" % exe)
        return 1
    size = os.path.getsize(exe) / (1024 * 1024)
    print("[build] OK %s (%.1f MB)" % (exe, size))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
