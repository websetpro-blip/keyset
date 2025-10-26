:: UTF-8 encoding. Login proxy dry-run entry point.
@echo off
setlocal
cd /d "%~dp0\.."
powershell -ExecutionPolicy Bypass -File tools\run_login_proxy_smoke.ps1 %*
endlocal
