"""
Modelos transversales: auditoría, fotos, documentos adjuntos, notificaciones,
propietarios y clientes.
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
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, SoftDeleteMixin, register_audit_trigger

# ============================================================
# PROPIETARIOS Y CLIENTES
# ============================================================


class Propietario(BaseModel, SoftDeleteMixin):
    """Propietarios de cilindros: Cliente, AGAS, Empresa Externa."""

    __tablename__ = "propietario"

    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # CLIENTE, AGAS, EMPRESA_EXTERNA
    cliente_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cliente.id"), unique=True, nullable=True
    )
    razon_social: Mapped[str] = mapped_column(String(200), nullable=False)
    rut: Mapped[str] = mapped_column(String(12), nullable=False)
    direccion: Mapped[str | None] = mapped_column(String(300))
    comuna: Mapped[str | None] = mapped_column(String(100))
    ciudad: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    telefono: Mapped[str | None] = mapped_column(String(20))
    correo: Mapped[str | None] = mapped_column(String(150))
    persona_contacto: Mapped[str | None] = mapped_column(String(150))
    estado: Mapped[str] = mapped_column(String(20), default="ACTIVO")
    observaciones: Mapped[str | None] = mapped_column(Text)
    es_institucional_agas: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relaciones
    cliente: Mapped[Cliente | None] = relationship()
    cilindros: Mapped[List[Cilindro]] = relationship(back_populates="propietario")
    recepciones: Mapped[List[Recepcion]] = relationship(back_populates="propietario")
    entregas: Mapped[List[Entrega]] = relationship(back_populates="propietario")
    cambios_propietario_anterior: Mapped[List[CambioPropietario]] = relationship(
        foreign_keys="CambioPropietario.propietario_anterior_id", back_populates="propietario_anterior"
    )
    cambios_propietario_nuevo: Mapped[List[CambioPropietario]] = relationship(
        foreign_keys="CambioPropietario.propietario_nuevo_id", back_populates="propietario_nuevo"
    )
    presupuestos: Mapped[List[Presupuesto]] = relationship(back_populates="propietario")

    __table_args__ = (
        CheckConstraint("tipo IN ('CLIENTE','AGAS','EMPRESA_EXTERNA')", name="ck_propietario_tipo"),
        CheckConstraint("estado IN ('ACTIVO','INACTIVO','BLOQUEADO')", name="ck_propietario_estado"),
        # Unicidades parciales como índice único parcial (PostgreSQL no
        # admite constraints únicos con WHERE a nivel de tabla)
        Index("uk_propietario_rut_tipo", "rut", "tipo", unique=True, postgresql_where=text("tipo <> 'CLIENTE'")),
        Index("uk_propietario_cliente", "cliente_id", unique=True, postgresql_where=text("cliente_id IS NOT NULL")),
        Index("idx_propietario_tipo_estado", "tipo", "estado"),
    )


class Cliente(BaseModel, SoftDeleteMixin):
    """Clientes independientes (pueden entregar, solicitar, recibir)."""

    __tablename__ = "cliente"

    rut: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)
    razon_social: Mapped[str] = mapped_column(String(200), nullable=False)
    direccion: Mapped[str | None] = mapped_column(String(300))
    comuna: Mapped[str | None] = mapped_column(String(100))
    ciudad: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    telefono: Mapped[str | None] = mapped_column(String(20))
    correo: Mapped[str | None] = mapped_column(String(150))
    persona_contacto: Mapped[str | None] = mapped_column(String(150))
    estado: Mapped[str] = mapped_column(String(20), default="ACTIVO")
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    propietario: Mapped[Propietario | None] = relationship(back_populates="cliente", uselist=False)
    recepciones_entrega: Mapped[List[Recepcion]] = relationship(
        foreign_keys="Recepcion.cliente_entrega_id", back_populates="cliente_entrega"
    )
    recepciones_solicita: Mapped[List[Recepcion]] = relationship(
        foreign_keys="Recepcion.cliente_solicita_id", back_populates="cliente_solicita"
    )
    entregas_recibe: Mapped[List[Entrega]] = relationship(back_populates="cliente_recibe")
    presupuestos: Mapped[List[Presupuesto]] = relationship(back_populates="cliente")
    receptores_autorizados: Mapped[List[ClienteReceptorAutorizado]] = relationship(
        back_populates="cliente", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("estado IN ('ACTIVO','INACTIVO','BLOQUEADO')", name="ck_cliente_estado"),
        Index("idx_cliente_rut", "rut"),
        Index("idx_cliente_estado", "estado"),
    )


class ClienteReceptorAutorizado(BaseModel):
    """Receptores autorizados para entregas a terceros."""

    __tablename__ = "cliente_receptor_autorizado"

    cliente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cliente.id", ondelete="CASCADE"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    rut: Mapped[str | None] = mapped_column(String(12))
    relacion: Mapped[str | None] = mapped_column(String(100))  # CHOFER, REPRESENTANTE, TERCERO
    telefono: Mapped[str | None] = mapped_column(String(20))
    correo: Mapped[str | None] = mapped_column(String(150))
    autorizado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"))
    fecha_autorizacion: Mapped[date] = mapped_column(Date, default=date.today)
    vigente_hasta: Mapped[date | None] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(20), default="VIGENTE")
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    cliente: Mapped[Cliente] = relationship(back_populates="receptores_autorizados")
    autorizado_por_usuario: Mapped[Usuario | None] = relationship()

    __table_args__ = (CheckConstraint("estado IN ('VIGENTE','VENCIDO','REVOCADO')", name="ck_receptor_estado"),)


# ============================================================
# AUDITORÍA Y TRAZABILIDAD TRANSVERSAL
# ============================================================


class Auditoria(Base):
    """Tabla de auditoría inmutable (solo INSERT, particionada por mes)."""

    __tablename__ = "auditoria"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"))
    fecha_hora: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    modulo: Mapped[str] = mapped_column(String(50), nullable=False)
    accion: Mapped[str] = mapped_column(String(30), nullable=False)
    registro_afectado_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    registro_tipo: Mapped[str | None] = mapped_column(String(50))
    valor_anterior: Mapped[dict | None] = mapped_column(JSONB)
    valor_nuevo: Mapped[dict | None] = mapped_column(JSONB)
    motivo: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    usuario: Mapped[Usuario | None] = relationship(back_populates="auditorias")

    __table_args__ = (
        CheckConstraint(
            "accion IN ('INSERT','UPDATE','DELETE','LOGIN','LOGOUT','EXPORT','IMPORT',"
            "'EXCEPCION','REASIGNAR','APROBAR','RECHAZAR','CAMBIO_ESTADO')",
            name="ck_auditoria_accion",
        ),
        Index("idx_auditoria_usuario_fecha", "usuario_id", "fecha_hora"),
        Index("idx_auditoria_registro", "registro_tipo", "registro_afectado_id"),
        Index("idx_auditoria_fecha", "fecha_hora"),
        # Particionado por mes se configura en migración
    )


class Fotografia(BaseModel):
    """Fotos polimórficas asociadas a cualquier entidad."""

    __tablename__ = "fotografia"

    entidad_tipo: Mapped[str] = mapped_column(String(50), nullable=False)
    entidad_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(300))
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"))
    fecha_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    es_principal: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relaciones
    usuario: Mapped[Usuario | None] = relationship()

    __table_args__ = (Index("idx_foto_entidad", "entidad_tipo", "entidad_id"),)


class DocumentoAdjunto(BaseModel):
    """Documentos adjuntos polimórficos (PDFs, escaneos, etc.)."""

    __tablename__ = "documento_adjunto"

    entidad_tipo: Mapped[str] = mapped_column(String(50), nullable=False)
    entidad_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tipo_documento: Mapped[str | None] = mapped_column(String(50))
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    nombre_original: Mapped[str | None] = mapped_column(String(255))
    descripcion: Mapped[str | None] = mapped_column(Text)
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"))
    fecha_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # Relaciones
    usuario: Mapped[Usuario | None] = relationship()

    __table_args__ = (Index("idx_doc_adjunto_entidad", "entidad_tipo", "entidad_id"),)


class Notificacion(BaseModel):
    """Notificaciones internas del sistema."""

    __tablename__ = "notificacion"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuario.id", ondelete="CASCADE"), nullable=False
    )
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    mensaje: Mapped[str] = mapped_column(Text, nullable=False)
    leida: Mapped[bool] = mapped_column(Boolean, default=False)
    fecha_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    entidad_relacionada_tipo: Mapped[str | None] = mapped_column(String(50))
    entidad_relacionada_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    prioridad: Mapped[str] = mapped_column(String(20), default="NORMAL")
    accion_url: Mapped[str | None] = mapped_column(String(500))

    # Relaciones
    usuario: Mapped[Usuario] = relationship(back_populates="notificaciones")

    __table_args__ = (
        CheckConstraint("prioridad IN ('BAJA','NORMAL','ALTA','CRITICA')", name="ck_notificacion_prioridad"),
        Index("idx_notif_usuario_leida", "usuario_id", "leida", "fecha_hora"),
    )


# Registrar triggers de auditoría para modelos críticos
for model in [Propietario, Cliente, ClienteReceptorAutorizado]:
    register_audit_trigger(model)
