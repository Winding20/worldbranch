@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo.
echo   WorldBranch - 唐史推演器
echo   ----------------------------------------
echo.

where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo   [错误] 没找到 Python。
    echo.
    echo   请先安装 Python 3.10 或更高版本：
    echo     https://www.python.org/downloads/
    echo   安装时请勾选 "Add Python to PATH"。
    echo.
    pause
    exit /b 1
  )
  py -3 tools\bootstrap.py %*
) else (
  python tools\bootstrap.py %*
)

if errorlevel 1 (
  echo.
  echo   启动失败，请把上面的信息截图反馈。
  pause
)
endlocal