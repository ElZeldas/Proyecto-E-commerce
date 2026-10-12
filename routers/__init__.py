"""
Enrutadores (Routers) FastAPI para Validación de Conectividad Firebird,
Salud del Servicio y Descubrimiento Automático de Tablas (Fase 1).
"""

from routers.database_router import router as database_router
from routers.health_router import router as health_router
from routers.auth_router import router as auth_router
from routers.articulos_router import router as articulos_router
from routers.almacenes_router import router as almacenes_router

__all__ = [
    "health_router",
    "database_router",
    "auth_router",
    "articulos_router",
    "almacenes_router",
]
