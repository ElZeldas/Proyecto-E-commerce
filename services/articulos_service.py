"""
FASE 2 - GENERACIÓN DINÁMICA DE CONSULTAS JOIN OPTIMIZADAS Y PARAMETRIZADAS
===========================================================================
Este servicio:
1. Utiliza el inspector automático (Fase 1) para detectar las tablas y columnas reales
   en la base de datos Firebird de Microsip ERP sin asumir nombres ciegamente.
2. Construye consultas SQL JOIN optimizadas y 100% parametrizadas (`?`) para obtener:
   - SKU o Clave del artículo (`sku`)
   - Nombre del artículo (`nombre`)
   - Último costo o último precio (`ultimo_precio`)
   - Existencia actual (`existencia`)
   - Fecha de consulta (`fecha_consulta`)
3. Opera exclusivamente en modo SOLO LECTURA (READ ONLY).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from app.config import settings
from app.exceptions import (
    ArticuloNotFoundError,
    ColumnNotFoundError,
    TableNotFoundError,
)
from app.logger import api_logger
from database import execute_readonly_query
from inspector import fetch_all_user_tables_and_columns, run_database_inspection
from models.schemas import ArticuloResponse

_IDENTIFIER_RE = re.compile(r"^[A-Z0-9_$]+$")


def _safe_ident(identifier: str) -> str:
    """
    Valida que un identificador de tabla o columna del catálogo de sistema de Firebird
    contenga únicamente caracteres alfanuméricos válidos antes de interpolar el esquema.
    """
    clean = identifier.strip().upper()
    if not _IDENTIFIER_RE.match(clean):
        raise ValueError(f"Identificador de esquema inválido: {identifier}")
    return clean


@dataclass
class ResolvedMicrosipSchema:
    """Esquema real detectado en la base de datos Firebird de Microsip."""

    master_table: str
    id_column: str
    name_column: str
    status_column: Optional[str]

    sku_table: Optional[str]
    sku_column: Optional[str]
    sku_fk_column: Optional[str]
    sku_role_column: Optional[str]

    price_subquery: str
    cost_subquery: str
    stock_subquery: str


# Caché en memoria del plan de esquema detectado para evitar re-inspeccionar en cada petición
_cached_schema_plan: Optional[ResolvedMicrosipSchema] = None


def get_or_create_inspection_report(
    credentials: Optional[Tuple[str, str]] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Obtiene el reporte JSON de Fase 1 desde disco si ya existe o ejecuta `inspector.py`
    en vivo contra Firebird.
    """
    report_path = settings.resolved_inspection_report_path
    if not force_refresh and report_path.is_file():
        try:
            return json.loads(report_path.read_text(encoding="utf-8"))
        except Exception as exc:
            api_logger.warning(f"Reconstruyendo reporte de inspección tras error de lectura: {exc}")

    return run_database_inspection(credentials=credentials, save_to_file=True)


