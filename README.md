# Microsip ERP — Validador de Conexión Firebird & Descubrimiento de Tablas (Windows 11)

Dashboard Web en **Bootstrap 5** y **API REST (Solo Lectura)** en **FastAPI + Python 3.12** para validar conectividad remota TCP/IP hacia **Microsip ERP (`192.168.1.5` — `E:\Microsip datos\CAPACITACION.FDB`)**, autenticar usuarios de Firebird y descubrir automáticamente todas las tablas y su cantidad aproximada de registros antes de pasar a la Fase 2 (consulta de SKU, Nombre, Último Costo y Existencias).

---

## 1. Solución a los Errores de PowerShell en Windows 11

### ¿Por qué ocurría `El módulo 'venv' no pudo cargarse. CommandNotFoundException`?
1. En Windows 11, el alias de Microsoft Store (`WindowsApps\python.exe`) impedía que `venv` se creara con el intérprete real de Python 3.12 (`C:\Users\DeLL\AppData\Local\Programs\Python\Python312\python.exe`).
2. Además, en **PowerShell**, escribir `venv\Scripts\Activate.ps1` **sin anteponer `.\`** hace que PowerShell intente buscar un módulo del sistema llamado `venv`.
   - **Incorrecto en PowerShell:** `venv\Scripts\activate`
   - **Correcto en PowerShell:** `.\venv\Scripts\Activate.ps1` (o simplemente ejecutar `.\start.bat`).

### ¿Por qué ocurría `service.bat no se reconoce como comando`?
En **PowerShell**, por seguridad, los scripts ubicados en la carpeta actual requieren el prefijo `.\`:
- **Correcto:** `.\start.bat`, `.\install.bat`, `.\service.bat`

*(Además, los scripts y archivos del proyecto han sido configurados tanto en la raíz del proyecto `c:\wamp64\www\Calculadora-Ecommerce` como en `c:\wamp64\www\Calculadora-Ecommerce\microsip-api` para que funcionen desde cualquiera de las dos carpetas).*

---

## 2. Instrucciones Paso a Paso para Windows 11

### Paso 1: Abrir PowerShell en la carpeta del proyecto
Abra su terminal de PowerShell en:
```powershell
cd C:\wamp64\www\Calculadora-Ecommerce\microsip-api
```
*(O directamente desde `C:\wamp64\www\Calculadora-Ecommerce`).*

### Paso 2: Instalar y preparar el entorno virtual (solo la primera vez)
```powershell
.\install.bat
```

### Paso 3: Iniciar el Servidor y abrir el Dashboard automáticamente
```powershell
.\start.bat
```
*(También puede usar `.\start.ps1` o `.\service.bat`).*

Este comando:
1. Activa automáticamente el entorno virtual `venv`.
2. Inicia el servidor **FastAPI** en el puerto `8000`.
3. Abre automáticamente su navegador web en **`http://localhost:8000`**.

---

## 3. Uso del Dashboard Web (`http://localhost:8000`)

Al abrir **`http://localhost:8000`**, verá el panel de control en Bootstrap 5 con:

1. **Tarjetas de Estado Superior**:
   - **Estado de API**: `ONLINE`
   - **Estado Conexión Firebird**: Indica si el puerto TCP `3050` responde y si ya se autenticó.
   - **IP Configurada**: `192.168.1.5`
   - **Ruta FDB Configurada**: `E:\Microsip datos\CAPACITACION.FDB`
   - **Cantidad de Tablas Encontradas**: Total de tablas descubiertas en la base de datos.

2. **Formulario "Validar Conexión a Firebird"**:
   - Verifique el Servidor (`192.168.1.5`) y la Base (`E:\Microsip datos\CAPACITACION.FDB`).
   - Ingrese su **Usuario** (ej. `SYSDBA`) y **Contraseña**.
   - Presione el botón **"Probar Conexión"**.

3. **Resultado de la Prueba**:
   - Si las credenciales son válidas, mostrará el mensaje **`✅ Conexión Exitosa`** junto con la versión del motor Firebird y la latencia en milisegundos.
   - En la tabla derecha se listarán todas las **tablas encontradas** con su **nombre de tabla**, **cantidad de registros aproximada**, número de columnas y su rol para la **Fase 2 (SKU, Nombre, Último Costo y Existencias)**.

---

## 4. Endpoints Disponibles en esta Fase

| Método | Ruta | Descripción |
| :--- | :--- | :--- |
| `GET` | `/` | Dashboard Web interactivo en Bootstrap 5 (`http://localhost:8000`). |
| `GET` | `/api/health` | Estado de la API, estado de conexión Firebird, IP y ruta FDB configurada. |
| `POST` | `/api/database/test` | Prueba conexión en modo `READ-ONLY` con Usuario/Contraseña y descubre tablas + registros. |
| `GET` | `/api/database/tables` | Devuelve la lista de tablas encontradas y cantidad de registros aproximada. |
| `GET` | `/api/logs` | Devuelve los últimos eventos registrados en `logs/api.log`. |
| `GET` | `/docs` | Documentación interactiva Swagger UI (`http://localhost:8000/docs`). |
