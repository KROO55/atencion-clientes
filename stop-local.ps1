$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.local-services.json')) {
    Write-Host 'No hay servicios registrados.'
    exit
}
$records = Get-Content -LiteralPath '.local-services.json' -Raw | ConvertFrom-Json
foreach ($record in $records) {
    $serviceProcess = Get-Process -Id $record.Id -ErrorAction SilentlyContinue
    if ($serviceProcess -and $serviceProcess.ProcessName -eq $record.Name -and
        $serviceProcess.StartTime.ToUniversalTime().Ticks -eq $record.Started) {
        Stop-Process -Id $serviceProcess.Id
    }
}
Remove-Item -LiteralPath '.local-services.json'
Write-Host 'Servicios detenidos.'
