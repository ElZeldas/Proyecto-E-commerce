"""
Sistema de Bitácora y Auditoría Empresarial (logs/api.log).
Registra: Fecha, Hora, Usuario Autenticado, IP Origen, Endpoint, Resultado y Error.
"""

from __future__ import annotations

import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional

from app.config import settings


def setup_logger() -> logging.Logger:
    """
    Configura y devuelve el logger principal de la API Microsip ERP.
    Crea automáticamente el directorio y archivo logs/api.log.
    """
    log_file = settings.resolved_log_path
    logger = logging.getLogger("microsip_api")

    if logger.handlers:
        return logger

    level = getattr(logging, settings.log_level, logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Handler rotativo en archivo logs/api.log (10 MB por archivo, hasta 5 respaldos)
    file_handler = RotatingFileHandler(
        filename=str(log_file),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    # Handler en consola para monitoreo en vivo
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


api_logger = setup_logger()


def log_audit_event(
    endpoint: str,
    resultado: str,
    usuario: str = "ANONIMO",
    ip_origen: str = "127.0.0.1",
    error: Optional[str] = None,
    level: int = logging.INFO,
) -> None:
    """
    Registra una línea de auditoría estructurada en logs/api.log con todos los campos requeridos:
    - Fecha
    - Hora
    - Usuario autenticado
    - IP origen
    - Endpoint utilizado
    - Resultado
    - Error (si existe)
    """
    now = datetime.now()
    fecha = now.strftime("%Y-%m-%d")
    hora = now.strftime("%H:%M:%S")
    error_str = error if error else "NINGUNO"

    log_line = (
        f"FECHA={fecha} | HORA={hora} | USUARIO={usuario} | "
        f"IP={ip_origen} | ENDPOINT={endpoint} | "
        f"RESULTADO={resultado} | ERROR={error_str}"
    )

    if error and level < logging.WARNING:
        level = logging.ERROR

    api_logger.log(level, log_line)
