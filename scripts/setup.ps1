[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "toolchain.ps1")

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot "frontend"

Push-Location $repoRoot
try {
    $uv = Get-ProjectUv
    $node = Resolve-NodeTool -Executable "node.exe"
    $npm = Resolve-NodeTool -Executable "npm.cmd"

    $pythonVersion = (& $uv run python -c "import platform; print(platform.python_version())").Trim()
    if ($pythonVersion -ne $RequiredPythonVersion) {
        throw "Python version mismatch: required $RequiredPythonVersion, actual $pythonVersion."
    }

    $nodeVersion = (& $node --version).Trim()
    if ($nodeVersion -ne $RequiredNodeVersion) {
        throw "Node.js version mismatch: required $RequiredNodeVersion, actual $nodeVersion."
    }

    $npmVersion = (& $npm --version).Trim()
    if ($npmVersion -ne $RequiredNpmVersion) {
        throw "npm version mismatch: required $RequiredNpmVersion, actual $npmVersion."
    }

    $sqliteVersion = (& $uv run python -c "import sqlite3; print(sqlite3.sqlite_version)").Trim()
    Write-Host "Python $pythonVersion"
    Write-Host "SQLite $sqliteVersion (bundled with the Python runtime)"
    Write-Host "Node.js $nodeVersion"
    Write-Host "npm $npmVersion"

    & $uv sync --locked
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync --locked failed."
    }

    & $npm ci --prefix $frontendRoot
    if ($LASTEXITCODE -ne 0) {
        throw "npm ci --prefix frontend failed."
    }
}
finally {
    Pop-Location
}
