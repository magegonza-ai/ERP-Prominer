"""
Esquemas de los catálogos de la ETAPA 3 (subetapas 3.1 y 3.2).

Área, categoría (jerárquica), tipo de gas, forma de pago y tipo de
documento (3.1); parámetros del sistema y tasas de impuesto (3.2).
Estados validados con `Literal` (solo `ck_categoria_tipo` existe en BD);
`codigo`/`clave` son únicos e inmutables en PATCH y el `null` en la
actualización parcial significa "sin cambio" (el endpoint filtra antes de
aplicar, igual que en la ETAPA 2.1).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

# Valores permitidos por ck_categoria_tipo.
TipoCategoria = Literal["PRODUCTO", "SERVICIO", "AMBOS"]

# Valores permitidos por ck_parametro_tipo.
TipoParametro = Literal["STRING", "INTEGER", "DECIMAL", "BOOLEAN", "JSON", "DATE"]

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


# ============================================================
# PARÁMETROS DEL SISTEMA (PK natural: clave)
# ============================================================


class ParametroCreate(BaseModel):
    clave: str = Field(min_length=1, max_length=100)
    valor: str
    tipo: TipoParametro
    descripcion: str | None = None
    editable: bool = True


class ParametroUpdate(BaseModel):
    """Actualización parcial (clave y tipo inmutables)."""

    valor: str | None = None
    descripcion: str | None = None


class ParametroResponse(BaseModel):
    clave: str
    valor: str
    tipo: str
    descripcion: str | None = None
    editable: bool
    actualizada_por: uuid.UUID | None = None
    fecha_actualizacion: datetime


# ============================================================
# TASAS DE IMPUESTO
# ============================================================

EstadoTasaImpuesto = Literal["ACTIVA", "INACTIVA"]


class TasaImpuestoCreate(BaseModel):
    codigo: str = Field(min_length=2, max_length=20)
    nombre: str = Field(min_length=1, max_length=50)
    valor: Decimal = Field(ge=0, le=100, description="Porcentaje (0–100), p. ej. 19.00.")
    es_default: bool = False
    vigencia_desde: date = Field(default_factory=date.today)
    vigencia_hasta: date | None = None
    estado: EstadoTasaImpuesto = "ACTIVA"


class TasaImpuestoUpdate(BaseModel):
    """Actualización parcial (estado vía PATCH /tasas-impuesto/{id}/estado).

    `vigencia_hasta` con `null` = sin cambio; para quitar el cierre use
    `cerrar_vigencia=false` y para cerrar hoy use `cerrar_vigencia=true`
    (no se pueden combinar con `vigencia_hasta` explícito).
    """

    nombre: str | None = Field(default=None, min_length=1, max_length=50)
    valor: Decimal | None = Field(default=None, ge=0, le=100)
    es_default: bool | None = None
    vigencia_desde: date | None = None
    vigencia_hasta: date | None = None
    cerrar_vigencia: bool | None = None


class TasaImpuestoEstadoUpdate(BaseModel):
    estado: EstadoTasaImpuesto


class TasaImpuestoResponse(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str
    valor: Decimal
    es_default: bool
    vigencia_desde: date
    vigencia_hasta: date | None = None
    estado: str
    fecha_creacion: datetime
    fecha_actualizacion: datetime
