@echo off
rem JellyIcons diagnose (GBK+CRLF)
setlocal
cd /d "%~dp0"
set "PY="
set "PYARGS="
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    goto :have_py
)
py -3 -c "import sys" >nul 2>nul && (
    set "PY=py"
    set "PYARGS=-3"
    goto :have_py
)
where python >nul 2>nul && (
    set "PY=python"
    goto :have_py
)
echo [ERROR] no Python found.
echo         run: uv venv --python 3.11 .venv
echo              uv pip install --python .venv\Scripts\python.exe -r requirements.txt
pause
exit /b 1
:have_py
%PY% %PYARGS% -X utf8 run.py --diagnose 8
pause
endlocal
