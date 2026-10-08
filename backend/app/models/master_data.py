"""
Modelos de datos maestros: áreas, categorías, tipos de gas, formas de pago,
tipos de documento, parámetros, empleados, usuarios, sesiones, tareas, permisos.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
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
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, SoftDeleteMixin, register_audit_trigger

# ============================================================
# CATÁLOGOS MAESTROS
# ============================================================


class Area(BaseModel):
    """Áreas operativas de AGAS."""

    __tablename__ = "area"

    codigo: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), default="ACTIVA", nullable=False)
    orden_visual: Mapped[int] = mapped_column(Integer, default=0)

    # Relaciones
    empleados: Mapped[List[Empleado]] = relationship(back_populates="area")
    ordenes_trabajo: Mapped[List[OrdenTrabajo]] = relationship(back_populates="area_responsable")


class Categoria(BaseModel):
    """Categorías para productos y servicios (jerárquicas)."""

    __tablename__ = "categoria"

    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # PRODUCTO, SERVICIO, AMBOS
    codigo: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text)
    padre_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("categoria.id"), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="ACTIVA")

    # Relaciones
    padre: Mapped[Categoria | None] = relationship(remote_side="Categoria.id", back_populates="hijos")
    hijos: Mapped[List[Categoria]] = relationship(back_populates="padre")
    productos: Mapped[List[Producto]] = relationship(back_populates="categoria")
    servicios: Mapped[List[Servicio]] = relationship(back_populates="categoria")

    __table_args__ = (CheckConstraint("tipo IN ('PRODUCTO','SERVICIO','AMBOS')", name="ck_categoria_tipo"),)


class TipoGas(BaseModel):
    """Tipos de gas manejados."""

    __tablename__ = "tipo_gas"

    codigo: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(50), nullable=False)
    requiere_prueba_hidraulica: Mapped[bool] = mapped_column(Boolean, default=True)
    color_etiqueta: Mapped[str | None] = mapped_column(String(7))  # Hex color
    estado: Mapped[str] = mapped_column(String(20), default="ACTIVO")

    cilindros: Mapped[List[Cilindro]] = relationship(back_populates="tipo_gas")
    ordenes_llenado: Mapped[List[OrdenTrabajo]] = relationship(back_populates="tipo_gas")


class FormaPago(BaseModel):
    """Catálogo de formas de pago."""

    __tablename__ = "forma_pago"

    codigo: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(50), nullable=False)
    es_tributario: Mapped[bool] = mapped_column(Boolean, default=False)
    requiere_nro_operacion: Mapped[bool] = mapped_column(Boolean, default=True)
    estado: Mapped[str] = mapped_column(String(20), default="ACTIVA")

    pagos: Mapped[List[Pago]] = relationship(back_populates="forma_pago")
    documentos: Mapped[List[DocumentoComercial]] = relationship(back_populates="forma_pago")


class TipoDocumento(BaseModel):
    """Tipos de documentos comerciales configurables."""

    __tablename__ = "tipo_documento"

    codigo: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(50), nullable=False)
    es_tributario: Mapped[bool] = mapped_column(Boolean, default=False)
    requiere_folio_unico: Mapped[bool] = mapped_column(Boolean, default=True)
    requiere_receptor: Mapped[bool] = mapped_column(Boolean, default=True)
    plantilla_pdf: Mapped[str | None] = mapped_column(String(100))
    estado: Mapped[str] = mapped_column(String(20), default="ACTIVO")

    documentos: Mapped[List[DocumentoComercial]] = relationship(back_populates="tipo_documento")


class Parametro(Base):
    """Parámetros de configuración global (key-value tipado)."""

    __tablename__ = "parametro"

    clave: Mapped[str] = mapped_column(String(100), primary_key=True)
    valor: Mapped[str] = mapped_column(Text, nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # STRING, INTEGER, DECIMAL, BOOLEAN, JSON, DATE
    descripcion: Mapped[str | None] = mapped_column(Text)
    editable: Mapped[bool] = mapped_column(Boolean, default=True)
    actualizada_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    fecha_actualizacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        CheckConstraint("tipo IN ('STRING','INTEGER','DECIMAL','BOOLEAN','JSON','DATE')", name="ck_parametro_tipo"),
    )


class TasaImpuesto(BaseModel):
    """Tasas de impuesto (IVA, etc.) con vigencia."""

    __tablename__ = "tasa_impuesto"

    codigo: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(50), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)  # 19.00, 0.00
    es_default: Mapped[bool] = mapped_column(Boolean, default=False)
    vigencia_desde: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    vigencia_hasta: Mapped[date | None] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(20), default="ACTIVA")

    productos: Mapped[List[Producto]] = relationship(back_populates="tasa_impuesto")
    servicios: Mapped[List[Servicio]] = relationship(back_populates="tasa_impuesto")


# ============================================================
# SEGURIDAD Y PERSONAL
# ============================================================


class Empleado(BaseModel, SoftDeleteMixin):
    """Datos laborales de empleados de AGAS."""

    __tablename__ = "empleado"

    rut: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)
    nombres: Mapped[str] = mapped_column(String(100), nullable=False)
    apellidos: Mapped[str] = mapped_column(String(100), nullable=False)
    cargo: Mapped[str] = mapped_column(String(100), nullable=False)
    area_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("area.id"), nullable=False)
    correo: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(20))
    fecha_ingreso: Mapped[date] = mapped_column(Date, nullable=False)
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    area: Mapped[Area] = relationship(back_populates="empleados")
    usuario: Mapped[Usuario | None] = relationship(back_populates="empleado", uselist=False)
    tareas_asignadas: Mapped[List[EmpleadoTarea]] = relationship(back_populates="empleado")
    tareas_responsable: Mapped[List[TareaAsignada]] = relationship(back_populates="responsable")

    __table_args__ = (
        CheckConstraint(
            "estado IN ('ACTIVO','INACTIVO','SUSPENDIDO','LICENCIA','RETIRADO')", name="ck_empleado_estado"
        ),
        Index("idx_empleado_area_estado", "area_id", "estado"),
    )

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombres} {self.apellidos}"


class Usuario(BaseModel):
    """Cuentas de acceso al sistema."""

    __tablename__ = "usuario"

    empleado_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("empleado.id"), unique=True, nullable=True
    )
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    estado: Mapped[str] = mapped_column(String(30), default="PENDIENTE_ACTIVACION", nullable=False)
    requiere_cambio_password: Mapped[bool] = mapped_column(Boolean, default=True)
    totp_secret: Mapped[str | None] = mapped_column(String(32))
    totp_activado: Mapped[bool] = mapped_column(Boolean, default=False)
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intentos_fallidos: Mapped[int] = mapped_column(Integer, default=0)
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relaciones
    empleado: Mapped[Empleado | None] = relationship(back_populates="usuario")
    sesiones: Mapped[List[Sesion]] = relationship(back_populates="usuario")
    ordenes_creadas: Mapped[List[OrdenTrabajo]] = relationship(
        foreign_keys="OrdenTrabajo.usuario_creador_id", back_populates="usuario_creador"
    )
    ordenes_asignadas: Mapped[List[OrdenTrabajo]] = relationship(
        foreign_keys="OrdenTrabajo.usuario_asignado_id", back_populates="usuario_asignado"
    )
    recepciones: Mapped[List[Recepcion]] = relationship(back_populates="usuario_responsable")
    inspecciones: Mapped[List[Inspeccion]] = relationship(back_populates="usuario")
    controles_calidad: Mapped[List[ControlCalidad]] = relationship(back_populates="usuario")
    tareas_asignadas_creadas: Mapped[List[TareaAsignada]] = relationship(
        primaryjoin="foreign(TareaAsignada.creado_por)==Usuario.id", viewonly=True
    )
    entregas: Mapped[List[Entrega]] = relationship(
        foreign_keys="Entrega.usuario_responsable_id", back_populates="usuario_responsable"
    )
    documentos: Mapped[List[DocumentoComercial]] = relationship(
        primaryjoin="foreign(DocumentoComercial.creado_por)==Usuario.id", viewonly=True
    )
    pagos: Mapped[List[Pago]] = relationship(
        primaryjoin="foreign(Pago.creado_por)==Usuario.id", viewonly=True
    )
    notificaciones: Mapped[List[Notificacion]] = relationship(back_populates="usuario")
    auditorias: Mapped[List[Auditoria]] = relationship(back_populates="usuario")
    cambios_propietario_autorizados: Mapped[List[CambioPropietario]] = relationship(
        back_populates="usuario_autoriza"
    )

    __table_args__ = (
        CheckConstraint("estado IN ('ACTIVO','BLOQUEADO','EXPIRADO','PENDIENTE_ACTIVACION')", name="ck_usuario_estado"),
        Index("idx_usuario_empleado", "empleado_id"),
        Index("idx_usuario_estado", "estado"),
    )


class Sesion(BaseModel):
    """Control de sesiones activas (refresh tokens)."""

    __tablename__ = "sesion"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuario.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip_inicio: Mapped[str | None] = mapped_column(INET)
    ip_ultima: Mapped[str | None] = mapped_column(INET)
    iniciada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    ultima_actividad: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revocada: Mapped[bool] = mapped_column(Boolean, default=False)
    revocada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocada_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    usuario: Mapped[Usuario] = relationship(back_populates="sesiones")

    __table_args__ = (
        Index("idx_sesion_usuario_activa", "usuario_id", postgresql_where=text("NOT revocada")),
        Index("idx_sesion_expira", "expira_en"),
    )


class Tarea(BaseModel):
    """Catálogo de tareas operativas y administrativas."""

    __tablename__ = "tarea"

    codigo: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text)
    categoria: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # MAESTROS, OPERATIVO, CALIDAD, DESPACHO, COMERCIAL, ADMIN, REPORTES, AUDITORIA
    es_operativa: Mapped[bool] = mapped_column(Boolean, default=True)
    requiere_supervision: Mapped[bool] = mapped_column(Boolean, default=False)
    estado: Mapped[str] = mapped_column(String(20), default="ACTIVA")

    # Relaciones
    permisos: Mapped[List[TareaPermiso]] = relationship(back_populates="tarea")
    empleados: Mapped[List[EmpleadoTarea]] = relationship(back_populates="tarea")
    tareas_asignadas: Mapped[List[TareaAsignada]] = relationship(back_populates="tarea")

    __table_args__ = (
        CheckConstraint(
            "categoria IN ('MAESTROS','OPERATIVO','CALIDAD','DESPACHO','COMERCIAL','ADMIN','REPORTES','AUDITORIA')",
            name="ck_tarea_categoria",
        ),
    )


class Permiso(BaseModel):
    """Permisos granulares por acción."""

    __tablename__ = "permiso"

    codigo: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(50), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text)
    es_critico: Mapped[bool] = mapped_column(Boolean, default=False)

    tareas: Mapped[List[TareaPermiso]] = relationship(back_populates="permiso")


class TareaPermiso(Base):
    """Matriz configurable tarea-permiso."""

    __tablename__ = "tarea_permiso"

    tarea_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tarea.id", ondelete="CASCADE"), primary_key=True
    )
    permiso_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permiso.id", ondelete="CASCADE"), primary_key=True
    )
    concedido: Mapped[bool] = mapped_column(Boolean, default=True)

    tarea: Mapped[Tarea] = relationship(back_populates="permisos")
    permiso: Mapped[Permiso] = relationship(back_populates="tareas")


class EmpleadoTarea(BaseModel):
    """Asignación de tareas a empleados con vigencia."""

    __tablename__ = "empleado_tarea"

    empleado_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("empleado.id", ondelete="CASCADE"), nullable=False
    )
    tarea_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tarea.id", ondelete="CASCADE"), nullable=False
    )
    fecha_asignacion: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    fecha_inicio: Mapped[date | None] = mapped_column(Date)
    fecha_termino: Mapped[date | None] = mapped_column(Date)
    usuario_asigno_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), default="VIGENTE", nullable=False)
    observaciones: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    empleado: Mapped[Empleado] = relationship(back_populates="tareas_asignadas")
    tarea: Mapped[Tarea] = relationship(back_populates="empleados")
    usuario_asigno: Mapped[Usuario] = relationship()

    __table_args__ = (
        CheckConstraint("estado IN ('VIGENTE','VENCIDA','REVOCADA','SUSPENDIDA')", name="ck_empleado_tarea_estado"),
        UniqueConstraint("empleado_id", "tarea_id", "fecha_asignacion", name="uk_empleado_tarea_asignacion"),
        Index("idx_emp_tarea_vigente", "empleado_id", "tarea_id", postgresql_where=text("estado='VIGENTE'")),
    )


# Registrar triggers de auditoría para modelos críticos
for model in [Area, Categoria, TipoGas, FormaPago, TipoDocumento, TasaImpuesto, Empleado, Usuario, Tarea, Permiso]:
    register_audit_trigger(model)
