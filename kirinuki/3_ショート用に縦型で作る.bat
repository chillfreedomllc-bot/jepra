@echo off
rem ==============================================================
rem  Drag a video file onto this .bat to cut the top 5 moments
rem  as 9:16 vertical clips for Shorts, at 1.25x speed.
rem  The game screen is never
rem  cropped; the background is a blurred fill.
rem  Voice pitch is preserved (atempo, not resampling).
rem
rem  Keep this file ASCII-only, and avoid parenthesised if-blocks.
rem  See 1_*.bat for why.
rem ==============================================================
chcp 65001 >nul
setlocal

if "%~1"=="" goto :noarg

set "PYTHONPATH=%~dp0"
set "PYTHONIOENCODING=utf-8"

echo.
echo ============ kirinuki : vertical cut ============
echo.

python --version
if errorlevel 1 goto :nopython

echo.
echo Preparing (first run only)...
python -m pip install --quiet --disable-pip-version-check numpy imageio-ffmpeg

echo.
python -m kirinuki cut "%~1" --top 5 --vertical --speed 1.25
if errorlevel 1 goto :failed

echo.
echo Done. The folder is shown above.
goto :end

:noarg
echo.
echo   Drag a video file onto this .bat file.
goto :end

:nopython
echo.
echo   Python was not found.
echo   Install Python 3 from the Microsoft Store, then try again.
goto :end

:failed
echo.
echo   Something went wrong. Copy the messages above and send them.
goto :end

:end
echo.
pause