def _resolve_microsip_schema(
    credentials: Optional[Tuple[str, str]] = None,
) -> ResolvedMicrosipSchema:
    """
    Analiza el catálogo real de tablas y columnas de Firebird (Fase 1 -> Fase 2)
    y construye el plan óptimo de JOINs para Microsip ERP.
    """
    global _cached_schema_plan
    if _cached_schema_plan is not None:
        return _cached_schema_plan

    tables_map = fetch_all_user_tables_and_columns(credentials=credentials)
    if not tables_map:
        raise TableNotFoundError(
            detail="No se encontraron tablas de usuario en la base de datos Firebird."
        )

    def get_cols(table: str) -> Set[str]:
        return {c["campo"].upper() for c in tables_map.get(table.upper(), [])}

    # -------------------------------------------------------------------------
    # 1. Detectar Tabla Maestra de Artículos (ej. ARTICULOS en Microsip)
    # -------------------------------------------------------------------------
    master_table: Optional[str] = None
    for candidate in ("ARTICULOS", "ARTICULO", "CAT_ARTICULOS", "INVENTARIO"):
        if candidate in tables_map:
            master_table = candidate
            break

    if master_table is None:
        # Buscar dinámicamente cualquier tabla que tenga ARTICULO_ID y NOMBRE
        for t_name in tables_map:
            cols = get_cols(t_name)
            if "ARTICULO" in t_name and ("NOMBRE" in cols or "DESCRIPCION" in cols):
                master_table = t_name
                break

    if master_table is None:
        raise TableNotFoundError(
            table_name="ARTICULOS",
            detail="No se detectó ninguna tabla maestra de artículos en la base de datos.",
        )

    master_cols = get_cols(master_table)

    # Columna ID primaria del artículo
    id_column = "ARTICULO_ID"
    if id_column not in master_cols:
        for candidate_id in ("ID_ARTICULO", "ID", "CLAVE", "SKU"):
            if candidate_id in master_cols:
                id_column = candidate_id
                break
        else:
            raise ColumnNotFoundError(
                column_name="ARTICULO_ID",
                detail=f"La tabla {master_table} no contiene una columna identificadora reconocida.",
            )

    # Columna Nombre del artículo
    name_column = "NOMBRE"
    if name_column not in master_cols:
        for candidate_name in ("DESCRIPCION", "NOMBRE_ARTICULO", "ARTICULO"):
            if candidate_name in master_cols:
                name_column = candidate_name
                break
        else:
            raise ColumnNotFoundError(
                column_name="NOMBRE",
                detail=f"La tabla {master_table} no contiene columna de nombre o descripción.",
            )

    status_column = "ESTATUS" if "ESTATUS" in master_cols else None

    # -------------------------------------------------------------------------
    # 2. Detectar Tabla de SKU / Claves de Artículo (ej. CLAVES_ARTICULOS)
    # -------------------------------------------------------------------------
    sku_table: Optional[str] = None
    sku_column: Optional[str] = None
    sku_fk_column: Optional[str] = None
    sku_role_column: Optional[str] = None

    if "CLAVES_ARTICULOS" in tables_map:
        ca_cols = get_cols("CLAVES_ARTICULOS")
        if "CLAVE_ARTICULO" in ca_cols and id_column in ca_cols:
            sku_table = "CLAVES_ARTICULOS"
            sku_column = "CLAVE_ARTICULO"
            sku_fk_column = id_column
            if "ROL_CLAVE_ART_ID" in ca_cols:
                sku_role_column = "ROL_CLAVE_ART_ID"
    else:
        # Búsqueda dinámica en otras tablas o en la misma tabla maestra
        for cand_col in ("SKU", "CLAVE_ARTICULO", "CLAVE", "CODIGO"):
            if cand_col in master_cols:
                sku_table = None
                sku_column = cand_col
                break

    # -------------------------------------------------------------------------
    # 3. Detectar Subconsulta de Último Precio / Último Costo
    # -------------------------------------------------------------------------
    price_subquery = "CAST(0.0 AS DOUBLE PRECISION)"
    cost_subquery = "CAST(0.0 AS DOUBLE PRECISION)"

    # 3a. Precios de venta en PRECIOS_ARTICULOS (estándar Microsip)
    if "PRECIOS_ARTICULOS" in tables_map:
        pa_cols = get_cols("PRECIOS_ARTICULOS")
        if "PRECIO" in pa_cols and id_column in pa_cols:
            if "PRECIO_EMPRESA_ID" in pa_cols:
                # Priorizar Precio de Lista (42 en Microsip) o el primer precio registrado
                price_subquery = (
                    f"(SELECT FIRST 1 pa.PRECIO FROM PRECIOS_ARTICULOS pa "
                    f"WHERE pa.{_safe_ident(id_column)} = a.{_safe_ident(id_column)} "
                    f"ORDER BY CASE WHEN pa.PRECIO_EMPRESA_ID = 42 THEN 0 ELSE 1 END, "
                    f"pa.PRECIO_EMPRESA_ID ASC)"
                )
            else:
                price_subquery = (
                    f"(SELECT MAX(pa.PRECIO) FROM PRECIOS_ARTICULOS pa "
                    f"WHERE pa.{_safe_ident(id_column)} = a.{_safe_ident(id_column)})"
                )
    elif "PRECIO" in master_cols:
        price_subquery = "a.PRECIO"

    # 3b. Último costo en SALDOS_IN o DOCTOS_IN_DET o DOCTOS_CM_DET
    if "SALDOS_IN" in tables_map and id_column in get_cols("SALDOS_IN"):
        si_cols = get_cols("SALDOS_IN")
        if "ULTIMO_COSTO" in si_cols and "ANO" in si_cols and "MES" in si_cols:
            cost_subquery = (
                f"(SELECT FIRST 1 si.ULTIMO_COSTO FROM SALDOS_IN si "
                f"WHERE si.{_safe_ident(id_column)} = a.{_safe_ident(id_column)} "
                f"AND si.ULTIMO_COSTO > 0 "
                f"ORDER BY si.ANO DESC, si.MES DESC)"
            )
        elif "ENTRADAS_COSTO" in si_cols and "ENTRADAS_UNIDADES" in si_cols:
            cost_subquery = (
                f"(SELECT FIRST 1 (si.ENTRADAS_COSTO / NULLIF(si.ENTRADAS_UNIDADES, 0)) "
                f"FROM SALDOS_IN si "
                f"WHERE si.{_safe_ident(id_column)} = a.{_safe_ident(id_column)} "
                f"AND si.ENTRADAS_UNIDADES > 0 AND si.ENTRADAS_COSTO > 0 "
                f"ORDER BY si.ANO DESC, si.MES DESC)"
            )
    elif "DOCTOS_IN_DET" in tables_map and id_column in get_cols("DOCTOS_IN_DET"):
        din_cols = get_cols("DOCTOS_IN_DET")
        if "COSTO_UNITARIO" in din_cols and "DOCTO_IN_DET_ID" in din_cols:
            cost_subquery = (
                f"(SELECT FIRST 1 d.COSTO_UNITARIO FROM DOCTOS_IN_DET d "
                f"WHERE d.{_safe_ident(id_column)} = a.{_safe_ident(id_column)} "
                f"AND d.COSTO_UNITARIO > 0 "
                f"ORDER BY d.DOCTO_IN_DET_ID DESC)"
            )
    elif "ULTIMO_COSTO" in master_cols:
        cost_subquery = "a.ULTIMO_COSTO"
    elif "COSTO" in master_cols:
        cost_subquery = "a.COSTO"

    # -------------------------------------------------------------------------
    # 4. Detectar Subconsulta de Existencia Actual (SALDOS_IN en Microsip)
    # -------------------------------------------------------------------------
    stock_subquery = "CAST(0 AS DOUBLE PRECISION)"
    if "SALDOS_IN" in tables_map and id_column in get_cols("SALDOS_IN"):
        si_cols = get_cols("SALDOS_IN")
        if "ENTRADAS_UNIDADES" in si_cols and "SALIDAS_UNIDADES" in si_cols:
            stock_subquery = (
                f"COALESCE((SELECT SUM(s.ENTRADAS_UNIDADES - s.SALIDAS_UNIDADES) "
                f"FROM SALDOS_IN s "
                f"WHERE s.{_safe_ident(id_column)} = a.{_safe_ident(id_column)}), 0)"
            )
        elif "EXISTENCIA" in si_cols:
            stock_subquery = (
                f"COALESCE((SELECT SUM(s.EXISTENCIA) "
                f"FROM SALDOS_IN s "
                f"WHERE s.{_safe_ident(id_column)} = a.{_safe_ident(id_column)}), 0)"
            )
    elif "EXISTENCIA" in master_cols:
        stock_subquery = "COALESCE(a.EXISTENCIA, 0)"

    _cached_schema_plan = ResolvedMicrosipSchema(
        master_table=_safe_ident(master_table),
        id_column=_safe_ident(id_column),
        name_column=_safe_ident(name_column),
        status_column=_safe_ident(status_column) if status_column else None,
        sku_table=_safe_ident(sku_table) if sku_table else None,
        sku_column=_safe_ident(sku_column) if sku_column else None,
        sku_fk_column=_safe_ident(sku_fk_column) if sku_fk_column else None,
        sku_role_column=_safe_ident(sku_role_column) if sku_role_column else None,
        price_subquery=price_subquery,
        cost_subquery=cost_subquery,
        stock_subquery=stock_subquery,
    )
    return _cached_schema_plan


