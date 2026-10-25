# LLMDyno setup for Windows: creates a virtual environment, installs LLMDyno and opens it in your browser.
# Usage:  powershell -ExecutionPolicy Bypass -File setup.ps1            (safe to re-run)
#         powershell -ExecutionPolicy Bypass -File setup.ps1 -NoStart   (install without starting the server)
param([switch]$NoStart)
# "Continue": Windows PowerShell 5.1 turns any stderr line from python/pip into a fatal error under "Stop";
# each step checks its exit code instead
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

function Find-Python {
    foreach ($candidate in @(@("py", "-3"), @("python"), @("python3"))) {
        if (Get-Command $candidate[0] -ErrorAction SilentlyContinue) {
            $extra = @($candidate | Select-Object -Skip 1)
            $ok = & $candidate[0] @extra -c "import sys; print(int(sys.version_info >= (3, 11)))" 2>$null
            if ($ok -eq "1") { return ,$candidate }
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "LLMDyno needs Python 3.11 or newer." -ForegroundColor Yellow
    Write-Host "Install it from https://www.python.org/downloads/ or run:  winget install Python.Python.3.12"
    exit 1
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating .venv ..."
    $pyArgs = @($python | Select-Object -Skip 1) + @("-m", "venv", ".venv")
    & $python[0] @pyArgs
}

function Invoke-Checked {
    param([string]$What)
    if ($LASTEXITCODE -ne 0) { Write-Host "Setup failed while trying to $What (exit code $LASTEXITCODE)." -ForegroundColor Red; exit 1 }
}

$venvPy = ".\.venv\Scripts\python.exe"
& $venvPy -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
    # environments made by uv or some distributions ship without pip
    & $venvPy -m ensurepip --upgrade *> $null
    Invoke-Checked "install pip into .venv"
}
Write-Host "Installing LLMDyno ..."
& $venvPy -m pip install --quiet --upgrade pip
Invoke-Checked "upgrade pip"
& $venvPy -m pip install --quiet -e .
Invoke-Checked "install LLMDyno"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker was not found. The setup wizard in the browser can install Docker Desktop for you." -ForegroundColor Yellow
}

$version = & .\.venv\Scripts\llmdyno.exe --version
Write-Host "$version is installed." -ForegroundColor Green
if ($NoStart) {
    Write-Host "Start it with:  .venv\Scripts\llmdyno serve --open"
} else {
    Write-Host "Starting on http://127.0.0.1:8777 (Ctrl+C stops it) ..."
    & .\.venv\Scripts\llmdyno.exe serve --open
}
