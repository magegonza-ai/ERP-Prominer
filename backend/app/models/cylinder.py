"""
Modelos de cilindros, ubicaciones, recepciones, inspecciones, movimientos y trazabilidad.
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
    Integer,
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
# UBICACIONES Y MOVIMIENTOS
# ============================================================


class Ubicacion(BaseModel):
    """Catálogo de ubicaciones físicas/lógicas."""

    __tablename__ = "ubicacion"

    codigo: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)  # INTERNA, CLIENTE, EXTERNA, FUERA
    permite_entrada: Mapped[bool] = mapped_column(Boolean, default=True)
    permite_salida: Mapped[bool] = mapped_column(Boolean, default=True)
    orden_visual: Mapped[int] = mapped_column(Integer, default=0)
    estado: Mapped[str] = mapped_column(String(20), default="ACTIVA")

    # Relaciones
    cilindros_actuales: Mapped[List[Cilindro]] = relationship(back_populates="ubicacion_actual")
    movimientos_origen: Mapped[List[Movimiento]] = relationship(
        back_populates="ubicacion_origen", foreign_keys="Movimiento.ubicacion_origen_id"
    )
    movimientos_destino: Mapped[List[Movimiento]] = relationship(
        back_populates="ubicacion_destino", foreign_keys="Movimiento.ubicacion_destino_id"
    )

    __table_args__ = (CheckConstraint("tipo IN ('INTERNA','CLIENTE','EXTERNA','FUERA')", name="ck_ubicacion_tipo"),)


class Cilindro(BaseModel, SoftDeleteMixin):
    """Entidad central: cilindro de gas con trazabilidad completa."""

    __tablename__ = "cilindro"

    codigo_interno: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    numero_serie: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    codigo_qr: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    codigo_barras: Mapped[str | None] = mapped_column(String(100), unique=True)

    propietario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("propietario.id"), nullable=False)
    tipo_gas_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tipo_gas.id"), nullable=False)
    capacidad_kg: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)

    marca: Mapped[str | None] = mapped_column(String(100))
    fabricante: Mapped[str | None] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(30))
    fecha_fabricacion: Mapped[date | None] = mapped_column(Date)
    fecha_ultima_prueba_hidraulica: Mapped[date | None] = mapped_column(Date)
    fecha_vencimiento_prueba: Mapped[date | None] = mapped_column(Date)

    estado_operativo: Mapped[str] = mapped_column(String(30), default="REGISTRADO", nullable=False)
    ubicacion_actual_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ubicacion.id"), nullable=False
    )
    fotografia_url: Mapped[str | None] = mapped_column(String(500))
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    propietario: Mapped[Propietario] = relationship(back_populates="cilindros")
    tipo_gas: Mapped[TipoGas] = relationship(back_populates="cilindros")
    ubicacion_actual: Mapped[Ubicacion] = relationship(back_populates="cilindros_actuales")
    recepciones: Mapped[List[DetalleRecepcion]] = relationship(back_populates="cilindro")
    inspecciones: Mapped[List[Inspeccion]] = relationship(back_populates="cilindro")
    ordenes_detalle: Mapped[List[DetalleOrden]] = relationship(back_populates="cilindro")
    controles_calidad: Mapped[List[ControlCalidad]] = relationship(back_populates="cilindro")
    movimientos: Mapped[List[Movimiento]] = relationship(back_populates="cilindro")
    entregas: Mapped[List[DetalleEntrega]] = relationship(back_populates="cilindro")
    cambios_propietario: Mapped[List[CambioPropietario]] = relationship(back_populates="cilindro")
    fotografias: Mapped[List[Fotografia]] = relationship(
        primaryjoin="and_(Cilindro.id==Fotografia.entidad_id, Fotografia.entidad_tipo=='CILINDRO')", viewonly=True
    )
    documentos_adjuntos: Mapped[List[DocumentoAdjunto]] = relationship(
        primaryjoin="and_(Cilindro.id==DocumentoAdjunto.entidad_id, DocumentoAdjunto.entidad_tipo=='CILINDRO')",
        viewonly=True,
    )

    __table_args__ = (
        CheckConstraint(
            "estado_operativo IN ("
            "'REGISTRADO','RECIBIDO','PENDIENTE_INSPECCION','APTO_LLENADO',"
            "'ENVIADO_LLENADO','EN_PROCESO_LLENADO','FINALIZADO_LLENADO',"
            "'APTO_REPARACION','ENVIADO_REPARACION','EN_REPARACION','REPARADO',"
            "'PENDIENTE_CONTROL_CALIDAD','APROBADO','APROBADO_OBSERVACIONES',"
            "'LISTO_PARA_ENTREGAR','ENTREGADO','OBSERVADO','RECHAZADO',"
            "'FUERA_SERVICIO','DADO_DE_BAJA')",
            name="ck_cilindro_estado",
        ),
        Index("idx_cilindro_propietario", "propietario_id"),
        Index("idx_cilindro_estado", "estado_operativo"),
        Index("idx_cilindro_ubicacion", "ubicacion_actual_id"),
        Index(
            "idx_cilindro_vencimiento_prueba",
            "fecha_vencimiento_prueba",
            postgresql_where=text("estado_operativo NOT IN ('DADO_DE_BAJA','FUERA_SERVICIO')"),
        ),
        Index("idx_cilindro_serie", "numero_serie"),
    )


class Movimiento(BaseModel):
    """Trazabilidad de movimientos de cilindros entre ubicaciones y estados."""

    __tablename__ = "movimiento"

    cilindro_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cilindro.id", ondelete="RESTRICT"), nullable=False
    )
    ubicacion_origen_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ubicacion.id"), nullable=True
    )
    ubicacion_destino_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ubicacion.id"), nullable=False
    )
    estado_anterior: Mapped[str] = mapped_column(String(30), nullable=False)
    estado_nuevo: Mapped[str] = mapped_column(String(30), nullable=False)
    usuario_entrega_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"))
    usuario_recibe_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"))
    fecha_hora: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    motivo: Mapped[str | None] = mapped_column(String(100))
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    cilindro: Mapped[Cilindro] = relationship(back_populates="movimientos")
    ubicacion_origen: Mapped[Ubicacion | None] = relationship(
        back_populates="movimientos_origen", foreign_keys=[ubicacion_origen_id]
    )
    ubicacion_destino: Mapped[Ubicacion] = relationship(
        back_populates="movimientos_destino", foreign_keys=[ubicacion_destino_id]
    )
    usuario_entrega: Mapped[Usuario | None] = relationship(foreign_keys=[usuario_entrega_id])
    usuario_recibe: Mapped[Usuario | None] = relationship(foreign_keys=[usuario_recibe_id])

    __table_args__ = (
        Index("idx_movimiento_cilindro_fecha", "cilindro_id", "fecha_hora"),
        Index("idx_movimiento_fecha", "fecha_hora"),
    )


# ============================================================
# RECEPCIÓN
# ============================================================


class Recepcion(BaseModel):
    """Cabecera de recepción de cilindros."""

    __tablename__ = "recepcion"

    numero: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    cliente_entrega_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cliente.id"), nullable=False)
    propietario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("propietario.id"), nullable=False)
    cliente_solicita_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cliente.id"), nullable=True
    )
    fecha_hora: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    usuario_responsable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=False
    )
    documento_referencia: Mapped[str | None] = mapped_column(String(100))
    motivo_servicio: Mapped[str] = mapped_column(String(30), nullable=False)  # LLENADO, REPARACION, INSPECCION, OTRO
    observaciones: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), default="COMPLETADA")

    # Relaciones
    cliente_entrega: Mapped[Cliente] = relationship(foreign_keys=[cliente_entrega_id])
    propietario: Mapped[Propietario] = relationship()
    cliente_solicita: Mapped[Cliente | None] = relationship(foreign_keys=[cliente_solicita_id])
    usuario_responsable: Mapped[Usuario] = relationship()
    detalles: Mapped[List[DetalleRecepcion]] = relationship(back_populates="recepcion", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("motivo_servicio IN ('LLENADO','REPARACION','INSPECCION','OTRO')", name="ck_recepcion_motivo"),
        CheckConstraint("estado IN ('COMPLETADA','ANULADA')", name="ck_recepcion_estado"),
        Index("idx_recepcion_fecha", "fecha_hora"),
        Index("idx_recepcion_cliente_entrega", "cliente_entrega_id"),
        Index("idx_recepcion_propietario", "propietario_id"),
    )


class DetalleRecepcion(BaseModel):
    """Detalle de cilindros en una recepción."""

    __tablename__ = "detalle_recepcion"

    recepcion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recepcion.id", ondelete="CASCADE"), nullable=False
    )
    cilindro_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cilindro.id", ondelete="RESTRICT"), nullable=False
    )
    estado_fisico: Mapped[str] = mapped_column(String(20), nullable=False)  # BUENO, REGULAR, MALO, CRITICO
    nivel_llenado_pct: Mapped[int | None] = mapped_column(Integer)
    accesorios: Mapped[dict | None] = mapped_column(JSONB)
    fotografias: Mapped[dict | None] = mapped_column(JSONB)
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    recepcion: Mapped[Recepcion] = relationship(back_populates="detalles")
    cilindro: Mapped[Cilindro] = relationship(back_populates="recepciones")

    __table_args__ = (
        CheckConstraint("estado_fisico IN ('BUENO','REGULAR','MALO','CRITICO')", name="ck_detalle_recepcion_estado"),
        CheckConstraint(
            "nivel_llenado_pct IS NULL OR (nivel_llenado_pct >= 0 AND nivel_llenado_pct <= 100)",
            name="ck_detalle_recepcion_nivel",
        ),
        UniqueConstraint("recepcion_id", "cilindro_id", name="uk_detalle_recepcion_cilindro"),
    )


# ============================================================
# INSPECCIÓN
# ============================================================


class Inspeccion(BaseModel):
    """Inspección técnica de cilindros."""

    __tablename__ = "inspeccion"

    cilindro_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cilindro.id", ondelete="RESTRICT"), nullable=False
    )
    recepcion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recepcion.id"), nullable=True
    )
    usuario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=False)
    fecha_hora: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Checklist
    estado_general: Mapped[str | None] = mapped_column(String(20))
    pintura_ok: Mapped[bool | None] = mapped_column(Boolean)
    corrosion_nivel: Mapped[str | None] = mapped_column(String(20))
    abolladuras: Mapped[bool | None] = mapped_column(Boolean)
    valvula_estado: Mapped[str | None] = mapped_column(String(20))
    fugas_detectadas: Mapped[bool | None] = mapped_column(Boolean)
    serie_legible: Mapped[bool | None] = mapped_column(Boolean)
    prueba_hidraulica_vigente: Mapped[bool | None] = mapped_column(Boolean)
    gas_compatible: Mapped[bool | None] = mapped_column(Boolean)

    resultado: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # APTO_LLENADO, REQUIERE_REPARACION, REQUIERE_INSPECCION_TECNICA, RECHAZADO, FUERA_SERVICIO
    observaciones: Mapped[str | None] = mapped_column(Text)
    fotografias: Mapped[dict | None] = mapped_column(JSONB)

    # Relaciones
    cilindro: Mapped[Cilindro] = relationship(back_populates="inspecciones")
    recepcion: Mapped[Recepcion | None] = relationship()
    usuario: Mapped[Usuario] = relationship()

    __table_args__ = (
        CheckConstraint("estado_general IN ('BUENO','REGULAR','MALO','CRITICO')", name="ck_inspeccion_estado_general"),
        CheckConstraint("corrosion_nivel IN ('NINGUNA','LEVE','MODERADA','SEVERA')", name="ck_inspeccion_corrosion"),
        CheckConstraint("valvula_estado IN ('BUENO','REGULAR','MALO','FALTANTE')", name="ck_inspeccion_valvula"),
        CheckConstraint(
            "resultado IN ('APTO_LLENADO','REQUIERE_REPARACION','REQUIERE_INSPECCION_TECNICA',"
            "'RECHAZADO','FUERA_SERVICIO')",
            name="ck_inspeccion_resultado",
        ),
        Index("idx_inspeccion_cilindro_fecha", "cilindro_id", "fecha_hora"),
    )


# ============================================================
# CONTROL DE CALIDAD
# ============================================================


class ControlCalidad(BaseModel):
    """Control de calidad post-proceso (llenado/reparación)."""

    __tablename__ = "control_calidad"

    cilindro_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cilindro.id", ondelete="RESTRICT"), nullable=False
    )
    orden_relacionada_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orden_trabajo.id"), nullable=True
    )
    usuario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=False)
    fecha_hora: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Checklist CC
    presion_ok: Mapped[bool | None] = mapped_column(Boolean)
    peso_ok: Mapped[bool | None] = mapped_column(Boolean)
    fuga_ok: Mapped[bool | None] = mapped_column(Boolean)
    etiquetado_ok: Mapped[bool | None] = mapped_column(Boolean)
    pintura_ok: Mapped[bool | None] = mapped_column(Boolean)
    accesorios_ok: Mapped[bool | None] = mapped_column(Boolean)
    documentacion_ok: Mapped[bool | None] = mapped_column(Boolean)

    resultado: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # APROBADO, APROBADO_OBSERVACIONES, REQUIERE_NUEVA_REPARACION, RECHAZADO, PENDIENTE_REVISION
    observaciones: Mapped[str | None] = mapped_column(Text)
    autoriza_entrega: Mapped[bool] = mapped_column(Boolean, default=False)
    fotografias: Mapped[dict | None] = mapped_column(JSONB)

    # Relaciones
    cilindro: Mapped[Cilindro] = relationship(back_populates="controles_calidad")
    orden_relacionada: Mapped[OrdenTrabajo | None] = relationship()
    usuario: Mapped[Usuario] = relationship()

    __table_args__ = (
        CheckConstraint(
            "resultado IN ('APROBADO','APROBADO_OBSERVACIONES','REQUIERE_NUEVA_REPARACION',"
            "'RECHAZADO','PENDIENTE_REVISION')",
            name="ck_control_calidad_resultado",
        ),
        Index("idx_cc_cilindro_fecha", "cilindro_id", "fecha_hora"),
    )


# Registrar triggers de auditoría
for model in [Ubicacion, Cilindro, Movimiento, Recepcion, DetalleRecepcion, Inspeccion, ControlCalidad]:
    register_audit_trigger(model)