def _build_articulos_query(
    schema: ResolvedMicrosipSchema,
    sku_filter: Optional[str] = None,
    nombre_filter: Optional[str] = None,
    exact_sku: bool = False,
    limit: int = 100,
) -> Tuple[str, List[Any]]:
    """
    Construye una consulta SQL SELECT + LEFT JOIN 100% parametrizada (`?`)
    adaptada al esquema real de Microsip ERP.
    """
    params: List[Any] = [int(limit)]

    # Expresión para obtener el último precio o último costo (prioriza precio de lista, o último costo si no tiene precio)
    ultimo_precio_expr = (
        f"COALESCE(NULLIF({schema.price_subquery}, 0), "
        f"NULLIF({schema.cost_subquery}, 0), 0.0)"
    )

    where_clauses: List[str] = []

    if schema.sku_table and schema.sku_column and schema.sku_fk_column:
        # En Microsip, CLAVES_ARTICULOS relaciona cada SKU/Clave con ARTICULOS.ARTICULO_ID.
        # Si se busca un SKU específico, hacemos JOIN con la clave buscada;
        # de lo contrario, obtenemos la clave principal (ROL_CLAVE_ART_ID = 17 en Microsip) o la primera disponible.
        if sku_filter:
            join_clause = (
                f"LEFT JOIN {schema.sku_table} ca "
                f"ON ca.{schema.sku_fk_column} = a.{schema.id_column}"
            )
            sku_select = f"COALESCE(TRIM(ca.{schema.sku_column}), CAST(a.{schema.id_column} AS VARCHAR(30)))"
            if exact_sku:
                where_clauses.append(
                    f"(UPPER(TRIM(ca.{schema.sku_column})) = UPPER(TRIM(?)) "
                    f"OR CAST(a.{schema.id_column} AS VARCHAR(30)) = TRIM(?))"
                )
                params.extend([sku_filter.strip(), sku_filter.strip()])
            else:
                where_clauses.append(
                    f"(UPPER(TRIM(ca.{schema.sku_column})) = UPPER(TRIM(?)) "
                    f"OR UPPER(TRIM(ca.{schema.sku_column})) STARTING WITH UPPER(TRIM(?)) "
                    f"OR CAST(a.{schema.id_column} AS VARCHAR(30)) = TRIM(?))"
                )
                params.extend([sku_filter.strip(), sku_filter.strip(), sku_filter.strip()])
        else:
            order_role = (
                f"CASE WHEN ca.{schema.sku_role_column} = 17 THEN 0 ELSE 1 END, "
                if schema.sku_role_column
                else ""
            )
            join_clause = ""
            sku_select = (
                f"COALESCE(("
                f"SELECT FIRST 1 TRIM(ca.{schema.sku_column}) "
                f"FROM {schema.sku_table} ca "
                f"WHERE ca.{schema.sku_fk_column} = a.{schema.id_column} "
                f"ORDER BY {order_role} ca.{schema.sku_column} ASC"
                f"), CAST(a.{schema.id_column} AS VARCHAR(30)))"
            )
    elif schema.sku_column:
        join_clause = ""
        sku_select = f"COALESCE(TRIM(CAST(a.{schema.sku_column} AS VARCHAR(50))), CAST(a.{schema.id_column} AS VARCHAR(30)))"
        if sku_filter:
            if exact_sku:
                where_clauses.append(f"UPPER(TRIM(CAST(a.{schema.sku_column} AS VARCHAR(50)))) = UPPER(TRIM(?))")
                params.append(sku_filter.strip())
            else:
                where_clauses.append(f"UPPER(TRIM(CAST(a.{schema.sku_column} AS VARCHAR(50)))) STARTING WITH UPPER(TRIM(?))")
                params.append(sku_filter.strip())
    else:
        join_clause = ""
        sku_select = f"CAST(a.{schema.id_column} AS VARCHAR(30))"
        if sku_filter:
            where_clauses.append(f"CAST(a.{schema.id_column} AS VARCHAR(30)) = TRIM(?)")
            params.append(sku_filter.strip())

    # Filtro opcional por nombre del artículo (búsqueda case-insensitive en Firebird con CONTAINING)
    if nombre_filter:
        where_clauses.append(f"UPPER(a.{schema.name_column}) CONTAINING UPPER(TRIM(?))")
        params.append(nombre_filter.strip())

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    sql = f"""
        SELECT FIRST ?
            {sku_select} AS sku,
            TRIM(a.{schema.name_column}) AS nombre,
            CAST({ultimo_precio_expr} AS DOUBLE PRECISION) AS ultimo_precio,
            CAST({schema.stock_subquery} AS DOUBLE PRECISION) AS existencia
        FROM {schema.master_table} a
        {join_clause}
        {where_sql}
        ORDER BY a.{schema.name_column} ASC
    """
    return sql, params


