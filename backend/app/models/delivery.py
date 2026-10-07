"""
Modelos de entrega, documentos comerciales, pagos, cambios de propietario.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import List

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel, SoftDeleteMixin, register_audit_trigger

# ============================================================
# ENTREGAS
# ============================================================


class Entrega(BaseModel, SoftDeleteMixin):
    """Entrega de cilindros a cliente/propietario/receptor."""

    __tablename__ = "entrega"

    numero: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    cliente_recibe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cliente.id"), nullable=False)
    propietario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("propietario.id"), nullable=False)
    fecha_hora: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    usuario_responsable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=False
    )

    receptor_nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    receptor_rut: Mapped[str | None] = mapped_column(String(12))
    receptor_relacion: Mapped[str | None] = mapped_column(String(100))  # PROPIETARIO, CHOFER, REPRESENTANTE, TERCERO

    documento_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("documento_comercial.id"))
    firma_confirmacion_url: Mapped[str | None] = mapped_column(String(500))
    firma_tipo: Mapped[str | None] = mapped_column(String(20))
    observaciones: Mapped[str | None] = mapped_column(Text)

    estado: Mapped[str] = mapped_column(
        String(20), default="BORRADOR", nullable=False
    )  # BORRADOR, PENDIENTE, CONFIRMADA, ENTREGADA, CANCELADA, EXCEPCION_DOC

    excepcion_documento: Mapped[bool] = mapped_column(Boolean, default=False)
    excepcion_usuario_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"))
    excepcion_fecha: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    excepcion_motivo: Mapped[str | None] = mapped_column(Text)

    valorizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("valorizacion.id"), unique=True
    )

    # Relaciones
    cliente_recibe: Mapped[Cliente] = relationship()
    propietario: Mapped[Propietario] = relationship()
    usuario_responsable: Mapped[Usuario] = relationship()
    documento: Mapped[DocumentoComercial | None] = relationship()
    excepcion_usuario: Mapped[Usuario | None] = relationship(foreign_keys=[excepcion_usuario_id])
    valorizacion: Mapped[Valorizacion | None] = relationship(back_populates="entrega")
    detalles: Mapped[List[DetalleEntrega]] = relationship(back_populates="entrega", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "estado IN ('BORRADOR','PENDIENTE','CONFIRMADA','ENTREGADA','CANCELADA','EXCEPCION_DOC')",
            name="ck_entrega_estado",
        ),
        CheckConstraint("firma_tipo IN ('DIGITAL','FOTO_MANUSCRITA','HUELLA','OTRO')", name="ck_entrega_firma_tipo"),
        Index("idx_entrega_fecha", "fecha_hora"),
        Index("idx_entrega_cliente", "cliente_recibe_id"),
        Index("idx_entrega_estado", "estado"),
    )


class DetalleEntrega(BaseModel):
    """Detalle de cilindros y líneas de valorización en una entrega."""

    __tablename__ = "detalle_entrega"

    entrega_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entrega.id", ondelete="CASCADE"), nullable=False
    )
    cilindro_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cilindro.id", ondelete="RESTRICT"), nullable=False
    )
    entidad_tipo: Mapped[str | None] = mapped_column(String(20))  # PRODUCTO, SERVICIO (para líneas valorización)
    entidad_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    cantidad: Mapped[float] = mapped_column(Numeric(10, 2), default=1)
    precio_unitario: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    descuento_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    descuento_monto: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    tasa_impuesto_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Campos calculados
    subtotal: Mapped[float] = mapped_column(Numeric(14, 2))
    impuesto_monto: Mapped[float] = mapped_column(Numeric(14, 2))
    total: Mapped[float] = mapped_column(Numeric(14, 2))

    # Relaciones
    entrega: Mapped[Entrega] = relationship(back_populates="detalles")
    cilindro: Mapped[Cilindro] = relationship(back_populates="entregas")

    __table_args__ = (
        UniqueConstraint("entrega_id", "cilindro_id", name="uk_detalle_entrega_cilindro"),
        CheckConstraint(
            "entidad_tipo IS NULL OR entidad_tipo IN ('PRODUCTO','SERVICIO')", name="ck_detalle_entrega_entidad_tipo"
        ),
    )


# ============================================================
# DOCUMENTOS COMERCIALES
# ============================================================


class DocumentoComercial(BaseModel, SoftDeleteMixin):
    """Documentos comerciales: boletas, facturas, vales, guías, vouchers."""

    __tablename__ = "documento_comercial"

    tipo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tipo_documento.id"), nullable=False)
    folio: Mapped[str] = mapped_column(String(50), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)

    rut_emisor: Mapped[str] = mapped_column(String(12), nullable=False)
    nombre_emisor: Mapped[str] = mapped_column(String(200), nullable=False)
    rut_receptor: Mapped[str] = mapped_column(String(12), nullable=False)
    nombre_receptor: Mapped[str] = mapped_column(String(200), nullable=False)

    neto: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    impuesto: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    total: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    moneda: Mapped[str] = mapped_column(String(3), default="CLP")

    forma_pago_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("forma_pago.id"), nullable=False)
    estado: Mapped[str] = mapped_column(
        String(20), default="EMITIDO", nullable=False
    )  # EMITIDO, ANULADO, PAGADO, PENDIENTE_PAGO, PARCIALMENTE_PAGADO
    adjunto_url: Mapped[str | None] = mapped_column(String(500))
    es_tributario: Mapped[bool] = mapped_column(Boolean, nullable=False)
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Excepción para cierre entrega sin documento
    excepcion_autorizada: Mapped[bool] = mapped_column(Boolean, default=False)
    excepcion_usuario_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"))
    excepcion_fecha: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    excepcion_motivo: Mapped[str | None] = mapped_column(Text)

    # Conciliación (campo calculado)
    saldo_pendiente: Mapped[float] = mapped_column(Numeric(14, 2))

    # Relaciones
    tipo_documento: Mapped[TipoDocumento] = relationship(back_populates="documentos")
    forma_pago: Mapped[FormaPago] = relationship(back_populates="documentos")
    excepcion_usuario: Mapped[Usuario | None] = relationship(foreign_keys=[excepcion_usuario_id])
    pagos: Mapped[List[Pago]] = relationship(back_populates="documento", cascade="all, delete-orphan")
    entregas: Mapped[List[Entrega]] = relationship(back_populates="documento")

    __table_args__ = (
        CheckConstraint(
            "estado IN ('EMITIDO','ANULADO','PAGADO','PENDIENTE_PAGO','PARCIALMENTE_PAGADO')",
            name="ck_documento_estado",
        ),
        UniqueConstraint("tipo_id", "folio", "rut_emisor", name="uk_documento_tipo_folio_emisor"),
        Index("idx_documento_receptor_fecha", "rut_receptor", "fecha"),
        Index("idx_documento_estado_saldo", "estado", "saldo_pendiente", postgresql_where=text("saldo_pendiente > 0")),
    )


# ============================================================
# PAGOS
# ============================================================


class Pago(BaseModel, SoftDeleteMixin):
    """Pagos registrados contra documentos comerciales."""

    __tablename__ = "pago"

    documento_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documento_comercial.id", ondelete="RESTRICT"), nullable=False
    )
    forma_pago_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("forma_pago.id"), nullable=False)
    monto: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    saldo_pendiente_anterior: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    numero_operacion: Mapped[str | None] = mapped_column(String(100))
    estado: Mapped[str] = mapped_column(String(20), default="REGISTRADO")  # REGISTRADO, CONFIRMADO, ANULADO, DEVUELTO
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    documento: Mapped[DocumentoComercial] = relationship(back_populates="pagos")
    forma_pago: Mapped[FormaPago] = relationship(back_populates="pagos")

    __table_args__ = (
        CheckConstraint("estado IN ('REGISTRADO','CONFIRMADO','ANULADO','DEVUELTO')", name="ck_pago_estado"),
        CheckConstraint("monto > 0", name="ck_pago_monto_positivo"),
        Index("idx_pago_documento", "documento_id"),
        Index("idx_pago_fecha", "fecha"),
    )


# ============================================================
# CAMBIO DE PROPIETARIO
# ============================================================


class CambioPropietario(BaseModel):
    """Historial de cambios de propietario de cilindros."""

    __tablename__ = "cambio_propietario"

    cilindro_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cilindro.id", ondelete="RESTRICT"), nullable=False
    )
    propietario_anterior_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("propietario.id"), nullable=False
    )
    propietario_nuevo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("propietario.id"), nullable=False
    )
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    usuario_autoriza_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=False)
    motivo: Mapped[str] = mapped_column(String(200), nullable=False)
    documento_respaldo_url: Mapped[str | None] = mapped_column(String(500))
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    cilindro: Mapped[Cilindro] = relationship(back_populates="cambios_propietario")
    propietario_anterior: Mapped[Propietario] = relationship(foreign_keys=[propietario_anterior_id])
    propietario_nuevo: Mapped[Propietario] = relationship(foreign_keys=[propietario_nuevo_id])
    usuario_autoriza: Mapped[Usuario] = relationship()

    __table_args__ = (Index("idx_cambio_prop_cilindro_fecha", "cilindro_id", "fecha"),)


# Registrar triggers de auditoría
for model in [Entrega, DetalleEntrega, DocumentoComercial, Pago, CambioPropietario]:
    register_audit_trigger(model)
