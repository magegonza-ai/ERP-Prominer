"""
Modelos de devoluciones de cilindros (ETAPA 5.6).

Flujo inverso de la entrega: cilindros `ENTREGADO` que el cliente devuelve a
AGAS. Cada devolución registra la cabecera y sus cilindros anidados
(`DevolucionDetalle`); al crearse, se emite un `Movimiento` por cilindro en la
misma transacción (D31) que lo deja en `RECIBIDO`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import List

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel, SoftDeleteMixin, register_audit_trigger


class Devolucion(BaseModel, SoftDeleteMixin):
    """Devolución de cilindros entregados (retorno a AGAS)."""

    __tablename__ = "devolucion"

    numero: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    cliente_devuelve_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cliente.id"), nullable=False
    )
    entrega_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entrega.id"), nullable=True
    )
    fecha_hora: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    usuario_responsable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=False
    )
    # DEVOLUCION_CLIENTE, DANO_EN_TRANSITO, ERROR_ENTREGA, GARANTIA, OTRO
    motivo: Mapped[str] = mapped_column(String(30), nullable=False)
    documento_referencia: Mapped[str | None] = mapped_column(String(100))
    observaciones: Mapped[str | None] = mapped_column(Text)
    # Bodega/P.C. al que ingresa el cilindro (opcional: omitido = sin cambio
    # de ubicación, como en las recepciones).
    ubicacion_destino_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ubicacion.id"), nullable=True
    )
    estado: Mapped[str] = mapped_column(
        String(20), default="REGISTRADA", nullable=False
    )  # REGISTRADA, ANULADA

    # Relaciones
    cliente_devuelve: Mapped[Cliente] = relationship(foreign_keys=[cliente_devuelve_id])
    entrega: Mapped[Entrega | None] = relationship()
    usuario_responsable: Mapped[Usuario] = relationship()
    ubicacion_destino: Mapped[Ubicacion | None] = relationship()
    detalles: Mapped[List[DevolucionDetalle]] = relationship(
        back_populates="devolucion", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "motivo IN ('DEVOLUCION_CLIENTE','DANO_EN_TRANSITO','ERROR_ENTREGA','GARANTIA','OTRO')",
            name="ck_devolucion_motivo",
        ),
        CheckConstraint("estado IN ('REGISTRADA','ANULADA')", name="ck_devolucion_estado"),
        Index("idx_devolucion_fecha", "fecha_hora"),
        Index("idx_devolucion_cliente", "cliente_devuelve_id"),
        Index("idx_devolucion_estado", "estado"),
    )


class DevolucionDetalle(BaseModel):
    """Detalle de cilindros devueltos."""

    __tablename__ = "detalle_devolucion"

    devolucion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devolucion.id", ondelete="CASCADE"), nullable=False
    )
    cilindro_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cilindro.id", ondelete="RESTRICT"), nullable=False
    )
    estado_fisico: Mapped[str] = mapped_column(String(20), nullable=False)  # BUENO, REGULAR, MALO, CRITICO
    accesorios: Mapped[dict | None] = mapped_column(JSONB)
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    devolucion: Mapped[Devolucion] = relationship(back_populates="detalles")
    cilindro: Mapped[Cilindro] = relationship(back_populates="devoluciones")

    __table_args__ = (
        CheckConstraint(
            "estado_fisico IN ('BUENO','REGULAR','MALO','CRITICO')",
            name="ck_detalle_devolucion_estado",
        ),
        UniqueConstraint("devolucion_id", "cilindro_id", name="uk_detalle_devolucion_cilindro"),
    )


# Registrar triggers de auditoría
for model in [Devolucion, DevolucionDetalle]:
    register_audit_trigger(model)
