"""
Guardián de Seguridad de Solo Lectura (READ-ONLY GUARD) y Middleware de Auditoría.
Garantiza por diseño arquitectónico que la API JAMÁS ejecute:
INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, MERGE ni modificaciones.
"""

from __future__ import annotations

import re
import time
from typing import Callable, Set

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.exceptions import ReadOnlyViolationError
from app.logger import log_audit_event

# Palabras clave DML/DDL de escritura estrictamente prohibidas
FORBIDDEN_SQL_KEYWORDS: Set[str] = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "MERGE",
    "RECREATE",
    "GRANT",
    "REVOKE",
    "EXECUTE",
    "EXEC",
    "COMMIT",
    "ROLLBACK",
    "SAVEPOINT",
    "SET",
}

_COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_LINE_RE = re.compile(r"--[^\r\n]*")
_STRING_LITERAL_RE = re.compile(r"'([^']|'')*'")
_WORD_TOKEN_RE = re.compile(r"\b[A-Z_][A-Z0-9_$]*\b", re.IGNORECASE)


def validate_readonly_sql(sql: str) -> str:
    """
    Inspecciona estáticamente cualquier sentencia SQL antes de enviarla a Firebird.
    Lanza ReadOnlyViolationError si detecta cualquier instrucción distinta a SELECT
    o si contiene palabras clave de modificación de datos/esquema.
    """
    if not sql or not sql.strip():
        raise ReadOnlyViolationError("Sentencia SQL vacía no permitida.")

    # Eliminar comentarios y literales de texto para evitar falsos positivos o inyecciones
    cleaned = _COMMENT_BLOCK_RE.sub(" ", sql)
    cleaned = _COMMENT_LINE_RE.sub(" ", cleaned)
    cleaned = _STRING_LITERAL_RE.sub("''", cleaned).strip()

    # Prohibir múltiples sentencias separadas por punto y coma
    statements = [stmt.strip() for stmt in cleaned.split(";") if stmt.strip()]
    if len(statements) > 1:
        raise ReadOnlyViolationError(
            "Múltiples sentencias SQL encadenadas (;) están prohibidas por seguridad."
        )

    tokens = [tok.upper() for tok in _WORD_TOKEN_RE.findall(cleaned)]
    if not tokens:
        raise ReadOnlyViolationError("Sentencia SQL inválida.")

    first_token = tokens[0]
    if first_token not in ("SELECT", "WITH"):
        raise ReadOnlyViolationError(
            f"Operación SQL '{first_token}' bloqueada. Solo se permiten consultas SELECT."
        )

    for token in tokens:
        if token in FORBIDDEN_SQL_KEYWORDS:
            raise ReadOnlyViolationError(
                f"Palabra clave SQL prohibida detectada ('{token}'). Modo estricto READ-ONLY."
            )

    return sql


class ReadOnlyAndAuditMiddleware(BaseHTTPMiddleware):
    """
    Middleware empresarial que:
    1. Bloquea cualquier método HTTP de modificación (PUT, PATCH, DELETE, y POST fuera de rutas de prueba/autenticación).
    2. Registra en logs/api.log cada petición exitosa con Fecha, Hora, Usuario, IP, Endpoint y Resultado.
    """

    ALLOWED_POST_PATHS = {
        "/login",
        "/api/login",
        "/api/database/test",
    }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        method = request.method.upper()
        path = request.url.path

        # Extraer IP origen
        ip_origen = request.client.host if request.client else "127.0.0.1"
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip_origen = forwarded.split(",")[0].strip()

        # Inicializar usuario en state
        if not hasattr(request.state, "username"):
            request.state.username = "ANONIMO"

        # 1. Validación estricta de métodos HTTP (Solo Lectura)
        if method in {"PUT", "PATCH", "DELETE"}:
            raise ReadOnlyViolationError(
                f"Método HTTP {method} deshabilitado. La API de Microsip es exclusivamente de consulta."
            )

        if method == "POST" and path not in self.ALLOWED_POST_PATHS:
            raise ReadOnlyViolationError(
                f"No se permite POST en '{path}'. La API opera exclusivamente en modo lectura."
            )

        response = await call_next(request)

        # 2. Registro automático en bitácora logs/api.log
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        usuario = getattr(request.state, "username", "ANONIMO")
        endpoint_str = f"{method} {path}"
        if request.url.query:
            endpoint_str = f"{endpoint_str}?{request.url.query}"

        if response.status_code < 400:
            log_audit_event(
                endpoint=endpoint_str,
                resultado=f"HTTP_{response.status_code}_OK ({elapsed_ms:.1f}ms)",
                usuario=usuario,
                ip_origen=ip_origen,
                error=None,
            )

        return response
