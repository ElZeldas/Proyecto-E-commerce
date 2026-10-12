"""
Módulo de configuración centralizada mediante variables de entorno (.env).
Cumple con políticas de seguridad empresarial: cero credenciales hardcodeadas.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Directorio raíz del proyecto (microsip-api/)
BASE_DIR: Path = Path(__file__).resolve().parent.parent
ENV_FILE: Path = BASE_DIR / ".env"

# Cargar variables de entorno desde .env
load_dotenv(dotenv_path=ENV_FILE, override=False)


def _discover_fbclient_dll() -> Optional[str]:
    """
    Detecta automáticamente la librería cliente de Firebird (fbclient.dll) en Windows
    compatible con la arquitectura del intérprete de Python (64-bit o 32-bit).
    """
    explicit_path = os.getenv("FIREBIRD_CLIENT_LIBRARY", "").strip()
    if explicit_path and Path(explicit_path).is_file():
        return explicit_path

    is_64bit = struct.calcsize("P") * 8 == 64

    candidate_paths: List[Path] = [
        BASE_DIR / "fbclient.dll",
        BASE_DIR / ".." / "fbclient.dll",
    ]
    import sys
    if getattr(sys, 'frozen', False):
        candidate_paths.append(Path(sys.executable).parent / "fbclient.dll")
        if hasattr(sys, '_MEIPASS'):
            candidate_paths.append(Path(sys._MEIPASS) / "fbclient.dll")
    if is_64bit:
        candidate_paths.extend(
            [
                Path(r"C:\Program Files\Firebird\Firebird_5_0\fbclient.dll"),
                Path(r"C:\Program Files\Firebird\Firebird_4_0\fbclient.dll"),
                Path(r"C:\Program Files\Firebird\Firebird_3_0\fbclient.dll"),
                Path(r"C:\Program Files\Firebird\Firebird_2_5\bin\fbclient.dll"),
                Path(r"C:\Program Files\Firebird\Firebird_2_5\WOW64\fbclient.dll"),
                Path(r"C:\Windows\System32\fbclient.dll"),
            ]
        )
    else:
        candidate_paths.extend(
            [
                Path(r"C:\Program Files (x86)\Firebird\Firebird_5_0\fbclient.dll"),
                Path(r"C:\Program Files (x86)\Firebird\Firebird_4_0\fbclient.dll"),
                Path(r"C:\Program Files (x86)\Firebird\Firebird_3_0\fbclient.dll"),
                Path(r"C:\Program Files (x86)\Firebird\Firebird_2_5\bin\fbclient.dll"),
                Path(r"C:\Windows\SysWOW64\fbclient.dll"),
            ]
        )

    for candidate in candidate_paths:
        if candidate.is_file():
            return str(candidate)

    return None


class Settings(BaseModel):
    """Configuración tipada de la API Microsip ERP (Solo Lectura)."""

    # Parámetros de conexión Firebird TCP/IP Remota
    db_host: str = Field(default_factory=lambda: os.getenv("MICROSIP_DB_HOST", "192.168.1.5").strip())
    db_port: int = Field(default_factory=lambda: int(os.getenv("MICROSIP_DB_PORT", "3050").strip()))
    db_path: str = Field(
        default_factory=lambda: os.getenv(
            "MICROSIP_DB_PATH", r"E:\Microsip datos\CAPACITACION.FDB"
        ).strip()
    )
    db_charset: str = Field(default_factory=lambda: os.getenv("MICROSIP_DB_CHARSET", "WIN1252").strip())
    db_timeout: int = Field(default_factory=lambda: int(os.getenv("MICROSIP_DB_TIMEOUT", "10").strip()))

    # Credenciales opcionales de servicio (nunca hardcodeadas en código fuente)
    db_user: str = Field(default_factory=lambda: os.getenv("MICROSIP_DB_USER", "").strip())
    db_password: str = Field(default_factory=lambda: os.getenv("MICROSIP_DB_PASSWORD", "").strip())

    # Librería cliente Firebird
    fb_client_library: Optional[str] = Field(default_factory=_discover_fbclient_dll)

    # Seguridad JWT
    jwt_secret_key: str = Field(
        default_factory=lambda: os.getenv(
            "JWT_SECRET_KEY", "microsip-readonly-enterprise-jwt-secret-key-change-me"
        ).strip()
    )
    jwt_algorithm: str = Field(default_factory=lambda: os.getenv("JWT_ALGORITHM", "HS256").strip())
    jwt_expiration_minutes: int = Field(
        default_factory=lambda: int(os.getenv("JWT_EXPIRATION_MINUTES", "480").strip())
    )

    # Servidor HTTP FastAPI
    api_host: str = Field(default_factory=lambda: os.getenv("API_HOST", "0.0.0.0").strip())
    api_port: int = Field(default_factory=lambda: int(os.getenv("API_PORT", "8000").strip()))
    api_env: str = Field(default_factory=lambda: os.getenv("API_ENV", "production").strip())
    cors_origins: str = Field(default_factory=lambda: os.getenv("CORS_ORIGINS", "*").strip())

    # Archivos de bitácora y reportes
    log_file_path: str = Field(default_factory=lambda: os.getenv("LOG_FILE_PATH", "logs/api.log").strip())
    log_level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").strip().upper())
    inspection_report_path: str = Field(
        default_factory=lambda: os.getenv(
            "INSPECTION_REPORT_PATH", "logs/inspection_report.json"
        ).strip()
    )

    @property
    def firebird_dsn(self) -> str:
        """
        Construye el DSN TCP/IP remoto estándar de Firebird:
        <host>/<port>:<ruta_remota_fdb>
        Ejemplo: 192.168.1.5/3050:E:\\Microsip datos\\CAPACITACION.FDB
        """
        return f"{self.db_host}/{self.db_port}:{self.db_path}"

    @property
    def resolved_log_path(self) -> Path:
        """Ruta absoluta hacia logs/api.log garantizando que el directorio exista."""
        log_path = Path(self.log_file_path)
        if not log_path.is_absolute():
            log_path = BASE_DIR / log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        return log_path

    @property
    def resolved_inspection_report_path(self) -> Path:
        """Ruta absoluta hacia el reporte JSON de inspección de la base de datos."""
        report_path = Path(self.inspection_report_path)
        if not report_path.is_absolute():
            report_path = BASE_DIR / report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        return report_path

    @property
    def cors_origins_list(self) -> List[str]:
        if self.cors_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
