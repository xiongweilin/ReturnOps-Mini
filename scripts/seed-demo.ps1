#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $repositoryRoot
try {
    $seedOutput = & docker compose exec -T api python -m returnops.seed
    if ($LASTEXITCODE -ne 0) {
        throw "Demo seed failed with exit code $LASTEXITCODE"
    }

    $organizationLine = $seedOutput | Where-Object { $_ -match '^organization_id=[0-9a-fA-F-]{36}$' } | Select-Object -First 1
    if (-not $organizationLine) {
        throw 'Demo seed did not return a valid local organization ID.'
    }

    $localDirectory = Join-Path $repositoryRoot '.local'
    if (-not (Test-Path -LiteralPath $localDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $localDirectory | Out-Null
    }
    $organizationId = $organizationLine -replace '^organization_id=', ''
    [System.IO.File]::WriteAllText(
        (Join-Path $localDirectory 'organization-id.txt'),
        "$organizationId`n",
        [System.Text.UTF8Encoding]::new($false)
    )
    Write-Host 'Repeatable demo data is ready; the local organization reference was saved under .local.'
}
finally {
    Pop-Location
}
