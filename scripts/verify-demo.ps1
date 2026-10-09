#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $repositoryRoot
try {
    & docker compose config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose config failed with exit code $LASTEXITCODE"
    }

    & docker compose ps
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose ps failed with exit code $LASTEXITCODE"
    }

    $apiBinding = (& docker compose port api 8000 | Select-Object -First 1).Trim()
    $frontendBinding = (& docker compose port frontend 80 | Select-Object -First 1).Trim()
    $n8nBinding = (& docker compose port n8n 5678 | Select-Object -First 1).Trim()
    $mailpitBinding = (& docker compose port mailpit 8025 | Select-Object -First 1).Trim()
    foreach ($binding in @($apiBinding, $frontendBinding, $n8nBinding, $mailpitBinding)) {
        if ([string]::IsNullOrWhiteSpace($binding)) {
            throw 'A required local service port is not published.'
        }
    }

    $apiHealth = Invoke-RestMethod -Uri "http://$apiBinding/health" -TimeoutSec 5
    if ($apiHealth.status -ne 'ok') {
        throw 'ReturnOps health endpoint did not return status=ok.'
    }
    $demoStatus = Invoke-RestMethod -Uri "http://$apiBinding/v1/demo/session" -TimeoutSec 5
    if (-not $demoStatus.enabled) {
        throw 'Demo identity endpoint is not enabled by the current local configuration.'
    }
    $frontendResponse = Invoke-WebRequest -Uri "http://$frontendBinding/" -TimeoutSec 5
    $n8nResponse = Invoke-WebRequest -Uri "http://$n8nBinding/" -TimeoutSec 5
    $mailpitResponse = Invoke-WebRequest -Uri "http://$mailpitBinding/" -TimeoutSec 5

    if ($frontendResponse.StatusCode -ne 200 -or $n8nResponse.StatusCode -ne 200 -or $mailpitResponse.StatusCode -ne 200) {
        throw 'Frontend, n8n, or Mailpit did not return HTTP 200.'
    }

    Write-Host 'ReturnOps API, demo mode, frontend, n8n editor, and Mailpit UI responded successfully.'
}
finally {
    Pop-Location
}
