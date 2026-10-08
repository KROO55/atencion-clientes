$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (Test-Path -LiteralPath '.local-services.json') { throw 'Ejecuta .\stop-local.ps1 antes de iniciar otra vez.' }
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

New-Item -ItemType Directory -Path '.logs' -Force | Out-Null
$backendProcess = Start-Process -FilePath (Join-Path $projectRoot '.venv\Scripts\python.exe') -WorkingDirectory $projectRoot -ArgumentList '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000' -WindowStyle Hidden -PassThru -RedirectStandardOutput '.logs/backend.log' -RedirectStandardError '.logs/backend-error.log'
try {
    $frontendRoot = Join-Path $projectRoot 'frontend'
    $frontendProcess = Start-Process -FilePath (Get-Command node.exe).Source -WorkingDirectory $frontendRoot -ArgumentList 'node_modules/@angular/cli/bin/ng.js', 'serve', '--host', '127.0.0.1', '--proxy-config', 'proxy.conf.json' -WindowStyle Hidden -PassThru -RedirectStandardOutput '.logs/frontend.log' -RedirectStandardError '.logs/frontend-error.log'
} catch {
    Stop-Process -Id $backendProcess.Id -ErrorAction SilentlyContinue
    throw
}
@(
    @{ Id = $backendProcess.Id; Started = $backendProcess.StartTime.ToUniversalTime().Ticks; Name = 'python' },
    @{ Id = $frontendProcess.Id; Started = $frontendProcess.StartTime.ToUniversalTime().Ticks; Name = 'node' }
) | ConvertTo-Json | Set-Content -LiteralPath '.local-services.json'
Write-Host 'Frontend: http://localhost:4200'
Write-Host 'API: http://127.0.0.1:8000/api/health'
Write-Host 'La clave de operador está en .operator-key. Usa Get-Content .operator-key para consultarla.'
Write-Host 'Servicios iniciados en segundo plano. Consulta .logs para confirmar que estén listos.'
Write-Host 'Para detenerlos: .\stop-local.ps1'
