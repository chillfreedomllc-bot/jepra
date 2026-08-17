@echo off
rem ==============================================================
rem  Drag a video file onto this .bat to cut the top 10 moments.
rem  Output goes to a kirinuki_out folder next to the video.
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
echo ================ kirinuki : cut ================
echo.

python --version
if errorlevel 1 goto :nopython

echo.
echo Preparing (first run only)...
python -m pip install --quiet --disable-pip-version-check numpy imageio-ffmpeg

echo.
python -m kirinuki cut "%~1" --top 10 --out "%~dp1kirinuki_out"
if errorlevel 1 goto :failed

echo.
echo Output folder: %~dp1kirinuki_out
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
