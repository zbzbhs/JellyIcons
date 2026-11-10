@echo off
rem JellyIcons launcher (GBK+CRLF)
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "PY="
set "PYARGS="
set "PP=%CD%\.venv\Lib\site-packages"

rem ---- 1) venv 的 base python：不带 Low 完整性标签 ----
if exist ".venv\pyvenv.cfg" (
    for /f "usebackq tokens=1,* delims==" %%a in (".venv\pyvenv.cfg") do (
        if /i "%%a"=="home " set "HOME_DIR=%%b"
        if /i "%%a"=="home" set "HOME_DIR=%%b"
    )
    if defined HOME_DIR set "HOME_DIR=!HOME_DIR:~1!"
    if defined HOME_DIR if exist "!HOME_DIR!\python.exe" set "PY=!HOME_DIR!\python.exe"
)

rem ---- 2) Python Launcher ----
if not defined PY where py >nul 2>nul && ( set "PY=py" & set "PYARGS=-3" )
rem ---- 3) PATH 里的 python ----
if not defined PY where python >nul 2>nul && set "PY=python"

if not defined PY (
    echo [ERROR] 没找到可用的 Python 解释器。
    echo         请先在本目录执行: uv venv --python 3.11 .venv
    echo                            uv pip install -r requirements.txt
    pause
    exit /b 1
)

rem venv 的 base python 需要手动接上 site-packages
if /i not "%PY%"=="python" if /i not "%PY%"=="py" set "PYTHONPATH=%PP%"
echo [JellyIcons] 启动中……关闭窗口或按 Ctrl+C 停止
echo [JellyIcons] 日志：JellyIcons.log
"%PY%" %PYARGS% -X utf8 run.py %*
if errorlevel 1 pause
endlocal
