#Requires -Version 7.0
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$localDirectory = Join-Path $repositoryRoot '.local'
$credentialsPath = Join-Path $localDirectory 'n8n-demo-credentials.json'
$intakeCredentialsPath = Join-Path $localDirectory 'n8n-intake-credentials.json'
$organizationIdPath = Join-Path $localDirectory 'organization-id.txt'
$automationTokenPath = Join-Path $localDirectory 'automation-token.txt'
$frontendDirectory = Join-Path $repositoryRoot 'frontend'

foreach ($commandName in @('node', 'npm')) {
    if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
        throw "First-run n8n provisioning requires Node.js/npm on PATH; install Node.js 24 or later and rerun scripts/start-demo.ps1."
    }
}

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
    Write-Host 'Created ignored n8n owner credentials in .local; values were not displayed.'
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
    Write-Host 'Created ignored local webhook credentials in .local; values were not displayed.'
}
else {
    Write-Host 'Using the existing ignored webhook credentials without displaying values.'
}

if (-not (Test-Path -LiteralPath $organizationIdPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $automationTokenPath -PathType Leaf)) {
    & (Join-Path $PSScriptRoot 'seed-demo.ps1')
    if ($LASTEXITCODE -ne 0) {
        throw "Demo seed failed while preparing n8n credentials (exit $LASTEXITCODE)."
    }
}

if ([string]::IsNullOrWhiteSpace($env:N8N_BASE_URL)) {
    $port = $env:N8N_PORT
    if ([string]::IsNullOrWhiteSpace($port)) {
        $envFile = Join-Path $repositoryRoot '.env'
        $portLine = Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^N8N_PORT=([0-9]+)$' } | Select-Object -First 1
        $port = if ($portLine -match '^N8N_PORT=([0-9]+)$') { $Matches[1] } else { '5678' }
    }
    $env:N8N_BASE_URL = "http://127.0.0.1:$port"
}

$n8nUri = [Uri]::new($env:N8N_BASE_URL)
if ($n8nUri.Host -notin @('127.0.0.1', 'localhost', '::1')) {
    throw 'The local n8n bootstrap is restricted to a loopback URL.'
}

$n8nReady = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri "$($env:N8N_BASE_URL.TrimEnd('/'))/" -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $n8nReady = $true
            break
        }
    }
    catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $n8nReady) {
    throw 'n8n did not become ready within 120 seconds; services were left running so bootstrap can be retried.'
}

Push-Location $frontendDirectory
try {
    $nodeVersion = (& node --version | Select-Object -Last 1).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read the Node.js version (exit $LASTEXITCODE)."
    }
    $lockHash = (Get-FileHash -LiteralPath (Join-Path $frontendDirectory 'package-lock.json') -Algorithm SHA256).Hash
    $installStamp = Join-Path $frontendDirectory 'node_modules\.returnflow-install-stamp'
    $expectedStamp = "$nodeVersion`n$lockHash"
    $installedStamp = if (Test-Path -LiteralPath $installStamp -PathType Leaf) {
        [System.IO.File]::ReadAllText($installStamp, [System.Text.Encoding]::UTF8).Trim()
    }
    else {
        ''
    }

    if (-not (Test-Path -LiteralPath (Join-Path $frontendDirectory 'node_modules\@playwright\test') -PathType Container) -or
        $installedStamp -ne $expectedStamp) {
        Write-Host 'Installing the locked local n8n bootstrap dependencies with npm ci.'
        & npm ci
        if ($LASTEXITCODE -ne 0) {
            throw "npm ci failed with exit code $LASTEXITCODE."
        }
        [System.IO.File]::WriteAllText($installStamp, "$expectedStamp`n", [System.Text.UTF8Encoding]::new($false))
    }

    $chromiumExecutable = (& node -e "import('@playwright/test').then(({ chromium }) => console.log(chromium.executablePath()))" | Select-Object -Last 1).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($chromiumExecutable)) {
        throw 'Could not resolve the local Playwright Chromium executable.'
    }
    if (-not (Test-Path -LiteralPath $chromiumExecutable -PathType Leaf)) {
        Write-Host 'Installing the headless Chromium browser required for local n8n owner/API-key setup.'
        & npx playwright install chromium
        if ($LASTEXITCODE -ne 0) {
            throw "Playwright Chromium installation failed with exit code $LASTEXITCODE."
        }
    }

    & node (Join-Path $frontendDirectory 'scripts\bootstrap-n8n-owner.mjs')
    if ($LASTEXITCODE -ne 0) {
        throw "n8n owner setup failed with exit code $LASTEXITCODE."
    }
    & node (Join-Path $frontendDirectory 'scripts\bootstrap-n8n-api-key.mjs')
    if ($LASTEXITCODE -ne 0) {
        throw "n8n local API key setup failed with exit code $LASTEXITCODE."
    }
    & node (Join-Path $frontendDirectory 'scripts\provision-n8n-workflows.mjs')
    if ($LASTEXITCODE -ne 0) {
        throw "n8n credential/workflow provisioning failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

Write-Host 'n8n owner, local credentials, and both published workflows are ready.'
