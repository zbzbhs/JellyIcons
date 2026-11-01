# -*- coding: utf-8 -*-
"""生成启动脚本（GBK+CRLF 的 .bat 与纯 ASCII 的 .vbs）。在项目根运行一次。"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))

bat_lines = [
    "@echo off",
    "rem JellyIcons launcher (GBK+CRLF)",
    "setlocal",
    'cd /d "%~dp0"',
    "set PY=",
    "where python >nul 2>nul && set PY=python",
    "if not defined PY (",
    "    echo [ERROR] python not found in PATH",
    "    pause",
    "    exit /b 1",
    ")",
    "echo [JellyIcons] running... close window or Ctrl+C to stop",
    "echo [JellyIcons] log file: JellyIcons.log",
    "%PY% -X utf8 run.py %*",
    "if errorlevel 1 pause",
    "endlocal",
]

diag_lines = [
    "@echo off",
    "rem JellyIcons diagnose (GBK+CRLF)",
    "setlocal",
    'cd /d "%~dp0"',
    "set PY=",
    "where python >nul 2>nul && set PY=python",
    "if not defined PY (",
    "    echo [ERROR] python not found in PATH",
    "    pause",
    "    exit /b 1",
    ")",
    "%PY% -X utf8 run.py --diagnose 8",
    "pause",
    "endlocal",
]
with open(os.path.join(BASE, "启动.bat"), "wb") as f:
    f.write(("\r\n".join(bat_lines) + "\r\n").encode("gbk"))
with open(os.path.join(BASE, "诊断.bat"), "wb") as f:
    f.write(("\r\n".join(diag_lines) + "\r\n").encode("gbk"))

vbs_lines = [
    'Set fso = CreateObject("Scripting.FileSystemObject")',
    'Set sh = CreateObject("WScript.Shell")',
    "base = fso.GetParentFolderName(WScript.ScriptFullName)",
    'sh.Run "python -X utf8 """ & base & "\\run.py""""", 0, False',
]
with open(os.path.join(BASE, "静默启动.vbs"), "w", encoding="ascii", newline="") as f:
    f.write("\r\n".join(vbs_lines) + "\r\n")

print("scripts written to", BASE)
