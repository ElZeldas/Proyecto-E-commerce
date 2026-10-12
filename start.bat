@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

cd /d "%~dp0"

echo ============================================================================
echo   INICIANDO MICROSIP ERP - DASHBOARD DE VALIDACION FIREBIRD
echo   URL: http://localhost:8000
echo ============================================================================
echo.

:: Si el entorno virtual aun no existe, ejecutar install.bat automaticamente
if not exist "%~dp0venv\Scripts\python.exe" (
    echo [INFO] El entorno virtual venv aun no existe. Ejecutando instalacion inicial...
    call "%~dp0install.bat"
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] No se pudo preparar el entorno virtual.
        pause
        exit /b 1
    )
)

:: 1. Activar entorno virtual
echo [1/3] Activando entorno virtual ^(venv^)...
call "%~dp0venv\Scripts\activate.bat"

:: 2. Abrir automaticamente el navegador en http://localhost:8000 tras 2 segundos
echo [2/3] Abriendo navegador web en http://localhost:8000 ...
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8000"

:: 3. Iniciar servidor FastAPI en el puerto 8000
echo [3/3] Iniciando FastAPI ^(Presione Ctrl+C para detener^)...
echo.
"%~dp0venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000
exit /b %ERRORLEVEL%
