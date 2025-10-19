@echo off
setlocal
cd /d "%~dp0\.."
powershell -ExecutionPolicy Bypass -File tools\run_smoke.ps1 %*
endlocal
