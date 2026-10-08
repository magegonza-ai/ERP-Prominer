"""
Esquemas de cilindros (ETAPA 4.2, entidad central).

Identidad **única e inmutable**: `codigo_interno`, `numero_serie` y
`codigo_qr` (409 `DUPLICATE_VALUE` al crear; fuera del `Update` → 400);
`codigo_barras` único pero **sí editable** (revalidado → 409).

Alta: valida FKs → 404 (`propietario_id`, `tipo_gas_id`,
`ubicacion_actual_id`) y **nace `REGISTRADO`** — `estado_operativo` no va
en el Create ni en el Update (los cambios de estado y de ubicación solo
vía `POST /movimientos`, para no romper la trazabilidad; `propietario_id`
y `tipo_gas_id` tampoco: el cambio de propietario es TAREA_20 con
`CambioPropietario` en una etapa posterior).

Semántica `null` en PATCH = sin cambio (400 si solo se envían nulos).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# Los 20 estados del ck_cilindro_estado, en orden del modelo.
EstadoOperativoCilindro = Literal[
    "REGISTRADO",
    "RECIBIDO",
    "PENDIENTE_INSPECCION",
    "APTO_LLENADO",
    "ENVIADO_LLENADO",
    "EN_PROCESO_LLENADO",
    "FINALIZADO_LLENADO",
    "APTO_REPARACION",
    "ENVIADO_REPARACION",
    "EN_REPARACION",
    "REPARADO",
    "PENDIENTE_CONTROL_CALIDAD",
    "APROBADO",
    "APROBADO_OBSERVACIONES",
    "LISTO_PARA_ENTREGAR",
    "ENTREGADO",
    "OBSERVADO",
    "RECHAZADO",
    "FUERA_SERVICIO",
    "DADO_DE_BAJA",
]

# Límite técnico de Numeric(8, 2) para no provocar error 500 en BD.
_CAPACIDAD_MAX = 99_999_999.99


class CilindroCreate(BaseModel):
    """Alta de cilindro (siempre nace `REGISTRADO` en ubicación indicada)."""

    codigo_interno: str = Field(min_length=1, max_length=30)
    numero_serie: str = Field(min_length=1, max_length=50)
    codigo_qr: str = Field(min_length=1, max_length=100)
    codigo_barras: str | None = Field(default=None, max_length=100)
    propietario_id: uuid.UUID
    tipo_gas_id: uuid.UUID
    ubicacion_actual_id: uuid.UUID
    capacidad_kg: float = Field(ge=0, le=_CAPACIDAD_MAX)
    marca: str | None = Field(default=None, max_length=100)
    fabricante: str | None = Field(default=None, max_length=100)
    color: str | None = Field(default=None, max_length=30)
    fecha_fabricacion: date | None = None
    fecha_ultima_prueba_hidraulica: date | None = None
    fecha_vencimiento_prueba: date | None = None
    fotografia_url: str | None = Field(default=None, max_length=500)
    observaciones: str | None = None


class CilindroUpdate(BaseModel):
    """
    Solo campos descriptivos: los tres códigos de identidad, las FKs
    (`propietario_id`, `tipo_gas_id`, `ubicacion_actual_id`) y
    `estado_operativo` no aparecen (inmutables → 400 si son lo único que
    se envía). `null` = sin cambio.
    """

    codigo_barras: str | None = Field(default=None, max_length=100)
    capacidad_kg: float | None = Field(default=None, ge=0, le=_CAPACIDAD_MAX)
    marca: str | None = Field(default=None, max_length=100)
    fabricante: str | None = Field(default=None, max_length=100)
    color: str | None = Field(default=None, max_length=30)
    fecha_fabricacion: date | None = None
    fecha_ultima_prueba_hidraulica: date | None = None
    fecha_vencimiento_prueba: date | None = None
    fotografia_url: str | None = Field(default=None, max_length=500)
    observaciones: str | None = None


class CilindroResponse(BaseModel):
    """Respuesta de cilindro (espejo del modelo; `estado_operativo` es su estado real)."""

    id: uuid.UUID
    codigo_interno: str
    numero_serie: str
    codigo_qr: str
    codigo_barras: str | None
    propietario_id: uuid.UUID
    tipo_gas_id: uuid.UUID
    ubicacion_actual_id: uuid.UUID
    capacidad_kg: float
    marca: str | None
    fabricante: str | None
    color: str | None
    fecha_fabricacion: date | None
    fecha_ultima_prueba_hidraulica: date | None
    fecha_vencimiento_prueba: date | None
    estado_operativo: str
    fotografia_url: str | None
    observaciones: str | None
    fecha_creacion: datetime
    fecha_actualizacion: datetime

    model_config = {"from_attributes": True}
