"""
Esquemas de ubicaciones (ETAPA 4.2, subetapa de cilindros).

`codigo` único e inmutable (409 `DUPLICATE_VALUE` al crear, fuera del
`Update` → 400); `tipo` con los valores del modelo
(`INTERNA/CLIENTE/EXTERNA/FUERA`, `Literal` → 422) y **mutable**; estados
`ACTIVA/INACTIVA` vía `PATCH /{id}/estado` (misma transición → 409 con
`allowed_states`). `permite_entrada`/`permite_salida` rigen los
movimientos de cilindros (ETAPA 4.2).

Semántica `null` en PATCH = sin cambio (400 si solo se envían nulos).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TipoUbicacion = Literal["INTERNA", "CLIENTE", "EXTERNA", "FUERA"]
EstadoUbicacion = Literal["ACTIVA", "INACTIVA"]

# Estados de negocio en orden (para allowed_states sin el actual)
_ESTADOS_UBICACION: tuple[str, ...] = ("ACTIVA", "INACTIVA")


class UbicacionCreate(BaseModel):
    """Alta de ubicación (`estado` nace `ACTIVA` por defecto)."""

    codigo: str = Field(min_length=2, max_length=30)
    nombre: str = Field(min_length=1, max_length=100)
    tipo: TipoUbicacion = "INTERNA"
    descripcion: str | None = Field(default=None, max_length=255)
    permite_entrada: bool = True
    permite_salida: bool = True
    orden_visual: int = Field(default=0, ge=0)
    estado: EstadoUbicacion = "ACTIVA"


class UbicacionUpdate(BaseModel):
    """
    Actualización parcial: `codigo` no aparece (inmutable), `estado` se
    gestiona vía `PATCH /{id}/estado`. `null` = sin cambio.
    """

    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    tipo: TipoUbicacion | None = None
    descripcion: str | None = Field(default=None, max_length=255)
    permite_entrada: bool | None = None
    permite_salida: bool | None = None
    orden_visual: int | None = Field(default=None, ge=0)


class UbicacionEstadoUpdate(BaseModel):
    """Cambio de estado con transición validada (409 + allowed_states)."""

    estado: EstadoUbicacion


class UbicacionResponse(BaseModel):
    """Respuesta de ubicación (espejo del modelo)."""

    id: uuid.UUID
    codigo: str
    nombre: str
    tipo: str
    descripcion: str | None
    permite_entrada: bool
    permite_salida: bool
    orden_visual: int
    estado: str
    fecha_creacion: datetime
    fecha_actualizacion: datetime

    model_config = {"from_attributes": True}
