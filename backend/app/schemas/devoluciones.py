"""
Esquemas de devoluciones de cilindros (ETAPA 5.6).

`Devolucion` es la cabecera del retorno de cilindros `ENTREGADO` a AGAS
(dominio RBAC TAREA_19 «Registrar devoluciones»): `numero` lo genera el
servidor (``DEV-<AÑO>-######``, D30), `usuario_responsable_id` es el usuario
autenticado y `fecha_hora` la fija el servidor. `estado` solo cambia por
`PATCH /devoluciones/{id}/estado`:

    REGISTRADA → ANULADA   (terminal)

Cada devolución lleva sus cilindros en `detalles` (`DevolucionDetalle`),
creados **inline** con la cabecera (alta atómica). El cilindro debe estar en
`ENTREGADO`, no repetirse y no figurar en otra devolución activa (409). La
`UniqueConstraint (devolucion_id, cilindro_id)` impide repetir un cilindro en
la misma devolución (409 `DUPLICATE_VALUE`).

Al registrar la devolución se emite un `Movimiento` por cilindro en la misma
transacción (D31): ``ENTREGADO → RECIBIDO`` con `usuario_recibe_id`; si se
indica `ubicacion_destino_id`, además se actualiza la ubicación del cilindro.
La anulación **no** revierte la traza (la devolución ya ocurrió físicamente).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Valores permitidos por ck_devolucion_estado.
EstadoDevolucion = Literal["REGISTRADA", "ANULADA"]

# Valores permitidos por ck_devolucion_motivo.
MotivoDevolucion = Literal[
    "DEVOLUCION_CLIENTE",
    "DANO_EN_TRANSITO",
    "ERROR_ENTREGA",
    "GARANTIA",
    "OTRO",
]

# Valores permitidos por ck_detalle_devolucion_estado.
EstadoFisico = Literal["BUENO", "REGULAR", "MALO", "CRITICO"]


# ============================================================
# DETALLES (cilindros devueltos)
# ============================================================


class DetalleDevolucionCreate(BaseModel):
    """Cilindro devuelto (estado físico al ingreso)."""

    cilindro_id: uuid.UUID
    estado_fisico: EstadoFisico
    accesorios: dict | None = None
    observaciones: str | None = None


# ============================================================
# DEVOLUCIÓN (cabecera)
# ============================================================


class DevolucionCreate(BaseModel):
    """Alta de devolución: nace `REGISTRADA` con >= 1 cilindro (numero del servidor)."""

    cliente_devuelve_id: uuid.UUID
    entrega_id: uuid.UUID | None = None
    motivo: MotivoDevolucion
    documento_referencia: str | None = Field(default=None, max_length=100)
    observaciones: str | None = None
    ubicacion_destino_id: uuid.UUID | None = None
    detalles: list[DetalleDevolucionCreate] = Field(min_length=1)


class DevolucionUpdate(BaseModel):
    """
    Actualización de campos descriptivos (solo en `REGISTRADA`).

    `None` = sin cambio (se filtra con `exclude_unset`). Los detalles y
    `ubicacion_destino_id` se excluyen: el `Movimiento` (y la ubicación del
    cilindro) ya se materializó al crear la devolución y no se recalcula.
    """

    motivo: MotivoDevolucion | None = None
    documento_referencia: str | None = None
    observaciones: str | None = None


class DevolucionEstadoUpdate(BaseModel):
    """Cambio de estado con transición validada (solo `ANULADA`)."""

    estado: EstadoDevolucion


# ============================================================
# RESPUESTAS
# ============================================================


class ClienteDevolucion(BaseModel):
    """Resumen del cliente que devuelve los cilindros."""

    id: uuid.UUID
    rut: str
    razon_social: str


class EntregaDevolucion(BaseModel):
    """Resumen de la entrega de referencia (opcional)."""

    id: uuid.UUID
    numero: str


class UbicacionDevolucion(BaseModel):
    """Resumen de la ubicación de destino (opcional)."""

    id: uuid.UUID
    nombre: str


class TipoGasDevolucion(BaseModel):
    """Resumen del tipo de gas del cilindro."""

    id: uuid.UUID
    codigo: str
    nombre: str


class CilindroDevolucion(BaseModel):
    """Resumen del cilindro devuelto."""

    id: uuid.UUID
    codigo_interno: str
    numero_serie: str
    estado_operativo: str
    tipo_gas: TipoGasDevolucion | None = None


class DetalleDevolucionResponse(BaseModel):
    """Respuesta de detalle de devolución (espejo del modelo + cilindro)."""

    id: uuid.UUID
    devolucion_id: uuid.UUID
    cilindro_id: uuid.UUID
    cilindro: CilindroDevolucion | None = None
    estado_fisico: str
    accesorios: dict | None
    observaciones: str | None
    fecha_creacion: datetime
    fecha_actualizacion: datetime | None

    model_config = {"from_attributes": True}


class DevolucionResponse(BaseModel):
    """Respuesta de devolución (espejo del modelo + relaciones)."""

    id: uuid.UUID
    numero: str
    cliente_devuelve_id: uuid.UUID
    cliente_devuelve: ClienteDevolucion | None = None
    entrega_id: uuid.UUID | None
    entrega: EntregaDevolucion | None = None
    fecha_hora: datetime
    usuario_responsable_id: uuid.UUID
    motivo: str
    documento_referencia: str | None
    observaciones: str | None
    ubicacion_destino_id: uuid.UUID | None
    ubicacion_destino: UbicacionDevolucion | None = None
    estado: str
    detalles: list[DetalleDevolucionResponse] = []
    fecha_creacion: datetime
    fecha_actualizacion: datetime | None

    model_config = {"from_attributes": True}
