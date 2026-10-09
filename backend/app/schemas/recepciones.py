"""
Esquemas de recepción de cilindros (ETAPA 5.1).

`Recepcion` es la cabecera del ingreso de cilindros (TAREA_04): `numero`
lo genera el servidor (correlativo ``REC-<AÑO>-######``, D30),
`usuario_responsable_id` es el usuario autenticado y `fecha_hora` la fija
el servidor. `cliente_entrega_id`/`propietario_id`/`motivo_servicio` son
inmutables; `estado` solo se cambia por `PATCH /recepciones/{id}/estado`
(``COMPLETADA``/``ANULADA``, misma transición → 409).

`DetalleRecepcion` es el sub-recurso anidado con los cilindros recibidos;
`estado_fisico` reproduce el `ck_detalle_recepcion_estado` y
`nivel_llenado_pct` el rango 0–100 (`Literal`/`Field` → 422). La
`UniqueConstraint (recepcion_id, cilindro_id)` impide repetir un cilindro
en la misma recepción (409 `DUPLICATE_VALUE`).

Semántica `null` en PATCH = sin cambio (400 si solo se envían nulos).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Valores permitidos por ck_recepcion_motivo.
MotivoServicio = Literal["LLENADO", "REPARACION", "INSPECCION", "OTRO"]

# Valores permitidos por ck_recepcion_estado.
EstadoRecepcion = Literal["COMPLETADA", "ANULADA"]

# Valores permitidos por ck_detalle_recepcion_estado.
EstadoFisico = Literal["BUENO", "REGULAR", "MALO", "CRITICO"]


# ============================================================
# RECEPCIONES (cabecera)
# ============================================================


class RecepcionCreate(BaseModel):
    """Alta de recepción: nace `COMPLETADA` (numero y fecha del servidor)."""

    cliente_entrega_id: uuid.UUID
    propietario_id: uuid.UUID
    cliente_solicita_id: uuid.UUID | None = None
    documento_referencia: str | None = Field(default=None, max_length=100)
    motivo_servicio: MotivoServicio
    observaciones: str | None = None


class RecepcionUpdate(BaseModel):
    """
    Actualización parcial: `cliente_entrega_id`, `propietario_id` y
    `motivo_servicio` no aparecen (inmutables → 400 si son lo único que se
    envía). `null` = sin cambio.
    """

    cliente_solicita_id: uuid.UUID | None = None
    documento_referencia: str | None = Field(default=None, max_length=100)
    observaciones: str | None = None


class RecepcionEstadoUpdate(BaseModel):
    """Cambio de estado con transición validada (misma → 409)."""

    estado: EstadoRecepcion


class RecepcionResponse(BaseModel):
    """Respuesta de recepción (espejo del modelo)."""

    id: uuid.UUID
    numero: str
    cliente_entrega_id: uuid.UUID
    propietario_id: uuid.UUID
    cliente_solicita_id: uuid.UUID | None
    fecha_hora: datetime
    usuario_responsable_id: uuid.UUID
    documento_referencia: str | None
    motivo_servicio: str
    observaciones: str | None
    estado: str
    fecha_creacion: datetime
    fecha_actualizacion: datetime

    model_config = {"from_attributes": True}


# ============================================================
# DETALLES (sub-recurso de /recepciones/{id})
# ============================================================


class DetalleRecepcionCreate(BaseModel):
    """Alta de un cilindro dentro de una recepción (emite el movimiento)."""

    cilindro_id: uuid.UUID
    estado_fisico: EstadoFisico
    nivel_llenado_pct: int | None = Field(default=None, ge=0, le=100)
    accesorios: dict | None = None
    fotografias: dict | None = None
    observaciones: str | None = None


class DetalleRecepcionResponse(BaseModel):
    """Respuesta de detalle de recepción (espejo del modelo)."""

    id: uuid.UUID
    recepcion_id: uuid.UUID
    cilindro_id: uuid.UUID
    estado_fisico: str
    nivel_llenado_pct: int | None
    accesorios: dict | None
    fotografias: dict | None
    observaciones: str | None
    fecha_creacion: datetime
    fecha_actualizacion: datetime

    model_config = {"from_attributes": True}
