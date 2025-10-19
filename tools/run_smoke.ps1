# UTF-8 encoding. Smoke runner for proxy test.
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location "$scriptRoot\.."

Write-Host "== KeySet Proxy SMOKE =="

Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

$python = "${env:LOCALAPPDATA}\Programs\Python\Python311\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

& $python -X utf8 -u tools\smoke_proxy_launch.py @args

$logs = Get-ChildItem -Path .\logs\proxy_smoke_*.csv -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
if ($logs -and $logs.Length -gt 0) {
    Start-Process $logs[0].FullName
}
