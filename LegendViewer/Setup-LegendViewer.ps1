param(
    [string]$Python = "py"
)

$ErrorActionPreference = "Stop"
$ViewerRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ViewerRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    & $Python -3 -m venv (Join-Path $ViewerRoot ".venv")
}

& $VenvPython -m pip install -e $ViewerRoot
Write-Host "セットアップが完了しました。Start-LegendViewer.cmd から起動できます。"
