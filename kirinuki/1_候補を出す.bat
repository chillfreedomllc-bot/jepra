@echo off
rem ---------------------------------------------------------------
rem  動画ファイルをこの .bat にドラッグ＆ドロップすると、
rem  盛り上がり候補の一覧が出ます。ファイルは作りません。
rem
rem  PYTHONPATH を通して直接呼ぶので pip install は不要。
rem  インストール手順とフォルダ移動をまるごと省くためのもの。
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

rem 初回だけ必要なものを入れる。2回目以降はすぐ終わる。
python -m pip install --quiet --disable-pip-version-check numpy imageio-ffmpeg

python -m kirinuki scan "%~1" --csv "%~dpn1_candidates.csv"

echo.
echo   CSV: %~dpn1_candidates.csv
echo.
pause
