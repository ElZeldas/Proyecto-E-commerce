"""
Router de Autenticación JWT (`POST /login`).
Autentica las credenciales del usuario Microsip directamente contra Firebird
en modo SOLO LECTURA y emite el token JWT firmado.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from auth import authenticate_and_create_token
from models.schemas import ErrorResponse, LoginRequest, TokenResponse

router = APIRouter(tags=["Autenticación JWT"])


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Autenticar usuario Microsip y obtener Token JWT",
    description=(
        "Valida las credenciales del usuario (`username` y `password`) directamente contra "
        "el servidor Firebird de Microsip ERP (`192.168.1.5`) en modo estricto de solo lectura "
        "y devuelve un token JWT firmado para consumir los endpoints protegidos."
    ),
    responses={
        200: {"model": TokenResponse, "description": "Autenticación exitosa."},
        401: {"model": ErrorResponse, "description": "Credenciales de Microsip inválidas."},
        503: {"model": ErrorResponse, "description": "Servidor Firebird no disponible."},
        504: {"model": ErrorResponse, "description": "Timeout de conexión con Firebird."},
    },
)
def login_microsip(payload: LoginRequest, request: Request) -> TokenResponse:
    """
    Autentica al usuario de Microsip y devuelve `{"token": "jwt_token"}`.
    """
    request.state.username = payload.username.strip()
    jwt_token = authenticate_and_create_token(
        username=payload.username,
        password=payload.password,
    )
    return TokenResponse(token=jwt_token)
