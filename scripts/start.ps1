$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPath = Join-Path $root ".venv"
$pythonExe = Join-Path $venvPath "Scripts\python.exe"

function Resolve-BootstrapPython {
    if (Test-Path $pythonExe) {
        return $pythonExe
    }

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        return "py"
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return "python"
    }

    throw "Python was not found. Install Python 3 first."
}

try {
    $bootstrapPython = Resolve-BootstrapPython

    if (-not (Test-Path $pythonExe)) {
        Write-Host ">>> Creating virtual environment"
        if ($bootstrapPython -eq "py") {
            & py -3 -m venv $venvPath
        }
        else {
            & $bootstrapPython -m venv $venvPath
        }
    }

    if (-not (Test-Path (Join-Path $root ".env"))) {
        Copy-Item (Join-Path $root ".env.example") (Join-Path $root ".env")
        Write-Host ">>> Created .env from template"
    }

    Write-Host ">>> Installing dependencies"
    & $pythonExe -m pip install --upgrade pip
    & $pythonExe -m pip install -r (Join-Path $root "requirements.txt")

    Write-Host ">>> Starting server on http://127.0.0.1:8000"
    Start-Process "http://127.0.0.1:8000"
    & $pythonExe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
}
catch {
    Write-Host ""
    Write-Host "Start failed:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Press Enter to close..."
    Read-Host | Out-Null
    exit 1
}
