[CmdletBinding()]
param(
    [switch] $Check
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "toolchain.ps1")

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot "frontend"
$target = Join-Path $frontendRoot "src\api\generated.ts"
$schemaPath = Join-Path ([IO.Path]::GetTempPath()) "clear-sky-openapi-$PID.json"
$generatedPath = Join-Path ([IO.Path]::GetTempPath()) "clear-sky-openapi-$PID.ts"
$previousPythonPath = $env:PYTHONPATH

Push-Location $repoRoot
try {
    $env:PYTHONPATH = Join-Path $repoRoot "backend\src"
    $uv = Get-ProjectUv
    $generator = Join-Path $frontendRoot "node_modules\.bin\openapi-typescript.cmd"
    if (-not (Test-Path -LiteralPath $generator)) {
        throw "openapi-typescript is not installed. Run scripts\setup.ps1 first."
    }

    & $uv run python "scripts\export_openapi.py" --output $schemaPath
    if ($LASTEXITCODE -ne 0) {
        throw "OpenAPI schema export failed."
    }

    & $generator $schemaPath --output $generatedPath
    if ($LASTEXITCODE -ne 0) {
        throw "OpenAPI TypeScript generation failed."
    }

    if ($Check) {
        if (-not (Test-Path -LiteralPath $target)) {
            throw "Generated API types are missing. Run scripts\generate-api.ps1."
        }
        $expected = Get-Content -Raw -LiteralPath $generatedPath
        $actual = Get-Content -Raw -LiteralPath $target
        if ($actual -cne $expected) {
            throw "Generated API types are stale. Run scripts\generate-api.ps1."
        }
    }
    else {
        $targetDirectory = Split-Path -Parent $target
        New-Item -ItemType Directory -Force -Path $targetDirectory | Out-Null
        Copy-Item -LiteralPath $generatedPath -Destination $target -Force
    }
}
finally {
    if ($null -eq $previousPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONPATH = $previousPythonPath
    }
    Pop-Location
    if (Test-Path -LiteralPath $schemaPath) {
        Remove-Item -LiteralPath $schemaPath -Force
    }
    if (Test-Path -LiteralPath $generatedPath) {
        Remove-Item -LiteralPath $generatedPath -Force
    }
}
