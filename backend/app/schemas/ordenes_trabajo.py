"""
Esquemas de órdenes de trabajo (ETAPA 5.3, llenado y reparación).

La `OrdenTrabajo` es la cabecera del proceso: `numero` lo genera el servidor
(``OTL-<AÑO>-######`` para llenado y ``OTR-<AÑO>-######`` para reparación,
D30), `usuario_creador_id` y `fecha_creacion` los fija el servidor y `estado`
solo cambia por `PATCH /ordenes-trabajo/{id}/estado`. En 5.3 solo se exponen
los tipos ``LLENADO`` y ``REPARACION``.

Cada orden lleva sus cilindros en `detalles` (`DetalleOrden`), creados
**inline** con la cabecera (alta atómica) o por el sub-recurso anidado. El
cilindro debe estar ``APTO_LLENADO`` (llenado) o ``APTO_REPARACION``
(reparación) y no puede repetirse dentro de la orden
(`UNIQUE(orden_id, cilindro_id)` → 409).

Semántica `null` en PATCH = sin cambio (400 si solo se envían nulos).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Valores permitidos por ck_orden_tipo (5.3 solo expone estos dos).
TipoOrden = Literal["LLENADO", "REPARACION"]

# Valores permitidos por ck_orden_prioridad.
Prioridad = Literal["NORMAL", "URGENTE", "EXPRESS"]

# Valores permitidos por ck_orden_estado (5.3 usa PENDIENTE/EN_PROCESO/
# FINALIZADA/PENDIENTE_CALIDAD/CANCELADA; el resto lo fijará 5.4 o queda reservado).
EstadoOrden = Literal[
    "PENDIENTE",
    "PREPARADA",
    "EN_PROCESO",
    "EN_PAUSA",
    "FINALIZADA",
    "PENDIENTE_CALIDAD",
    "APROBADA",
    "RECHAZADA",
    "REQUIERE_NUEVA_REPARACION",
    "CANCELADA",
]


# ============================================================
# DETALLES (cilindros de la orden)
# ============================================================


class DetalleOrdenCreate(BaseModel):
    """Cilindro a incorporar a la orden (debe ser elegible según el tipo)."""

    cilindro_id: uuid.UUID
    tipo_gas_id: uuid.UUID | None = None
    cantidad: float = Field(default=1, gt=0)
    observaciones: str | None = None


class DetalleOrdenEjecucionUpdate(BaseModel):
    """Resultados de ejecución del detalle (pesos/presión/lote). `null` = sin cambio."""

    peso_inicial_kg: float | None = None
    peso_final_kg: float | None = None
    presion_bar: float | None = None
    lote_gas: str | None = Field(default=None, max_length=50)
    observaciones: str | None = None


class DetalleOrdenResponse(BaseModel):
    """Respuesta de detalle de orden (espejo del modelo)."""

    id: uuid.UUID
    orden_id: uuid.UUID
    cilindro_id: uuid.UUID
    tipo_gas_id: uuid.UUID | None
    cantidad: float
    observaciones: str | None
    peso_inicial_kg: float | None
    peso_final_kg: float | None
    presion_bar: float | None
    lote_gas: str | None
    fecha_creacion: datetime
    fecha_actualizacion: datetime

    model_config = {"from_attributes": True}


# ============================================================
# ORDEN DE TRABAJO (cabecera)
# ============================================================


class OrdenTrabajoCreate(BaseModel):
    """Alta de orden: nace `PENDIENTE` con ≥ 1 cilindro (numero del servidor)."""

    tipo: TipoOrden
    area_responsable_id: uuid.UUID
    usuario_asignado_id: uuid.UUID | None = None
    prioridad: Prioridad = "NORMAL"
    fecha_estimada_termino: datetime | None = None

    # Campos específicos por tipo
    tipo_gas_id: uuid.UUID | None = None
    tipo_falla: str | None = Field(default=None, max_length=50)
    diagnostico: str | None = None
    trabajo_solicitado: str | None = None
    observaciones: str | None = None

    detalles: list[DetalleOrdenCreate] = Field(min_length=1)


class OrdenTrabajoUpdate(BaseModel):
    """
    Actualización parcial de la cabecera (solo en `PENDIENTE`). `tipo`,
    `numero`, `estado` y `usuario_creador_id` no aparecen (inmutables).
    `null` = sin cambio.
    """

    area_responsable_id: uuid.UUID | None = None
    usuario_asignado_id: uuid.UUID | None = None
    prioridad: Prioridad | None = None
    fecha_estimada_termino: datetime | None = None
    tipo_gas_id: uuid.UUID | None = None
    tipo_falla: str | None = Field(default=None, max_length=50)
    diagnostico: str | None = None
    trabajo_solicitado: str | None = None
    observaciones: str | None = None


class OrdenTrabajoEstadoUpdate(BaseModel):
    """Cambio de estado con transición validada (misma → 409)."""

    estado: EstadoOrden
    motivo: str | None = Field(default=None, max_length=100)


class OrdenTrabajoResponse(BaseModel):
    """Respuesta de orden de trabajo (espejo del modelo)."""

    id: uuid.UUID
    tipo: str
    numero: str
    fecha_creacion: datetime
    area_responsable_id: uuid.UUID
    usuario_creador_id: uuid.UUID
    usuario_asignado_id: uuid.UUID | None
    prioridad: str
    estado: str
    fecha_inicio: datetime | None
    fecha_estimada_termino: datetime | None
    fecha_termino_real: datetime | None
    resultado: str | None
    observaciones: str | None
    tipo_gas_id: uuid.UUID | None
    tipo_falla: str | None
    diagnostico: str | None
    trabajo_solicitado: str | None
    fecha_actualizacion: datetime | None

    model_config = {"from_attributes": True}


# ============================================================
# TAREAS ASIGNADAS (5.3.b)
# ============================================================

# Valores permitidos por ck_tarea_asig_estado.
EstadoTareaAsignada = Literal[
    "PENDIENTE",
    "ASIGNADA",
    "EN_PROCESO",
    "EN_PAUSA",
    "COMPLETADA",
    "RECHAZADA",
    "CANCELADA",
    "REASIGNADA",
]


class TareaAsignadaCreate(BaseModel):
    """Asigna una tarea RBAC (`tarea_id`) de una orden a un empleado responsable."""

    tarea_id: uuid.UUID
    responsable_id: uuid.UUID
    cilindro_id: uuid.UUID | None = None
    prioridad: Prioridad = "NORMAL"
    fecha_estimada_termino: datetime | None = None
    observaciones: str | None = None


class TareaAsignadaUpdate(BaseModel):
    """
    Actualización parcial: avance de estado y datos de ejecución.
    `null` = sin cambio; la transición de `estado` se valida.
    """

    estado: EstadoTareaAsignada | None = None
    prioridad: Prioridad | None = None
    fecha_estimada_termino: datetime | None = None
    resultado: str | None = None
    observaciones: str | None = None
    evidencias: dict | None = None


class TareaAsignadaReasignar(BaseModel):
    """Reasigna la tarea a otro empleado dejando traza (D34)."""

    nuevo_responsable_id: uuid.UUID
    motivo: str | None = Field(default=None, max_length=200)


class TareaAsignadaResponse(BaseModel):
    """Respuesta de tarea asignada (espejo del modelo, con traza de reasignación)."""

    id: uuid.UUID
    orden_id: uuid.UUID
    tarea_id: uuid.UUID
    cilindro_id: uuid.UUID | None
    responsable_id: uuid.UUID
    estado: str
    prioridad: str
    fecha_asignacion: datetime
    fecha_inicio: datetime | None
    fecha_termino: datetime | None
    fecha_estimada_termino: datetime | None
    resultado: str | None
    observaciones: str | None
    evidencias: dict | None
    reasignada_desde_id: uuid.UUID | None
    usuario_reasigno_id: uuid.UUID | None
    fecha_reasignacion: datetime | None
    motivo_reasignacion: str | None

    model_config = {"from_attributes": True}
