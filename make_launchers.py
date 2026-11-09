# -*- coding: utf-8 -*-
"""生成启动脚本（GBK+CRLF 的 .bat 与纯 ASCII 的 .vbs）。在项目根运行一次。

为什么要生成而不是手写：cmd 按 GBK 解析批处理，文件如果是 UTF-8，中文行会
被当成命令执行（早期真踩过）。所以这里统一用 GBK+CRLF 写盘。

解释器选择顺序（本机实测 `where python` 只有 Microsoft Store 的存根，
直接调用返回 9009，所以必须优先用项目内的 .venv）：
    1. .venv\\Scripts\\python.exe      项目自带依赖（推荐）
    2. py -3                          官方启动器
    3. python                         兜底
找不到就明确报错并 pause，不静默失败。
"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))

# 探测解释器：优先项目 venv，其次 py -3，最后 PATH 里的 python
PY_PROBE = [
    'set "PY="',
    'set "PYARGS="',
    'if exist ".venv\\Scripts\\python.exe" (',
    '    set "PY=.venv\\Scripts\\python.exe"',
    '    goto :have_py',
    ')',
    'py -3 -c "import sys" >nul 2>nul && (',
    '    set "PY=py"',
    '    set "PYARGS=-3"',
    '    goto :have_py',
    ')',
    'where python >nul 2>nul && (',
    '    set "PY=python"',
    '    goto :have_py',
    ')',
    'echo [ERROR] no Python found.',
    'echo         run: uv venv --python 3.11 .venv',
    'echo              uv pip install --python .venv\\Scripts\\python.exe -r requirements.txt',
    'pause',
    'exit /b 1',
    ':have_py',
]


def _bat(comment, body_lines):
    lines = [
        "@echo off",
        "rem JellyIcons %s (GBK+CRLF)" % comment,
        "setlocal",
        'cd /d "%~dp0"',
    ]
    lines += PY_PROBE
    lines += body_lines
    lines += ["endlocal"]
    return ("\r\n".join(lines) + "\r\n").encode("gbk")


run_bat = [
    "echo [JellyIcons] running...",
    "echo [JellyIcons] hotkeys: Ctrl+Alt+F9 quit / Ctrl+Alt+arrow switch mode",
    "echo [JellyIcons] log file: JellyIcons.log",
    "%PY% %PYARGS% -X utf8 run.py %*",
    "if errorlevel 1 pause",
]

diag_bat = [
    "%PY% %PYARGS% -X utf8 run.py --diagnose 8",
    "pause",
]

panel_bat = [
    "start \"JellyIcons\" %PY% %PYARGS% -X utf8 run.py %*",
]

for name, comment, body in (
    ("启动.bat", "launcher", run_bat),
    ("诊断.bat", "diagnose", diag_bat),
    ("启动（无窗口）.bat", "launcher detached", panel_bat),
):
    with open(os.path.join(BASE, name), "wb") as f:
        f.write(_bat(comment, body))

vbs_lines = [
    'Set fso = CreateObject("Scripting.FileSystemObject")',
    'Set sh = CreateObject("WScript.Shell")',
    "base = fso.GetParentFolderName(WScript.ScriptFullName)",
    'py = base & "\\.venv\\Scripts\\python.exe"',
    'If Not fso.FileExists(py) Then py = "python"',
    'sh.CurrentDirectory = base',
    'sh.Run """" & py & """ -X utf8 """ & base & "\\run.py""", 0, False',
]
with open(os.path.join(BASE, "静默启动.vbs"), "w", encoding="ascii",
          newline="") as f:
    f.write("\r\n".join(vbs_lines) + "\r\n")

print("scripts written to", BASE)
