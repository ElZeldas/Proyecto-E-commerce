"""
Router de Monitoreo y Salud (`GET /api/health`).
Verifica el estado de la API, el estado del motor Firebird en 192.168.1.5,
la IP configurada, la ruta FDB configurada y la cantidad de tablas descubiertas.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from database import check_database_health
from models.schemas import ErrorResponse, HealthResponse

router = APIRouter(prefix="/api", tags=["1. Salud y Diagnóstico"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Verificar estado de API y de conexión a Firebird",
    description=(
        "Devuelve el estado actual de la API, el estado de conectividad con el servidor "
        "Firebird (`192.168.1.5`), la ruta FDB configurada (`E:\\Microsip datos\\CAPACITACION.FDB`) "
        "y el total de tablas encontradas en la última validación."
    ),
    responses={
        200: {"model": HealthResponse, "description": "Diagnóstico de salud de la API y Firebird."},
        503: {"model": ErrorResponse, "description": "Base de datos no disponible."},
    },
)
def health_check() -> HealthResponse:
    """Endpoint `GET /api/health`."""
    health_data = check_database_health()
    return HealthResponse(**health_data)
