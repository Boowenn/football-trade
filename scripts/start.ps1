$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPath = Join-Path $root ".venv"
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
$envPath = Join-Path $root ".env"

function Get-AppPort {
    param(
        [string]$Path
    )

    $defaultPort = 5001
    if (-not (Test-Path $Path)) {
        return $defaultPort
    }

    $line = Get-Content $Path | Where-Object { $_ -match '^APP_PORT=' } | Select-Object -First 1
    if (-not $line) {
        return $defaultPort
    }

    $value = ($line -split '=', 2)[1].Trim()
    if ($value -match '^\d+$') {
        return [int]$value
    }

    return $defaultPort
}

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

    if (-not (Test-Path $envPath)) {
        Copy-Item (Join-Path $root ".env.example") $envPath
        Write-Host ">>> Created .env from template"
    }

    Write-Host ">>> Installing dependencies"
    & $pythonExe -m pip install --upgrade pip
    & $pythonExe -m pip install -r (Join-Path $root "requirements.txt")

    $appPort = Get-AppPort -Path $envPath
    Write-Host ">>> Starting server on http://127.0.0.1:$appPort"
    Start-Process "http://127.0.0.1:$appPort"
    & $pythonExe -m uvicorn backend.app.main:app --host 127.0.0.1 --port $appPort
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
