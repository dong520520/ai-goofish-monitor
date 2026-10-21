# Start the existing FastAPI + built Vue app on loopback, without Cookie/AI setup.
param(
    [switch]$Background,
    [switch]$OpenBrowser,
    [switch]$Restart,
    [switch]$Stop,
    [ValidateRange(1024, 65535)][int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$radarUrl = "http://127.0.0.1:$Port/opportunities"

function Get-RadarProcesses([int]$ServerProcessId) {
    $worker = Get-CimInstance Win32_Process -Filter "ProcessId=$ServerProcessId"
    if (-not $worker -or $worker.CommandLine -notmatch '-m\s+uvicorn\s+src\.app:app') {
        throw "Port $Port belongs to another application. It was not stopped."
    }
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($worker.ParentProcessId)"
    if ($worker.ExecutablePath -ieq $pythonPath) { return @($worker) }
    if ($parent -and $parent.ExecutablePath -ieq $pythonPath) { return @($worker, $parent) }
    throw "Port $Port is not owned by this checkout. It was not stopped."
}

function Backup-RadarDatabase {
    if (-not (Test-Path -LiteralPath $pythonPath)) { return }
    $backupCode = @'
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from src.infrastructure.config.settings import settings
from src.infrastructure.persistence.sqlite_connection import get_database_path
database = Path(get_database_path()).resolve()
if database.exists():
    folder = Path('data/backups')
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ('app-before-restart-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.sqlite3')
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    print('SQLite backup: ' + str(target.resolve()))
'@
    & $pythonPath -c $backupCode
    if ($LASTEXITCODE -ne 0) { throw 'Database backup failed; restart cancelled.' }
}

$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
if ($listeners.Count) {
    $ownedProcesses = @($listeners | ForEach-Object { Get-RadarProcesses $_ })
    if ($Stop -or $Restart) {
        Backup-RadarDatabase
        $ownedProcesses | Sort-Object ProcessId -Unique | ForEach-Object {
            Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
        }
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 250
        }
        if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
            throw "Port $Port is still in use; startup cancelled."
        }
    } else {
        $health = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 5
        if ($health.status -ne 'healthy' -or $health.opportunity_version -ne 'p2') {
            throw 'A different or older version is running. Use -Restart to update this checkout.'
        }
        Write-Host "Radar already running: $radarUrl"
        if ($OpenBrowser) { Start-Process -FilePath $radarUrl }
        return
    }
}
if ($Stop) {
    if (Test-Path -LiteralPath 'data/radar-runtime.json') {
        $runtime = Get-Content -LiteralPath 'data/radar-runtime.json' -Raw | ConvertFrom-Json
        $runtime | Add-Member -MemberType NoteProperty -Name status -Value 'stopped' -Force
        $runtime | Add-Member -MemberType NoteProperty -Name stopped_at -Value (Get-Date).ToString('o') -Force
        $runtime | ConvertTo-Json | Set-Content -LiteralPath 'data/radar-runtime.json' -Encoding UTF8
    }
    Write-Host 'Radar stopped. Database retained.'
    return
}
if ($Restart -and -not $listeners.Count) { Backup-RadarDatabase }

if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment setup failed' }
    & '.venv/Scripts/python.exe' -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
}
$frontendBuild = Join-Path $PSScriptRoot 'dist/index.html'
$frontendInputs = @(Get-ChildItem -LiteralPath 'web-ui/src' -File -Recurse)
$frontendInputs += @(Get-ChildItem -LiteralPath 'web-ui' -File | Where-Object { $_.Name -match '^(package.*\.json|index\.html|vite\.config\..*|tsconfig.*\.json)$' })
$latestFrontendInput = ($frontendInputs | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1).LastWriteTimeUtc
if (-not (Test-Path -LiteralPath $frontendBuild) -or $latestFrontendInput -gt (Get-Item -LiteralPath $frontendBuild).LastWriteTimeUtc) {
    Push-Location -LiteralPath 'web-ui'
    try {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    } finally { Pop-Location }
}
Write-Host "Radar: $radarUrl"
if ($Background) {
    New-Item -ItemType Directory -Force -Path 'logs', 'data' | Out-Null
    $logStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $stdoutPath = Join-Path $PSScriptRoot "logs/radar-$logStamp.stdout.log"
    $stderrPath = Join-Path $PSScriptRoot "logs/radar-$logStamp.stderr.log"
    $server = Start-Process -FilePath $pythonPath -ArgumentList "-m uvicorn src.app:app --host 127.0.0.1 --port $Port" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $server.Refresh()
        if ($server.HasExited) { throw "Radar exited. See $stderrPath" }
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 1
            if ($health.status -eq 'healthy' -and $health.opportunity_version -eq 'p2') {
                $ready = $true
                break
            }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw "Radar is not ready. See $stderrPath" }
    @{ process_id = $server.Id; status = 'running'; url = $radarUrl; stdout = $stdoutPath; stderr = $stderrPath; started_at = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath 'data/radar-runtime.json' -Encoding UTF8
    Write-Host "Ready. Logs: $stderrPath"
    if ($OpenBrowser) { Start-Process -FilePath $radarUrl }
} else {
    & $pythonPath -m uvicorn src.app:app --host 127.0.0.1 --port $Port
}
