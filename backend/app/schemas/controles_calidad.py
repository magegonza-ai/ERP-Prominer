"""
Esquemas de control de calidad de cilindros (ETAPA 5.4).

`ControlCalidad` es el registro del control de calidad **post-proceso**
(llenado/reparación) de un cilindro: es **append-only** (POST + GET, sin
PATCH/DELETE), `usuario_id` es el usuario autenticado y `fecha_hora` la fija
el servidor.

En 5.4 el control se asocia **obligatoriamente** a la orden de trabajo origen
(`orden_relacionada_id`): la orden debe estar `PENDIENTE_CALIDAD` y el
cilindro `PENDIENTE_CONTROL_CALIDAD`. `resultado` reproduce el
`ck_control_calidad_resultado` y mueve el `estado_operativo` del cilindro vía
`Movimiento` (D31):

    APROBADO                   -> LISTO_PARA_ENTREGAR (si autoriza_entrega) o APROBADO
    APROBADO_OBSERVACIONES     -> APROBADO_OBSERVACIONES
    REQUIERE_NUEVA_REPARACION  -> APTO_REPARACION
    RECHAZADO                  -> RECHAZADO
    PENDIENTE_REVISION         -> sin cambio (deja el cilindro controlable de nuevo)

El checklist (todas opcionales) refleja las columnas `Boolean` del modelo
(`bool` → 422).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# Valores permitidos por ck_control_calidad_resultado.
ResultadoControlCalidad = Literal[
    "APROBADO",
    "APROBADO_OBSERVACIONES",
    "REQUIERE_NUEVA_REPARACION",
    "RECHAZADO",
    "PENDIENTE_REVISION",
]


class ControlCalidadCreate(BaseModel):
    """Alta de control de calidad (usuario y fecha los deriva el servidor)."""

    cilindro_id: uuid.UUID
    orden_relacionada_id: uuid.UUID

    # Checklist (todo opcional).
    presion_ok: bool | None = None
    peso_ok: bool | None = None
    fuga_ok: bool | None = None
    etiquetado_ok: bool | None = None
    pintura_ok: bool | None = None
    accesorios_ok: bool | None = None
    documentacion_ok: bool | None = None

    resultado: ResultadoControlCalidad
    observaciones: str | None = None
    autoriza_entrega: bool = False
    fotografias: dict | None = None


class ControlCalidadResponse(BaseModel):
    """Respuesta de control de calidad (espejo del modelo)."""

    id: uuid.UUID
    cilindro_id: uuid.UUID
    orden_relacionada_id: uuid.UUID | None
    usuario_id: uuid.UUID
    fecha_hora: datetime

    presion_ok: bool | None
    peso_ok: bool | None
    fuga_ok: bool | None
    etiquetado_ok: bool | None
    pintura_ok: bool | None
    accesorios_ok: bool | None
    documentacion_ok: bool | None

    resultado: str
    observaciones: str | None
    autoriza_entrega: bool
    fotografias: dict | None
    fecha_creacion: datetime
    fecha_actualizacion: datetime

    model_config = {"from_attributes": True}
