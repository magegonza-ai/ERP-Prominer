"""
Esquemas de clientes y receptores autorizados (ETAPA 4.1).

Cliente: `rut` único e inmutable y estados `ACTIVO/INACTIVO/BLOQUEADO`
(validados con `Literal`, `ck_cliente_estado`). El receptor autorizado es
un sub-recurso anidado del cliente con estados `VIGENTE/VENCIDO/REVOCADO`
(`ck_receptor_estado`), `fecha_autorizacion` inmutable y `autorizado_por`
que registra al usuario autenticado. En ambos, el `null` en la
actualización parcial significa "sin cambio" (contrato de la ETAPA 2.1).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# Valores permitidos por ck_cliente_estado.
EstadoCliente = Literal["ACTIVO", "INACTIVO", "BLOQUEADO"]

# Valores permitidos por ck_receptor_estado.
EstadoReceptor = Literal["VIGENTE", "VENCIDO", "REVOCADO"]


# ============================================================
# CLIENTES
# ============================================================


class ClienteCreate(BaseModel):
    rut: str = Field(min_length=1, max_length=12)
    razon_social: str = Field(min_length=1, max_length=200)
    direccion: str | None = Field(default=None, max_length=300)
    comuna: str | None = Field(default=None, max_length=100)
    ciudad: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    telefono: str | None = Field(default=None, max_length=20)
    correo: str | None = Field(default=None, max_length=150)
    persona_contacto: str | None = Field(default=None, max_length=150)
    observaciones: str | None = None
    estado: EstadoCliente = "ACTIVO"


class ClienteUpdate(BaseModel):
    """Actualización parcial (`rut` inmutable; estado vía PATCH /clientes/{id}/estado)."""

    razon_social: str | None = Field(default=None, min_length=1, max_length=200)
    direccion: str | None = Field(default=None, max_length=300)
    comuna: str | None = Field(default=None, max_length=100)
    ciudad: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    telefono: str | None = Field(default=None, max_length=20)
    correo: str | None = Field(default=None, max_length=150)
    persona_contacto: str | None = Field(default=None, max_length=150)
    observaciones: str | None = None


class ClienteEstadoUpdate(BaseModel):
    estado: EstadoCliente


class ClienteResponse(BaseModel):
    id: uuid.UUID
    rut: str
    razon_social: str
    direccion: str | None = None
    comuna: str | None = None
    ciudad: str | None = None
    region: str | None = None
    telefono: str | None = None
    correo: str | None = None
    persona_contacto: str | None = None
    observaciones: str | None = None
    estado: str
    fecha_creacion: datetime
    fecha_actualizacion: datetime


# ============================================================
# RECEPTORES AUTORIZADOS (sub-recurso de /clientes/{id})
# ============================================================


class ReceptorAutorizadoCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    rut: str | None = Field(default=None, max_length=12)
    relacion: str | None = Field(default=None, max_length=100)
    telefono: str | None = Field(default=None, max_length=20)
    correo: str | None = Field(default=None, max_length=150)
    vigente_hasta: date | None = None
    estado: EstadoReceptor = "VIGENTE"
    observaciones: str | None = None


class ReceptorAutorizadoUpdate(BaseModel):
    """Actualización parcial (`fecha_autorizacion`/`autorizado_por`/estado inmutables)."""

    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    rut: str | None = Field(default=None, max_length=12)
    relacion: str | None = Field(default=None, max_length=100)
    telefono: str | None = Field(default=None, max_length=20)
    correo: str | None = Field(default=None, max_length=150)
    vigente_hasta: date | None = None
    observaciones: str | None = None


class ReceptorAutorizadoEstadoUpdate(BaseModel):
    estado: EstadoReceptor


class ReceptorAutorizadoResponse(BaseModel):
    id: uuid.UUID
    cliente_id: uuid.UUID
    nombre: str
    rut: str | None = None
    relacion: str | None = None
    telefono: str | None = None
    correo: str | None = None
    autorizado_por: uuid.UUID | None = None
    fecha_autorizacion: date
    vigente_hasta: date | None = None
    estado: str
    observaciones: str | None = None
    fecha_creacion: datetime
    fecha_actualizacion: datetime
