"""Esquemas del módulo de tareas y su matriz de permisos (ETAPA 2.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Valores permitidos por ck_tarea_categoria.
CategoriaTarea = Literal[
    "MAESTROS", "OPERATIVO", "CALIDAD", "DESPACHO", "COMERCIAL", "ADMIN", "REPORTES", "AUDITORIA"
]

EstadoTarea = Literal["ACTIVA", "INACTIVA"]


class TareaCreate(BaseModel):
    codigo: str = Field(min_length=2, max_length=30)
    nombre: str = Field(min_length=1, max_length=100)
    descripcion: str | None = None
    categoria: CategoriaTarea
    es_operativa: bool = True
    requiere_supervision: bool = False
    estado: EstadoTarea = "ACTIVA"


class TareaUpdate(BaseModel):
    """Actualización parcial (estado vía PATCH /tareas/{id}/estado)."""

    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    descripcion: str | None = None
    categoria: CategoriaTarea | None = None
    es_operativa: bool | None = None
    requiere_supervision: bool | None = None


class TareaEstadoUpdate(BaseModel):
    estado: EstadoTarea


class TareaResponse(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str
    descripcion: str | None = None
    categoria: str
    es_operativa: bool
    requiere_supervision: bool
    estado: str
    fecha_creacion: datetime
    fecha_actualizacion: datetime


class TareaPermisoCreate(BaseModel):
    """Concede un permiso a la tarea (fila de la matriz tarea_permiso)."""

    permiso_id: uuid.UUID
    concedido: bool = True


class TareaPermisoResponse(BaseModel):
    """La matriz no tiene id propio: se identifica por (tarea_id, permiso_id)."""

    tarea_id: uuid.UUID
    permiso_id: uuid.UUID
    permiso_codigo: str
    permiso_nombre: str
    concedido: bool
