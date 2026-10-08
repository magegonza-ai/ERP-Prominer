"""Esquemas del módulo de empleados (ETAPA 2.1)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# Estados permitidos por la restricción ck_empleado_estado.
EstadosEmpleado = Literal["ACTIVO", "INACTIVO", "SUSPENDIDO", "LICENCIA", "RETIRADO"]
TODOS_ESTADOS_EMPLEADO = ("ACTIVO", "INACTIVO", "SUSPENDIDO", "LICENCIA", "RETIRADO")

_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class EmpleadoCreate(BaseModel):
    """Alta de empleado (siempre inicia ACTIVO)."""

    rut: str = Field(min_length=8, max_length=12)
    nombres: str = Field(min_length=1, max_length=100)
    apellidos: str = Field(min_length=1, max_length=100)
    cargo: str = Field(min_length=1, max_length=100)
    area_id: uuid.UUID
    correo: str = Field(min_length=5, max_length=150, pattern=_EMAIL_PATTERN)
    telefono: str | None = Field(default=None, max_length=20)
    fecha_ingreso: date
    observaciones: str | None = None


class EmpleadoUpdate(BaseModel):
    """Actualización parcial. Los campos ausentes o `null` no se modifican."""

    nombres: str | None = Field(default=None, min_length=1, max_length=100)
    apellidos: str | None = Field(default=None, min_length=1, max_length=100)
    cargo: str | None = Field(default=None, min_length=1, max_length=100)
    area_id: uuid.UUID | None = None
    correo: str | None = Field(default=None, min_length=5, max_length=150, pattern=_EMAIL_PATTERN)
    telefono: str | None = Field(default=None, max_length=20)
    fecha_ingreso: date | None = None
    observaciones: str | None = None


class EmpleadoEstadoUpdate(BaseModel):
    """Transición de estado laboral (baja definitiva = RETIRADO)."""

    estado: EstadosEmpleado


class EmpleadoResponse(BaseModel):
    id: uuid.UUID
    rut: str
    nombres: str
    apellidos: str
    cargo: str
    area_id: uuid.UUID
    correo: str
    telefono: str | None = None
    fecha_ingreso: date
    observaciones: str | None = None
    estado: str
    fecha_creacion: datetime
    fecha_actualizacion: datetime


class AsignacionTareaCreate(BaseModel):
    """Asignación de una tarea catálogo al empleado (queda VIGENTE)."""

    tarea_id: uuid.UUID
    fecha_inicio: date | None = None
    fecha_termino: date | None = None
    observaciones: str | None = None


class AsignacionTareaResponse(BaseModel):
    id: uuid.UUID
    empleado_id: uuid.UUID
    tarea_id: uuid.UUID
    fecha_asignacion: date
    fecha_inicio: date | None = None
    fecha_termino: date | None = None
    estado: str
    observaciones: str | None = None
    usuario_asigno_id: uuid.UUID
    fecha_creacion: datetime
    fecha_actualizacion: datetime
