@echo off
rem JellyIcons launcher (GBK+CRLF)
setlocal
cd /d "%~dp0"
set PY=
where python >nul 2>nul && set PY=python
if not defined PY (
    echo [ERROR] python not found in PATH
    pause
    exit /b 1
)
echo [JellyIcons] running... close window or Ctrl+C to stop
echo [JellyIcons] log file: JellyIcons.log
%PY% -X utf8 run.py %*
if errorlevel 1 pause
endlocal
