"""
Módulo de Excepciones Empresariales y Manejadores Globales para FastAPI.
Cubre:
- Credenciales inválidas
- Base de datos no disponible
- Timeout de conexión
- Tabla inexistente
- Campo inexistente
- Token inválido
- Token expirado
- Violación de política Read-Only
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.logger import log_audit_event


class MicrosipAPIException(Exception):
    """Excepción base de la API Microsip ERP."""

    def __init__(
        self,
        message: str,
        error_code: str = "MICROSIP_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.detail = detail or message


class InvalidCredentialsError(MicrosipAPIException):
    """Credenciales de usuario Microsip/Firebird inválidas."""

    def __init__(self, detail: Optional[str] = None) -> None:
        super().__init__(
            message="Credenciales de Microsip inválidas. Verifique usuario y contraseña.",
            error_code="INVALID_CREDENTIALS",
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )


class InvalidTokenError(MicrosipAPIException):
    """Token JWT inválido o malformado."""

    def __init__(self, detail: Optional[str] = None) -> None:
        super().__init__(
            message="El token de autenticación proporcionado no es válido.",
            error_code="INVALID_TOKEN",
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )


class ExpiredTokenError(MicrosipAPIException):
    """Token JWT expirado."""

    def __init__(self, detail: Optional[str] = None) -> None:
        super().__init__(
            message="Su sesión ha expirado. Inicie sesión nuevamente en POST /login.",
            error_code="EXPIRED_TOKEN",
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )


class ReadOnlyViolationError(MicrosipAPIException):
    """Intento de ejecutar una operación de escritura no permitida."""

    def __init__(self, detail: Optional[str] = None) -> None:
        super().__init__(
            message="Operación denegada: Esta API es estrictamente de SOLO LECTURA (READ ONLY).",
            error_code="READ_ONLY_VIOLATION",
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


class DatabaseUnavailableError(MicrosipAPIException):
    """Base de datos Firebird no disponible o ruta inaccesible."""

    def __init__(self, detail: Optional[str] = None) -> None:
        super().__init__(
            message="El servidor Firebird / Microsip no está disponible en este momento.",
            error_code="DATABASE_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        )


class DatabaseTimeoutError(MicrosipAPIException):
    """Timeout al conectar o consultar el servidor Firebird."""

    def __init__(self, detail: Optional[str] = None) -> None:
        super().__init__(
            message="Tiempo de espera agotado (timeout) al conectar con el servidor Microsip Firebird.",
            error_code="DATABASE_TIMEOUT",
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=detail,
        )


class TableNotFoundError(MicrosipAPIException):
    """Tabla inexistente en el catálogo de Firebird."""

    def __init__(self, table_name: str = "", detail: Optional[str] = None) -> None:
        msg = (
            f"La tabla requerida '{table_name}' no existe en la base de datos Microsip."
            if table_name
            else "Tabla inexistente en la base de datos Microsip."
        )
        super().__init__(
            message=msg,
            error_code="TABLE_NOT_FOUND",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail or msg,
        )


class ColumnNotFoundError(MicrosipAPIException):
    """Campo o columna inexistente en la tabla consultada."""

    def __init__(self, column_name: str = "", detail: Optional[str] = None) -> None:
        msg = (
            f"El campo o columna '{column_name}' no existe en la estructura de Microsip."
            if column_name
            else "Campo inexistente en la tabla consultada de Microsip."
        )
        super().__init__(
            message=msg,
            error_code="COLUMN_NOT_FOUND",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail or msg,
        )


class ArticuloNotFoundError(MicrosipAPIException):
    """Artículo o SKU no encontrado en el catálogo de Microsip."""

    def __init__(self, sku: str) -> None:
        super().__init__(
            message=f"No se encontró ningún artículo con el SKU o clave '{sku}'.",
            error_code="ARTICULO_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SKU '{sku}' inexistente en el catálogo de artículos.",
        )


def _extract_client_info(request: Request) -> tuple[str, str, str]:
    """Extrae usuario autenticado, IP origen y endpoint desde el objeto Request."""
    usuario = getattr(request.state, "username", "ANONIMO")
    ip_origen = request.client.host if request.client else "DESCONOCIDA"
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip_origen = forwarded.split(",")[0].strip()
    endpoint = f"{request.method} {request.url.path}"
    if request.url.query:
        endpoint = f"{endpoint}?{request.url.query}"
    return usuario, ip_origen, endpoint


def register_exception_handlers(app: FastAPI) -> None:
    """Registra los manejadores globales de excepciones en la instancia FastAPI."""

    @app.exception_handler(MicrosipAPIException)
    async def microsip_exception_handler(
        request: Request, exc: MicrosipAPIException
    ) -> JSONResponse:
        usuario, ip_origen, endpoint = _extract_client_info(request)
        log_audit_event(
            endpoint=endpoint,
            resultado=f"HTTP_{exc.status_code}_{exc.error_code}",
            usuario=usuario,
            ip_origen=ip_origen,
            error=f"{exc.message} ({exc.detail})",
            level=logging.WARNING if exc.status_code < 500 else logging.ERROR,
        )
        headers = (
            {"WWW-Authenticate": "Bearer"}
            if exc.status_code == status.HTTP_401_UNAUTHORIZED
            else None
        )
        return JSONResponse(
            status_code=exc.status_code,
            headers=headers,
            content={
                "error": exc.error_code,
                "mensaje": exc.message,
                "detalle": exc.detail,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "endpoint": request.url.path,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        usuario, ip_origen, endpoint = _extract_client_info(request)
        log_audit_event(
            endpoint=endpoint,
            resultado="HTTP_422_VALIDATION_ERROR",
            usuario=usuario,
            ip_origen=ip_origen,
            error=str(exc.errors()),
            level=logging.WARNING,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "VALIDATION_ERROR",
                "mensaje": "Parámetros de entrada inválidos.",
                "detalle": exc.errors(),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "endpoint": request.url.path,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        usuario, ip_origen, endpoint = _extract_client_info(request)
        log_audit_event(
            endpoint=endpoint,
            resultado="HTTP_500_INTERNAL_ERROR",
            usuario=usuario,
            ip_origen=ip_origen,
            error=f"{type(exc).__name__}: {exc}",
            level=logging.ERROR,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "INTERNAL_SERVER_ERROR",
                "mensaje": "Error interno al procesar la consulta en Microsip API.",
                "detalle": str(exc),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "endpoint": request.url.path,
            },
        )
