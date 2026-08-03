@echo off
setlocal
cd /d "%~dp0"

if exist "LegendViewer.exe" (
  start "" "LegendViewer.exe"
  exit /b 0
)

if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m legend_viewer
  exit /b 0
)

echo LegendViewer.exe または .venv が見つかりません。
echo README.md のセットアップ手順を確認してください。
pause
exit /b 1
