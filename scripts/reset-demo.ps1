#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$expectedPhrase = 'RESET-RETURNFLOW'
Write-Warning 'This removes only the returnflow-demo Compose containers and volumes (PostgreSQL, payment, n8n, and Mailpit), plus its local automation token and organization reference.'
$confirmation = Read-Host "Type $expectedPhrase to continue"
if ($confirmation -cne $expectedPhrase) {
    Write-Host 'Reset cancelled.'
    exit 1
}

Push-Location $repositoryRoot
try {
    & docker compose -p returnflow-demo down --volumes --remove-orphans
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose down failed with exit code $LASTEXITCODE"
    }

    $automationTokenPath = Join-Path $repositoryRoot '.local\automation-token.txt'
    if (Test-Path -LiteralPath $automationTokenPath -PathType Leaf) {
        Remove-Item -LiteralPath $automationTokenPath -Force
    }
    $organizationIdPath = Join-Path $repositoryRoot '.local\organization-id.txt'
    if (Test-Path -LiteralPath $organizationIdPath -PathType Leaf) {
        Remove-Item -LiteralPath $organizationIdPath -Force
    }
    Write-Host 'ReturnFlow demo data was reset. Run start-demo.ps1 to initialize business data and n8n workflows again.'
}
finally {
    Pop-Location
}
