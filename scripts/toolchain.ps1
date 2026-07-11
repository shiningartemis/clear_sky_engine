$script:RequiredPythonVersion = "3.14.6"
$script:RequiredNodeVersion = "v24.18.0"
$script:RequiredNpmVersion = "11.16.0"

function Get-ProjectUv {
    $command = Get-Command "uv" -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "uv was not found. Install uv before running project scripts."
    }
    return $command.Source
}

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
