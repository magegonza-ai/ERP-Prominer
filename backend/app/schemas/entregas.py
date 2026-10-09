"""
Esquemas de entregas de cilindros (ETAPA 5.5 — despacho y entregas).

`Entrega` es la cabecera del despacho/entrega de cilindros a un cliente
(dominios RBAC TAREA_17 «Preparar entregas» / TAREA_18 «Entregar
cilindros»): `numero` lo genera el servidor (``ENT-<AÑO>-######``, D30),
`usuario_responsable_id` es el usuario autenticado y `fecha_hora` la fija
el servidor. `estado` solo cambia por `PATCH /entregas/{id}/estado`:

    BORRADOR → PENDIENTE → CONFIRMADA → ENTREGADA   (terminales)
    BORRADOR/PENDIENTE → CANCELADA                  (terminal)

Cada entrega lleva sus cilindros en `detalles` (`DetalleEntrega`), creados
**inline** con la cabecera (alta atómica). El cilindro debe estar en estado
despachable (RN13: `APROBADO` o `LISTO_PARA_ENTREGAR`), pertenecer al
propietario de la entrega y no figurar en otra entrega activa (409). La
`UniqueConstraint (entrega_id, cilindro_id)` impide repetir un cilindro en
la misma entrega (409 `DUPLICATE_VALUE`).

`cantidad` queda fija en 1 (una fila = un cilindro); las columnas
monetarias (valorización en subetapa/ETAPA posterior) usan default 0 y el
servidor calcula `subtotal`, `impuesto_monto` y `total` por fórmula.

Al pasar a `ENTREGADA` se emite un `Movimiento` por cilindro en la misma
transacción (D31): ``<estado actual> → ENTREGADO``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Valores permitidos por ck_entrega_estado (5.5 no expone EXCEPCION_DOC:
# queda reservado para la ETAPA de documentos).
EstadoEntrega = Literal["BORRADOR", "PENDIENTE", "CONFIRMADA", "ENTREGADA", "CANCELADA"]

# Valores permitidos por ck_entrega_firma_tipo.
FirmaTipo = Literal["DIGITAL", "FOTO_MANUSCRITA", "HUELLA", "OTRO"]

# Valores de receptor_relacion (comentario del modelo).
ReceptorRelacion = Literal["PROPIETARIO", "CHOFER", "REPRESENTANTE", "TERCERO"]


# ============================================================
# DETALLES (cilindros de la entrega)
# ============================================================


class DetalleEntregaCreate(BaseModel):
    """Cilindro a despachar (cantidad = 1; montos con default 0)."""

    cilindro_id: uuid.UUID
    precio_unitario: float = 0
    descuento_pct: float = 0
    descuento_monto: float = 0
    tasa_impuesto_pct: float = 0
    observaciones: str | None = None


# ============================================================
# ENTREGA (cabecera)
# ============================================================


class EntregaCreate(BaseModel):
    """Alta de entrega: nace `BORRADOR` con ≥ 1 cilindro (numero del servidor)."""

    cliente_recibe_id: uuid.UUID
    propietario_id: uuid.UUID
    receptor_nombre: str = Field(min_length=1, max_length=150)
    receptor_rut: str | None = Field(default=None, max_length=12)
    receptor_relacion: ReceptorRelacion | None = None
    observaciones: str | None = None
    detalles: list[DetalleEntregaCreate] = Field(min_length=1)


class EntregaUpdate(BaseModel):
    """Reemplazo de cabecera y cilindros (solo en `BORRADOR`)."""

    cliente_recibe_id: uuid.UUID
    propietario_id: uuid.UUID
    receptor_nombre: str = Field(min_length=1, max_length=150)
    receptor_rut: str | None = Field(default=None, max_length=12)
    receptor_relacion: ReceptorRelacion | None = None
    observaciones: str | None = None
    detalles: list[DetalleEntregaCreate] = Field(min_length=1)


class EntregaEstadoUpdate(BaseModel):
    """
    Cambio de estado con transición validada (misma/inválida → 409).

    Los campos de receptor/firma son opcionales: permiten capturar en
    terreno la confirmación al marcar `ENTREGADA`.
    """

    estado: EstadoEntrega
    receptor_nombre: str | None = Field(default=None, min_length=1, max_length=150)
    receptor_rut: str | None = Field(default=None, max_length=12)
    receptor_relacion: ReceptorRelacion | None = None
    firma_confirmacion_url: str | None = Field(default=None, max_length=500)
    firma_tipo: FirmaTipo | None = None
    observaciones: str | None = None
    motivo: str | None = Field(default=None, max_length=100)


# ============================================================
# RESPUESTAS
# ============================================================


class ClienteEntrega(BaseModel):
    """Resumen del cliente que recibe la entrega."""

    id: uuid.UUID
    rut: str
    razon_social: str


class PropietarioEntrega(BaseModel):
    """Resumen del propietario de los cilindros despachados."""

    id: uuid.UUID
    rut: str
    razon_social: str


class TipoGasEntrega(BaseModel):
    """Resumen del tipo de gas del cilindro."""

    id: uuid.UUID
    codigo: str
    nombre: str


class CilindroEntrega(BaseModel):
    """Resumen del cilindro despachado."""

    id: uuid.UUID
    codigo_interno: str
    numero_serie: str
    estado_operativo: str
    tipo_gas: TipoGasEntrega | None = None


class DetalleEntregaResponse(BaseModel):
    """Respuesta de detalle de entrega (espejo del modelo + cilindro)."""

    id: uuid.UUID
    entrega_id: uuid.UUID
    cilindro_id: uuid.UUID
    cilindro: CilindroEntrega | None = None
    entidad_tipo: str | None
    entidad_id: uuid.UUID | None
    cantidad: float
    precio_unitario: float
    descuento_pct: float
    descuento_monto: float
    tasa_impuesto_pct: float
    observaciones: str | None
    subtotal: float
    impuesto_monto: float
    total: float
    fecha_creacion: datetime
    fecha_actualizacion: datetime | None

    model_config = {"from_attributes": True}


class EntregaResponse(BaseModel):
    """Respuesta de entrega (espejo del modelo + relaciones)."""

    id: uuid.UUID
    numero: str
    cliente_recibe_id: uuid.UUID
    cliente_recibe: ClienteEntrega | None = None
    propietario_id: uuid.UUID
    propietario: PropietarioEntrega | None = None
    fecha_hora: datetime
    usuario_responsable_id: uuid.UUID

    receptor_nombre: str
    receptor_rut: str | None
    receptor_relacion: str | None

    documento_id: uuid.UUID | None
    firma_confirmacion_url: str | None
    firma_tipo: str | None
    observaciones: str | None

    estado: str
    excepcion_documento: bool
    excepcion_usuario_id: uuid.UUID | None
    excepcion_fecha: datetime | None
    excepcion_motivo: str | None

    valorizacion_id: uuid.UUID | None
    detalles: list[DetalleEntregaResponse] = []
    fecha_creacion: datetime
    fecha_actualizacion: datetime | None

    model_config = {"from_attributes": True}
