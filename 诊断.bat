@echo off
rem JellyIcons diagnose (GBK+CRLF)
setlocal
cd /d "%~dp0"
set PY=
where python >nul 2>nul && set PY=python
if not defined PY (
    echo [ERROR] python not found in PATH
    pause
    exit /b 1
)
%PY% -X utf8 run.py --diagnose 8
pause
endlocal
