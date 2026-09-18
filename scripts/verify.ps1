#Requires -Version 7.0
<#
.SYNOPSIS
    ReturnOps Mini 的本机确定性验证。

.DESCRIPTION
    跑与 .github/workflows/ci.yml 相同的确定性门禁，让改动在推到 GitHub 之前就能被证伪。
    每一步单独记录结果，任何一步失败都会在结尾汇总并以非零退出码结束。

    需要真实 PostgreSQL 的 integration 门禁默认不跑：设置 RETURNOPS_TEST_DATABASE_URL 后加 -Integration。
    依赖漏洞扫描默认不跑（要联网查漏洞库）：加 -Security。

.EXAMPLE
    pwsh -File .\scripts\verify.ps1

.EXAMPLE
    pwsh -File .\scripts\verify.ps1 -Integration -Security
#>
[CmdletBinding()]
param(
    [string]$Python = (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'),
    [switch]$Integration,
    [switch]$Security
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$failures = [System.Collections.Generic.List[string]]::new()

function Invoke-Gate {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Python @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-Host "FAILED $Name (exit $exitCode)" -ForegroundColor Red
        $failures.Add("$Name (exit $exitCode)")
    }
    return $exitCode
}

Push-Location $repositoryRoot
try {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "找不到 $Python。先执行：uv venv --python 3.12 .venv; uv pip install -e '.[dev]'"
    }

    Invoke-Gate -Name 'lint (ruff check)' -Arguments @('-m', 'ruff', 'check', '.') | Out-Null
    Invoke-Gate -Name 'format (ruff format --check)' -Arguments @('-m', 'ruff', 'format', '--check', '.') | Out-Null
    Invoke-Gate -Name 'typecheck (mypy)' -Arguments @('-m', 'mypy') | Out-Null

    if ($Integration) {
        if (-not $env:RETURNOPS_TEST_DATABASE_URL) {
            throw '-Integration 需要先设置 RETURNOPS_TEST_DATABASE_URL'
        }
        Invoke-Gate -Name 'integration (pytest -m integration)' -Arguments @('-m', 'pytest', '-q', '-m', 'integration') | Out-Null
    }
    else {
        Invoke-Gate -Name 'unit and API tests (pytest -m "not integration")' -Arguments @('-m', 'pytest', '-q', '-m', 'not integration') | Out-Null
    }

    if ($Security) {
        Invoke-Gate -Name 'dependencies (pip-audit)' -Arguments @('-m', 'pip_audit', '--skip-editable', '--progress-spinner', 'off') | Out-Null
    }
}
finally {
    Pop-Location
}

if ($failures.Count -gt 0) {
    Write-Host ''
    Write-Host ("verification failed: " + ($failures -join '; ')) -ForegroundColor Red
    exit 1
}

Write-Host 'verification passed' -ForegroundColor Green
exit 0

