"""
Capa de servicios de negocio y generación de consultas SQL parametrizadas (Fase 2).
"""

from services.articulos_service import (
    get_articulo_by_sku,
    get_articulos,
    get_or_create_inspection_report,
)

__all__ = [
    "get_articulos",
    "get_articulo_by_sku",
    "get_or_create_inspection_report",
]
