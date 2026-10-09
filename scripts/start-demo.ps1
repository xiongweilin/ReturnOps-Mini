#Requires -Version 7.0
[CmdletBinding()]
param([switch]$ValidateOnly)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$envPath = Join-Path $repositoryRoot '.env'
$examplePath = Join-Path $repositoryRoot '.env.example'

function New-LocalSecret {
    param([Parameter(Mandatory)][int]$ByteCount)

    $buffer = [byte[]]::new($ByteCount)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

Push-Location $repositoryRoot
try {
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        $envText = [System.IO.File]::ReadAllText($examplePath, [System.Text.Encoding]::UTF8)
        $envText = [regex]::Replace(
            $envText,
            '(?m)^POSTGRES_PASSWORD=.*$',
            "POSTGRES_PASSWORD=$(New-LocalSecret -ByteCount 32)"
        )
        $envText = [regex]::Replace(
            $envText,
            '(?m)^RETURNOPS_PAYMENT_WEBHOOK_SECRET=.*$',
            "RETURNOPS_PAYMENT_WEBHOOK_SECRET=$(New-LocalSecret -ByteCount 32)"
        )
        $envText = [regex]::Replace(
            $envText,
            '(?m)^N8N_ENCRYPTION_KEY=.*$',
            "N8N_ENCRYPTION_KEY=$(New-LocalSecret -ByteCount 32)"
        )
        [System.IO.File]::WriteAllText(
            $envPath,
            $envText,
            [System.Text.UTF8Encoding]::new($false)
        )
        Write-Host 'Created ignored .env with fresh local demo secrets; values were not displayed.'
    }
    else {
        Write-Host 'Using the existing ignored .env without reading or displaying its values.'
    }

    & docker compose config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose config failed with exit code $LASTEXITCODE"
    }
    Write-Host 'Compose configuration is valid.'

    if ($ValidateOnly) {
        Write-Host 'Validation-only mode; services were not started.'
        return
    }

    & docker compose up --build -d
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up failed with exit code $LASTEXITCODE"
    }

    $apiBinding = (& docker compose port api 8000 | Select-Object -First 1).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($apiBinding)) {
        throw 'Could not determine the local ReturnOps API binding.'
    }
    $apiReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $null = Invoke-RestMethod -Uri "http://$apiBinding/health" -TimeoutSec 2
            $apiReady = $true
            break
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    if (-not $apiReady) {
        throw 'ReturnOps API did not become healthy within 60 seconds.'
    }

    & (Join-Path $PSScriptRoot 'seed-demo.ps1')
    if ($LASTEXITCODE -ne 0) {
        throw "Demo initialization failed with exit code $LASTEXITCODE"
    }

    Write-Host 'ReturnFlow is running. Open the frontend, n8n editor, and Mailpit at the localhost ports configured in .env.'
}
finally {
    Pop-Location
}
