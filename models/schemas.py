"""
Esquemas Pydantic v2 para validación de conectividad Firebird, diagnóstico
paso a paso y descubrimiento automático de tablas (Fase 1).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class DatabaseTestRequest(BaseModel):
    """Solicitud para probar la conexión remota TCP/IP a Firebird y descubrir tablas."""

    username: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Usuario de Microsip / Firebird (opcional, hereda del backend).",
        examples=["SISTEMAS"],
    )
    password: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Contraseña del usuario (opcional, hereda del backend).",
        examples=["0809"],
    )
    host: Optional[str] = Field(
        default="192.168.1.5",
        description="IP o nombre del servidor Microsip Firebird.",
        examples=["192.168.1.5"],
    )
    database_path: Optional[str] = Field(
        default=r"E:\Microsip datos\CAPACITACION.FDB",
        description="Ruta física de la base de datos FDB en el servidor.",
        examples=[r"E:\Microsip datos\CAPACITACION.FDB"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "username": "SISTEMAS",
                "password": "0809",
                "host": "192.168.1.5",
                "database_path": r"E:\Microsip datos\CAPACITACION.FDB",
            }
        }
    )


class TableInfoItem(BaseModel):
    """Información de una tabla descubierta en la base de datos Firebird."""

    nombre_tabla: str = Field(..., examples=["ARTICULOS"])
    registros_aproximados: int = Field(..., examples=[1250])
    total_columnas: int = Field(default=0, examples=[28])
    columnas_muestra: List[str] = Field(
        default_factory=list,
        examples=[["ARTICULO_ID", "NOMBRE", "ESTATUS", "UNIDAD_VENTA"]],
    )
    es_tabla_articulos: bool = Field(default=False, examples=[True])
    rol_microsip: str = Field(default="Tabla General Microsip", examples=["Catálogo Maestro de Artículos (Nombre)"])


class DatabaseTestResponse(BaseModel):
    """Respuesta detallada de POST /api/database/test con diagnóstico completo de Firebird."""

    success: bool = Field(default=True, examples=[True])
    mensaje: str = Field(default="✅ Conexión Exitosa", examples=["✅ Conexión Exitosa"])
    api_status: str = Field(default="online", examples=["online"])
    firebird_status: str = Field(default="connected", examples=["connected"])
    host: str = Field(..., examples=["192.168.1.5"])
    port: int = Field(default=3050, examples=[3050])
    database_path: str = Field(..., examples=[r"E:\Microsip datos\CAPACITACION.FDB"])
    username: str = Field(..., examples=["SISTEMAS"])
    active_dsn: Optional[str] = Field(default=None, examples=[r"192.168.1.5:E:\Microsip datos\CAPACITACION.FDB"])
    active_driver: Optional[str] = Field(default=None, examples=["firebird-driver"])
    engine_version: Optional[str] = Field(default=None, examples=["3.0.10"])
    latency_ms: Optional[float] = Field(default=None, examples=[2.45])
    inspection_time_ms: Optional[float] = Field(default=None, examples=[650.2])
    timestamp: str = Field(..., examples=["2026-10-06 13:00:00"])

    # Campos de diagnóstico requeridos
    ping_ok: bool = Field(default=True, examples=[True])
    ping_ms: Optional[float] = Field(default=None, examples=[1.5])
    ping_output: Optional[str] = Field(default=None)
    port_3050_open: bool = Field(default=True, examples=[True])
    fdb_located: bool = Field(default=True, examples=[True])
    login_success: bool = Field(default=True, examples=[True])
    login_rejected: bool = Field(default=False, examples=[False])
    firebird_raw_error: Optional[str] = Field(default=None)
    checks: Dict[str, Any] = Field(default_factory=dict)
    dsn_attempts: List[Dict[str, Any]] = Field(default_factory=list)

    # Descubrimiento automático de tablas
    total_tables: int = Field(default=0, examples=[655])
    tables: List[TableInfoItem] = Field(default_factory=list)
    categorized_tables: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    preparacion_fase2: Dict[str, Any] = Field(default_factory=dict)


class DatabaseTablesResponse(BaseModel):
    """Respuesta del endpoint GET /api/database/tables."""

    connected: bool = Field(default=False, examples=[True])
    host: str = Field(..., examples=["192.168.1.5"])
    database_path: str = Field(..., examples=[r"E:\Microsip datos\CAPACITACION.FDB"])
    active_dsn: Optional[str] = Field(default=None)
    active_driver: Optional[str] = Field(default=None)
    last_tested_at: Optional[str] = Field(default=None, examples=["2026-10-06 13:00:00"])
    total_tables: int = Field(default=0, examples=[655])
    tables: List[TableInfoItem] = Field(default_factory=list)
    categorized_tables: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    preparacion_fase2: Dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """Respuesta de estado de salud de la API y del motor Firebird (GET /api/health)."""

    status: str = Field(default="ok", examples=["ok"])
    api_status: str = Field(default="online", examples=["online"])
    database: str = Field(default="online", examples=["online"])
    firebird_status: str = Field(default="connected", examples=["connected"])
    connected: bool = Field(default=False, examples=[True])
    host: str = Field(default="192.168.1.5", examples=["192.168.1.5"])
    port: int = Field(default=3050, examples=[3050])
    database_path: str = Field(
        default=r"E:\Microsip datos\CAPACITACION.FDB",
        examples=[r"E:\Microsip datos\CAPACITACION.FDB"],
    )
    active_dsn: Optional[str] = Field(default=None)
    active_driver: Optional[str] = Field(default=None)
    engine_version: Optional[str] = Field(default=None, examples=["3.0.10"])
    latency_ms: Optional[float] = Field(default=None, examples=[2.15])
    total_tables: int = Field(default=0, examples=[655])
    last_tested_at: Optional[str] = Field(default=None, examples=["2026-10-06 13:00:00"])
    mode: str = Field(default="READ_ONLY", examples=["READ_ONLY"])


class LoginRequest(BaseModel):
    """Credenciales de usuario Microsip para autenticación JWT."""

    username: str = Field(..., min_length=1, max_length=64, examples=["SISTEMAS"])
    password: str = Field(..., min_length=1, max_length=128, examples=["0809"])


class TokenResponse(BaseModel):
    """Respuesta de autenticación con token JWT firmado."""

    token: str = Field(..., examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."])


class ArticuloResponse(BaseModel):
    """Modelo preparado para Fase 2: Consulta de Artículos en Microsip ERP."""

    sku: str = Field(..., examples=["621"])
    nombre: str = Field(..., examples=["TUBO GALVAN 13MM 1/2"])
    ultimo_precio: float = Field(..., examples=[125.50])
    existencia: Union[int, float] = Field(..., examples=[200])
    fecha_consulta: str = Field(..., examples=["2026-10-06"])


class InspectionMatchItem(BaseModel):
    """Elemento de coincidencia detectado por el inspector automático de Fase 1."""

    tabla_encontrada: str = Field(..., examples=["ARTICULOS"])
    campo_encontrado: str = Field(..., examples=["NOMBRE"])
    tipo_dato: str = Field(..., examples=["VARCHAR(100)"])


class InspectionReportResponse(BaseModel):
    """Respuesta estructurada del reporte de inspección de base de datos Firebird."""

    metadata: Dict[str, Any]
    coincidencias: List[InspectionMatchItem]
    sugerencias_tablas_articulos: Dict[str, Any]


class ErrorResponse(BaseModel):
    """Estructura estándar de respuesta ante errores."""

    error: str = Field(..., examples=["INVALID_CREDENTIALS"])
    mensaje: str = Field(
        ...,
        examples=["Credenciales de Microsip inválidas. Verifique usuario y contraseña."],
    )
    detalle: Optional[Any] = Field(default=None)
    timestamp: str = Field(..., examples=["2026-10-06 13:00:00"])
    endpoint: str = Field(..., examples=["/api/database/test"])

class AlmacenResponse(BaseModel):
    """Información básica de un almacén."""
    almacen_id: int = Field(..., examples=[458162])
    nombre: str = Field(..., examples=["14-MERCADO LIBRE"])

class InventarioAlmacenItem(BaseModel):
    """Información de inventario para un artículo en un almacén específico."""
    clave: str = Field(..., examples=["330"])
    nombre: str = Field(..., examples=["ACCESORIOS BAÑO BLANCO"])
    unidad_medida: str = Field(..., examples=["PZA"])
    existencia: float = Field(..., examples=[15.0])
    ultimo_costo: float = Field(..., examples=[205.93])
    valor_total: float = Field(..., examples=[3088.95])
