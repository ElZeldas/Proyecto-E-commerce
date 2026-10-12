@echo off
echo ====================================================
echo Compilando Calculadora Ecommerce a Ejecutable (.exe)
echo ====================================================

REM Activar entorno virtual
call env_desktop\Scripts\activate

REM Ejecutar PyInstaller
python -m PyInstaller --noconfirm ^
    --onedir ^
    --windowed ^
    --name "CalculadoraEcommerce" ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --add-binary "fbclient.dll;." ^
    --add-data ".env;." ^
    --add-data "app_icon.ico;." ^
    --icon "app_icon.ico" ^
    --hidden-import=uvicorn.logging ^
    --hidden-import=uvicorn.loops ^
    --hidden-import=uvicorn.loops.auto ^
    --hidden-import=uvicorn.protocols ^
    --hidden-import=uvicorn.protocols.http ^
    --hidden-import=uvicorn.protocols.http.auto ^
    --hidden-import=uvicorn.protocols.websockets ^
    --hidden-import=uvicorn.protocols.websockets.auto ^
    --hidden-import=uvicorn.lifespan ^
    --hidden-import=uvicorn.lifespan.on ^
    --hidden-import=passlib.handlers.bcrypt ^
    desktop_app.py

echo.
echo Compilacion terminada. El ejecutable esta en la carpeta dist\CalculadoraEcommerce
pause
