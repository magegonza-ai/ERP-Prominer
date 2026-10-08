"""
Modelos de órdenes de trabajo, tareas asignadas y operaciones de llenado/reparación.
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel, SoftDeleteMixin, register_audit_trigger

# ============================================================
# ÓRDENES DE TRABAJO (Unificadas: Llenado, Reparación, Inspección, Calidad, Entrega)
# ============================================================


class OrdenTrabajo(BaseModel, SoftDeleteMixin):
    """Órdenes de trabajo unificadas para todos los tipos de proceso."""

    __tablename__ = "orden_trabajo"

    tipo: Mapped[str] = mapped_column(String(30), nullable=False)  # LLENADO, REPARACION, INSPECCION, CALIDAD, ENTREGA
    numero: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    area_responsable_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("area.id"), nullable=False)
    usuario_creador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=False)
    usuario_asignado_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"))

    prioridad: Mapped[str] = mapped_column(String(20), default="NORMAL")
    estado: Mapped[str] = mapped_column(String(30), default="PENDIENTE", nullable=False)

    fecha_inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_estimada_termino: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_termino_real: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    resultado: Mapped[str | None] = mapped_column(Text)
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Campos específicos por tipo
    tipo_gas_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tipo_gas.id"))
    tipo_falla: Mapped[str | None] = mapped_column(String(50))
    diagnostico: Mapped[str | None] = mapped_column(Text)
    trabajo_solicitado: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    area_responsable: Mapped[Area] = relationship(back_populates="ordenes_trabajo")
    usuario_creador: Mapped[Usuario] = relationship(foreign_keys=[usuario_creador_id], back_populates="ordenes_creadas")
    usuario_asignado: Mapped[Usuario | None] = relationship(
        foreign_keys=[usuario_asignado_id], back_populates="ordenes_asignadas"
    )
    tipo_gas: Mapped[TipoGas | None] = relationship(back_populates="ordenes_llenado")
    detalles: Mapped[List[DetalleOrden]] = relationship(back_populates="orden", cascade="all, delete-orphan")
    tareas_asignadas: Mapped[List[TareaAsignada]] = relationship(back_populates="orden", cascade="all, delete-orphan")
    controles_calidad: Mapped[List[ControlCalidad]] = relationship(back_populates="orden_relacionada")
    valorizaciones: Mapped[List[Valorizacion]] = relationship(
        primaryjoin=(
            "and_(OrdenTrabajo.id==foreign(Valorizacion.operacion_id), "
            "Valorizacion.operacion_tipo.in_(['ORDEN_LLENADO','ORDEN_REPARACION','INSPECCION']))"
        ),
        viewonly=True,
    )

    __table_args__ = (
        CheckConstraint("tipo IN ('LLENADO','REPARACION','INSPECCION','CALIDAD','ENTREGA')", name="ck_orden_tipo"),
        CheckConstraint("prioridad IN ('NORMAL','URGENTE','EXPRESS')", name="ck_orden_prioridad"),
        CheckConstraint(
            "estado IN ('PENDIENTE','PREPARADA','EN_PROCESO','EN_PAUSA','FINALIZADA',"
            "'PENDIENTE_CALIDAD','APROBADA','RECHAZADA','REQUIERE_NUEVA_REPARACION','CANCELADA')",
            name="ck_orden_estado",
        ),
        Index("idx_orden_tipo_estado", "tipo", "estado"),
        Index("idx_orden_asignado_fecha", "usuario_asignado_id", "fecha_creacion"),
        Index(
            "idx_orden_fecha_estimada",
            "fecha_estimada_termino",
            postgresql_where=text("estado IN ('PENDIENTE','PREPARADA','EN_PROCESO','EN_PAUSA')"),
        ),
    )


class DetalleOrden(BaseModel):
    """Cilindros asociados a una orden de trabajo."""

    __tablename__ = "detalle_orden"

    orden_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orden_trabajo.id", ondelete="CASCADE"), nullable=False
    )
    cilindro_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cilindro.id", ondelete="RESTRICT"), nullable=False
    )
    tipo_gas_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tipo_gas.id"))
    cantidad: Mapped[float] = mapped_column(Numeric(10, 2), default=1)
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Resultados de ejecución (para llenado)
    peso_inicial_kg: Mapped[float | None] = mapped_column(Numeric(10, 2))
    peso_final_kg: Mapped[float | None] = mapped_column(Numeric(10, 2))
    presion_bar: Mapped[float | None] = mapped_column(Numeric(6, 2))
    lote_gas: Mapped[str | None] = mapped_column(String(50))

    # Relaciones
    orden: Mapped[OrdenTrabajo] = relationship(back_populates="detalles")
    cilindro: Mapped[Cilindro] = relationship(back_populates="ordenes_detalle")
    tipo_gas: Mapped[TipoGas | None] = relationship()

    __table_args__ = (UniqueConstraint("orden_id", "cilindro_id", name="uk_detalle_orden_cilindro"),)


# ============================================================
# TAREAS ASIGNADAS DENTRO DE ÓRDENES
# ============================================================


class TareaAsignada(BaseModel):
    """Tareas específicas asignadas dentro de una orden."""

    __tablename__ = "tarea_asignada"

    orden_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orden_trabajo.id", ondelete="CASCADE"), nullable=False
    )
    tarea_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tarea.id"), nullable=False)
    cilindro_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("cilindro.id"), nullable=True)

    responsable_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("empleado.id"), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), default="PENDIENTE", nullable=False)
    prioridad: Mapped[str] = mapped_column(String(20), default="NORMAL")

    fecha_asignacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    fecha_inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_termino: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_estimada_termino: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    resultado: Mapped[str | None] = mapped_column(Text)
    observaciones: Mapped[str | None] = mapped_column(Text)
    evidencias: Mapped[dict | None] = mapped_column(JSONB)

    # Trazabilidad de reasignación
    reasignada_desde_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tarea_asignada.id"), nullable=True
    )
    usuario_reasigno_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"))
    fecha_reasignacion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo_reasignacion: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    orden: Mapped[OrdenTrabajo] = relationship(back_populates="tareas_asignadas")
    tarea: Mapped[Tarea] = relationship(back_populates="tareas_asignadas")
    cilindro: Mapped[Cilindro | None] = relationship()
    responsable: Mapped[Empleado] = relationship(back_populates="tareas_responsable")
    reasignada_desde: Mapped[TareaAsignada | None] = relationship(
        remote_side="TareaAsignada.id", back_populates="reasignaciones"
    )
    reasignaciones: Mapped[List[TareaAsignada]] = relationship(back_populates="reasignada_desde")
    usuario_reasigno: Mapped[Usuario | None] = relationship(foreign_keys=[usuario_reasigno_id])

    __table_args__ = (
        CheckConstraint(
            "estado IN ('PENDIENTE','ASIGNADA','EN_PROCESO','EN_PAUSA','COMPLETADA',"
            "'RECHAZADA','CANCELADA','REASIGNADA')",
            name="ck_tarea_asig_estado",
        ),
        CheckConstraint("prioridad IN ('NORMAL','URGENTE','EXPRESS')", name="ck_tarea_asig_prioridad"),
        Index("idx_tarea_asig_responsable_estado", "responsable_id", "estado"),
        Index("idx_tarea_asig_orden", "orden_id"),
        Index(
            "idx_tarea_asig_fecha_estimada",
            "fecha_estimada_termino",
            postgresql_where=text("estado IN ('PENDIENTE','ASIGNADA','EN_PROCESO','EN_PAUSA')"),
        ),
    )


# Registrar triggers de auditoría
for model in [OrdenTrabajo, DetalleOrden, TareaAsignada]:
    register_audit_trigger(model)
