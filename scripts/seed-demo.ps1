#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $repositoryRoot
try {
    & docker compose exec -T api python -m returnops.seed
    if ($LASTEXITCODE -ne 0) {
        throw "Demo seed failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
