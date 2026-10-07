"""
Helper de auditoría para registrar eventos desde la capa de servicio.

Los triggers de BD (INSERT/UPDATE/DELETE en tablas críticas) ya cubren
las modificaciones de datos. Este módulo registra eventos de aplicación:
LOGIN, LOGOUT, EXPORT, IMPORT, EXCEPCION, REASIGNAR, APROBAR, RECHAZAR,
CAMBIO_ESTADO y eventos que requieren contexto de la aplicación.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Auditoria


async def log_audit(
    session: AsyncSession,
    *,
    usuario_id: uuid.UUID | None,
    modulo: str,
    accion: str,
    registro_id: uuid.UUID | None = None,
    registro_tipo: str | None = None,
    valor_anterior: Dict[str, Any] | None = None,
    valor_nuevo: Dict[str, Any] | None = None,
    motivo: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """
    Registra un evento de auditoría.

    Args:
        session: Sesión de BD activa.
        usuario_id: ID del usuario que realiza la acción (None = sistema).
        modulo: Nombre del módulo o tabla afectada.
        accion: Una de INSERT, UPDATE, DELETE, LOGIN, LOGOUT, EXPORT,
                IMPORT, EXCEPCION, REASIGNAR, APROBAR, RECHAZAR, CAMBIO_ESTADO.
        registro_id: ID del registro afectado.
        registro_tipo: Nombre de la tabla del registro afectado.
        valor_anterior: Estado previo (dict) para UPDATE/DELETE.
        valor_nuevo: Estado nuevo (dict) para INSERT/UPDATE.
        motivo: Motivo de la acción (obligatorio para EXCEPCION y UPDATE sensibles).
        ip: IP del cliente.
        user_agent: User-Agent del cliente.
    """
    evento = Auditoria(
        usuario_id=usuario_id,
        modulo=modulo,
        accion=accion,
        registro_afectado_id=registro_id,
        registro_tipo=registro_tipo,
        valor_anterior=valor_anterior,
        valor_nuevo=valor_nuevo,
        motivo=motivo,
        ip=ip,
        user_agent=user_agent,
    )
    session.add(evento)


# ============================================================
# HELPERS ESPECIALIZADOS (azúcar sintáctico comunes)
# ============================================================


async def log_login(
    session: AsyncSession,
    usuario_id: uuid.UUID,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    await log_audit(
        session,
        usuario_id=usuario_id,
        modulo="auth",
        accion="LOGIN",
        ip=ip,
        user_agent=user_agent,
    )


async def log_logout(
    session: AsyncSession,
    usuario_id: uuid.UUID,
    ip: str | None = None,
) -> None:
    await log_audit(
        session,
        usuario_id=usuario_id,
        modulo="auth",
        accion="LOGOUT",
        ip=ip,
    )


async def log_export(
    session: AsyncSession,
    usuario_id: uuid.UUID,
    modulo: str,
    formato: str,
    filtros: Dict[str, Any] | None = None,
) -> None:
    """Registra exportación de reportes/datos."""
    await log_audit(
        session,
        usuario_id=usuario_id,
        modulo=modulo,
        accion="EXPORT",
        valor_nuevo={"formato": formato, "filtros": filtros or {}},
    )


async def log_exception(
    session: AsyncSession,
    usuario_id: uuid.UUID,
    modulo: str,
    registro_id: uuid.UUID,
    registro_tipo: str,
    motivo: str,
    extra: Dict[str, Any] | None = None,
) -> None:
    """
    Registra una excepción autorizada (ej: entrega sin documento).
    El motivo es obligatorio.
    """
    await log_audit(
        session,
        usuario_id=usuario_id,
        modulo=modulo,
        accion="EXCEPCION",
        registro_id=registro_id,
        registro_tipo=registro_tipo,
        motivo=motivo,
        valor_nuevo=extra or {},
    )


async def log_state_change(
    session: AsyncSession,
    usuario_id: uuid.UUID,
    modulo: str,
    registro_id: uuid.UUID,
    registro_tipo: str,
    estado_anterior: str,
    estado_nuevo: str,
    motivo: str | None = None,
) -> None:
    """Registra cambio de estado de un registro."""
    await log_audit(
        session,
        usuario_id=usuario_id,
        modulo=modulo,
        accion="CAMBIO_ESTADO",
        registro_id=registro_id,
        registro_tipo=registro_tipo,
        valor_anterior={"estado": estado_anterior},
        valor_nuevo={"estado": estado_nuevo},
        motivo=motivo,
    )


async def log_approval(
    session: AsyncSession,
    usuario_id: uuid.UUID,
    modulo: str,
    registro_id: uuid.UUID,
    registro_tipo: str,
    motivo: str | None = None,
) -> None:
    await log_audit(
        session,
        usuario_id=usuario_id,
        modulo=modulo,
        accion="APROBAR",
        registro_id=registro_id,
        registro_tipo=registro_tipo,
        motivo=motivo,
    )


async def log_rejection(
    session: AsyncSession,
    usuario_id: uuid.UUID,
    modulo: str,
    registro_id: uuid.UUID,
    registro_tipo: str,
    motivo: str | None = None,
) -> None:
    await log_audit(
        session,
        usuario_id=usuario_id,
        modulo=modulo,
        accion="RECHAZAR",
        registro_id=registro_id,
        registro_tipo=registro_tipo,
        motivo=motivo,
    )


async def log_reassignment(
    session: AsyncSession,
    usuario_id: uuid.UUID,
    registro_id: uuid.UUID,
    registro_tipo: str,
    responsable_anterior_id: uuid.UUID,
    responsable_nuevo_id: uuid.UUID,
    motivo: str,
) -> None:
    """Registra reasignación de tarea (RN26, requiere motivo)."""
    await log_audit(
        session,
        usuario_id=usuario_id,
        modulo="tarea_asignada",
        accion="REASIGNAR",
        registro_id=registro_id,
        registro_tipo=registro_tipo,
        valor_anterior={"responsable_id": str(responsable_anterior_id)},
        valor_nuevo={"responsable_id": str(responsable_nuevo_id)},
        motivo=motivo,
    )
