@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 Tools\SELF_TEST.py & pause & goto :eof)
where python >nul 2>nul
if %errorlevel%==0 (python Tools\SELF_TEST.py & pause & goto :eof)
echo Python 3 not found.
pause
