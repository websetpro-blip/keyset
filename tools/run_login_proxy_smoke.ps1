# UTF-8 encoding. Runner for login proxy dry-run.
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location "$scriptRoot\.."

Write-Host "== KeySet Login Proxy SMOKE ==" -ForegroundColor Cyan

$python = "${env:LOCALAPPDATA}\Programs\Python\Python311\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

& $python -X utf8 -u tools\login_proxy_smoke.py @args

Write-Host ""
Write-Host "Откройте logs\login_proxy_smoke.log для подробностей." -ForegroundColor Green
