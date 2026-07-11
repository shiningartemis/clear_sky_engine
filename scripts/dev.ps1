[CmdletBinding()]
param(
    [switch] $SmokeTest
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "toolchain.ps1")

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$node = Resolve-NodeTool -Executable "node.exe"
$vite = Join-Path $repoRoot "frontend\node_modules\vite\bin\vite.js"
$backend = $null
$frontend = $null

if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $vite)) {
    throw "Development dependencies are missing. Run scripts\setup.ps1 first."
}

Push-Location $repoRoot
try {
    $backend = Start-Process -FilePath $python -ArgumentList @(
        "-m",
        "uvicorn",
        "app.main:create_app",
        "--factory",
        "--app-dir",
        "backend/src",
        "--host",
        "127.0.0.1",
        "--port",
        "8000"
    ) -PassThru -NoNewWindow
    $frontend = Start-Process -FilePath $node -ArgumentList @(
        $vite,
        "frontend",
        "--host",
        "127.0.0.1",
        "--port",
        "5173",
        "--strictPort"
    ) -PassThru -NoNewWindow

    if ($SmokeTest) {
        $ready = $false
        for ($attempt = 0; $attempt -lt 60; $attempt += 1) {
            if ($backend.HasExited -or $frontend.HasExited) {
                break
            }
            try {
                $health = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" -UseBasicParsing
                $page = Invoke-WebRequest -Uri "http://127.0.0.1:5173/" -UseBasicParsing
                if ($health.StatusCode -eq 200 -and $page.StatusCode -eq 200) {
                    $ready = $true
                    break
                }
            }
            catch {
                Start-Sleep -Milliseconds 250
            }
        }
        if (-not $ready) {
            throw "Development servers did not become ready within 15 seconds."
        }
        Write-Host "Development smoke test passed."
        return
    }

    while (-not $backend.HasExited -and -not $frontend.HasExited) {
        Start-Sleep -Seconds 1
    }

    if ($backend.HasExited -and $backend.ExitCode -ne 0) {
        throw "FastAPI development server exited with code $($backend.ExitCode)."
    }
    if ($frontend.HasExited -and $frontend.ExitCode -ne 0) {
        throw "Vite development server exited with code $($frontend.ExitCode)."
    }
}
finally {
    foreach ($process in @($backend, $frontend)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id
            $process.WaitForExit()
        }
    }
    Pop-Location
}
