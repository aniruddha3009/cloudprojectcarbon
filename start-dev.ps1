<#
  Carbon Debt Computing — Windows development launcher.
  Usage:  powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
  Installs dependencies on first run, then opens the backend and frontend in two windows.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Require($cmd, $hint) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd not found. $hint" }
}
Require python "Install Python 3.11+ from python.org and tick 'Add to PATH'."
Require npm "Install Node.js 20 LTS or newer from nodejs.org."

foreach ($port in 8000, 5173) {
  if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    Write-Warning "Port $port is already in use. Close the other program (or an earlier run of this script) first."
  }
}

if (-not (Test-Path "backend\.venv")) {
  Write-Host "Creating Python virtual environment…"
  python -m venv backend\.venv
  backend\.venv\Scripts\python -m pip install --upgrade pip
  backend\.venv\Scripts\pip install -r backend\requirements.txt
}
if (-not (Test-Path "frontend\node_modules")) {
  Write-Host "Installing frontend packages…"
  Push-Location frontend; npm install --no-audit --no-fund; Pop-Location
}
if (-not (Test-Path ".env") -and (Test-Path ".env.example")) { Copy-Item .env.example .env }

Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; .\.venv\Scripts\python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\frontend'; npm run dev"
Start-Sleep -Seconds 6
Start-Process "http://127.0.0.1:5173"
Write-Host ""
Write-Host "Frontend: http://127.0.0.1:5173"
Write-Host "Backend:  http://127.0.0.1:8000  (API docs at /docs)"
Write-Host "Close the two PowerShell windows to stop."
