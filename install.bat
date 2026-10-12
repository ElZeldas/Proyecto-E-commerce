@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ============================================================================
echo   INSTALADOR AUTOMATICO - MICROSIP ERP FIREBIRD API ^(WINDOWS 11 / 10^)
echo ============================================================================
echo.

cd /d "%~dp0"

:: 1. Localizar Python 3.12 real (evitando el alias vacio de WindowsApps)
set "PYTHON_EXE="

if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
) else if exist "C:\Program Files\Python312\python.exe" (
    set "PYTHON_EXE=C:\Program Files\Python312\python.exe"
) else if exist "C:\Python312\python.exe" (
    set "PYTHON_EXE=C:\Python312\python.exe"
) else if exist "C:\Windows\py.exe" (
    set "PYTHON_EXE=C:\Windows\py.exe -3.12"
) else (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        echo "%%i" | findstr /I "WindowsApps" >nul
        if !ERRORLEVEL! NEQ 0 (
            if "!PYTHON_EXE!"=="" set "PYTHON_EXE=%%i"
        )
    )
)

if "%PYTHON_EXE%"=="" (
    echo [AVISO] Instalando Python 3.12 automaticamente mediante winget...
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements --scope user
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    )
)

if "%PYTHON_EXE%"=="" (
    echo [ERROR] No se encontro Python 3.12 en el sistema.
    pause
    exit /b 1
)

echo [1/6] Usando interprete Python:
echo       %PYTHON_EXE%
"%PYTHON_EXE%" --version
echo.

:: 2. Crear entorno virtual venv
if not exist "%~dp0venv\Scripts\python.exe" (
    echo [2/6] Creando entorno virtual aislado en "%~dp0venv"...
    "%PYTHON_EXE%" -m venv "%~dp0venv"
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Fallo la creacion del entorno virtual venv.
        pause
        exit /b 1
    )
) else (
    echo [2/6] Entorno virtual "%~dp0venv" ya existe.
)

:: 3. Activar entorno virtual e instalar dependencias
echo [3/6] Activando entorno virtual e instalando dependencias...
call "%~dp0venv\Scripts\activate.bat"
"%~dp0venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
"%~dp0venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Ocurrio un error al instalar requirements.txt.
    pause
    exit /b 1
)

:: 4. Crear carpeta logs y archivo .env
echo [4/6] Verificando directorio logs y archivo .env...
if not exist "%~dp0logs" mkdir "%~dp0logs"
if not exist "%~dp0.env" (
    if exist "%~dp0.env.example" copy /Y "%~dp0.env.example" "%~dp0.env" >nul
)

:: 5. Verificar fbclient.dll
echo [5/6] Verificando cliente Firebird ^(fbclient.dll^)...
if exist "C:\Program Files\Firebird\Firebird_5_0\fbclient.dll" (
    echo       [OK] Detectado: C:\Program Files\Firebird\Firebird_5_0\fbclient.dll
) else if exist "C:\Program Files\Firebird\Firebird_4_0\fbclient.dll" (
    echo       [OK] Detectado: C:\Program Files\Firebird\Firebird_4_0\fbclient.dll
) else if exist "C:\Program Files\Firebird\Firebird_3_0\fbclient.dll" (
    echo       [OK] Detectado: C:\Program Files\Firebird\Firebird_3_0\fbclient.dll
) else if exist "C:\Program Files\Firebird\Firebird_2_5\bin\fbclient.dll" (
    echo       [OK] Detectado: C:\Program Files\Firebird\Firebird_2_5\bin\fbclient.dll
) else if exist "C:\Windows\System32\fbclient.dll" (
    echo       [OK] Detectado: C:\Windows\System32\fbclient.dll
) else (
    echo       [AVISO] No se detecto fbclient.dll en rutas estandar.
)

:: 6. Verificar conectividad TCP/IP hacia 192.168.1.5:3050
echo [6/6] Probando red hacia Servidor Microsip ^(192.168.1.5:3050^)...
powershell -NoProfile -Command "if (Test-NetConnection -ComputerName 192.168.1.5 -Port 3050 -InformationLevel Quiet) { Write-Host '      [OK] Puerto 3050 accesible en 192.168.1.5' -ForegroundColor Green } else { Write-Host '      [AVISO] No hubo respuesta en 192.168.1.5:3050' -ForegroundColor Yellow }"

echo.
echo ============================================================================
echo   INSTALACION LISTA
echo   Para iniciar el Dashboard Web ejecute en PowerShell:
echo       .\start.bat
echo ============================================================================
exit /b 0
