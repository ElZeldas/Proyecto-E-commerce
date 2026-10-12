@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

:: ============================================================================
:: GESTOR DE SERVICIO Y EJECUCION - MICROSIP ERP READ-ONLY API
:: Uso en PowerShell:
::   .\service.bat           -> Inicia la API en consola y abre http://localhost:8000
::   .\service.bat run       -> Inicia la API en consola y abre http://localhost:8000
::   .\service.bat install   -> Instala e inicia como Servicio Windows mediante NSSM
::   .\service.bat start     -> Inicia el Servicio Windows
::   .\service.bat stop      -> Detiene el Servicio Windows
::   .\service.bat restart   -> Reinicia el Servicio Windows
::   .\service.bat status    -> Muestra el estado del Servicio Windows
::   .\service.bat remove    -> Elimina el Servicio Windows
:: ============================================================================

cd /d "%~dp0"

set "SERVICE_NAME=MicrosipReadOnlyAPI"
set "SERVICE_DISPLAY=Microsip ERP Read-Only REST API"
set "SERVICE_DESC=API REST Empresarial exclusivamente de consulta (READ ONLY) para Microsip ERP sobre Firebird SQL."
set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

set "PYTHON_EXE=%APP_DIR%\venv\Scripts\python.exe"
set "STDOUT_LOG=%APP_DIR%\logs\service_stdout.log"
set "STDERR_LOG=%APP_DIR%\logs\service_stderr.log"

if not exist "%APP_DIR%\logs" mkdir "%APP_DIR%\logs"

set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=run"

if /I "%ACTION%"=="run" goto :RUN_CONSOLE
if /I "%ACTION%"=="help" goto :SHOW_HELP

:: Verificar privilegios de Administrador para operaciones NSSM
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Para administrar el Servicio de Windows con NSSM debe abrir PowerShell/CMD como ADMINISTRADOR.
    echo Si solo desea ejecutar la API inmediatamente, ejecute:
    echo     .\start.bat
    pause
    exit /b 1
)

:: Localizar nssm.exe
set "NSSM_EXE="
if exist "%APP_DIR%\nssm.exe" (
    set "NSSM_EXE=%APP_DIR%\nssm.exe"
) else (
    where nssm >nul 2>nul
    if !ERRORLEVEL! EQU 0 (
        set "NSSM_EXE=nssm"
    )
)

if "%NSSM_EXE%"=="" (
    echo [INFO] Instalando NSSM automaticamente mediante winget...
    winget install -e --id NSSM.NSSM --accept-package-agreements --accept-source-agreements
    where nssm >nul 2>nul
    if !ERRORLEVEL! EQU 0 (
        set "NSSM_EXE=nssm"
    )
)

if "%NSSM_EXE%"=="" (
    echo [ERROR] No se encontro nssm.exe. Descarguelo desde https://nssm.cc/download y copielo en %APP_DIR%\nssm.exe
    pause
    exit /b 1
)

if /I "%ACTION%"=="install" goto :INSTALL_SERVICE
if /I "%ACTION%"=="start" goto :START_SERVICE
if /I "%ACTION%"=="stop" goto :STOP_SERVICE
if /I "%ACTION%"=="restart" goto :RESTART_SERVICE
if /I "%ACTION%"=="status" goto :STATUS_SERVICE
if /I "%ACTION%"=="remove" goto :REMOVE_SERVICE
goto :SHOW_HELP

:INSTALL_SERVICE
if not exist "%PYTHON_EXE%" (
    call "%APP_DIR%\install.bat"
)

echo ============================================================================
echo   Instalando Servicio Windows "%SERVICE_NAME%" mediante NSSM...
echo ============================================================================
"%NSSM_EXE%" install "%SERVICE_NAME%" "%PYTHON_EXE%" "-m uvicorn main:app --host 0.0.0.0 --port 8000"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppDirectory "%APP_DIR%"
"%NSSM_EXE%" set "%SERVICE_NAME%" DisplayName "%SERVICE_DISPLAY%"
"%NSSM_EXE%" set "%SERVICE_NAME%" Description "%SERVICE_DESC%"
"%NSSM_EXE%" set "%SERVICE_NAME%" Start SERVICE_AUTO_START
"%NSSM_EXE%" set "%SERVICE_NAME%" AppStdout "%STDOUT_LOG%"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppStderr "%STDERR_LOG%"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRotateFiles 1
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRotateOnline 1
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRotateBytes 10485760
"%NSSM_EXE%" set "%SERVICE_NAME%" AppExit Default Restart
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRestartDelay 5000

echo Iniciando servicio "%SERVICE_NAME%"...
"%NSSM_EXE%" start "%SERVICE_NAME%"
echo.
echo [OK] Servicio activo en http://localhost:8000
exit /b 0

:START_SERVICE
"%NSSM_EXE%" start "%SERVICE_NAME%"
exit /b %ERRORLEVEL%

:STOP_SERVICE
"%NSSM_EXE%" stop "%SERVICE_NAME%"
exit /b %ERRORLEVEL%

:RESTART_SERVICE
"%NSSM_EXE%" restart "%SERVICE_NAME%"
exit /b %ERRORLEVEL%

:STATUS_SERVICE
"%NSSM_EXE%" status "%SERVICE_NAME%"
exit /b %ERRORLEVEL%

:REMOVE_SERVICE
"%NSSM_EXE%" stop "%SERVICE_NAME%" >nul 2>nul
"%NSSM_EXE%" remove "%SERVICE_NAME%" confirm
echo [OK] Servicio "%SERVICE_NAME%" eliminado correctamente.
exit /b 0

:RUN_CONSOLE
call "%APP_DIR%\start.bat"
exit /b %ERRORLEVEL%

:SHOW_HELP
echo ============================================================================
echo   USO DE SERVICE.BAT ^(En PowerShell anteponga .\ al comando^)
echo ============================================================================
echo   .\service.bat           - Inicia la API en consola y abre http://localhost:8000
echo   .\service.bat install   - Instala e inicia como Servicio Windows con NSSM
echo   .\service.bat start     - Inicia el Servicio Windows
echo   .\service.bat stop      - Detiene el Servicio Windows
echo   .\service.bat restart   - Reinicia el Servicio Windows
echo   .\service.bat status    - Consulta el estado del Servicio Windows
echo   .\service.bat remove    - Elimina el Servicio Windows
echo ============================================================================
exit /b 0
