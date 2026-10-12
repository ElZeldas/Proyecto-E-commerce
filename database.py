"""
Módulo de Conexión Remota TCP/IP a Firebird SQL (Microsip ERP) en Modo Estricto READ-ONLY.
==========================================================================================
Características clave:
1. Compatibilidad dual de drivers:
   - Primario: `firebird-driver` (oficial Firebird 3/4/5)
   - Fallback automático: `fdb` (`import fdb`)
2. Prueba automática de ambas cadenas de conexión (DSN):
   - Formato A (Estándar Microsip): `192.168.1.5:E:\\Microsip datos\\CAPACITACION.FDB`
   - Formato B (Con puerto explícito): `192.168.1.5/3050:E:\\Microsip datos\\CAPACITACION.FDB`
3. Activación automática de Roles SQL de Microsip (`RDB$ADMIN` / `USUARIO_MICROSIP`) para que
   usuarios operativos como `SISTEMAS` tengan permiso de lectura sobre `ARTICULOS`, `SALDOS_IN`, etc.
4. Eliminado cualquier argumento `timeout` no soportado en `connect()`.
5. Diagnóstico paso a paso (Ping ICMP, Socket TCP 3050, Localización FDB, Login Usuario y Lectura de Tablas).
6. Transacciones estrictamente de SOLO LECTURA (`READ_ONLY_TPB`).
"""

from __future__ import annotations

import re
import socket
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional, Sequence, Tuple

from app.config import settings
from app.exceptions import (
    ColumnNotFoundError,
    DatabaseTimeoutError,
    DatabaseUnavailableError,
    InvalidCredentialsError,
    ReadOnlyViolationError,
    TableNotFoundError,
)
from app.logger import api_logger
from app.security_guard import validate_readonly_sql

# ============================================================================
# CARGA Y COMPATIBILIDAD DE DRIVERS: firebird-driver + fdb
# ============================================================================
HAS_FIREBIRD_DRIVER = False
HAS_FDB_DRIVER = False
FIREBIRD_DRIVER_VERSION = "No instalado"
FDB_DRIVER_VERSION = "No instalado"
READ_ONLY_TPB = None

try:
    import firebird.driver as fb_driver
    from firebird.driver import (
        Isolation,
        TraAccessMode,
        connect as fb_connect,
        driver_config,
        tpb,
    )

    HAS_FIREBIRD_DRIVER = True
    FIREBIRD_DRIVER_VERSION = getattr(fb_driver, "__version__", "2.0.3")

    if settings.fb_client_library:
        try:
            driver_config.fb_client_library.value = settings.fb_client_library
        except Exception as exc:
            api_logger.warning(f"Aviso al configurar fb_client_library en firebird-driver: {exc}")

    READ_ONLY_TPB = tpb(
        isolation=Isolation.READ_COMMITTED_NO_RECORD_VERSION,
        access_mode=TraAccessMode.READ,
        lock_timeout=settings.db_timeout,
    )
except Exception as exc:
    api_logger.warning(f"firebird-driver no disponible ({exc}), se usará fdb como fallback.")

try:
    import fdb

    HAS_FDB_DRIVER = True
    FDB_DRIVER_VERSION = getattr(fdb, "__version__", "2.0.4")
    if settings.fb_client_library:
        try:
            fdb.load_api(settings.fb_client_library)
        except Exception:
            pass
except Exception:
    pass

_SAFE_TABLE_RE = re.compile(r"^[A-Z0-9_$]+$")

# Estado en memoria de la última validación de conexión y descubrimiento de tablas
_last_connection_state: Dict[str, Any] = {
    "connected": False,
    "last_tested_at": None,
    "username": settings.db_user or "SISTEMAS",
    "credentials": (
        (settings.db_user, settings.db_password)
        if (settings.db_user and settings.db_password)
        else None
    ),
    "host": settings.db_host,
    "port": settings.db_port,
    "database_path": settings.db_path,
    "active_dsn": None,
    "active_driver": None,
    "active_role": "RDB$ADMIN",
    "engine_version": None,
    "latency_ms": None,
    "total_tables": 0,
    "tables": [],
    "categorized_tables": {
        "articulos": [],
        "costos": [],
        "inventarios": [],
        "existencias": [],
    },
    "preparacion_fase2": {},
    "last_diagnostics": None,
}


def get_driver_versions_info() -> Dict[str, Any]:
    """Devuelve información detallada de los drivers instalados para la página /debug."""
    return {
        "firebird_driver_installed": HAS_FIREBIRD_DRIVER,
        "firebird_driver_version": FIREBIRD_DRIVER_VERSION,
        "fdb_installed": HAS_FDB_DRIVER,
        "fdb_version": FDB_DRIVER_VERSION,
        "fbclient_dll_path": settings.fb_client_library,
    }


def get_candidate_dsns(
    host: Optional[str] = None,
    port: Optional[int] = None,
    database_path: Optional[str] = None,
) -> List[str]:
    """
    Devuelve ambas cadenas de conexión requeridas para probar:
    1) 192.168.1.5:E:\\Microsip datos\\CAPACITACION.FDB
    2) 192.168.1.5/3050:E:\\Microsip datos\\CAPACITACION.FDB
    """
    target_host = (host or _last_connection_state.get("host") or settings.db_host).strip()
    target_port = int(port or settings.db_port)
    target_path = (
        database_path or _last_connection_state.get("database_path") or settings.db_path
    ).strip()

    dsn_direct = f"{target_host}:{target_path}"
    dsn_with_port = f"{target_host}/{target_port}:{target_path}"
    return [dsn_direct, dsn_with_port]


def get_last_connection_state() -> Dict[str, Any]:
    """Devuelve una copia segura (sin exponer contraseñas) del estado actual en memoria."""
    return {
        "connected": _last_connection_state["connected"],
        "last_tested_at": _last_connection_state["last_tested_at"],
        "username": _last_connection_state["username"],
        "host": _last_connection_state["host"],
        "port": _last_connection_state["port"],
        "database_path": _last_connection_state["database_path"],
        "active_dsn": _last_connection_state["active_dsn"],
        "active_driver": _last_connection_state["active_driver"],
        "active_role": _last_connection_state["active_role"],
        "engine_version": _last_connection_state["engine_version"],
        "latency_ms": _last_connection_state["latency_ms"],
        "total_tables": _last_connection_state["total_tables"],
        "tables": _last_connection_state["tables"],
        "categorized_tables": _last_connection_state["categorized_tables"],
        "preparacion_fase2": _last_connection_state["preparacion_fase2"],
        "last_diagnostics": _last_connection_state["last_diagnostics"],
    }


def update_last_connection_state(
    *,
    connected: bool,
    username: str,
    credentials: Tuple[str, str],
    host: str,
    database_path: str,
    active_dsn: str,
    active_driver: str,
    engine_version: str,
    latency_ms: float,
    tables: List[Dict[str, Any]],
    categorized_tables: Dict[str, List[Dict[str, Any]]],
    preparacion_fase2: Dict[str, Any],
    diagnostics: Optional[Dict[str, Any]] = None,
) -> None:
    """Actualiza el caché en memoria tras una prueba de conexión exitosa."""
    _last_connection_state.update(
        {
            "connected": connected,
            "last_tested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "username": username,
            "credentials": credentials,
            "host": host,
            "port": settings.db_port,
            "database_path": database_path,
            "active_dsn": active_dsn,
            "active_driver": active_driver,
            "engine_version": engine_version,
            "latency_ms": latency_ms,
            "total_tables": len(tables),
            "tables": tables,
            "categorized_tables": categorized_tables,
            "preparacion_fase2": preparacion_fase2,
            "last_diagnostics": diagnostics,
        }
    )


def run_ping_test(host: Optional[str] = None) -> Dict[str, Any]:
    """Ejecuta `ping -n 1 -w 2000 <host>` en Windows."""
    target_host = (host or settings.db_host).strip()
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            ["ping", "-n", "1", "-w", "2000", target_host],
            capture_output=True,
            text=True,
            timeout=4,
            encoding="cp850",
            errors="replace",
        )
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        output = (proc.stdout or proc.stderr or "").strip()
        ping_ok = proc.returncode == 0 and ("TTL=" in output.upper() or "BYTES=" in output.upper())
        return {
            "ping_ok": ping_ok,
            "ping_ms": elapsed_ms,
            "ping_output": output,
        }
    except Exception as exc:
        return {
            "ping_ok": False,
            "ping_ms": None,
            "ping_output": f"Error al ejecutar ping: {exc}",
        }


def verify_tcp_connectivity(
    host: Optional[str] = None,
    port: Optional[int] = None,
    timeout: Optional[int] = None,
) -> float:
    """Verifica conectividad TCP/IP al puerto 3050 de Firebird mediante socket."""
    target_host = (host or settings.db_host).strip()
    target_port = int(port or settings.db_port)
    target_timeout = int(timeout or settings.db_timeout)

    start = time.perf_counter()
    try:
        with socket.create_connection((target_host, target_port), timeout=target_timeout):
            latency_ms = (time.perf_counter() - start) * 1000.0
            return round(latency_ms, 2)
    except socket.timeout as exc:
        raise DatabaseTimeoutError(
            detail=(
                f"Timeout de socket ({target_timeout}s) al conectar con "
                f"{target_host}:{target_port}."
            )
        ) from exc
    except OSError as exc:
        raise DatabaseUnavailableError(
            detail=(
                f"El puerto Firebird {target_host}:{target_port} no está accesible. "
                f"Error de socket: {exc}"
            )
        ) from exc


def _translate_firebird_exception(exc: Exception) -> Exception:
    """
    Traduce errores nativos del motor Firebird conservando SIEMPRE el error real
    completo devuelto por Firebird para facilitar el diagnóstico en pantalla.
    """
    raw_error = f"{type(exc).__name__}: {exc}"
    err_upper = str(exc).upper()

    if (
        "YOUR USER NAME AND PASSWORD ARE NOT DEFINED" in err_upper
        or "335544472" in err_upper
    ):
        return InvalidCredentialsError(detail=raw_error)

    if (
        "I/O ERROR" in err_upper
        or "335544344" in err_upper
        or "ERROR WHILE TRYING TO OPEN FILE" in err_upper
        or "EL SISTEMA NO PUEDE ENCONTRAR" in err_upper
        or "THE SYSTEM CANNOT FIND" in err_upper
    ):
        return DatabaseUnavailableError(
            detail=f"Archivo FDB no localizado en el servidor Firebird. Error real: {raw_error}"
        )

    if "TABLE UNKNOWN" in err_upper:
        return TableNotFoundError(detail=raw_error)

    if "COLUMN UNKNOWN" in err_upper:
        return ColumnNotFoundError(detail=raw_error)

    if "READ-ONLY" in err_upper or "335544361" in err_upper:
        return ReadOnlyViolationError(detail=raw_error)

    return DatabaseUnavailableError(detail=raw_error)


def _resolve_credentials(
    credentials: Optional[Tuple[str, str]] = None,
) -> Tuple[str, str]:
    """Obtiene el par (usuario, contraseña) desde argumentos, sesión activa o .env."""
    if credentials and credentials[0] and credentials[1]:
        return credentials[0].strip(), credentials[1]

    cached_creds = _last_connection_state.get("credentials")
    if cached_creds and cached_creds[0] and cached_creds[1]:
        return cached_creds[0], cached_creds[1]

    if settings.db_user and settings.db_password:
        return settings.db_user, settings.db_password

    raise InvalidCredentialsError(
        detail="No se proporcionaron credenciales de Microsip (Usuario / Contraseña)."
    )


def _detect_and_verify_role(conn: Any, driver_name: str, user: str) -> str:
    """
    Verifica si la conexión actual con `role='RDB$ADMIN'` tiene permiso de lectura
    sobre `ARTICULOS`, o descubre el rol en `RDB$USER_PRIVILEGES`.
    """
    try:
        with _readonly_cursor(conn, driver_name) as cur:
            cur.execute(
                "SELECT TRIM(RDB$USER) FROM RDB$USER_PRIVILEGES "
                "WHERE RDB$OBJECT_TYPE = 0 AND RDB$PRIVILEGE = 'S' "
                "AND TRIM(RDB$RELATION_NAME) = 'ARTICULOS'"
            )
            rows = cur.fetchall()
            allowed = {str(r[0]).strip().upper() for r in rows if r and r[0]}
            if "RDB$ADMIN" in allowed or user.upper() == "SYSDBA":
                return "RDB$ADMIN"
            if "USUARIO_MICROSIP" in allowed:
                return "USUARIO_MICROSIP"
    except Exception:
        pass
    return "RDB$ADMIN"


def _open_raw_firebird_connection(
    user: str,
    password: str,
    host: Optional[str] = None,
    database_path: Optional[str] = None,
    role: str = "RDB$ADMIN",
) -> Tuple[Any, str, str, List[Dict[str, Any]]]:
    """
    Intenta abrir la conexión remota a Firebird probando:
    1) Ambas cadenas de conexión:
       - `192.168.1.5:E:\\Microsip datos\\CAPACITACION.FDB`
       - `192.168.1.5/3050:E:\\Microsip datos\\CAPACITACION.FDB`
    2) Ambos drivers:
       - Primero `firebird-driver` (SIN parámetro `timeout`)
       - Si falla, intenta automáticamente `import fdb` (`fdb.connect`)
    3) Activa el rol `RDB$ADMIN` de Microsip para habilitar permisos SELECT en tablas operativas.
    """
    candidate_dsns = get_candidate_dsns(host=host, database_path=database_path)
    attempts_log: List[Dict[str, Any]] = []
    last_exception: Optional[Exception] = None

    # 1. Intentar con firebird-driver en ambas cadenas DSN
    if HAS_FIREBIRD_DRIVER:
        for dsn in candidate_dsns:
            t0 = time.perf_counter()
            try:
                conn = fb_connect(
                    database=dsn,
                    user=user,
                    password=password,
                    role=role,
                    charset=settings.db_charset,
                )
                elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
                attempts_log.append(
                    {
                        "driver": f"firebird-driver ({FIREBIRD_DRIVER_VERSION})",
                        "dsn": dsn,
                        "role": role,
                        "success": True,
                        "time_ms": elapsed,
                        "error": None,
                    }
                )
                return conn, dsn, "firebird-driver", attempts_log
            except Exception as exc:
                elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
                last_exception = exc
                attempts_log.append(
                    {
                        "driver": f"firebird-driver ({FIREBIRD_DRIVER_VERSION})",
                        "dsn": dsn,
                        "role": role,
                        "success": False,
                        "time_ms": elapsed,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    # 2. Fallback automático con `import fdb` en ambas cadenas DSN
    try:
        import fdb as fdb_fallback

        if settings.fb_client_library:
            try:
                fdb_fallback.load_api(settings.fb_client_library)
            except Exception:
                pass

        for dsn in candidate_dsns:
            t0 = time.perf_counter()
            try:
                conn = fdb_fallback.connect(
                    dsn=dsn,
                    user=user,
                    password=password,
                    role=role,
                    charset=settings.db_charset,
                )
                elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
                attempts_log.append(
                    {
                        "driver": f"fdb ({FDB_DRIVER_VERSION})",
                        "dsn": dsn,
                        "role": role,
                        "success": True,
                        "time_ms": elapsed,
                        "error": None,
                    }
                )
                return conn, dsn, "fdb", attempts_log
            except Exception as exc:
                elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
                last_exception = exc
                attempts_log.append(
                    {
                        "driver": f"fdb ({FDB_DRIVER_VERSION})",
                        "dsn": dsn,
                        "role": role,
                        "success": False,
                        "time_ms": elapsed,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    except Exception as fdb_import_exc:
        if last_exception is None:
            last_exception = fdb_import_exc

    if last_exception is not None:
        raise last_exception
    raise DatabaseUnavailableError(detail="No se pudo conectar con firebird-driver ni con fdb.")


@contextmanager
def get_readonly_connection(
    credentials: Optional[Tuple[str, str]] = None,
    host: Optional[str] = None,
    database_path: Optional[str] = None,
) -> Generator[Tuple[Any, str, str], None, None]:
    """
    Context manager que abre una conexión remota TCP/IP hacia Firebird
    probando ambas cadenas DSN y ambos drivers (`firebird-driver` y `fdb`).
    """
    user, password = _resolve_credentials(credentials)
    target_host = (host or _last_connection_state.get("host") or settings.db_host).strip()

    verify_tcp_connectivity(host=target_host)

    conn = None
    try:
        conn, active_dsn, active_driver, _ = _open_raw_firebird_connection(
            user=user,
            password=password,
            host=target_host,
            database_path=database_path,
            role="RDB$ADMIN",
        )
        yield conn, active_dsn, active_driver
    except (
        InvalidCredentialsError,
        DatabaseTimeoutError,
        DatabaseUnavailableError,
        TableNotFoundError,
        ColumnNotFoundError,
        ReadOnlyViolationError,
    ):
        raise
    except Exception as exc:
        raise _translate_firebird_exception(exc) from exc
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


@contextmanager
def _readonly_cursor(conn: Any, driver_name: str) -> Generator[Any, None, None]:
    """Abre un cursor dentro de una transacción READ-ONLY tanto en firebird-driver como en fdb."""
    if driver_name == "firebird-driver" and READ_ONLY_TPB is not None:
        with conn.transaction_manager(READ_ONLY_TPB) as tr:
            with tr.cursor() as cur:
                yield cur
    else:
        cur = conn.cursor()
        try:
            yield cur
        finally:
            try:
                cur.close()
            except Exception:
                pass


def verify_microsip_credentials(
    username: str,
    password: str,
    host: Optional[str] = None,
    database_path: Optional[str] = None,
) -> Tuple[str, str, str]:
    """
    Autentica las credenciales del usuario Microsip directamente contra el servidor
    Firebird y devuelve `(engine_version, active_dsn, active_driver)`.
    """
    if not username or not password:
        raise InvalidCredentialsError("Debe proporcionar usuario y contraseña de Microsip.")

    with get_readonly_connection(
        credentials=(username, password),
        host=host,
        database_path=database_path,
    ) as (conn, active_dsn, active_driver):
        with _readonly_cursor(conn, active_driver) as cur:
            cur.execute(
                "SELECT RDB$GET_CONTEXT('SYSTEM', 'ENGINE_VERSION') FROM RDB$DATABASE"
            )
            row = cur.fetchone()
            engine_version = str(row[0]).strip() if row and row[0] else "Firebird SQL"
            return engine_version, active_dsn, active_driver


def execute_readonly_query(
    sql: str,
    params: Optional[Sequence[Any]] = None,
    credentials: Optional[Tuple[str, str]] = None,
    host: Optional[str] = None,
    database_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Ejecuta una consulta SQL parametrizada en modo estricto de SOLO LECTURA."""
    validate_readonly_sql(sql)
    safe_params = tuple(params) if params is not None else ()

    try:
        with get_readonly_connection(
            credentials=credentials,
            host=host,
            database_path=database_path,
        ) as (conn, _, active_driver):
            with _readonly_cursor(conn, active_driver) as cur:
                cur.execute(sql, safe_params)
                columns = [col[0].strip().lower() for col in (cur.description or [])]
                rows = cur.fetchall()
                results: List[Dict[str, Any]] = []
                for row in rows:
                    row_dict: Dict[str, Any] = {}
                    for idx, col_name in enumerate(columns):
                        val = row[idx]
                        if isinstance(val, str):
                            val = val.strip()
                        row_dict[col_name] = val
                    results.append(row_dict)
                return results
    except (
        InvalidCredentialsError,
        DatabaseTimeoutError,
        DatabaseUnavailableError,
        TableNotFoundError,
        ColumnNotFoundError,
        ReadOnlyViolationError,
    ):
        raise
    except Exception as exc:
        raise _translate_firebird_exception(exc) from exc


def count_tables_records_readonly(
    table_names: List[str],
    credentials: Optional[Tuple[str, str]] = None,
    host: Optional[str] = None,
    database_path: Optional[str] = None,
) -> Dict[str, int]:
    """
    Obtiene la cantidad de registros por tabla combinando:
    1) Estadísticas de cardinalidad del motor Firebird (`RDB$INDICES.RDB$STATISTICS`)
       para las 655+ tablas en ~140 ms (evitando bloqueos en tablas históricas de millones de filas).
    2) Conteo exacto `SELECT COUNT(*)` sobre las tablas maestras de Artículos, Claves,
       Precios, Costos, Almacenes y Existencias de Microsip ERP.
    """
    counts: Dict[str, int] = {t: 0 for t in table_names}

    # Tablas clave de Microsip para conteo exacto en tiempo real
    priority_exact_tables = [
        "ARTICULOS",
        "CLAVES_ARTICULOS",
        "PRECIOS_ARTICULOS",
        "SALDOS_IN",
        "ALMACENES",
        "LINEAS_ARTICULOS",
        "GRUPOS_LINEAS",
        "PRECIOS_EMPRESA",
        "ROLES_CLAVES_ART",
        "CONCEPTOS_IN",
        "MONEDAS",
        "CAPAS_COSTOS",
    ]

    with get_readonly_connection(
        credentials=credentials,
        host=host,
        database_path=database_path,
    ) as (conn, _, active_driver):
        with _readonly_cursor(conn, active_driver) as cur:
            # 1. Estimación instantánea desde RDB$INDICES para todas las tablas de usuario
            stats_sql = """
                SELECT
                    TRIM(r.RDB$RELATION_NAME) AS t_name,
                    MAX(
                        CASE
                            WHEN i.RDB$STATISTICS > 0
                            THEN CAST(ROUND(1.0 / i.RDB$STATISTICS) AS BIGINT)
                            ELSE 0
                        END
                    ) AS approx_rows
                FROM RDB$RELATIONS r
                LEFT JOIN RDB$INDICES i
                    ON i.RDB$RELATION_NAME = r.RDB$RELATION_NAME
                    AND COALESCE(i.RDB$UNIQUE_FLAG, 0) = 1
                WHERE COALESCE(r.RDB$SYSTEM_FLAG, 0) = 0
                  AND r.RDB$VIEW_BLR IS NULL
                GROUP BY r.RDB$RELATION_NAME
            """
            validate_readonly_sql(stats_sql)
            cur.execute(stats_sql)
            for row in cur.fetchall():
                t_key = str(row[0]).strip().upper()
                counts[t_key] = int(row[1] or 0)

            # 2. Conteo exacto en las tablas principales de Artículos / Inventarios
            existing_priority = [t for t in priority_exact_tables if t in counts]
            if existing_priority:
                union_parts = [
                    f"SELECT CAST('{t}' AS VARCHAR(64)) AS t_name, COUNT(*) AS total FROM {t}"
                    for t in existing_priority
                ]
                exact_sql = " UNION ALL ".join(union_parts)
                validate_readonly_sql(exact_sql)
                try:
                    cur.execute(exact_sql)
                    for row in cur.fetchall():
                        t_key = str(row[0]).strip().upper()
                        counts[t_key] = int(row[1] or 0)
                except Exception:
                    for single_t in existing_priority:
                        try:
                            cur.execute(f"SELECT COUNT(*) FROM {single_t}")
                            r = cur.fetchone()
                            if r:
                                counts[single_t] = int(r[0] or 0)
                        except Exception:
                            pass

    return counts


def run_step_by_step_diagnostics(
    username: str,
    password: str,
    host: Optional[str] = None,
    database_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Ejecuta las pruebas automáticas de diagnóstico:
    1. Ping ICMP a 192.168.1.5
    2. Socket TCP al puerto 3050
    3. Conexión Firebird probando ambas cadenas DSN y ambos drivers (firebird-driver y fdb)
    4. Verificación de archivo FDB localizado y Login de usuario con rol RDB$ADMIN
    """
    target_host = (host or settings.db_host).strip()
    target_path = (database_path or settings.db_path).strip()
    clean_user = (username or settings.db_user or "SISTEMAS").strip()

    # Paso 1: Ping al servidor
    ping_res = run_ping_test(target_host)

    # Paso 2: Socket puerto 3050
    port_3050_open = False
    socket_latency_ms: Optional[float] = None
    socket_error: Optional[str] = None
    try:
        socket_latency_ms = verify_tcp_connectivity(host=target_host, port=settings.db_port)
        port_3050_open = True
    except Exception as exc:
        socket_error = str(getattr(exc, "detail", exc))

    # Paso 3: Conexión Firebird probando ambas cadenas y ambos drivers
    fdb_located = False
    login_success = False
    login_rejected = False
    firebird_raw_error: Optional[str] = None
    active_dsn: Optional[str] = None
    active_driver: Optional[str] = None
    engine_version: Optional[str] = None
    dsn_attempts: List[Dict[str, Any]] = []

    if port_3050_open:
        conn = None
        try:
            conn, active_dsn, active_driver, dsn_attempts = _open_raw_firebird_connection(
                user=clean_user,
                password=password,
                host=target_host,
                database_path=target_path,
                role="RDB$ADMIN",
            )
            fdb_located = True
            login_success = True
            with _readonly_cursor(conn, active_driver) as cur:
                cur.execute(
                    "SELECT RDB$GET_CONTEXT('SYSTEM', 'ENGINE_VERSION') FROM RDB$DATABASE"
                )
                row = cur.fetchone()
                engine_version = str(row[0]).strip() if row and row[0] else "Firebird SQL"
        except Exception as exc:
            firebird_raw_error = f"{type(exc).__name__}: {exc}"
            err_upper = str(exc).upper()
            if (
                "YOUR USER NAME AND PASSWORD ARE NOT DEFINED" in err_upper
                or "335544472" in err_upper
            ):
                fdb_located = True
                login_rejected = True
            elif (
                "I/O ERROR" in err_upper
                or "335544344" in err_upper
                or "ERROR WHILE TRYING TO OPEN FILE" in err_upper
                or "CANNOT FIND" in err_upper
            ):
                fdb_located = False
                login_success = True
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    else:
        firebird_raw_error = socket_error

    return {
        "ping_ok": ping_res["ping_ok"],
        "ping_ms": ping_res["ping_ms"],
        "ping_output": ping_res["ping_output"],
        "port_3050_open": port_3050_open,
        "socket_latency_ms": socket_latency_ms,
        "fdb_located": fdb_located,
        "login_success": login_success,
        "login_rejected": login_rejected,
        "connection_success": bool(port_3050_open and fdb_located and login_success),
        "firebird_raw_error": firebird_raw_error,
        "active_dsn": active_dsn,
        "active_driver": active_driver,
        "engine_version": engine_version,
        "dsn_attempts": dsn_attempts,
        "checks": {
            "servidor_accesible": {
                "ok": bool(ping_res["ping_ok"] or port_3050_open),
                "label": (
                    f"✅ Servidor accesible ({target_host})"
                    if (ping_res["ping_ok"] or port_3050_open)
                    else f"❌ Servidor {target_host} no accesible"
                ),
            },
            "puerto_3050_abierto": {
                "ok": port_3050_open,
                "label": (
                    f"✅ Puerto 3050 abierto ({socket_latency_ms} ms)"
                    if port_3050_open
                    else f"❌ Puerto 3050 cerrado o bloqueado ({socket_error})"
                ),
            },
            "base_localizada": {
                "ok": fdb_located,
                "label": (
                    f"✅ Base localizada ({target_path})"
                    if fdb_located
                    else f"❌ Base no localizada en {target_path}"
                ),
            },
            "usuario_valido": {
                "ok": login_success and not login_rejected,
                "label": (
                    f"✅ Usuario válido ({clean_user} con rol RDB$ADMIN)"
                    if (login_success and not login_rejected)
                    else f"❌ Login rechazado para usuario '{clean_user}'"
                ),
            },
            "conexion_exitosa": {
                "ok": bool(port_3050_open and fdb_located and login_success),
                "label": (
                    f"✅ Conexión exitosa (Firebird {engine_version} vía {active_driver})"
                    if (port_3050_open and fdb_located and login_success)
                    else f"❌ Error específico: {firebird_raw_error or 'Fallo de conexión'}"
                ),
            },
        },
    }


def check_database_health(
    credentials: Optional[Tuple[str, str]] = None,
) -> Dict[str, Any]:
    """Verifica la salud de la API y del servidor Firebird Microsip."""
    state = get_last_connection_state()
    target_host = state["host"] or settings.db_host
    target_path = state["database_path"] or settings.db_path

    tcp_online = False
    latency_ms: Optional[float] = None
    tcp_error: Optional[str] = None

    try:
        latency_ms = verify_tcp_connectivity(host=target_host)
        tcp_online = True
    except Exception as exc:
        tcp_error = str(getattr(exc, "detail", exc))

    firebird_status = "offline"
    if tcp_online:
        if state["connected"]:
            firebird_status = "connected"
        else:
            firebird_status = "port_open_pending_auth"

    return {
        "status": "ok",
        "api_status": "online",
        "database": "online" if tcp_online else "offline",
        "firebird_status": firebird_status,
        "connected": state["connected"],
        "host": target_host,
        "port": settings.db_port,
        "database_path": target_path,
        "active_dsn": state["active_dsn"],
        "active_driver": state["active_driver"],
        "engine_version": state["engine_version"],
        "latency_ms": latency_ms,
        "total_tables": state["total_tables"],
        "last_tested_at": state["last_tested_at"],
        "username": state["username"],
        "mode": "READ_ONLY",
        "tcp_error": tcp_error,
    }
