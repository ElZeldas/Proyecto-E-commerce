"""
Router de Validación de Conexión, Diagnóstico Avanzado y Descubrimiento Automático de Tablas.
Endpoints:
- POST /api/database/test   -> Ejecuta Ping, Socket 3050, prueba ambas cadenas DSN y ambos drivers
                               (firebird-driver y fdb), valida login y descubre todas las tablas.
- GET  /api/database/tables -> Devuelve la lista de tablas encontradas, cantidad de registros
                               y clasificación automática (artículos, costos, inventarios, existencias).
- GET  /api/debug           -> Devuelve información técnica de versiones (Python, Firebird Driver,
                               FastAPI) y configuración cargada.
- GET  /api/logs            -> Devuelve los últimos eventos registrados en logs/api.log.
"""

from __future__ import annotations

import platform
import sys
from typing import Any, Dict, List

import fastapi
from fastapi import APIRouter, Request, status

from app.config import settings
from app.logger import log_audit_event
from database import (
    get_candidate_dsns,
    get_driver_versions_info,
    get_last_connection_state,
)
from inspector import test_connection_and_discover_tables
from models.schemas import (
    DatabaseTablesResponse,
    DatabaseTestRequest,
    DatabaseTestResponse,
)

router = APIRouter(prefix="/api", tags=["2. Validación Firebird, Diagnóstico y Tablas"])


@router.post(
    "/database/test",
    response_model=DatabaseTestResponse,
    status_code=status.HTTP_200_OK,
    summary="Probar conexión a Firebird, ejecutar Diagnóstico Avanzado y descubrir tablas",
    description=(
        "Ejecuta pruebas automáticas contra `192.168.1.5` (`E:\\Microsip datos\\CAPACITACION.FDB`):\n"
        "1. Ping al servidor (`192.168.1.5`)\n"
        "2. Socket al puerto Firebird (`3050`)\n"
        "3. Prueba ambas cadenas de conexión:\n"
        "   - `192.168.1.5:E:\\Microsip datos\\CAPACITACION.FDB`\n"
        "   - `192.168.1.5/3050:E:\\Microsip datos\\CAPACITACION.FDB`\n"
        "4. Compatibilidad automática `firebird-driver` y fallback `fdb`\n"
        "5. Descubrimiento automático de tablas, conteo de registros y clasificación de "
        "`artículos`, `costos`, `inventarios` y `existencias`."
    ),
)
def probar_conexion_firebird(
    payload: DatabaseTestRequest,
    request: Request,
) -> DatabaseTestResponse:
    """Endpoint `POST /api/database/test`."""
    clean_user = (payload.username or settings.db_user or "SISTEMAS").strip()
    request.state.username = clean_user
    ip_origen = request.client.host if request.client else "127.0.0.1"

    try:
        result = test_connection_and_discover_tables(
            username=clean_user,
            password=payload.password if payload.password is not None else settings.db_password,
            host=payload.host or settings.db_host,
            database_path=payload.database_path or settings.db_path,
            save_to_file=True,
        )
    except Exception as exc:
        raw_err = f"{type(exc).__name__}: {exc}"
        log_audit_event(
            endpoint="POST /api/database/test",
            resultado="ERROR_CONEXION",
            usuario=clean_user,
            ip_origen=ip_origen,
            error=raw_err,
        )
        return DatabaseTestResponse(
            success=False,
            mensaje=f"❌ Error específico: {raw_err}",
            api_status="online",
            firebird_status="error",
            host=payload.host or settings.db_host,
            port=settings.db_port,
            database_path=payload.database_path or settings.db_path,
            username=clean_user,
            timestamp="",
            ping_ok=False,
            port_3050_open=False,
            fdb_located=False,
            login_success=False,
            login_rejected=False,
            firebird_raw_error=raw_err,
            checks={},
            dsn_attempts=[],
            total_tables=0,
            tables=[],
        )

    if result["success"]:
        log_audit_event(
            endpoint="POST /api/database/test",
            resultado=(
                f"CONEXION_EXITOSA | DSN={result['active_dsn']} | "
                f"DRIVER={result['active_driver']} | "
                f"TABLAS={result['total_tables']}"
            ),
            usuario=clean_user,
            ip_origen=ip_origen,
        )
    else:
        log_audit_event(
            endpoint="POST /api/database/test",
            resultado="FALLO_DIAGNOSTICO_CONEXION",
            usuario=clean_user,
            ip_origen=ip_origen,
            error=result.get("firebird_raw_error"),
        )

    return DatabaseTestResponse(**result)


