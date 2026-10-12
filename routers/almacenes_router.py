from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from database import execute_readonly_query
from models.schemas import AlmacenResponse, InventarioAlmacenItem

router = APIRouter(prefix="/api/almacenes", tags=["Almacenes"])

@router.get("", response_model=List[AlmacenResponse])
def get_todos_los_almacenes():
    """
    Devuelve la lista de todos los almacenes registrados.
    """
    sql = "SELECT ALMACEN_ID, TRIM(NOMBRE) AS NOMBRE FROM ALMACENES ORDER BY NOMBRE ASC"
    rows = execute_readonly_query(sql, None)
    return [
        AlmacenResponse(almacen_id=r["almacen_id"], nombre=r["nombre"])
        for r in rows
    ]

@router.get("/ml", response_model=List[AlmacenResponse])
def get_mercado_libre_almacenes():
    """
    Devuelve la lista de almacenes que pertenecen a Mercado Libre.
    """
    sql = "SELECT ALMACEN_ID, TRIM(NOMBRE) AS NOMBRE FROM ALMACENES WHERE NOMBRE LIKE '%MERCADO LIBRE%' ORDER BY NOMBRE ASC"
    rows = execute_readonly_query(sql, None)
    return [
        AlmacenResponse(almacen_id=r["almacen_id"], nombre=r["nombre"])
        for r in rows
    ]

@router.get("/{almacen_id}/inventario", response_model=List[InventarioAlmacenItem])
def get_inventario_por_almacen(
    almacen_id: int, 
    search_query: Optional[str] = Query(None, description="Término de búsqueda por SKU o Nombre")
):
    """
    Devuelve los artículos que tienen existencia en el almacén especificado.
    Permite búsqueda dinámica por prefijo de SKU o fragmento de nombre.
    """
    base_sql = """
    SELECT 
        COALESCE(TRIM(ca.CLAVE_ARTICULO), CAST(a.ARTICULO_ID AS VARCHAR(30))) AS clave,
        TRIM(a.NOMBRE) AS nombre,
        TRIM(a.UNIDAD_VENTA) AS unidad_medida,
        (
            SELECT SUM(s.ENTRADAS_UNIDADES - s.SALIDAS_UNIDADES)
            FROM SALDOS_IN s
            WHERE s.ARTICULO_ID = a.ARTICULO_ID AND s.ALMACEN_ID = ?
        ) AS existencia,
        (
            SELECT FIRST 1 (si.ENTRADAS_COSTO / NULLIF(si.ENTRADAS_UNIDADES, 0))
            FROM SALDOS_IN si
            WHERE si.ARTICULO_ID = a.ARTICULO_ID
              AND si.ENTRADAS_UNIDADES > 0 AND si.ENTRADAS_COSTO > 0
            ORDER BY si.ANO DESC, si.MES DESC
        ) AS ultimo_costo
    FROM ARTICULOS a
    LEFT JOIN CLAVES_ARTICULOS ca ON ca.ARTICULO_ID = a.ARTICULO_ID AND ca.ROL_CLAVE_ART_ID = 17
    WHERE (
        SELECT SUM(s.ENTRADAS_UNIDADES - s.SALIDAS_UNIDADES)
        FROM SALDOS_IN s
        WHERE s.ARTICULO_ID = a.ARTICULO_ID AND s.ALMACEN_ID = ?
    ) > 0
    """
    
    params = [almacen_id, almacen_id]

    if search_query:
        clean_query = search_query.strip()
        if clean_query.isdigit():
            # Si son SOLO números, buscar estrictamente por prefijo en el SKU/Clave
            base_sql += """
            AND UPPER(COALESCE(TRIM(ca.CLAVE_ARTICULO), CAST(a.ARTICULO_ID AS VARCHAR(30)))) STARTING WITH UPPER(?)
            """
            params.append(clean_query)
        else:
            # Si contiene letras o cualquier otro carácter, buscar por fragmento en el Nombre
            base_sql += """
            AND UPPER(a.NOMBRE) CONTAINING UPPER(?)
            """
            params.append(clean_query)

    base_sql += " ORDER BY a.NOMBRE ASC"

    try:
        rows = execute_readonly_query(base_sql, params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    resultados = []
    for r in rows:
        clave = str(r["clave"] or "")
        nombre = str(r["nombre"] or "")
        unidad_medida = str(r["unidad_medida"] or "PZA")
        existencia = float(r["existencia"] or 0.0)
        ultimo_costo = float(r["ultimo_costo"] or 0.0)
        valor_total = existencia * ultimo_costo
        
        resultados.append(
            InventarioAlmacenItem(
                clave=clave,
                nombre=nombre,
                unidad_medida=unidad_medida,
                existencia=round(existencia, 4),
                ultimo_costo=round(ultimo_costo, 2),
                valor_total=round(valor_total, 2)
            )
        )
    return resultados
