#Requires -Version 7.0
[CmdletBinding()]
param(
    [ValidatePattern('^DEMO-ORDER-UNKNOWN-[0-9]{3}$')]
    [string]$OrderRef = 'DEMO-ORDER-UNKNOWN-001'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $repositoryRoot
$workerStopped = $false
$runExitCode = 1
try {
    & docker compose stop worker
    if ($LASTEXITCODE -ne 0) {
        throw "Could not pause the ReturnFlow worker (exit $LASTEXITCODE)."
    }
    $workerStopped = $true

    & docker compose run --rm --no-deps worker python -m returnops.demo_scenarios --order-ref $OrderRef
    $runExitCode = $LASTEXITCODE
}
finally {
    if ($workerStopped) {
        & docker compose start worker
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "The ReturnFlow worker did not restart cleanly (exit $LASTEXITCODE)."
        }
    }
    Pop-Location
}

if ($runExitCode -ne 0) {
    throw "Unknown-result scenario failed with exit code $runExitCode"
}
