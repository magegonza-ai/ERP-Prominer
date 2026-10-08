"""
Esquemas de propietarios de cilindros (ETAPA 4.1).

`tipo` (`CLIENTE/AGAS/EMPRESA_EXTERNA`, `ck_propietario_tipo`) y `rut` son
inmutables (ausentes de `PropietarioUpdate`); los estados se validan con
`Literal` (`ck_propietario_estado`: `ACTIVO/INACTIVO/BLOQUEADO`). El `null`
en la actualización parcial significa "sin cambio" — incluido `cliente_id`,
que es el vínculo con el cliente (solo obligatorio en tipo CLIENTE, el
cambio de vínculo se valida en el endpoint).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Valores permitidos por ck_propietario_tipo.
TipoPropietario = Literal["CLIENTE", "AGAS", "EMPRESA_EXTERNA"]

# Valores permitidos por ck_propietario_estado.
EstadoPropietario = Literal["ACTIVO", "INACTIVO", "BLOQUEADO"]


class PropietarioCreate(BaseModel):
    tipo: TipoPropietario
    rut: str = Field(min_length=1, max_length=12)
    razon_social: str = Field(min_length=1, max_length=200)
    cliente_id: uuid.UUID | None = None
    direccion: str | None = Field(default=None, max_length=300)
    comuna: str | None = Field(default=None, max_length=100)
    ciudad: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    telefono: str | None = Field(default=None, max_length=20)
    correo: str | None = Field(default=None, max_length=150)
    persona_contacto: str | None = Field(default=None, max_length=150)
    observaciones: str | None = None
    es_institucional_agas: bool = False
    estado: EstadoPropietario = "ACTIVO"


class PropietarioUpdate(BaseModel):
    """Actualización parcial (`tipo` y `rut` inmutables; estado vía PATCH /propietarios/{id}/estado)."""

    razon_social: str | None = Field(default=None, min_length=1, max_length=200)
    cliente_id: uuid.UUID | None = None
    direccion: str | None = Field(default=None, max_length=300)
    comuna: str | None = Field(default=None, max_length=100)
    ciudad: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    telefono: str | None = Field(default=None, max_length=20)
    correo: str | None = Field(default=None, max_length=150)
    persona_contacto: str | None = Field(default=None, max_length=150)
    observaciones: str | None = None
    es_institucional_agas: bool | None = None


class PropietarioEstadoUpdate(BaseModel):
    estado: EstadoPropietario


class PropietarioResponse(BaseModel):
    id: uuid.UUID
    tipo: str
    rut: str
    razon_social: str
    cliente_id: uuid.UUID | None = None
    direccion: str | None = None
    comuna: str | None = None
    ciudad: str | None = None
    region: str | None = None
    telefono: str | None = None
    correo: str | None = None
    persona_contacto: str | None = None
    observaciones: str | None = None
    es_institucional_agas: bool
    estado: str
    fecha_creacion: datetime
    fecha_actualizacion: datetime
