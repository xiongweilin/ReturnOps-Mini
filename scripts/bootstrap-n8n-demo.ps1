#Requires -Version 7.0
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$localDirectory = Join-Path $repositoryRoot '.local'
$credentialsPath = Join-Path $localDirectory 'n8n-demo-credentials.json'
$intakeCredentialsPath = Join-Path $localDirectory 'n8n-intake-credentials.json'
$runnerPath = Join-Path $repositoryRoot 'frontend\scripts\bootstrap-n8n-owner.mjs'
$frontendDirectory = Join-Path $repositoryRoot 'frontend'

if (-not (Test-Path -LiteralPath $localDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $localDirectory | Out-Null
}

if (-not (Test-Path -LiteralPath $credentialsPath -PathType Leaf)) {
    $buffer = [byte[]]::new(36)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    $suffix = [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $credential = [ordered]@{
        email     = 'n8n-owner@example.test'
        firstName = 'ReturnFlow'
        lastName  = 'Demo'
        password  = "RF-$suffix-8A!"
    }
    [System.IO.File]::WriteAllText(
        $credentialsPath,
        ($credential | ConvertTo-Json),
        [System.Text.UTF8Encoding]::new($false)
    )
    Write-Host 'Created ignored n8n owner credentials in .local/n8n-demo-credentials.json; values were not displayed.'
}
else {
    Write-Host 'Using the existing ignored n8n owner credentials without displaying values.'
}

if (-not (Test-Path -LiteralPath $intakeCredentialsPath -PathType Leaf)) {
    $buffer = [byte[]]::new(32)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    $suffix = [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $intakeCredential = [ordered]@{
        user     = 'returnflow-demo-intake'
        password = "Intake-$suffix-7Z!"
    }
    [System.IO.File]::WriteAllText(
        $intakeCredentialsPath,
        ($intakeCredential | ConvertTo-Json),
        [System.Text.UTF8Encoding]::new($false)
    )
    Write-Host 'Created ignored local Webhook Basic Auth credentials in .local/n8n-intake-credentials.json; values were not displayed.'
}
else {
    Write-Host 'Using the existing ignored n8n Webhook credentials without displaying values.'
}

Push-Location $frontendDirectory
try {
    & node $runnerPath
    if ($LASTEXITCODE -ne 0) {
        throw "n8n owner setup failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
