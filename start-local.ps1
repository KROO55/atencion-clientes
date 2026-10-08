$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Instala Python 3.11 o superior y vuelve a ejecutar.' }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Instala Node.js 22.12 o superior y vuelve a ejecutar.' }

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno Python.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r backend/requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Falló la instalación del backend.' }
Push-Location -LiteralPath (Join-Path $projectRoot 'frontend')
try {
    & npm.cmd install
    if ($LASTEXITCODE -ne 0) { throw 'Falló la instalación del frontend.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Falló la compilación del frontend.' }
} finally { Pop-Location }

$keyPath = Join-Path $projectRoot '.operator-key'
if (-not (Test-Path -LiteralPath $keyPath)) {
    $keyBytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($keyBytes) } finally { $rng.Dispose() }
    [Convert]::ToBase64String($keyBytes) | Set-Content -LiteralPath $keyPath -NoNewline
}
$keyValue = (Get-Content -LiteralPath $keyPath -Raw).Trim()
if ($keyValue.Length -lt 16) { throw 'La clave de operador debe tener al menos 16 caracteres.' }
$env:OPERATOR_KEY = $keyValue

# Static helper scripts avoid interpolating paths or secrets into shell code.
Start-Process powershell.exe -WorkingDirectory $projectRoot -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', '.\scripts\run-backend.ps1'
Start-Process powershell.exe -WorkingDirectory $projectRoot -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', '.\scripts\run-frontend.ps1'

Write-Host 'Frontend: http://localhost:4200'
Write-Host 'API: http://127.0.0.1:8000/api/health'
Write-Host 'La clave de operador está en .operator-key. Usa Get-Content .operator-key para consultarla.'
Write-Host 'Espera a que ambas terminales indiquen que están listas.'
