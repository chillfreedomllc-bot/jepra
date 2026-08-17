@echo off
rem ==============================================================
rem  Drag a video file onto this .bat to list the loud moments.
rem
rem  IMPORTANT: keep this file ASCII-only. cmd.exe on a Japanese
rem  Windows reads .bat files in CP932, so UTF-8 Japanese text
rem  inside the file gets mangled and the script dies silently.
rem  Japanese belongs in the filename and in the Python output,
rem  never in here.
rem
rem  Also: no parenthesised if-blocks. Paths like "folder (1)"
rem  break cmd's parser inside them. Use goto instead.
rem ==============================================================
chcp 65001 >nul
setlocal

if "%~1"=="" goto :noarg

set "PYTHONPATH=%~dp0"
set "PYTHONIOENCODING=utf-8"

echo.
echo ================ kirinuki : scan ================
echo.

python --version
if errorlevel 1 goto :nopython

echo.
echo Preparing (first run only)...
python -m pip install --quiet --disable-pip-version-check numpy imageio-ffmpeg

echo.
python -m kirinuki scan "%~1" --csv "%~dpn1_candidates.csv"
if errorlevel 1 goto :failed

echo.
echo CSV saved: %~dpn1_candidates.csv
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
