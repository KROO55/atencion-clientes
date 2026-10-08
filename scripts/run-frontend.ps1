$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend')
& npm.cmd start
