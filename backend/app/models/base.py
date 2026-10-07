"""
Modelos base y mixins para SQLAlchemy 2.0.
Incluye campos de auditoría, soft delete, y utilidades comunes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict

from sqlalchemy import (
    DDL,
    DateTime,
    String,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)


class Base(DeclarativeBase):
    """Base declarativa con metadata común."""


class TimestampMixin:
    """Mixin para campos de timestamps automáticos."""

    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        comment="Fecha de creación del registro",
    )
    fecha_actualizacion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=True,
        comment="Fecha de última actualización",
    )


class UserTrackingMixin:
    """Mixin para tracking de usuario creador/actualizador."""

    creado_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="ID del usuario que creó el registro",
    )
    actualizado_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="ID del usuario que actualizó el registro por última vez",
    )


class SoftDeleteMixin:
    """Mixin para soft delete con campo estado."""

    estado: Mapped[str] = mapped_column(
        String(30),
        default="ACTIVO",
        nullable=False,
        comment="Estado del registro: ACTIVO, INACTIVO, ANULADO, ELIMINADO",
    )

    @property
    def is_active(self) -> bool:
        return self.estado == "ACTIVO"

    def soft_delete(self, user_id: uuid.UUID | None = None) -> None:
        self.estado = "ELIMINADO"
        if user_id:
            self.actualizado_por = user_id


class AuditMixin(TimestampMixin, UserTrackingMixin):
    """Mixin completo de auditoría: timestamps + usuarios."""


class BaseModel(Base, AuditMixin):
    """Modelo base con UUID PK, timestamps y user tracking."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Identificador único (UUID v4)",
    )

    def to_dict(self, exclude: set = None) -> Dict[str, Any]:
        """Convierte el modelo a diccionario excluyendo campos sensibles."""
        exclude = exclude or {"password_hash", "totp_secret"}
        return {c.name: getattr(self, c.name) for c in self.__table__.columns if c.name not in exclude}


# ============================================================
# EVENT LISTENERS PARA AUDITORÍA AUTOMÁTICA
# ============================================================


def generate_audit_trigger(table_name: str) -> DDL:
    """Genera trigger de auditoría para una tabla."""
    return DDL(f"""
        CREATE OR REPLACE FUNCTION audit_{table_name}_trigger()
        RETURNS TRIGGER AS $$
        BEGIN
            IF (TG_OP = 'DELETE') THEN
                INSERT INTO auditoria (
                    usuario_id, fecha_hora, modulo, accion,
                    registro_afectado_id, registro_tipo,
                    valor_anterior, valor_nuevo, motivo
                ) VALUES (
                    COALESCE(current_setting('app.current_user_id', true)::uuid, NULL),
                    now(),
                    '{table_name}',
                    TG_OP,
                    OLD.id,
                    '{table_name}',
                    to_jsonb(OLD),
                    NULL,
                    COALESCE(current_setting('app.audit_motivo', true), '')
                );
                RETURN OLD;
            ELSIF (TG_OP = 'UPDATE') THEN
                INSERT INTO auditoria (
                    usuario_id, fecha_hora, modulo, accion,
                    registro_afectado_id, registro_tipo,
                    valor_anterior, valor_nuevo, motivo
                ) VALUES (
                    COALESCE(current_setting('app.current_user_id', true)::uuid, NULL),
                    now(),
                    '{table_name}',
                    TG_OP,
                    NEW.id,
                    '{table_name}',
                    to_jsonb(OLD),
                    to_jsonb(NEW),
                    COALESCE(current_setting('app.audit_motivo', true), '')
                );
                RETURN NEW;
            ELSIF (TG_OP = 'INSERT') THEN
                INSERT INTO auditoria (
                    usuario_id, fecha_hora, modulo, accion,
                    registro_afectado_id, registro_tipo,
                    valor_anterior, valor_nuevo, motivo
                ) VALUES (
                    COALESCE(current_setting('app.current_user_id', true)::uuid, NULL),
                    now(),
                    '{table_name}',
                    TG_OP,
                    NEW.id,
                    '{table_name}',
                    NULL,
                    to_jsonb(NEW),
                    COALESCE(current_setting('app.audit_motivo', true), '')
                );
                RETURN NEW;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;

        DROP TRIGGER IF EXISTS audit_{table_name}_trigger ON {table_name};
        CREATE TRIGGER audit_{table_name}_trigger
        AFTER INSERT OR UPDATE OR DELETE ON {table_name}
        FOR EACH ROW EXECUTE FUNCTION audit_{table_name}_trigger();
    """)


def register_audit_trigger(model_class) -> None:
    """Registra trigger de auditoría para un modelo."""
    table_name = model_class.__tablename__
    event.listen(model_class.__table__, "after_create", generate_audit_trigger(table_name))


# ============================================================
# UTILIDADES DE SESIÓN PARA AUDITORÍA
# ============================================================


async def set_audit_context(session: AsyncSession, user_id: uuid.UUID | None = None, motivo: str = "") -> None:
    """Configura variables de sesión para triggers de auditoría."""
    if user_id:
        await session.execute(text(f"SET LOCAL app.current_user_id = '{user_id}'"))
    if motivo:
        await session.execute(text(f"SET LOCAL app.audit_motivo = '{motivo.replace(chr(39), chr(39) * 2)}'"))


async def clear_audit_context(session: AsyncSession) -> None:
    """Limpia variables de sesión de auditoría."""
    await session.execute(text("RESET app.current_user_id"))
    await session.execute(text("RESET app.audit_motivo"))
