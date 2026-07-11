[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "toolchain.ps1")

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot "frontend"

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory)]
        [string] $FilePath,
        [Parameter(Mandatory)]
        [string[]] $Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE."
    }
}

Push-Location $repoRoot
try {
    $uv = Get-ProjectUv
    $npm = Resolve-NodeTool -Executable "npm.cmd"

    & (Join-Path $PSScriptRoot "generate-api.ps1") -Check
    Invoke-NativeCommand $uv @("run", "ruff", "format", "--check", "backend", "scripts/export_openapi.py")
    Invoke-NativeCommand $uv @("run", "ruff", "check", "backend", "scripts/export_openapi.py")
    Invoke-NativeCommand $uv @("run", "pyright", "backend/src", "backend/tests", "scripts/export_openapi.py")
    Invoke-NativeCommand $uv @("run", "pytest", "backend/tests", "-q")
    Invoke-NativeCommand $npm @("--prefix", $frontendRoot, "run", "check")
    Invoke-NativeCommand $npm @("--prefix", $frontendRoot, "run", "typecheck")
    Invoke-NativeCommand $npm @("--prefix", $frontendRoot, "run", "test", "--", "--run")
    Invoke-NativeCommand $npm @("--prefix", $frontendRoot, "run", "build")
}
finally {
    Pop-Location
}
