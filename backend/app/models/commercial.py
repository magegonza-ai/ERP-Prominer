"""
Modelos comerciales: productos, servicios, listas de precios, presupuestos, valorización.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import List

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel, SoftDeleteMixin, register_audit_trigger

# ============================================================
# PRODUCTOS Y SERVICIOS
# ============================================================


class Producto(BaseModel, SoftDeleteMixin):
    """Catálogo de productos valorizables."""

    __tablename__ = "producto"

    codigo: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text)
    categoria_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("categoria.id"), nullable=False)
    unidad_medida: Mapped[str] = mapped_column(String(20), nullable=False)  # UN, KG, LT, MT, GLB
    precio_neto_base: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    tasa_impuesto_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tasa_impuesto.id"))
    estado: Mapped[str] = mapped_column(String(20), default="ACTIVO")
    vigencia_desde: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    vigencia_hasta: Mapped[date | None] = mapped_column(Date)
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    categoria: Mapped[Categoria] = relationship(back_populates="productos")
    tasa_impuesto: Mapped[TasaImpuesto | None] = relationship(back_populates="productos")
    detalles_lista_precios: Mapped[List[DetalleListaPrecios]] = relationship(back_populates="producto")
    detalles_presupuesto: Mapped[List[DetallePresupuesto]] = relationship(
        primaryjoin="and_(Producto.id==DetallePresupuesto.entidad_id, DetallePresupuesto.entidad_tipo=='PRODUCTO')",
        viewonly=True,
    )
    detalles_valorizacion: Mapped[List[DetalleValorizacion]] = relationship(
        primaryjoin="and_(Producto.id==DetalleValorizacion.entidad_id, DetalleValorizacion.entidad_tipo=='PRODUCTO')",
        viewonly=True,
    )
    detalles_entrega: Mapped[List[DetalleEntrega]] = relationship(
        primaryjoin="and_(Producto.id==DetalleEntrega.entidad_id, DetalleEntrega.entidad_tipo=='PRODUCTO')",
        viewonly=True,
    )

    __table_args__ = (CheckConstraint("estado IN ('ACTIVO','INACTIVO','DESCONTINUADO')", name="ck_producto_estado"),)


class Servicio(BaseModel, SoftDeleteMixin):
    """Catálogo de servicios valorizables."""

    __tablename__ = "servicio"

    codigo: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text)
    categoria_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("categoria.id"), nullable=False)
    unidad_cobro: Mapped[str] = mapped_column(String(20), nullable=False)  # CILINDRO, KG, HORA, VIAJE, DIA, LOTE
    precio_neto_base: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    tasa_impuesto_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tasa_impuesto.id"))
    estado: Mapped[str] = mapped_column(String(20), default="ACTIVO")
    vigencia_desde: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    vigencia_hasta: Mapped[date | None] = mapped_column(Date)
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    categoria: Mapped[Categoria] = relationship(back_populates="servicios")
    tasa_impuesto: Mapped[TasaImpuesto | None] = relationship(back_populates="servicios")
    detalles_lista_precios: Mapped[List[DetalleListaPrecios]] = relationship(back_populates="servicio")
    detalles_presupuesto: Mapped[List[DetallePresupuesto]] = relationship(
        primaryjoin="and_(Servicio.id==DetallePresupuesto.entidad_id, DetallePresupuesto.entidad_tipo=='SERVICIO')",
        viewonly=True,
    )
    detalles_valorizacion: Mapped[List[DetalleValorizacion]] = relationship(
        primaryjoin="and_(Servicio.id==DetalleValorizacion.entidad_id, DetalleValorizacion.entidad_tipo=='SERVICIO')",
        viewonly=True,
    )
    detalles_entrega: Mapped[List[DetalleEntrega]] = relationship(
        primaryjoin="and_(Servicio.id==DetalleEntrega.entidad_id, DetalleEntrega.entidad_tipo=='SERVICIO')",
        viewonly=True,
    )

    __table_args__ = (CheckConstraint("estado IN ('ACTIVO','INACTIVO','DESCONTINUADO')", name="ck_servicio_estado"),)


# ============================================================
# LISTAS DE PRECIOS Y TARIFAS
# ============================================================


class ListaPrecios(BaseModel):
    """Listas de precios con vigencias y versiones."""

    __tablename__ = "lista_precios"

    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text)
    vigencia_desde: Mapped[date] = mapped_column(Date, nullable=False)
    vigencia_hasta: Mapped[date | None] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(20), default="BORRADOR")  # BORRADOR, VIGENTE, OBSOLETA, ANULADA
    version: Mapped[int] = mapped_column(Integer, default=1)

    # Relaciones
    detalles: Mapped[List[DetalleListaPrecios]] = relationship(
        back_populates="lista_precios", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("estado IN ('BORRADOR','VIGENTE','OBSOLETA','ANULADA')", name="ck_lista_precios_estado"),
        Index("idx_lista_precios_vigencia", "vigencia_desde", "vigencia_hasta"),
    )


class DetalleListaPrecios(BaseModel):
    """Detalle de precios por producto/servicio con criterios de diferenciación."""

    __tablename__ = "detalle_lista_precios"

    lista_precios_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lista_precios.id", ondelete="CASCADE"), nullable=False
    )
    entidad_tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # PRODUCTO, SERVICIO
    entidad_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    criterios: Mapped[dict] = mapped_column(JSONB, default={}, nullable=False)  # Criterios de diferenciación
    precio_neto: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    tasa_impuesto_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tasa_impuesto.id"))
    vigencia_desde: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    vigencia_hasta: Mapped[date | None] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(20), default="ACTIVO")

    # Relaciones
    lista_precios: Mapped[ListaPrecios] = relationship(back_populates="detalles")
    tasa_impuesto: Mapped[TasaImpuesto | None] = relationship()

    __table_args__ = (
        CheckConstraint("entidad_tipo IN ('PRODUCTO','SERVICIO')", name="ck_dlp_entidad_tipo"),
        CheckConstraint("estado IN ('ACTIVO','INACTIVO')", name="ck_dlp_estado"),
        Index(
            "idx_dlp_lista_vigente",
            "lista_precios_id",
            "vigencia_desde",
            "vigencia_hasta",
            postgresql_where=text("estado='ACTIVO'"),
        ),
        Index("idx_dlp_entidad", "entidad_tipo", "entidad_id"),
    )


# ============================================================
# PRESUPUESTOS
# ============================================================


class Presupuesto(BaseModel, SoftDeleteMixin):
    """Presupuestos con ciclo de aprobación y versionado."""

    __tablename__ = "presupuesto"

    numero: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    cliente_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cliente.id"), nullable=False)
    propietario_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("propietario.id"))
    fecha: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    fecha_vencimiento: Mapped[date] = mapped_column(Date, nullable=False)
    usuario_creador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=False)
    usuario_aprobador_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"))
    estado: Mapped[str] = mapped_column(
        String(20), default="BORRADOR", nullable=False
    )  # BORRADOR, PENDIENTE_APROBACION, APROBADO, RECHAZADO, ANULADO, CONVERTIDO
    neto: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    descuento_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    impuesto_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    observaciones: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    presupuesto_original_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("presupuesto.id"))

    # Relaciones
    cliente: Mapped[Cliente] = relationship()
    propietario: Mapped[Propietario | None] = relationship()
    usuario_creador: Mapped[Usuario] = relationship(foreign_keys=[usuario_creador_id])
    usuario_aprobador: Mapped[Usuario | None] = relationship(foreign_keys=[usuario_aprobador_id])
    detalles: Mapped[List[DetallePresupuesto]] = relationship(
        back_populates="presupuesto", cascade="all, delete-orphan"
    )
    valorizaciones: Mapped[List[Valorizacion]] = relationship(
        primaryjoin="and_(Presupuesto.id==Valorizacion.operacion_id, Valorizacion.operacion_tipo=='PRESUPUESTO')",
        viewonly=True,
    )
    presupuesto_original: Mapped[Presupuesto | None] = relationship(
        remote_side="Presupuesto.id", back_populates="versiones"
    )
    versiones: Mapped[List[Presupuesto]] = relationship(back_populates="presupuesto_original")

    __table_args__ = (
        CheckConstraint(
            "estado IN ('BORRADOR','PENDIENTE_APROBACION','APROBADO','RECHAZADO','ANULADO','CONVERTIDO')",
            name="ck_presupuesto_estado",
        ),
        Index("idx_presupuesto_cliente_estado", "cliente_id", "estado"),
        Index(
            "idx_presupuesto_fecha_venc",
            "fecha_vencimiento",
            postgresql_where=text("estado IN ('BORRADOR','PENDIENTE_APROBACION','APROBADO')"),
        ),
    )


class DetallePresupuesto(BaseModel):
    """Detalle de líneas de presupuesto (productos/servicios con precios históricos)."""

    __tablename__ = "detalle_presupuesto"

    presupuesto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("presupuesto.id", ondelete="CASCADE"), nullable=False
    )
    entidad_tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # PRODUCTO, SERVICIO
    entidad_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(300), nullable=False)
    cantidad: Mapped[float] = mapped_column(Numeric(10, 2), default=1, nullable=False)
    unidad: Mapped[str] = mapped_column(String(20), nullable=False)
    precio_unitario: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)  # Precio histórico
    descuento_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    descuento_monto: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    tasa_impuesto_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    orden_linea: Mapped[int] = mapped_column(Integer, default=0)
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Campos calculados (generated columns)
    subtotal: Mapped[float] = mapped_column(Numeric(14, 2))
    impuesto_monto: Mapped[float] = mapped_column(Numeric(14, 2))
    total: Mapped[float] = mapped_column(Numeric(14, 2))

    # Relaciones
    presupuesto: Mapped[Presupuesto] = relationship(back_populates="detalles")

    __table_args__ = (
        CheckConstraint("entidad_tipo IN ('PRODUCTO','SERVICIO')", name="ck_det_presupuesto_entidad_tipo"),
    )


# ============================================================
# VALORIZACIÓN
# ============================================================


class Valorizacion(BaseModel, SoftDeleteMixin):
    """Valorización de operaciones (recepciones, órdenes, entregas, presupuestos)."""

    __tablename__ = "valorizacion"

    operacion_tipo: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # RECEPCION, ORDEN_LLENADO, ORDEN_REPARACION, INSPECCION, ENTREGA, PRESUPUESTO
    operacion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    neto: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    descuento_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    impuesto_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    estado: Mapped[str] = mapped_column(String(20), default="BORRADOR")  # BORRADOR, CALCULADA, VALIDADA, ANULADA
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    detalles: Mapped[List[DetalleValorizacion]] = relationship(
        back_populates="valorizacion", cascade="all, delete-orphan"
    )
    entrega: Mapped[Entrega | None] = relationship(back_populates="valorizacion", uselist=False)

    __table_args__ = (
        CheckConstraint(
            "operacion_tipo IN ('RECEPCION','ORDEN_LLENADO','ORDEN_REPARACION','INSPECCION','ENTREGA','PRESUPUESTO')",
            name="ck_valorizacion_operacion_tipo",
        ),
        CheckConstraint("estado IN ('BORRADOR','CALCULADA','VALIDADA','ANULADA')", name="ck_valorizacion_estado"),
        Index("idx_valorizacion_operacion", "operacion_tipo", "operacion_id"),
        # Unicidad por operación excluyendo anuladas (índice único parcial)
        Index(
            "uk_valorizacion_operacion",
            "operacion_tipo",
            "operacion_id",
            unique=True,
            postgresql_where=text("estado <> 'ANULADA'"),
        ),
    )


class DetalleValorizacion(BaseModel):
    """Detalle de valorización con precios históricos inmutables."""

    __tablename__ = "detalle_valorizacion"

    valorizacion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("valorizacion.id", ondelete="CASCADE"), nullable=False
    )
    entidad_tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # PRODUCTO, SERVICIO
    entidad_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(300), nullable=False)
    cantidad: Mapped[float] = mapped_column(Numeric(10, 2), default=1, nullable=False)
    unidad: Mapped[str] = mapped_column(String(20), nullable=False)
    precio_unitario_hist: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)  # PRECIO HISTÓRICO INMUTABLE
    descuento_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    descuento_monto: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    tasa_impuesto_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    orden_linea: Mapped[int] = mapped_column(Integer, default=0)
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Campos calculados (generated columns)
    subtotal: Mapped[float] = mapped_column(Numeric(14, 2))
    impuesto_monto: Mapped[float] = mapped_column(Numeric(14, 2))
    total: Mapped[float] = mapped_column(Numeric(14, 2))

    # Relaciones
    valorizacion: Mapped[Valorizacion] = relationship(back_populates="detalles")

    __table_args__ = (
        CheckConstraint("entidad_tipo IN ('PRODUCTO','SERVICIO')", name="ck_det_valorizacion_entidad_tipo"),
    )


# Registrar triggers de auditoría
for model in [
    Producto,
    Servicio,
    ListaPrecios,
    DetalleListaPrecios,
    Presupuesto,
    DetallePresupuesto,
    Valorizacion,
    DetalleValorizacion,
]:
    register_audit_trigger(model)
