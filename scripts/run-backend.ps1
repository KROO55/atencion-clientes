$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if (-not $env:OPERATOR_KEY) {
    $env:OPERATOR_KEY = (Get-Content -LiteralPath '.operator-key' -Raw).Trim()
}
& '.\.venv\Scripts\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