def _normalize_articulo_row(row: Dict[str, Any], fecha_consulta: str) -> ArticuloResponse:
    """
    Normaliza los tipos numéricos y de texto devueltos por Firebird al esquema
    exacto requerido por el contrato REST (`ArticuloResponse`).
    """
    raw_sku = row.get("sku")
    sku_str = str(raw_sku).strip() if raw_sku is not None else ""

    raw_nombre = row.get("nombre")
    nombre_str = str(raw_nombre).strip() if raw_nombre is not None else ""

    raw_precio = row.get("ultimo_precio")
    try:
        ultimo_precio = round(float(raw_precio or 0.0), 2)
    except (TypeError, ValueError):
        ultimo_precio = 0.0

    raw_existencia = row.get("existencia")
    try:
        existencia_float = float(raw_existencia or 0.0)
        existencia_val: int | float = (
            int(existencia_float)
            if existencia_float.is_integer()
            else round(existencia_float, 4)
        )
    except (TypeError, ValueError):
        existencia_val = 0

    return ArticuloResponse(
        sku=sku_str,
        nombre=nombre_str,
        ultimo_precio=ultimo_precio,
        existencia=existencia_val,
        fecha_consulta=fecha_consulta,
    )


def get_articulos(
    credentials: Optional[Tuple[str, str]] = None,
    sku: Optional[str] = None,
    nombre: Optional[str] = None,
    limit: int = 100,
) -> List[ArticuloResponse]:
    """
    Consulta la lista de artículos en Microsip con filtros opcionales parametrizados:
    - `sku`: Filtra por SKU o clave del artículo.
    - `nombre`: Filtra por coincidencia parcial en el nombre del artículo.
    - `limit`: Límite máximo de registros a devolver (por defecto 100, máx 1000).
    """
    safe_limit = max(1, min(int(limit), 1000))
    schema = _resolve_microsip_schema(credentials=credentials)

    sql, params = _build_articulos_query(
        schema=schema,
        sku_filter=sku,
        nombre_filter=nombre,
        exact_sku=False,
        limit=safe_limit,
    )

    rows = execute_readonly_query(sql=sql, params=params, credentials=credentials)
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")

    return [_normalize_articulo_row(row, fecha_hoy) for row in rows]


def get_articulo_by_sku(
    sku: str,
    credentials: Optional[Tuple[str, str]] = None,
) -> ArticuloResponse:
    """
    Consulta un artículo individual por su SKU o Clave exacta (`GET /api/articulos/{sku}`).
    Lanza `ArticuloNotFoundError` (HTTP 404) si el SKU no existe.
    """
    clean_sku = (sku or "").strip()
    if not clean_sku:
        raise ArticuloNotFoundError(sku="")

    schema = _resolve_microsip_schema(credentials=credentials)
    sql, params = _build_articulos_query(
        schema=schema,
        sku_filter=clean_sku,
        nombre_filter=None,
        exact_sku=True,
        limit=1,
    )

    rows = execute_readonly_query(sql=sql, params=params, credentials=credentials)
    if not rows:
        raise ArticuloNotFoundError(sku=clean_sku)

    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    return _normalize_articulo_row(rows[0], fecha_hoy)
