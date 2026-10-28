@echo off
rem WorldBranch launcher. Keep this file ASCII-only and CRLF:
rem cmd.exe misparses UTF-8 text and LF-only line endings.
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if not errorlevel 1 (
  python tools\bootstrap.py %*
  goto done
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3 tools\bootstrap.py %*
  goto done
)

echo.
echo   Python not found.
echo   Install Python 3.10+ from https://www.python.org/downloads/
echo   and tick "Add Python to PATH", then run this file again.
echo.
pause
exit /b 1

:done
if errorlevel 1 (
  echo.
  echo   Startup failed. Please send the message above.
  pause
)
endlocal
