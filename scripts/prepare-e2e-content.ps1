[CmdletBinding()]
param([switch]$StartBackend)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "toolchain.ps1")
$repoRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$repoPrefix = $repoRoot.TrimEnd("\", "/") + [IO.Path]::DirectorySeparatorChar
$localAppData = [IO.Path]::GetFullPath((Join-Path $repoRoot "config_test\e2e-localappdata"))
$fixtureRoot = Join-Path $repoRoot "backend\tests\fixtures\content\characters"
$characterRoot = Join-Path $localAppData "ClearSkyEngine\content\characters"

# 递归删除前必须证明目标仍是仓库子目录，避免测试清理误伤真实用户数据。
if (-not ($localAppData.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase))) {
    throw "E2E LocalAppData escaped the repository root: $localAppData"
}
if (Test-Path -LiteralPath $localAppData) {
    Remove-Item -LiteralPath $localAppData -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $characterRoot | Out-Null
Copy-Item -Path (Join-Path $fixtureRoot "*") -Destination $characterRoot -Recurse
$env:LOCALAPPDATA = $localAppData
Write-Host "E2E LOCALAPPDATA=$localAppData"

if ($StartBackend) {
    Push-Location $repoRoot
    try {
        $uv = Get-ProjectUv
        $env:PYTHONPATH = Join-Path $repoRoot "backend\src"
        # 隔离目录每次都会重建，启动真实 UI 前必须从空库迁移到 head。
        $migrationCode = "from pathlib import Path; from app.config import AppConfig; from app.db.migrations import upgrade_database; config = AppConfig.for_local_app_data(); config.paths.create_directories(); upgrade_database(config.paths.database_path, Path('alembic.ini').resolve())"
        & $uv run python -c $migrationCode
        if ($LASTEXITCODE -ne 0) { throw "E2E database migration failed." }
        & $uv run python -m uvicorn app.main:create_app --factory --app-dir backend/src --host 127.0.0.1 --port 8000
        if ($LASTEXITCODE -ne 0) { throw "E2E backend failed." }
    }
    finally {
        Pop-Location
    }
}
