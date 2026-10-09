"""
Esquemas de cambios de propietario de cilindros (ETAPA 5.7).

`CambioPropietario` es el historial **append-only** de traspasos de propiedad de
cilindros (dominio RBAC TAREA_20 «Autorizar cambio de propietario», matriz
sembrada ``[0,3,4]`` = PERM_01 leer / PERM_04 aprobar / PERM_05 rechazar). La
tabla existe desde la ETAPA 1 (sin migración) y **no tiene columna `estado`**:
por eso la única vía de crear un registro es autorizándolo — `POST` = crear +
autorizar en un único paso atómico con PERM_04.

`propietario_anterior_id`, `fecha` y `usuario_autoriza_id` los deriva el
servidor; el cuerpo solo aporta `cilindro_id`, `propietario_nuevo_id`, `motivo`
(obligatorio), `documento_respaldo_url` y `observaciones`. En la misma
transacción el cilindro pasa a `propietario_nuevo_id`. No hay edición ni
anulación (PATCH/DELETE → 405) y PERM_05 (rechazar) queda sembrado sin
endpoint: no crear el registro es la negativa.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CambioPropietarioCreate(BaseModel):
    """Nuevo traspaso de propiedad: nace autorizado (valida 404s y no-op)."""

    cilindro_id: uuid.UUID
    propietario_nuevo_id: uuid.UUID
    motivo: str = Field(..., min_length=1, max_length=200)
    documento_respaldo_url: str | None = Field(default=None, max_length=500)
    observaciones: str | None = None


# ============================================================
# RESPUESTAS
# ============================================================


class TipoGasCambio(BaseModel):
    """Resumen del tipo de gas del cilindro traspasado."""

    id: uuid.UUID
    codigo: str
    nombre: str


class CilindroCambioPropietario(BaseModel):
    """Resumen del cilindro traspasado (con su `propietario_id` ya actualizado)."""

    id: uuid.UUID
    codigo_interno: str
    numero_serie: str
    estado_operativo: str
    propietario_id: uuid.UUID
    tipo_gas: TipoGasCambio | None = None


class PropietarioCambio(BaseModel):
    """Resumen del propietario (anterior o nuevo) del traspaso."""

    id: uuid.UUID
    tipo: str
    rut: str
    razon_social: str
    estado: str


class UsuarioAutorizaCambio(BaseModel):
    """Resumen del usuario que autoriza el traspaso."""

    id: uuid.UUID
    username: str
    email: str


class CambioPropietarioResponse(BaseModel):
    """Respuesta de cambio de propietario (espejo del modelo + relaciones)."""

    id: uuid.UUID
    cilindro_id: uuid.UUID
    cilindro: CilindroCambioPropietario | None = None
    propietario_anterior_id: uuid.UUID
    propietario_anterior: PropietarioCambio | None = None
    propietario_nuevo_id: uuid.UUID
    propietario_nuevo: PropietarioCambio | None = None
    fecha: datetime
    usuario_autoriza_id: uuid.UUID
    usuario_autoriza: UsuarioAutorizaCambio | None = None
    motivo: str
    documento_respaldo_url: str | None
    observaciones: str | None
    fecha_creacion: datetime
    fecha_actualizacion: datetime | None

    model_config = {"from_attributes": True}
