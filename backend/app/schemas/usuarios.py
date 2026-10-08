"""Esquemas del módulo de usuarios (ETAPA 2.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Estados permitidos por la restricción ck_usuario_estado.
EstadosUsuario = Literal["ACTIVO", "BLOQUEADO", "EXPIRADO", "PENDIENTE_ACTIVACION"]
TODOS_ESTADOS_USUARIO = ("ACTIVO", "BLOQUEADO", "EXPIRADO", "PENDIENTE_ACTIVACION")

_USERNAME_PATTERN = r"^[a-zA-Z0-9._-]+$"
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class UsuarioCreate(BaseModel):
    """Alta de usuario. Sin `estado` el valor por defecto es PENDIENTE_ACTIVACION."""

    username: str = Field(min_length=3, max_length=50, pattern=_USERNAME_PATTERN)
    email: str = Field(min_length=5, max_length=150, pattern=_EMAIL_PATTERN)
    password: str = Field(
        min_length=1,
        max_length=1024,
        description="Texto plano; se valida contra la política y se guarda con bcrypt.",
    )
    empleado_id: uuid.UUID | None = Field(default=None, description="Vincula la cuenta a un empleado.")
    estado: EstadosUsuario | None = None
    requiere_cambio_password: bool = True


class UsuarioUpdate(BaseModel):
    """Actualización parcial. Los campos ausentes o `null` no se modifican."""

    username: str | None = Field(default=None, min_length=3, max_length=50, pattern=_USERNAME_PATTERN)
    email: str | None = Field(default=None, min_length=5, max_length=150, pattern=_EMAIL_PATTERN)
    empleado_id: uuid.UUID | None = None
    requiere_cambio_password: bool | None = None


class UsuarioEstadoUpdate(BaseModel):
    """Transición de estado de la cuenta (ciclo completo permitido)."""

    estado: EstadosUsuario


class UsuarioPasswordUpdate(BaseModel):
    """Reseteo de contraseña por administrador (aplica la política)."""

    password: str = Field(min_length=1, max_length=1024)


class UsuarioResponse(BaseModel):
    """Usuario sin datos sensibles (sin password_hash ni totp_secret)."""

    id: uuid.UUID
    username: str
    email: str
    estado: str
    empleado_id: uuid.UUID | None = None
    requiere_cambio_password: bool
    totp_activado: bool
    intentos_fallidos: int
    bloqueado_hasta: datetime | None = None
    ultimo_acceso: datetime | None = None
    fecha_creacion: datetime
    fecha_actualizacion: datetime