@router.get(
    "/database/tables",
    response_model=DatabaseTablesResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener lista de tablas encontradas y cantidad de registros aproximada",
)
def listar_tablas_encontradas(request: Request) -> DatabaseTablesResponse:
    """Endpoint `GET /api/database/tables`."""
    state = get_last_connection_state()

    if not state["connected"] and settings.db_user and settings.db_password:
        try:
            request.state.username = settings.db_user
            test_connection_and_discover_tables(
                username=settings.db_user,
                password=settings.db_password,
                host=settings.db_host,
                database_path=settings.db_path,
                save_to_file=True,
            )
            state = get_last_connection_state()
        except Exception:
            pass

    return DatabaseTablesResponse(
        connected=state["connected"],
        host=state["host"],
        database_path=state["database_path"],
        active_dsn=state["active_dsn"],
        active_driver=state["active_driver"],
        last_tested_at=state["last_tested_at"],
        total_tables=state["total_tables"],
        tables=state["tables"],
        categorized_tables=state["categorized_tables"],
        preparacion_fase2=state["preparacion_fase2"],
    )


@router.get(
    "/debug",
    status_code=status.HTTP_200_OK,
    summary="Obtener información de depuración (Python, Firebird Driver, FastAPI y Configuración)",
)
def get_debug_info() -> Dict[str, Any]:
    """Devuelve toda la información técnica para la página `/debug`."""
    driver_info = get_driver_versions_info()
    state = get_last_connection_state()
    return {
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "architecture": platform.architecture()[0],
        "fastapi_version": fastapi.__version__,
        "firebird_driver_version": driver_info["firebird_driver_version"],
        "fdb_driver_version": driver_info["fdb_version"],
        "fbclient_dll": driver_info["fbclient_dll_path"],
        "configuracion_cargada": {
            "MICROSIP_DB_HOST": settings.db_host,
            "MICROSIP_DB_PORT": settings.db_port,
            "MICROSIP_DB_PATH": settings.db_path,
            "MICROSIP_DB_CHARSET": settings.db_charset,
            "MICROSIP_DB_USER": settings.db_user,
            "MICROSIP_DB_PASSWORD_SET": bool(settings.db_password),
            "CANDIDATE_DSNS": get_candidate_dsns(),
            "LOG_FILE_PATH": str(settings.resolved_log_path),
            "INSPECTION_REPORT_PATH": str(settings.resolved_inspection_report_path),
            "MODE": "STRICT_READ_ONLY",
        },
        "estado_conexion_actual": {
            "connected": state["connected"],
            "active_dsn": state["active_dsn"],
            "active_driver": state["active_driver"],
            "engine_version": state["engine_version"],
            "total_tables": state["total_tables"],
            "last_tested_at": state["last_tested_at"],
        },
    }


@router.get(
    "/logs",
    status_code=status.HTTP_200_OK,
    summary="Consultar últimos registros de bitácora (logs/api.log)",
)
def obtener_ultimos_logs(limit: int = 40) -> Dict[str, Any]:
    """Devuelve las últimas líneas registradas en `logs/api.log`."""
    log_path = settings.resolved_log_path
    lines: List[str] = []
    if log_path.is_file():
        raw_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        lines = [ln for ln in raw_lines if ln.strip() and not ln.startswith("#")][-limit:]
    return {
        "log_file": str(log_path),
        "total_lines": len(lines),
        "entries": list(reversed(lines)),
    }
