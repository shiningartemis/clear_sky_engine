[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot "frontend"
$requiredPython = "3.14.6"
$requiredNode = "v24.18.0"
$requiredNpm = "11.16.0"

function Resolve-NodeTool {
    param(
        [Parameter(Mandatory)]
        [string] $Executable
    )

    $nodeHome = $env:CLEAR_SKY_NODE_HOME
    if (-not $nodeHome) {
        $nodeHome = [Environment]::GetEnvironmentVariable("CLEAR_SKY_NODE_HOME", "User")
    }

    if ($nodeHome) {
        $candidate = Join-Path $nodeHome $Executable
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    $command = Get-Command $Executable -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "$Executable was not found. Install the pinned portable Node.js and set CLEAR_SKY_NODE_HOME."
    }
    return $command.Source
}

Push-Location $repoRoot
try {
    $uv = Get-Command "uv" -ErrorAction Stop
    $node = Resolve-NodeTool -Executable "node.exe"
    $npm = Resolve-NodeTool -Executable "npm.cmd"

    $pythonVersion = (& $uv.Source run python -c "import platform; print(platform.python_version())").Trim()
    if ($pythonVersion -ne $requiredPython) {
        throw "Python version mismatch: required $requiredPython, actual $pythonVersion."
    }

    $nodeVersion = (& $node --version).Trim()
    if ($nodeVersion -ne $requiredNode) {
        throw "Node.js version mismatch: required $requiredNode, actual $nodeVersion."
    }

    $npmVersion = (& $npm --version).Trim()
    if ($npmVersion -ne $requiredNpm) {
        throw "npm version mismatch: required $requiredNpm, actual $npmVersion."
    }

    $sqliteVersion = (& $uv.Source run python -c "import sqlite3; print(sqlite3.sqlite_version)").Trim()
    Write-Host "Python $pythonVersion"
    Write-Host "SQLite $sqliteVersion (bundled with the Python runtime)"
    Write-Host "Node.js $nodeVersion"
    Write-Host "npm $npmVersion"

    & $uv.Source sync --locked
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
