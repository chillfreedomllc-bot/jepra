# kirinuki を最新版に更新する。
#
#   powershell -ExecutionPolicy Bypass -File update.ps1
#
# GitHub から ZIP を取ってきて、このフォルダに上書きする。
# kirinuki.json（保存先の設定）は ZIP に含まれないため消えない。

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # これが無いと Invoke-WebRequest が極端に遅い

$url = 'https://github.com/chillfreedomllc-bot/jepra/archive/refs/heads/claude/claude-api-monetization-4bhzjp.zip'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$zip = Join-Path $env:TEMP 'kirinuki_update.zip'
$tmp = Join-Path $env:TEMP 'kirinuki_update'

Write-Host ''
Write-Host '現在のバージョン:' -NoNewline
& python -m kirinuki --version

Write-Host ''
Write-Host 'ダウンロード中...'
Invoke-WebRequest $url -OutFile $zip

Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive $zip -DestinationPath $tmp

# ZIP の中は「リポジトリ名のフォルダ ＞ kirinuki」の二階層になっている。
$src = Join-Path (Get-ChildItem $tmp -Directory)[0].FullName 'kirinuki'
if (-not (Test-Path $src)) {
    throw "ZIP の中に kirinuki フォルダが見つかりませんでした: $tmp"
}

Write-Host '上書き中...'
Copy-Item (Join-Path $src '*') $here -Recurse -Force

Remove-Item $zip -Force -ErrorAction SilentlyContinue
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ''
Write-Host '更新後のバージョン:' -NoNewline
& python -m kirinuki --version
Write-Host ''
Write-Host '完了しました。保存先の設定はそのまま残っています。'
