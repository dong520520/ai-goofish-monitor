# Start the existing FastAPI + built Vue app on loopback, without Cookie/AI setup.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment setup failed' }
    & '.venv/Scripts/python.exe' -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
}
if (-not (Test-Path -LiteralPath 'dist/index.html')) {
    Push-Location -LiteralPath 'web-ui'
    try {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    } finally { Pop-Location }
}
Write-Host 'Radar: http://127.0.0.1:8000/opportunities'
& '.venv/Scripts/python.exe' -m uvicorn src.app:app --host 127.0.0.1 --port 8000
