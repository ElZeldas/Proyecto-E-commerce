"""
Router de Consulta de Artículos Microsip ERP (Modo Estricto SOLO LECTURA).
Endpoints:
- GET /api/articulos (con filtros opcionales: sku, nombre, limit)
- GET /api/articulos/{sku} (consulta individual por SKU o Clave)
- GET /api/inspector (reporte de inspección automática de base de datos Fase 1)
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Path, Query, status

from auth import AuthenticatedSession, verify_jwt_token
from models.schemas import (
    ArticuloResponse,
    ErrorResponse,
    InspectionReportResponse,
)
from services.articulos_service import (
    get_articulo_by_sku,
    get_articulos,
    get_or_create_inspection_report,
)

router = APIRouter(prefix="/api", tags=["Catálogo de Artículos (Read-Only)"])


@router.get(
    "/articulos",
    response_model=List[ArticuloResponse],
    status_code=status.HTTP_200_OK,
    summary="Consultar catálogo de artículos con filtros opcionales",
    description=(
        "Consulta en modo **SOLO LECTURA** los artículos de Microsip ERP obteniendo:\n"
        "- `sku`: Clave o SKU del artículo.\n"
        "- `nombre`: Nombre o descripción del artículo.\n"
        "- `ultimo_precio`: Último costo o último precio registrado.\n"
        "- `existencia`: Existencia actual en inventario.\n"
        "- `fecha_consulta`: Fecha actual de la consulta (`YYYY-MM-DD`).\n\n"
        "Soporta filtros opcionales parametrizados: `sku`, `nombre` y `limit`."
    ),
    responses={
        200: {"model": List[ArticuloResponse], "description": "Lista de artículos encontrados."},
        401: {"model": ErrorResponse, "description": "Token JWT inválido o expirado."},
        503: {"model": ErrorResponse, "description": "Base de datos Firebird no disponible."},
    },
)
def listar_articulos(
    sku: Optional[str] = Query(
        default=None,
        description="Filtrar por SKU o clave del artículo (ej. `621`).",
        examples=["621"],
    ),
    nombre: Optional[str] = Query(
        default=None,
        description="Filtrar por coincidencia parcial en el nombre del artículo (ej. `tubo`).",
        examples=["tubo"],
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Cantidad máxima de artículos a devolver (1 a 1000).",
        examples=[100],
    ),
) -> List[ArticuloResponse]:
    """
    Endpoint `GET /api/articulos` con soporte para `?sku=621`, `?nombre=tubo`, `?limit=100`.
    """
    return get_articulos(
        credentials=None,
        sku=sku,
        nombre=nombre,
        limit=limit,
    )


@router.get(
    "/articulos/{sku}",
    response_model=ArticuloResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar un artículo individual por su SKU o Clave",
    description=(
        "Obtiene la información detallada de un artículo específico mediante su `sku` o clave "
        "en Microsip ERP (modo estricto **SOLO LECTURA**)."
    ),
    responses={
        200: {"model": ArticuloResponse, "description": "Artículo encontrado exitosamente."},
        401: {"model": ErrorResponse, "description": "Token JWT inválido o expirado."},
        404: {"model": ErrorResponse, "description": "SKU no encontrado en Microsip."},
        503: {"model": ErrorResponse, "description": "Base de datos Firebird no disponible."},
    },
)
def obtener_articulo_por_sku(
    sku: str = Path(
        ...,
        min_length=1,
        max_length=50,
        description="SKU o clave exacta del artículo a consultar (ej. `621`).",
        examples=["621"],
    ),
    session: AuthenticatedSession = Depends(verify_jwt_token),
) -> ArticuloResponse:
    """
    Endpoint `GET /api/articulos/{sku}`.
    """
    return get_articulo_by_sku(
        sku=sku,
        credentials=session.credentials,
    )


@router.get(
    "/inspector",
    response_model=InspectionReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener reporte de inspección automática de la Base de Datos (Fase 1)",
    description=(
        "Ejecuta o recupera el reporte JSON del inspector automático (`inspector.py`) "
        "con todas las tablas y columnas relacionadas con artículos, inventarios, costos y precios."
    ),
    responses={
        200: {"model": InspectionReportResponse, "description": "Reporte JSON de estructura Firebird."},
        401: {"model": ErrorResponse, "description": "Token JWT inválido o expirado."},
    },
)
def obtener_reporte_inspector(
    refresh: bool = Query(
        default=False,
        description="Si es `true`, vuelve a consultar el catálogo de sistema de Firebird en vivo.",
    ),
    session: AuthenticatedSession = Depends(verify_jwt_token),
) -> InspectionReportResponse:
    """
    Endpoint `GET /api/inspector` para consultar la estructura detectada en Fase 1.
    """
    report = get_or_create_inspection_report(
        credentials=session.credentials,
        force_refresh=refresh,
    )
    return InspectionReportResponse(
        metadata=report["metadata"],
        coincidencias=report["coincidencias"],
        sugerencias_tablas_articulos=report["sugerencias_tablas_articulos"],
    )
