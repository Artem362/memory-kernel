param(
    [switch]$Release = $true
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$vsDevCmd = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat"
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
$profile = if ($Release) { "release" } else { "debug" }
$artifactDir = Join-Path $repoRoot "rust\target\$profile"
$dllPath = Join-Path $artifactDir "_native.dll"
$pydPath = Join-Path $repoRoot "src\memory_kernel\_native.pyd"

if (-not (Test-Path $vsDevCmd)) {
    throw "VsDevCmd.bat was not found. Install Visual Studio Build Tools with the C++ workload first."
}

cmd /c "`"$vsDevCmd`" -arch=x64 >nul && set" | ForEach-Object {
    if ($_ -match '^(.*?)=(.*)$') {
        Set-Item -Path "env:$($matches[1])" -Value $matches[2]
    }
}

$env:PATH = "$cargoBin;$env:PATH"

$cargoArgs = @("build", "--manifest-path", "rust\Cargo.toml")
if ($Release) {
    $cargoArgs += "--release"
}

Push-Location $repoRoot
try {
    & cargo @cargoArgs
    Copy-Item -LiteralPath $dllPath -Destination $pydPath -Force
    Write-Host "native accelerator ready: $pydPath"
} finally {
    Pop-Location
}
