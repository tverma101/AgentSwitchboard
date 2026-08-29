param(
    [string[]] $Only = @(),
    [string[]] $Skip = @(),
    [switch] $Fast,
    [switch] $Integration,
    [switch] $Installers,
    [switch] $Full,
    [switch] $DryRun,
    [switch] $Help,
    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]] $RemainingArgs = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$CheckOrder = @(
    "suppressions",
    "ruff-format",
    "ruff-check",
    "ty",
    "pytest"
)

function Show-Usage {
    @"
Usage: ci.ps1 [options]

Runs the local sequence for the same check IDs enforced by GitHub CI.
Requires uv on PATH when running ruff, ty, or pytest checks.
Local ruff checks repair formatting and autofixable lint before later checks.

Checks (in order):
  suppressions   Ban type ignores and legacy future annotations
  ruff-format    uv run ruff format
  ruff-check     uv run ruff check --fix
  ty             uv run ty check
  pytest         uv run pytest -q --tb=short

Options:
  -Only ID              Run only the given check (repeatable)
  -Skip ID              Skip the given check (repeatable)
  -Fast                 Run the safe deterministic pytest tier (the default).
  -Integration          Include local integration, live, and interactive pytest items.
  -Installers           Run installer/uninstaller pytest items serially; opt-in.
  -Full                 Run deterministic, integration, and installer pytest tiers.
  -DryRun               Print commands without running them.
  -Help                 Show this help text.
"@
}

function Write-Step {
    param([string] $Message)

    Write-Host ""
    Write-Host "==> $Message"
}

function Format-Argument {
    param([string] $Value)

    if ($Value -match '^[A-Za-z0-9_./:@%+=,\[\]-]+$') {
        return $Value
    }

    return "'" + ($Value -replace "'", "''") + "'"
}

function Invoke-CiCommand {
    param(
        [string] $FilePath,
        [string[]] $Arguments = @()
    )

    $parts = @($FilePath) + $Arguments
    $commandText = ($parts | ForEach-Object { Format-Argument ([string] $_) }) -join " "
    Write-Host "+ $commandText"

    if (-not $DryRun) {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed with exit code ${LASTEXITCODE}: $commandText"
        }
    }
}

function Test-ValidCheckId {
    param([string] $CheckId)

    return $CheckOrder -contains $CheckId
}

function Assert-ValidCheckId {
    param([string] $CheckId)

    if (-not (Test-ValidCheckId $CheckId)) {
        throw "unknown check id: $CheckId (expected one of: $($CheckOrder -join ', '))"
    }
}

function Test-ShouldRunCheck {
    param([string] $CheckId)

    if ($Only.Count -gt 0 -and ($Only -notcontains $CheckId)) {
        return $false
    }

    if ($Skip -contains $CheckId) {
        return $false
    }

    return $true
}

function Assert-UvAvailable {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv is required but was not found on PATH. Install uv first (see README or scripts/install.ps1)."
    }
}

function Test-SelectedChecksNeedUv {
    if ($DryRun) {
        return $false
    }

    foreach ($checkId in $CheckOrder) {
        if ((Test-ShouldRunCheck $checkId) -and $checkId -ne "suppressions") {
            return $true
        }
    }

    return $false
}

function Invoke-SuppressionsCheck {
    Write-Step "Ban suppressions and legacy annotations"
    $pattern = '# type: ignore|# ty: ignore|from __future__ import annotations'
    Write-Host "+ Get-ChildItem -Recurse -Filter *.py (excluding .venv, .git) | Select-String '$pattern'"

    if (-not $DryRun) {
        $matches = Get-ChildItem -Path . -Recurse -Filter *.py -File |
            Where-Object {
                $full = $_.FullName
                $full -notmatch '[\\/]\.venv[\\/]' -and
                    $full -notmatch '[\\/]\.git[\\/]'
            } |
            Select-String -Pattern $pattern

        if ($matches) {
            $matches | ForEach-Object { Write-Host $_.Line }
            throw "type: ignore / ty: ignore comments and legacy future annotations are not allowed. Fix the underlying type/import issue instead."
        }
    }
}

function Invoke-RuffFormatCheck {
    Write-Step "ruff format"
    Invoke-CiCommand -FilePath "uv" -Arguments @("run", "ruff", "format")
}

function Invoke-RuffLintCheck {
    Write-Step "ruff check --fix"
    Invoke-CiCommand -FilePath "uv" -Arguments @("run", "ruff", "check", "--fix")
}

