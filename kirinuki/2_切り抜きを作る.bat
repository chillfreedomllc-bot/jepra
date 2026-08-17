@echo off
rem ---------------------------------------------------------------
rem  動画ファイルをこの .bat にドラッグ＆ドロップすると、
rem  上位10箇所を mp4 として切り出します。
rem  出力先は、元の動画と同じフォルダの kirinuki_out です。
rem ---------------------------------------------------------------
chcp 65001 > nul
setlocal

if "%~1"=="" (
    echo.
    echo   Drag a video file onto this .bat file.
    echo.
    pause
    exit /b 1
)

set "PYTHONPATH=%~dp0"

python -m pip install --quiet --disable-pip-version-check numpy imageio-ffmpeg

python -m kirinuki cut "%~1" --top 10 --out "%~dp1kirinuki_out"

echo.
echo   Output: %~dp1kirinuki_out
echo.
pause
