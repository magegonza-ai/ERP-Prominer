"""
Esquemas de movimientos de cilindros (ETAPA 4.2).

`POST /movimientos` es la **única** forma de cambiar la ubicación y el
`estado_operativo` de un cilindro (atómico: inserta el movimiento con
`estado_anterior` derivado del servidor y actualiza el cilindro). Una vez
creo, el registro es **inmutable**: el router no expone PATCH ni DELETE
(trazabilidad pura).

`estado_nuevo: null` = sin cambio de estado (solo cambio de ubicación);
`ubicacion_origen_id` y `estado_anterior` no van en el body (los deriva
el servidor desde el cilindro).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# noqa en TC001: pydantic resuelve esta anotación en runtime (Literal de estado).
from app.schemas.cilindros import EstadoOperativoCilindro  # noqa: TC001


class MovimientoCreate(BaseModel):
    """
    Mueve y/o cambia de estado un cilindro (atómico).

    - El **no-op** (mismo destino **y** mismo estado) → 400.
    - Las validaciones de `permite_entrada`/`permite_salida`/`ACTIVA` del
      destino solo aplican cuando hay cambio real de ubicación.
    - `estado_nuevo` fuera del `ck_cilindro_estado` → 422.
    """

    cilindro_id: uuid.UUID
    ubicacion_destino_id: uuid.UUID
    estado_nuevo: EstadoOperativoCilindro | None = None
    motivo: str | None = Field(default=None, max_length=100)
    observaciones: str | None = None
    usuario_entrega_id: uuid.UUID | None = None
    usuario_recibe_id: uuid.UUID | None = None


class MovimientoResponse(BaseModel):
    """Respuesta de movimiento (espejo del modelo)."""

    id: uuid.UUID
    cilindro_id: uuid.UUID
    ubicacion_origen_id: uuid.UUID | None
    ubicacion_destino_id: uuid.UUID
    estado_anterior: str
    estado_nuevo: str
    usuario_entrega_id: uuid.UUID | None
    usuario_recibe_id: uuid.UUID | None
    fecha_hora: datetime
    motivo: str | None
    observaciones: str | None
    fecha_creacion: datetime
    fecha_actualizacion: datetime

    model_config = {"from_attributes": True}