function Invoke-TyCheck {
    Write-Step "ty check"
    Invoke-CiCommand -FilePath "uv" -Arguments @("run", "ty", "check")
}

function Invoke-LocalPytest {
    param([string[]] $PytestArguments = @())

    $pytestCommand = @("run", "pytest") + $PytestArguments
    if ((Get-Command taskpolicy -ErrorAction SilentlyContinue) -and
        (Get-Command nice -ErrorAction SilentlyContinue)) {
        Invoke-CiCommand -FilePath "nice" -Arguments (@("-n", "5", "taskpolicy", "-c", "utility", "uv") + $pytestCommand)
    } elseif (Get-Command taskpolicy -ErrorAction SilentlyContinue) {
        Invoke-CiCommand -FilePath "taskpolicy" -Arguments (@("-c", "utility", "uv") + $pytestCommand)
    } elseif (Get-Command nice -ErrorAction SilentlyContinue) {
        Invoke-CiCommand -FilePath "nice" -Arguments (@("-n", "5", "uv") + $pytestCommand)
    } else {
        Invoke-CiCommand -FilePath "uv" -Arguments $pytestCommand
    }
}

function Invoke-PytestCheck {
    Write-Step "pytest"
    if ($Fast -and $Installers) {
        throw "-Fast and -Installers cannot be combined."
    }
    if ($Fast -and $Integration) {
        throw "-Fast and -Integration cannot be combined."
    }
    if ($Full -and ($Fast -or $Integration -or $Installers)) {
        throw "-Full cannot be combined with -Fast, -Integration, or -Installers."
    }

    if ($Full) {
        Invoke-LocalPytest @(
            "-q", "--tb=short", "-n", "0",
            "-m", "not integration and not live and not interactive and not installer"
        )
        Invoke-LocalPytest @(
            "-q", "--tb=short", "-n", "0",
            "-m", "integration or live or interactive"
        )
        Invoke-LocalPytest @(
            "-q", "--tb=short", "-n", "0", "--run-installer-tests",
            "-m", "installer"
        )
    } elseif ($Installers) {
        Invoke-LocalPytest @(
            "-q", "--tb=short", "-n", "0", "--run-installer-tests",
            "-m", "installer"
        )
    } elseif ($Integration) {
        Invoke-LocalPytest @(
            "-q", "--tb=short", "-n", "0",
            "-m", "not integration and not live and not interactive and not installer"
        )
        Invoke-LocalPytest @(
            "-q", "--tb=short", "-n", "0",
            "-m", "integration or live or interactive"
        )
    } else {
        # Keep the default safe for an active developer workstation. The slow
        # tiers are explicit because they may spawn subprocesses or touch real
        # services; hosted CI remains the full enforcement boundary.
        Invoke-LocalPytest @(
            "-q", "--tb=short", "-n", "0",
            "-m", "not integration and not live and not interactive and not installer"
        )
    }
}

function Invoke-Check {
    param([string] $CheckId)

    switch ($CheckId) {
        "suppressions" { Invoke-SuppressionsCheck }
        "ruff-format" { Invoke-RuffFormatCheck }
        "ruff-check" { Invoke-RuffLintCheck }
        "ty" { Invoke-TyCheck }
        "pytest" { Invoke-PytestCheck }
        default { throw "unknown check id: $CheckId" }
    }
}

if ($Help) {
    Show-Usage
    return
}

if ($RemainingArgs.Count -gt 0) {
    Show-Usage
    throw "Unknown option: $($RemainingArgs -join ' ')"
}

if ($Fast -and $Installers) {
    throw "-Fast and -Installers cannot be combined."
}
if ($Fast -and $Integration) {
    throw "-Fast and -Integration cannot be combined."
}
if ($Full -and ($Fast -or $Integration -or $Installers)) {
    throw "-Full cannot be combined with -Fast, -Integration, or -Installers."
}

foreach ($checkId in $Only) {
    Assert-ValidCheckId $checkId
}

foreach ($checkId in $Skip) {
    Assert-ValidCheckId $checkId
}

if (Test-SelectedChecksNeedUv) {
    Assert-UvAvailable
}

foreach ($checkId in $CheckOrder) {
    if (Test-ShouldRunCheck $checkId) {
        Invoke-Check $checkId
    }
}

Write-Host ""
Write-Host "All selected CI checks passed."
