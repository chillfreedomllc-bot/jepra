@echo off
rem ==============================================================
rem  Cuts the top 10 moments into mp4 files.
rem
rem  Two ways to use it:
rem    1. Drag a video onto this .bat file's ICON in Explorer.
rem    2. Double-click it, then drop the video INTO the window
rem       and press Enter.
rem
rem  Way 2 exists because dropping a file into a window that is
rem  sitting at `pause` just satisfies the pause and closes it.
rem  People reasonably read "drag onto this .bat" as "drag into
rem  this window", so the prompt has to accept that too.
rem
rem  Keep this file ASCII-only: cmd.exe on a Japanese Windows
rem  reads .bat files in CP932, so UTF-8 Japanese inside the file
rem  gets mangled and the script dies silently.
rem  Also avoid parenthesised if-blocks: paths like "folder (1)"
rem  break cmd's parser inside them. Use goto instead.
rem ==============================================================
chcp 65001 >nul
setlocal

set "VIDEO=%~1"
if not "%VIDEO%"=="" goto :run

echo.
echo   Drop the video file into this window, then press Enter.
echo   (Or close this and drag the video onto the .bat icon.)
echo.
set /p "VIDEO=Video file: "
set VIDEO=%VIDEO:"=%
if "%VIDEO%"=="" goto :noarg

:run
if not exist "%VIDEO%" goto :notfound

set "PYTHONPATH=%~dp0"
set "PYTHONIOENCODING=utf-8"

echo.
echo ================ kirinuki : cut =================
echo.

python --version
if errorlevel 1 goto :nopython

echo.
echo Preparing (first run only)...
python -m pip install --quiet --disable-pip-version-check numpy imageio-ffmpeg

echo.
python -m kirinuki cut "%VIDEO%" --top 10
if errorlevel 1 goto :failed

echo.
echo Done. The output folder is shown above.
goto :end

:noarg
echo.
echo   No file given. Nothing to do.
goto :end

:notfound
echo.
echo   File not found: %VIDEO%
echo   Copy the path with Shift + right-click on the video.
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
