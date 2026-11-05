# start.ps1 - One-click launcher (ASCII only on purpose: PowerShell 5.1 reads
# BOM-less UTF-8 as ANSI, so non-ASCII comments would be garbled).
# Usage:  powershell -ExecutionPolicy Bypass -File .\start.ps1
# Optional: set PYTHON_BIN to force a specific interpreter, e.g.
#           $env:PYTHON_BIN = "C:\Python312\python.exe"

param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "[1/5] Project dir: $ProjectRoot"

# Pick a Python interpreter: PYTHON_BIN > project .venv > PATH > common install dirs.
# NOTE: on Windows the "python.exe" in WindowsApps is a Store stub that cannot run;
# every candidate is therefore test-launched instead of trusted by name.
$candidates = @()
if ($env:PYTHON_BIN) { $candidates += $env:PYTHON_BIN }
$candidates += (Join-Path $ProjectRoot ".venv\Scripts\python.exe")
$cmdPy = Get-Command python -ErrorAction SilentlyContinue
if ($cmdPy) { $candidates += $cmdPy.Source }
$cmdPy3 = Get-Command python3 -ErrorAction SilentlyContinue
if ($cmdPy3) { $candidates += $cmdPy3.Source }
$candidates += Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python" -Filter "python.exe" `
    -Recurse -Depth 2 -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }

$Python = $null
foreach ($cand in $candidates) {
    if (-not $cand) { continue }
    if (-not (Test-Path $cand)) { continue }
    try {
        & $cand -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $Python = $cand
            break
        }
    } catch {
        continue
    }
}
if (-not $Python) {
    Write-Host "ERROR: no usable Python found." -ForegroundColor Red
    Write-Host "Install Python 3.10+, or point PYTHON_BIN at a working interpreter:" -ForegroundColor Yellow
    Write-Host '  $env:PYTHON_BIN = "C:\path\to\python.exe"; .\start.ps1'
    exit 1
}
Write-Host "[2/5] Using python: $Python"

# Dependency check: fail with a clear instruction instead of a traceback.
& $Python -c "import streamlit, pypdf, pydantic, pandas" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: this interpreter is missing required packages." -ForegroundColor Red
    Write-Host "Fix it with:" -ForegroundColor Yellow
    Write-Host "  $Python -m pip install -r requirements.txt"
    Write-Host "Or point PYTHON_BIN at an interpreter that already has them:"
    Write-Host '  $env:PYTHON_BIN = "C:\path\to\python.exe"; .\start.ps1'
    exit 1
}
Write-Host "[3/5] Dependencies OK"

# Auto-load .env into the current process (no third-party dependency needed).
$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#")) {
            $kv = $line -split "=", 2
            if ($kv.Length -eq 2) {
                $name = $kv[0].Trim()
                $value = $kv[1].Trim().Trim('"')
                if ($name -and -not [System.Environment]::GetEnvironmentVariable($name)) {
                    Set-Item -Path "Env:$name" -Value $value
                }
            }
        }
    }
    Write-Host "[4/5] Loaded .env (values stay in this process only)"
} else {
    Write-Host "[4/5] No .env found -> app will start in DEMO mode (no API key needed)"
}

if ([System.Environment]::GetEnvironmentVariable("LLM_API_KEY")) {
    Write-Host "       LLM_API_KEY detected -> LLM mode available"
} else {
    Write-Host "       LLM_API_KEY not set  -> DEMO mode"
}

# Port pre-flight: a half-open or already-running server is the most common
# reason "double-click does nothing", so say it plainly instead of dumping a traceback.
$busy = $null
try {
    $busy = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction Stop
} catch {
    $busy = $null
}
if ($busy) {
    Write-Host ""
    Write-Host "Port 8501 is already in use (PID $($busy[0].OwningProcess))." -ForegroundColor Yellow
    Write-Host "  - If the app is already running, just open http://127.0.0.1:8501"
    Write-Host "  - Otherwise stop the old process first:  taskkill /PID $($busy[0].OwningProcess) /F"
    exit 0
}

if ($NoBrowser) {
    $Headless = "true"
    Write-Host "[5/5] Starting Streamlit (headless) ... http://127.0.0.1:8501"
} else {
    $Headless = "false"
    Write-Host "[5/5] Starting Streamlit ... open http://127.0.0.1:8501 in your browser"
}
# NOTE: use 127.0.0.1, NOT localhost. The system proxy on this machine intercepts
# "localhost" and answers 502, which looks exactly like "the page won't load".
Write-Host "      Keep this window open while demoing; closing it stops the server."
& $Python -m streamlit run app.py --server.headless $Headless
