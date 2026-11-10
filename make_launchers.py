# -*- coding: utf-8 -*-
"""生成启动脚本（GBK+CRLF 的 .bat 与纯 ASCII 的 .vbs）。在项目根运行一次。

## 为什么不能直接用 `.venv\\Scripts\\python.exe`

`.venv` 建在项目目录里。如果项目目录继承了 Windows 的
`Mandatory Label\\Low`（沙箱/受限工作区常见），这个标签会被 `(I)`
继承给 `.venv\\Scripts\\python.exe`。Windows 启动带 Low 标签的可执行
文件时，会把进程强制降到 Low 完整性。

低完整性进程读不到 explorer（Medium）拥有的桌面图标——UI Automation
会"看得见列表、看不见子项"，表现就是启动后毫无效果。

所以启动脚本优先使用 venv 配置里 `home` 指向的 **base python**
（装在用户 AppData 下，不带 Low 标签），再用 `PYTHONPATH` 指到 venv 的
site-packages。这样既是 Medium 完整性，又用得上 venv 里装的依赖。
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))

# 生成器本身也判断一次，方便在生成时给出提示
def _read_home():
    cfg = os.path.join(BASE, ".venv", "pyvenv.cfg")
    if not os.path.exists(cfg):
        return None
    for line in open(cfg, "r", encoding="utf-8", errors="replace"):
        key, _sep, val = line.partition("=")
        if key.strip().lower() == "home":
            return val.strip()
    return None


def _bat(purpose, args, pause_tail=True, hidden=False):
    """拼一个 GBK 启动脚本。

    解释器选择顺序：
      1) venv 的 base python（Medium 完整性，能读 UIA）——用 PYTHONPATH 接 venv 依赖
      2) py -3（Python Launcher）
      3) PATH 里的 python
    """
    lines = [
        "@echo off",
        "rem JellyIcons %s (GBK+CRLF)" % purpose,
        "setlocal enabledelayedexpansion",
        'cd /d "%~dp0"',
        "set \"PY=\"",
        "set \"PYARGS=\"",
        "set \"PP=%CD%\\.venv\\Lib\\site-packages\"",
        "",
        "rem ---- 1) venv 的 base python：不带 Low 完整性标签 ----",
        'if exist ".venv\\pyvenv.cfg" (',
        '    for /f "usebackq tokens=1,* delims==" %%a in (".venv\\pyvenv.cfg") do (',
        '        if /i "%%a"=="home " set "HOME_DIR=%%b"',
        '        if /i "%%a"=="home" set "HOME_DIR=%%b"',
        "    )",
        '    if defined HOME_DIR set "HOME_DIR=!HOME_DIR:~1!"',
        '    if defined HOME_DIR if exist "!HOME_DIR!\\python.exe" set "PY=!HOME_DIR!\\python.exe"',
        ")",
        "",
        "rem ---- 2) Python Launcher ----",
        'if not defined PY where py >nul 2>nul && ( set "PY=py" & set "PYARGS=-3" )',
        "rem ---- 3) PATH 里的 python ----",
        'if not defined PY where python >nul 2>nul && set "PY=python"',
        "",
        "if not defined PY (",
        "    echo [ERROR] 没找到可用的 Python 解释器。",
        "    echo         请先在本目录执行: uv venv --python 3.11 .venv",
        "    echo                            uv pip install -r requirements.txt",
        "    pause",
        "    exit /b 1",
        ")",
        "",
        "rem venv 的 base python 需要手动接上 site-packages",
        'if /i not "%PY%"=="python" if /i not "%PY%"=="py" set "PYTHONPATH=%PP%"',
    ]
    if not hidden:
        lines += [
            "echo [JellyIcons] 启动中……关闭窗口或按 Ctrl+C 停止",
            "echo [JellyIcons] 日志：JellyIcons.log",
        ]
    lines.append('"%PY%" %PYARGS% -X utf8 run.py ' + args)
    if pause_tail:
        lines += ["if errorlevel 1 pause"]
    lines.append("endlocal")
    return lines


def _write_bat(name, lines):
    path = os.path.join(BASE, name)
    with open(path, "wb") as f:
        f.write(("\r\n".join(lines) + "\r\n").encode("gbk"))
    return path


def _vbs():
    """无窗口启动：优先用 venv 的 base python。"""
    lines = [
        'Set fso = CreateObject("Scripting.FileSystemObject")',
        'Set sh = CreateObject("WScript.Shell")',
        "base = fso.GetParentFolderName(WScript.ScriptFullName)",
        'cfg = base & "\\.venv\\pyvenv.cfg"',
        "py = \"\"",
        "If fso.FileExists(cfg) Then",
        '    Set f = fso.OpenTextFile(cfg, 1)',
        "    Do Until f.AtEndOfStream",
        "        line = f.ReadLine",
        '        If LCase(Left(line, 5)) = "home " Then',
        '            home = Trim(Mid(line, InStr(line, "=") + 1))',
        '            If fso.FileExists(home & "\\python.exe") Then py = home & "\\python.exe"',
        "        End If",
        "    Loop",
        "    f.Close",
        "End If",
        'If py = "" Then py = "python"',
        'sh.Environment("PROCESS")("PYTHONPATH") = base & "\\.venv\\Lib\\site-packages"',
        'sh.CurrentDirectory = base',
        'sh.Run """" & py & """ -X utf8 """ & base & "\\run.py""", 0, False',
    ]
    path = os.path.join(BASE, "静默启动.vbs")
    with open(path, "w", encoding="ascii", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return path


def main():
    home = _read_home()
    made = [
        _write_bat("启动.bat", _bat("launcher", "%*")),
        _write_bat("诊断.bat", _bat("diagnose", "--diagnose 8")),
        _write_bat("启动（无窗口）.bat", _bat("silent", "%*", pause_tail=False,
                                             hidden=True)),
        _vbs(),
    ]
    for p in made:
        print("written:", os.path.basename(p))
    if home and os.path.exists(os.path.join(home, "python.exe")):
        print("base python（Medium 完整性）:", os.path.join(home, "python.exe"))
    else:
        print("[WARN] 没能从 .venv\\pyvenv.cfg 找到 base python，"
              "启动脚本会退回 py/python；若项目目录带 Low 完整性标签，"
              "程序会读不到桌面图标。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
