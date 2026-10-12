# ============================================================================
# SCRIPT POWERSHELL NATIVO - MICROSIP ERP FIREBIRD API (WINDOWS 11)
# Resuelve ExecutionPolicy y activa correctamente .\venv\Scripts\Activate.ps1
# ============================================================================
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "[INFO] Creando entorno virtual con install.bat..." -ForegroundColor Cyan
    cmd /c ".\install.bat"
}

Write-Host "[1/3] Activando entorno virtual en PowerShell..." -ForegroundColor Green
. ".\venv\Scripts\Activate.ps1"

Write-Host "[2/3] Abriendo navegador en http://localhost:8000 ..." -ForegroundColor Green
Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2
    Start-Process "http://localhost:8000"
} | Out-Null

Write-Host "[3/3] Iniciando FastAPI en http://localhost:8000 ..." -ForegroundColor Green
& ".\venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000
