@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 SC_CGF_Converter.py
    goto :eof
)
where python >nul 2>nul
if %errorlevel%==0 (
    python SC_CGF_Converter.py
    goto :eof
)
echo.
echo Python 3 was not found.
echo Install Python 3 or add it to PATH, then run this file again.
echo.
pause
