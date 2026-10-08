"""
Esquemas de los catálogos simples (ETAPA 3.1).

Área, categoría (jerárquica), tipo de gas, forma de pago y tipo de
documento. Estados validados con `Literal` (solo `ck_categoria_tipo`
existe en BD); `codigo` es único e inmutable en PATCH y el `null` en la
actualización parcial significa "sin cambio" (el endpoint filtra antes de
aplicar, igual que en la ETAPA 2.1).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Valores permitidos por ck_categoria_tipo.
TipoCategoria = Literal["PRODUCTO", "SERVICIO", "AMBOS"]

# Estados por módulo, con el género de su default en el modelo (ETAPA 1).
EstadoArea = Literal["ACTIVA", "INACTIVA"]
EstadoCategoria = Literal["ACTIVA", "INACTIVA"]
EstadoFormaPago = Literal["ACTIVA", "INACTIVA"]
EstadoTipoGas = Literal["ACTIVO", "INACTIVO"]
EstadoTipoDocumento = Literal["ACTIVO", "INACTIVO"]

_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"


# ============================================================
# ÁREAS
# ============================================================


class AreaCreate(BaseModel):
    codigo: str = Field(min_length=2, max_length=20)
    nombre: str = Field(min_length=1, max_length=100)
    descripcion: str | None = None
    estado: EstadoArea = "ACTIVA"
    orden_visual: int = Field(default=0, ge=0)


class AreaUpdate(BaseModel):
    """Actualización parcial (estado vía PATCH /areas/{id}/estado)."""

    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    descripcion: str | None = None
    orden_visual: int | None = Field(default=None, ge=0)


class AreaEstadoUpdate(BaseModel):
    estado: EstadoArea


class AreaResponse(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str
    descripcion: str | None = None
    estado: str
    orden_visual: int
    fecha_creacion: datetime
    fecha_actualizacion: datetime


# ============================================================
# CATEGORÍAS (jerárquicas)
# ============================================================


class CategoriaCreate(BaseModel):
    tipo: TipoCategoria
    codigo: str = Field(min_length=2, max_length=20)
    nombre: str = Field(min_length=1, max_length=100)
    descripcion: str | None = None
    padre_id: uuid.UUID | None = Field(default=None, description="Categoría madre (opcional).")
    estado: EstadoCategoria = "ACTIVA"


class CategoriaUpdate(BaseModel):
    """Actualización parcial (estado vía PATCH /categorias/{id}/estado)."""

    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    descripcion: str | None = None
    padre_id: uuid.UUID | None = None


class CategoriaEstadoUpdate(BaseModel):
    estado: EstadoCategoria


class CategoriaResponse(BaseModel):
    id: uuid.UUID
    tipo: str
    codigo: str
    nombre: str
    descripcion: str | None = None
    padre_id: uuid.UUID | None = None
    estado: str
    fecha_creacion: datetime
    fecha_actualizacion: datetime


# ============================================================
# TIPOS DE GAS
# ============================================================


class TipoGasCreate(BaseModel):
    codigo: str = Field(min_length=2, max_length=20)
    nombre: str = Field(min_length=1, max_length=50)
    requiere_prueba_hidraulica: bool = True
    color_etiqueta: str | None = Field(default=None, pattern=_COLOR_PATTERN)
    estado: EstadoTipoGas = "ACTIVO"


class TipoGasUpdate(BaseModel):
    """Actualización parcial (estado vía PATCH /tipos-gas/{id}/estado)."""

    nombre: str | None = Field(default=None, min_length=1, max_length=50)
    requiere_prueba_hidraulica: bool | None = None
    color_etiqueta: str | None = Field(default=None, pattern=_COLOR_PATTERN)


class TipoGasEstadoUpdate(BaseModel):
    estado: EstadoTipoGas


class TipoGasResponse(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str
    requiere_prueba_hidraulica: bool
    color_etiqueta: str | None = None
    estado: str
    fecha_creacion: datetime
    fecha_actualizacion: datetime


# ============================================================
# FORMAS DE PAGO
# ============================================================


class FormaPagoCreate(BaseModel):
    codigo: str = Field(min_length=2, max_length=20)
    nombre: str = Field(min_length=1, max_length=50)
    es_tributario: bool = False
    requiere_nro_operacion: bool = True
    estado: EstadoFormaPago = "ACTIVA"


class FormaPagoUpdate(BaseModel):
    """Actualización parcial (estado vía PATCH /formas-pago/{id}/estado)."""

    nombre: str | None = Field(default=None, min_length=1, max_length=50)
    es_tributario: bool | None = None
    requiere_nro_operacion: bool | None = None


class FormaPagoEstadoUpdate(BaseModel):
    estado: EstadoFormaPago


class FormaPagoResponse(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str
    es_tributario: bool
    requiere_nro_operacion: bool
    estado: str
    fecha_creacion: datetime
    fecha_actualizacion: datetime


# ============================================================
# TIPOS DE DOCUMENTO
# ============================================================


class TipoDocumentoCreate(BaseModel):
    codigo: str = Field(min_length=2, max_length=20)
    nombre: str = Field(min_length=1, max_length=50)
    es_tributario: bool = False
    requiere_folio_unico: bool = True
    requiere_receptor: bool = True
    plantilla_pdf: str | None = Field(default=None, max_length=100)
    estado: EstadoTipoDocumento = "ACTIVO"


class TipoDocumentoUpdate(BaseModel):
    """Actualización parcial (estado vía PATCH /tipos-documento/{id}/estado)."""

    nombre: str | None = Field(default=None, min_length=1, max_length=50)
    es_tributario: bool | None = None
    requiere_folio_unico: bool | None = None
    requiere_receptor: bool | None = None
    plantilla_pdf: str | None = Field(default=None, max_length=100)


class TipoDocumentoEstadoUpdate(BaseModel):
    estado: EstadoTipoDocumento


class TipoDocumentoResponse(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str
    es_tributario: bool
    requiere_folio_unico: bool
    requiere_receptor: bool
    plantilla_pdf: str | None = None
    estado: str
    fecha_creacion: datetime
    fecha_actualizacion: datetime
