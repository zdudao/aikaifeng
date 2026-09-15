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
echo  直接回车 = 生成最新一期
echo  要补以前某一天，就输入日期再回车，例如： 2026-09-10
echo.
set "DAYARG="
set /p "DAYARG=请输入后回车："
if defined DAYARG set "DAYARG=%DAYARG: =%"
echo.

rem ---- 找运行环境：uv 的常见位置逐个试，都没有就退回系统 Python ----
set "UVEXE="
if exist "%USERPROFILE%\.local\bin\uv.exe" set "UVEXE=%USERPROFILE%\.local\bin\uv.exe"
if not defined UVEXE if exist "%USERPROFILE%\.cargo\bin\uv.exe" set "UVEXE=%USERPROFILE%\.cargo\bin\uv.exe"
if not defined UVEXE if exist "%LOCALAPPDATA%\Programs\uv\uv.exe" set "UVEXE=%LOCALAPPDATA%\Programs\uv\uv.exe"
if not defined UVEXE if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe" set "UVEXE=%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe"
if not defined UVEXE for /f "delims=" %%i in ('where uv 2^>nul') do set "UVEXE=%%i"
if not defined UVEXE goto :run_py
goto :run_uv

:run_uv
"%UVEXE%" run python scripts\local_build.py %DAYARG%
set "RC=%errorlevel%"
goto :done

:run_py
echo [i] 没找到 uv，改用系统 Python 试一次。
python scripts\local_build.py %DAYARG%
set "RC=%errorlevel%"

:done
echo.
if "%RC%"=="3" (
  echo ================================================
  echo  [注意] 抖音体检发现高危项，建议先别发！
  echo         具体是哪一处，看上面「体检结果」那一段。
  echo         看清楚后，按任意键关闭本窗口。
  echo ================================================
  echo.
  pause >nul
  endlocal
  exit /b 0
)
if not "%RC%"=="0" (
  echo [x] 出错了，把上面的内容截图发出来就行。
  echo.
  pause
  endlocal
  exit /b 1
)

echo [完成] 这个窗口 10 秒后自动关闭。
timeout /t 10 >nul
endlocal
