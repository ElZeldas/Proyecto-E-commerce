"""
Módulo de Autenticación Empresarial JWT y Gestión Segura de Sesiones Microsip.
- Valida credenciales reales de Microsip contra el motor Firebird.
- Emite y verifica tokens JWT firmados (HS256) con control estricto de expiración.
- Nunca almacena contraseñas en código fuente ni las expone en el payload JWT.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.exceptions import (
    ExpiredTokenError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from database import verify_microsip_credentials

# Contexto criptográfico con passlib para hashing de verificación en memoria
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Esquema Bearer para Swagger UI (/docs) y clientes REST / IA
security_scheme = HTTPBearer(
    scheme_name="JWT Bearer Token",
    description="Ingrese el token JWT obtenido en `POST /login`.",
    auto_error=False,
)


@dataclass
class AuthenticatedSession:
    """Representa la sesión autenticada de un usuario Microsip."""

    username: str
    session_id: str
    credentials: Tuple[str, str]


class _EphemeralCredentialVault:
    """
    Bóveda efímera en memoria RAM cifrada mediante XOR-SHA256 con llave derivada de JWT_SECRET_KEY.
    Permite reutilizar las credenciales autenticadas del usuario Microsip durante la vigencia
    del JWT sin exponer la contraseña en el token ni guardarla en disco o código fuente.
    """

    def __init__(self, secret: str) -> None:
        self._key = hashlib.sha256(secret.encode("utf-8")).digest()
        self._store: Dict[str, Tuple[str, str, str]] = {}

    def _xor_bytes(self, data: bytes) -> bytes:
        key_len = len(self._key)
        return bytes(b ^ self._key[i % key_len] for i, b in enumerate(data))

    def store_session(self, username: str, password: str) -> str:
        session_id = secrets.token_urlsafe(24)
        encrypted_pwd = base64.urlsafe_b64encode(
            self._xor_bytes(password.encode("utf-8"))
        ).decode("ascii")
        pwd_hash = pwd_context.hash(password)
        self._store[session_id] = (username, encrypted_pwd, pwd_hash)
        return session_id

    def resolve_credentials(self, session_id: str, username: str) -> Optional[Tuple[str, str]]:
        record = self._store.get(session_id)
        if not record:
            return None
        stored_user, encrypted_pwd, _ = record
        if stored_user.upper() != username.upper():
            return None
        raw_pwd = self._xor_bytes(
            base64.urlsafe_b64decode(encrypted_pwd.encode("ascii"))
        ).decode("utf-8")
        return (stored_user, raw_pwd)


_session_vault = _EphemeralCredentialVault(settings.jwt_secret_key)


def authenticate_and_create_token(username: str, password: str) -> str:
    """
    1. Verifica las credenciales del usuario Microsip contra Firebird en modo solo lectura.
    2. Registra la sesión cifrada en memoria.
    3. Genera y firma el token JWT con expiración controlada.
    """
    clean_user = (username or "").strip()
    if not clean_user or not password:
        raise InvalidCredentialsError("Usuario y contraseña de Microsip son obligatorios.")

    # Validar credenciales directamente contra el servidor Firebird Microsip
    verify_microsip_credentials(clean_user, password)

    # Guardar en bóveda efímera de memoria para consultas subsecuentes
    session_id = _session_vault.store_session(clean_user, password)

    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_expiration_minutes)

    payload = {
        "sub": clean_user,
        "sid": session_id,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "scope": "microsip:readonly",
    }

    token = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token


def verify_jwt_token(
    request: Request,
    auth_creds: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> AuthenticatedSession:
    """
    Dependencia FastAPI que valida el encabezado `Authorization: Bearer <token>`,
    verifica firma y vigencia del JWT, e inyecta el usuario en `request.state.username`
    para el registro de auditoría en `logs/api.log`.
    """
    if auth_creds is None or not auth_creds.credentials:
        raise InvalidTokenError(
            "Encabezado Authorization Bearer ausente. Autentíquese primero en POST /login."
        )

    if auth_creds.scheme.lower() != "bearer":
        raise InvalidTokenError("Esquema de autenticación inválido. Use 'Bearer <token>'.")

    token = auth_creds.credentials.strip()

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except ExpiredSignatureError as exc:
        raise ExpiredTokenError("El token JWT ha expirado.") from exc
    except JWTError as exc:
        raise InvalidTokenError(f"Token JWT inválido o corrupto: {exc}") from exc

    username: Optional[str] = payload.get("sub")
    session_id: Optional[str] = payload.get("sid")
    scope: Optional[str] = payload.get("scope")

    if not username or scope != "microsip:readonly":
        raise InvalidTokenError("El token JWT no contiene los permisos requeridos.")

    # Registrar el usuario autenticado en el estado del Request para logs/api.log
    request.state.username = username

    # Recuperar credenciales de sesión o usar credenciales de servicio en .env
    creds = _session_vault.resolve_credentials(session_id or "", username)
    if creds is None:
        if settings.db_user and settings.db_password:
            creds = (settings.db_user, settings.db_password)
        else:
            raise ExpiredTokenError(
                "La sesión en memoria ha caducado tras reinicio del servicio. "
                "Por favor inicie sesión nuevamente en POST /login."
            )

    return AuthenticatedSession(
        username=username,
        session_id=session_id or "",
        credentials=creds,
    )
