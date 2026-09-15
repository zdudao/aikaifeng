@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

echo.
echo ================================================
echo   老许聊实体 · 生成今日抖音图文 / 公众号文章
echo ================================================
echo.

set "UVEXE="
if exist "%USERPROFILE%\.local\bin\uv.exe" set "UVEXE=%USERPROFILE%\.local\bin\uv.exe"
if defined UVEXE goto :found
for /f "delims=" %%i in ('where uv 2^>nul') do set "UVEXE=%%i"
:found

if not defined UVEXE (
  echo [x] 没找到运行环境，请把这行发给老许处理：uv not found
  echo.
  pause
  exit /b 1
)

"%UVEXE%" run python scripts\local_build.py
if errorlevel 1 (
  echo.
  echo [x] 出错了，把上面的内容截图发出来就行。
  echo.
  pause
  exit /b 1
)

echo.
echo [完成] 这个窗口 10 秒后自动关闭。
timeout /t 10 >nul
endlocal
