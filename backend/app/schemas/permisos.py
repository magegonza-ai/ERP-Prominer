"""Esquemas del módulo de permisos (catálogo de acciones, ETAPA 2.1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PermisoCreate(BaseModel):
    codigo: str = Field(min_length=2, max_length=30)
    nombre: str = Field(min_length=1, max_length=50)
    descripcion: str | None = None
    es_critico: bool = False


class PermisoUpdate(BaseModel):
    """Actualización parcial. `codigo` es inmutable (lo referencian las
    configuraciones de permisos de los endpoints)."""

    nombre: str | None = Field(default=None, min_length=1, max_length=50)
    descripcion: str | None = None
    es_critico: bool | None = None


class PermisoResponse(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str
    descripcion: str | None = None
    es_critico: bool
    fecha_creacion: datetime
    fecha_actualizacion: datetime
