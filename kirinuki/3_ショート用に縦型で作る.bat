@echo off
rem ---------------------------------------------------------------
rem  動画ファイルをこの .bat にドラッグ＆ドロップすると、
rem  上位5箇所を 9:16 の縦型（ショート用）で切り出します。
rem  背景はぼかしなので、ゲーム画面は一切切れません。
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

python -m kirinuki cut "%~1" --top 5 --vertical --out "%~dp1kirinuki_shorts"

echo.
echo   Output: %~dp1kirinuki_shorts
echo.
pause
