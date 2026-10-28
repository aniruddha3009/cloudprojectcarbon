<# Runs backend tests, frontend type-check and production build. #>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location "$root\backend"; .\.venv\Scripts\python -m pytest -q; $py = $LASTEXITCODE; Pop-Location
Push-Location "$root\frontend"; npm run build; $fe = $LASTEXITCODE; Pop-Location
if ($py -ne 0 -or $fe -ne 0) { Write-Error "Checks failed (pytest=$py, frontend=$fe)"; exit 1 }
Write-Host "All checks passed."
