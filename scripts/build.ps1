[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "toolchain.ps1")

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot "frontend"
$frontendDist = Join-Path $frontendRoot "dist"
$staticRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot "backend\src\app\static"))
$repoPrefix = [IO.Path]::GetFullPath($repoRoot).TrimEnd("\", "/") + [IO.Path]::DirectorySeparatorChar

if (-not $staticRoot.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Static output escaped the repository root: $staticRoot"
}

Push-Location $repoRoot
try {
    $uv = Get-ProjectUv
    $npm = Resolve-NodeTool -Executable "npm.cmd"

    & (Join-Path $PSScriptRoot "generate-api.ps1") -Check
    & $npm --prefix $frontendRoot run build
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend build failed."
    }

    if (Test-Path -LiteralPath $staticRoot) {
        Remove-Item -LiteralPath $staticRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $staticRoot | Out-Null
    Copy-Item -Path (Join-Path $frontendDist "*") -Destination $staticRoot -Recurse

    & $uv run pyinstaller --noconfirm --clean "clear_sky_engine.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }

    $executable = Join-Path $repoRoot "dist\ClearSkyEngine\ClearSkyEngine.exe"
    if (-not (Test-Path -LiteralPath $executable)) {
        throw "Packaged executable is missing: $executable"
    }
    Write-Host "Built $executable"
}
finally {
    Pop-Location
}
