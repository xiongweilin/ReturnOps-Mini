#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $repositoryRoot
try {
    & docker compose stop
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose stop failed with exit code $LASTEXITCODE"
    }
    Write-Host 'ReturnFlow services stopped. Project data volumes were preserved.'
}
finally {
    Pop-Location
}
