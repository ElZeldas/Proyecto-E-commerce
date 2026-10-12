"""
PUNTO DE ENTRADA PRINCIPAL - MICROSIP ERP READ-ONLY REST API (FASE 1: VALIDACIÓN FIREBIRD)
==========================================================================================
Desarrollada con FastAPI y Python 3.12.
- Dashboard Web Bootstrap: http://localhost:8000
- Página de Depuración:    http://localhost:8000/debug
- Documentación Swagger:   http://localhost:8000/docs
- Endpoints de Validación:
  * GET  /api/health
  * POST /api/database/test
  * GET  /api/database/tables
  * GET  /api/debug
"""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.config import settings
from app.exceptions import register_exception_handlers
from app.logger import api_logger
from app.security_guard import ReadOnlyAndAuditMiddleware
from routers import database_router, health_router, auth_router, articulos_router, almacenes_router

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_INDEX = BASE_DIR / "templates" / "index.html"
TEMPLATE_DEBUG = BASE_DIR / "templates" / "debug.html"
TEMPLATE_ML = BASE_DIR / "templates" / "reporte_ml.html"

OPENAPI_DESCRIPTION = """
## Microsip ERP — Validador de Conectividad Firebird, Diagnóstico y Descubrimiento de Tablas (Fase 1)

Esta versión valida en modo estricto **SOLO LECTURA (`READ ONLY`)**:
1. **Ping al servidor (`192.168.1.5`)** y **Socket al puerto Firebird (`3050`)**.
2. **Prueba automática de ambas cadenas de conexión**:
   - `192.168.1.5:E:\\Microsip datos\\CAPACITACION.FDB`
   - `192.168.1.5/3050:E:\\Microsip datos\\CAPACITACION.FDB`
3. **Compatibilidad dual de drivers**: `firebird-driver` y fallback automático a `fdb`.
4. **Descubrimiento automático** de tablas de `artículos`, `costos`, `inventarios` y `existencias` con su cantidad de registros.
"""

from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="Microsip ERP — Validador Firebird & Descubrimiento (Read-Only)",
    description=OPENAPI_DESCRIPTION,
    version="1.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.add_middleware(ReadOnlyAndAuditMiddleware)
register_exception_handlers(app)

app.include_router(health_router)
app.include_router(database_router)
app.include_router(auth_router)
app.include_router(articulos_router)
app.include_router(almacenes_router)


@app.get(
    "/",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def dashboard_home() -> HTMLResponse:
    """Sirve el Dashboard Web en Bootstrap 5 en http://localhost:8000."""
    return HTMLResponse(content=TEMPLATE_INDEX.read_text(encoding="utf-8"), status_code=200)

@app.get(
    "/almacenes-ml",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def reporte_almacenes_ml() -> HTMLResponse:
    """Sirve la nueva página de Reporte de Almacenes ML."""
    return HTMLResponse(content=TEMPLATE_ML.read_text(encoding="utf-8"), status_code=200)

@app.get(
    "/debug",
    response_class=HTMLResponse,
    tags=["Diagnóstico Técnico"],
    summary="Página visual /debug con versiones de Python, Firebird Driver, FastAPI y configuración",
)
def debug_page() -> HTMLResponse:
    """Sirve la página /debug en http://localhost:8000/debug."""
    return HTMLResponse(content=TEMPLATE_DEBUG.read_text(encoding="utf-8"), status_code=200)


if __name__ == "__main__":
    api_logger.info(
        f"Iniciando Dashboard de Validación Microsip Firebird en http://localhost:{settings.api_port}"
    )
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )
