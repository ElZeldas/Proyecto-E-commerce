"""
FASE 1 - INSPECCIÓN AUTOMÁTICA, DIAGNÓSTICO Y DESCUBRIMIENTO DE TABLAS FIREBIRD (MICROSIP ERP)
==============================================================================================
Módulo `inspector.py` que:
1. Ejecuta pruebas automáticas (Ping ICMP, Socket TCP 3050, Conexión Firebird con ambas cadenas DSN
   y ambos drivers `firebird-driver` / `fdb`, y Lectura de Tablas).
2. Lista automáticamente todas las tablas de usuario y sus columnas sin solicitar tablas manualmente.
3. Calcula la cantidad de registros por tabla.
4. Descubre automáticamente las tablas de:
   - artículos
   - costos
   - inventarios
   - existencias
5. Devuelve el error real completo de Firebird si ocurre cualquier fallo.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.logger import api_logger, log_audit_event
from database import (
    count_tables_records_readonly,
    execute_readonly_query,
    run_step_by_step_diagnostics,
    update_last_connection_state,
)

TARGET_KEYWORDS: List[str] = [
    "ARTICULO",
    "ARTICULOS",
    "INVENTARIO",
    "EXISTENCIA",
    "COSTO",
    "COSTOS",
    "PRECIO",
    "PRECIOS",
    "CLAVE",
    "NOMBRE",
    "SKU",
    "SALDOS_IN",
    "ALMACEN",
]


def _format_firebird_type(
    field_type: Optional[int],
    field_sub_type: Optional[int],
    field_length: Optional[int],
    field_precision: Optional[int],
    field_scale: Optional[int],
    char_length: Optional[int],
) -> str:
    """Traduce los códigos internos de RDB$FIELDS de Firebird al nombre legible del tipo SQL."""
    scale = abs(field_scale) if field_scale is not None and field_scale < 0 else 0
    prec = field_precision or 18

    if field_type in (7, 8, 16) and (field_sub_type in (1, 2) or scale > 0):
        kind = "DECIMAL" if field_sub_type == 2 else "NUMERIC"
        return f"{kind}({prec},{scale})"

    type_map = {
        7: "SMALLINT",
        8: "INTEGER",
        10: "FLOAT",
        12: "DATE",
        13: "TIME",
        14: f"CHAR({char_length or field_length or 1})",
        16: "BIGINT",
        23: "BOOLEAN",
        27: "DOUBLE PRECISION",
        35: "TIMESTAMP",
        37: f"VARCHAR({char_length or field_length or 1})",
        261: "BLOB",
    }
    return type_map.get(field_type or 0, f"FIREBIRD_TYPE_{field_type}")


def fetch_all_user_tables_and_columns(
    credentials: Optional[Tuple[str, str]] = None,
    host: Optional[str] = None,
    database_path: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Consulta el catálogo del sistema de Firebird (RDB$RELATIONS, RDB$RELATION_FIELDS, RDB$FIELDS)
    para obtener todas las tablas de usuario y sus columnas sin asumir ningún nombre de tabla.
    """
    catalog_sql = """
        SELECT
            TRIM(r.RDB$RELATION_NAME) AS table_name,
            TRIM(rf.RDB$FIELD_NAME) AS column_name,
            rf.RDB$FIELD_POSITION AS column_position,
            f.RDB$FIELD_TYPE AS field_type,
            f.RDB$FIELD_SUB_TYPE AS field_sub_type,
            f.RDB$FIELD_LENGTH AS field_length,
            f.RDB$FIELD_PRECISION AS field_precision,
            f.RDB$FIELD_SCALE AS field_scale,
            f.RDB$CHARACTER_LENGTH AS character_len,
            COALESCE(rf.RDB$NULL_FLAG, 0) AS not_null
        FROM RDB$RELATIONS r
        JOIN RDB$RELATION_FIELDS rf
            ON r.RDB$RELATION_NAME = rf.RDB$RELATION_NAME
        JOIN RDB$FIELDS f
            ON rf.RDB$FIELD_SOURCE = f.RDB$FIELD_NAME
        WHERE COALESCE(r.RDB$SYSTEM_FLAG, 0) = 0
          AND r.RDB$VIEW_BLR IS NULL
        ORDER BY r.RDB$RELATION_NAME, rf.RDB$FIELD_POSITION
    """
    rows = execute_readonly_query(
        catalog_sql,
        credentials=credentials,
        host=host,
        database_path=database_path,
    )

    tables_map: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        t_name = str(row["table_name"]).strip().upper()
        c_name = str(row["column_name"]).strip().upper()
        data_type = _format_firebird_type(
            field_type=row.get("field_type"),
            field_sub_type=row.get("field_sub_type"),
            field_length=row.get("field_length"),
            field_precision=row.get("field_precision"),
            field_scale=row.get("field_scale"),
            char_length=row.get("character_len"),
        )
        tables_map.setdefault(t_name, []).append(
            {
                "campo": c_name,
                "tipo_dato": data_type,
                "posicion": row.get("column_position", 0),
                "not_null": bool(row.get("not_null")),
            }
        )

    return tables_map


def _discover_domain_categories(
    tables_map: Dict[str, List[Dict[str, Any]]],
    row_counts: Dict[str, int],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Descubre automáticamente las tablas de Microsip correspondientes a:
    - artículos
    - costos
    - inventarios
    - existencias
    """
    articulos_tables: List[Dict[str, Any]] = []
    costos_tables: List[Dict[str, Any]] = []
    inventarios_tables: List[Dict[str, Any]] = []
    existencias_tables: List[Dict[str, Any]] = []

    for t_name, cols in sorted(tables_map.items()):
        col_names = {c["campo"] for c in cols}
        cnt = row_counts.get(t_name, 0)
        entry = {
            "tabla": t_name,
            "registros": cnt,
            "columnas": len(cols),
        }

        # 1. Artículos (ARTICULOS, CLAVES_ARTICULOS, LINEAS_ARTICULOS, GRUPOS_LINEAS, etc.)
        if (
            "ARTICULO" in t_name
            or "CLAVES_ART" in t_name
            or "LINEAS_ART" in t_name
            or ("ARTICULO_ID" in col_names and ("NOMBRE" in col_names or "CLAVE_ARTICULO" in col_names))
        ):
            articulos_tables.append(entry)

        # 2. Costos y Precios (SALDOS_IN, PRECIOS_ARTICULOS, COSTOS_ARTICULOS, CAPAS_COSTOS, DOCTOS_IN_DET, DOCTOS_CM_DET)
        if (
            "COSTO" in t_name
            or "PRECIO" in t_name
            or any(k in col_names for k in ("ULTIMO_COSTO", "COSTO_UNITARIO", "PRECIO", "PRECIO_UNITARIO", "ENTRADAS_COSTO"))
        ):
            costos_tables.append(entry)

        # 3. Inventarios (DOCTOS_IN, DOCTOS_IN_DET, ALMACENES, CONCEPTOS_IN, SUB_MOVTOS_IN, etc.)
        if (
            t_name.endswith("_IN")
            or "_IN_" in t_name
            or "ALMACEN" in t_name
            or "INVENTARIO" in t_name
            or "ALMACEN_ID" in col_names
        ):
            inventarios_tables.append(entry)

        # 4. Existencias (SALDOS_IN, CAPAS_COSTOS, CAPAS_PEDIMENTOS, DESGLOSE_EN_DISCRETOS, etc.)
        if (
            t_name in ("SALDOS_IN", "CAPAS_COSTOS", "CAPAS_PEDIMENTOS", "ARTICULOS_DISCRETOS")
            or "EXISTENCIA" in t_name
            or ("ENTRADAS_UNIDADES" in col_names and "SALIDAS_UNIDADES" in col_names)
            or any("EXISTENCIA" in c or "SALDO" in c for c in col_names)
        ):
            existencias_tables.append(entry)

    # Ordenar priorizando las tablas que tienen registros activos
    articulos_tables.sort(key=lambda x: (x["tabla"] not in ("ARTICULOS", "CLAVES_ARTICULOS"), -x["registros"]))
    costos_tables.sort(key=lambda x: (x["tabla"] not in ("PRECIOS_ARTICULOS", "SALDOS_IN", "DOCTOS_IN_DET"), -x["registros"]))
    inventarios_tables.sort(key=lambda x: (x["tabla"] not in ("SALDOS_IN", "ALMACENES", "DOCTOS_IN", "DOCTOS_IN_DET"), -x["registros"]))
    existencias_tables.sort(key=lambda x: (x["tabla"] not in ("SALDOS_IN", "CAPAS_COSTOS"), -x["registros"]))

    return {
        "articulos": articulos_tables,
        "costos": costos_tables,
        "inventarios": inventarios_tables,
        "existencias": existencias_tables,
    }


def _classify_table_role(table_name: str, col_names: set[str]) -> Tuple[bool, str]:
    """Determina si una tabla es clave en Microsip para Artículos, Costos, Inventarios o Existencias."""
    t = table_name.upper()
    if t == "ARTICULOS":
        return True, "Catálogo Maestro de Artículos (Nombre)"
    if t == "CLAVES_ARTICULOS":
        return True, "Claves y SKU de Artículos"
    if t == "PRECIOS_ARTICULOS":
        return True, "Precios de Venta de Artículos"
    if t == "SALDOS_IN":
        return True, "Existencias Actuales y Último Costo"
    if t in ("DOCTOS_IN", "DOCTOS_IN_DET"):
        return True, "Movimientos y Costos de Inventario"
    if t in ("DOCTOS_CM", "DOCTOS_CM_DET"):
        return True, "Compras y Último Costo"
    if t in ("ALMACENES", "LINEAS_ARTICULOS", "GRUPOS_LINEAS", "CONCEPTOS_IN", "PRECIOS_EMPRESA", "ROLES_CLAVES_ART"):
        return True, "Catálogo de Inventarios / Artículos"
    if "ARTICULO" in t or "PRECIO" in t or "COSTO" in t or "EXISTENCIA" in t or "INVENTARIO" in t or t.endswith("_IN"):
        return True, "Módulo de Artículos / Inventarios"
    if "ARTICULO_ID" in col_names:
        return True, "Relacionada por ARTICULO_ID"
    return False, "Tabla General Microsip"


def test_connection_and_discover_tables(
    username: str,
    password: str,
    host: Optional[str] = None,
    database_path: Optional[str] = None,
    save_to_file: bool = True,
) -> Dict[str, Any]:
    """
    Ejecuta el diagnóstico completo y descubrimiento automático de tablas:
    1. Ping al servidor (192.168.1.5)
    2. Socket puerto 3050
    3. Prueba de ambas cadenas DSN y ambos drivers (firebird-driver y fdb)
    4. Si conecta: lista todas las tablas, cuenta registros y descubre tablas de
       artículos, costos, inventarios y existencias.
    5. Si falla: devuelve el diagnóstico exacto paso a paso y el error real de Firebird.
    """
    target_host = (host or settings.db_host).strip()
    target_path = (database_path or settings.db_path).strip()
    clean_user = (username or settings.db_user or "SISTEMAS").strip()

    start_time = time.perf_counter()

    # 1. Ejecutar diagnóstico paso a paso (Ping, Puerto 3050, Archivo FDB, Login Usuario)
    diagnostics = run_step_by_step_diagnostics(
        username=clean_user,
        password=password,
        host=target_host,
        database_path=target_path,
    )

    if not diagnostics["connection_success"]:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return {
            "success": False,
            "mensaje": "❌ Error de Conexión a Firebird",
            "api_status": "online",
            "firebird_status": "error",
            "host": target_host,
            "port": settings.db_port,
            "database_path": target_path,
            "username": clean_user,
            "active_dsn": diagnostics["active_dsn"],
            "active_driver": diagnostics["active_driver"],
            "engine_version": diagnostics["engine_version"],
            "latency_ms": diagnostics["socket_latency_ms"],
            "inspection_time_ms": elapsed_ms,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ping_ok": diagnostics["ping_ok"],
            "ping_ms": diagnostics["ping_ms"],
            "ping_output": diagnostics["ping_output"],
            "port_3050_open": diagnostics["port_3050_open"],
            "fdb_located": diagnostics["fdb_located"],
            "login_success": diagnostics["login_success"],
            "login_rejected": diagnostics["login_rejected"],
            "firebird_raw_error": diagnostics["firebird_raw_error"],
            "checks": diagnostics["checks"],
            "dsn_attempts": diagnostics["dsn_attempts"],
            "total_tables": 0,
            "tables": [],
            "categorized_tables": {
                "articulos": [],
                "costos": [],
                "inventarios": [],
                "existencias": [],
            },
            "preparacion_fase2": {},
        }

    # 2. Conexión exitosa -> Listar automáticamente todas las tablas y columnas
    tables_map = fetch_all_user_tables_and_columns(
        credentials=(clean_user, password),
        host=target_host,
        database_path=target_path,
    )

    all_table_names = sorted(tables_map.keys())
    row_counts = count_tables_records_readonly(
        table_names=all_table_names,
        credentials=(clean_user, password),
        host=target_host,
        database_path=target_path,
    )

    tables_list: List[Dict[str, Any]] = []
    for t_name in all_table_names:
        cols = tables_map[t_name]
        col_names_set = {c["campo"] for c in cols}
        es_relevante, rol_microsip = _classify_table_role(t_name, col_names_set)
        sample_cols = [c["campo"] for c in cols[:8]]

        tables_list.append(
            {
                "nombre_tabla": t_name,
                "registros_aproximados": row_counts.get(t_name, 0),
                "total_columnas": len(cols),
                "columnas_muestra": sample_cols,
                "es_tabla_articulos": es_relevante,
                "rol_microsip": rol_microsip,
            }
        )

    # Ordenar tablas mostrando primero las que tienen mayor cantidad de registros o son clave
    categorized = _discover_domain_categories(tables_map, row_counts)

    preparacion_fase2 = {
        "listo_para_fase2": "ARTICULOS" in tables_map,
        "tabla_nombre_articulo": "ARTICULOS" if "ARTICULOS" in tables_map else (categorized["articulos"][0]["tabla"] if categorized["articulos"] else "Pendiente"),
        "tabla_sku_clave": "CLAVES_ARTICULOS" if "CLAVES_ARTICULOS" in tables_map else "ARTICULOS",
        "tabla_ultimo_costo_precio": "SALDOS_IN / PRECIOS_ARTICULOS" if "SALDOS_IN" in tables_map else "PRECIOS_ARTICULOS",
        "tabla_existencias": "SALDOS_IN" if "SALDOS_IN" in tables_map else "Pendiente",
        "resumen_descubrimiento": {
            "total_tablas_articulos": len(categorized["articulos"]),
            "total_tablas_costos": len(categorized["costos"]),
            "total_tablas_inventarios": len(categorized["inventarios"]),
            "total_tablas_existencias": len(categorized["existencias"]),
        },
    }

    elapsed_total_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

    # Agregar el check de lectura de tablas al diagnóstico
    diagnostics["checks"]["lectura_tablas"] = {
        "ok": True,
        "label": f"✅ Lectura de tablas exitosa ({len(tables_list)} tablas descubiertas)",
    }

    update_last_connection_state(
        connected=True,
        username=clean_user,
        credentials=(clean_user, password),
        host=target_host,
        database_path=target_path,
        active_dsn=diagnostics["active_dsn"] or f"{target_host}:{target_path}",
        active_driver=diagnostics["active_driver"] or "firebird-driver",
        engine_version=diagnostics["engine_version"] or "Firebird SQL",
        latency_ms=diagnostics["socket_latency_ms"] or 0.0,
        tables=tables_list,
        categorized_tables=categorized,
        preparacion_fase2=preparacion_fase2,
        diagnostics=diagnostics,
    )

    if save_to_file:
        report_payload = {
            "metadata": {
                "fecha_inspeccion": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "servidor_firebird": target_host,
                "puerto": settings.db_port,
                "base_de_datos": target_path,
                "dsn_utilizado": diagnostics["active_dsn"],
                "driver_utilizado": diagnostics["active_driver"],
                "motor_firebird": diagnostics["engine_version"],
                "usuario_autenticado": clean_user,
                "modo_conexion": "TCP/IP Remota - READ ONLY",
                "latencia_tcp_ms": diagnostics["socket_latency_ms"],
                "tiempo_total_inspeccion_ms": elapsed_total_ms,
                "total_tablas_usuario": len(tables_list),
            },
            "diagnostico": diagnostics,
            "descubrimiento_automatico": categorized,
            "preparacion_fase2": preparacion_fase2,
            "tablas_encontradas": tables_list,
        }
        report_path: Path = settings.resolved_inspection_report_path
        report_path.write_text(
            json.dumps(report_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return {
        "success": True,
        "mensaje": "✅ Conexión Exitosa",
        "api_status": "online",
        "firebird_status": "connected",
        "host": target_host,
        "port": settings.db_port,
        "database_path": target_path,
        "username": clean_user,
        "active_dsn": diagnostics["active_dsn"],
        "active_driver": diagnostics["active_driver"],
        "engine_version": diagnostics["engine_version"],
        "latency_ms": diagnostics["socket_latency_ms"],
        "inspection_time_ms": elapsed_total_ms,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ping_ok": diagnostics["ping_ok"],
        "ping_ms": diagnostics["ping_ms"],
        "ping_output": diagnostics["ping_output"],
        "port_3050_open": diagnostics["port_3050_open"],
        "fdb_located": diagnostics["fdb_located"],
        "login_success": diagnostics["login_success"],
        "login_rejected": diagnostics["login_rejected"],
        "firebird_raw_error": None,
        "checks": diagnostics["checks"],
        "dsn_attempts": diagnostics["dsn_attempts"],
        "total_tables": len(tables_list),
        "tables": tables_list,
        "categorized_tables": categorized,
        "preparacion_fase2": preparacion_fase2,
    }


def run_database_inspection(
    credentials: Optional[Tuple[str, str]] = None,
    save_to_file: bool = True,
) -> Dict[str, Any]:
    """Compatibilidad directa con el servicio de inspección."""
    user = credentials[0] if credentials else settings.db_user
    pwd = credentials[1] if credentials else settings.db_password
    return test_connection_and_discover_tables(
        username=user,
        password=pwd,
        save_to_file=save_to_file,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fase 1: Inspector y Diagnóstico Automático Firebird para Microsip ERP."
    )
    parser.add_argument("--user", "-u", default=settings.db_user or "SISTEMAS")
    parser.add_argument("--password", "-p", default=settings.db_password or "0809")
    args = parser.parse_args()

    user = (args.user or "SISTEMAS").strip()
    password = args.password or getpass.getpass(f"Contraseña Microsip para '{user}': ")

    result = test_connection_and_discover_tables(
        username=user,
        password=password,
        save_to_file=True,
    )
    print("=" * 80)
    print(f"  RESULTADO: {result['mensaje']}")
    for k, chk in result.get("checks", {}).items():
        print(f"  {chk['label']}")
    if result.get("firebird_raw_error"):
        print(f"  ERROR REAL FIREBIRD: {result['firebird_raw_error']}")
    else:
        print(f"  Tablas descubiertas: {result['total_tables']} en {result['inspection_time_ms']} ms")
    print("=" * 80)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
