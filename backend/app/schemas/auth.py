"""
Esquemas de autenticación (ETAPA 2): login, renovación de tokens y
usuario autenticado.

Los campos de tokens siguen el formato OAuth2 estándar (access_token,
refresh_token, token_type, expires_in) para compatibilidad con clientes
hábidos.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Credenciales de inicio de sesión."""

    username: str = Field(min_length=1, max_length=50, examples=["admin"])
    password: str = Field(
        min_length=1,
        max_length=1024,
        description="Contraseña en texto plano (se compara con bcrypt).",
    )
    totp_code: str | None = Field(
        default=None,
        min_length=6,
        max_length=6,
        description="Código TOTP (2FA); requerido si la cuenta lo tiene activado.",
    )


class RefreshRequest(BaseModel):
    """Refresh token para renovar la sesión sin repetir credenciales."""

    refresh_token: str = Field(min_length=1, max_length=4096)


class TokenResponse(BaseModel):
    """Par de tokens emitido por login y refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Vigencia del access token en segundos.")


class UsuarioActualResponse(BaseModel):
    """Usuario autenticado con sus permisos RBAC efectivos."""

    id: uuid.UUID
    username: str
    email: str
    estado: str
    empleado_id: uuid.UUID | None = None
    requiere_cambio_password: bool
    totp_activado: bool
    ultimo_acceso: datetime | None = None
    permisos: list[str] = []
