"""
Sistema de autorización basado en Tareas y Permisos (RBAC configurable).

Flujo:
    usuario → empleado → empleado_tarea (VIGENTE) → tarea → tarea_permiso → permiso

No hay roles fijos: un empleado puede tener una o varias tareas, y cada
tarea tiene un conjunto configurable de permisos.
"""

from __future__ import annotations

import uuid
from typing import List, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EmployeeInactive, PermissionDenied, SeparationOfDutiesError
from app.models import Empleado, EmpleadoTarea, Permiso, Tarea, TareaAsignada, TareaPermiso, Usuario

# ============================================================
# CONSULTAS DE PERMISOS
# ============================================================


async def get_user_permissions(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> List[str]:
    """
    Retorna lista de códigos de permiso activos del usuario.
    Solo considera empleados ACTIVOS con asignaciones VIGENTES.
    """
    stmt = (
        select(Permiso.codigo)
        .join(TareaPermiso, TareaPermiso.permiso_id == Permiso.id)
        .join(Tarea, Tarea.id == TareaPermiso.tarea_id)
        .join(EmpleadoTarea, EmpleadoTarea.tarea_id == Tarea.id)
        .join(Usuario, Usuario.empleado_id == EmpleadoTarea.empleado_id)
        .join(Empleado, Empleado.id == Usuario.empleado_id)
        .where(
            Usuario.id == user_id,
            Usuario.estado == "ACTIVO",
            Empleado.estado == "ACTIVO",
            EmpleadoTarea.estado == "VIGENTE",
            Tarea.estado == "ACTIVA",
            TareaPermiso.concedido.is_(True),
        )
        .distinct()
    )
    result = await session.execute(stmt)
    return [row[0] for row in result]


async def get_user_tasks(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> List[str]:
    """Retorna códigos de tareas vigentes del usuario."""
    stmt = (
        select(Tarea.codigo)
        .join(EmpleadoTarea, EmpleadoTarea.tarea_id == Tarea.id)
        .join(Usuario, Usuario.empleado_id == EmpleadoTarea.empleado_id)
        .join(Empleado, Empleado.id == Usuario.empleado_id)
        .where(
            Usuario.id == user_id,
            Usuario.estado == "ACTIVO",
            Empleado.estado == "ACTIVO",
            EmpleadoTarea.estado == "VIGENTE",
            Tarea.estado == "ACTIVA",
        )
        .distinct()
    )
    result = await session.execute(stmt)
    return [row[0] for row in result]


async def has_permission(
    session: AsyncSession,
    user_id: uuid.UUID,
    permission_code: str,
) -> bool:
    """Verifica si el usuario tiene un permiso específico."""
    perms = await get_user_permissions(session, user_id)
    return permission_code in perms


async def has_task(
    session: AsyncSession,
    user_id: uuid.UUID,
    task_code: str,
) -> bool:
    """Verifica si el usuario tiene una tarea específica."""
    tasks = await get_user_tasks(session, user_id)
    return task_code in tasks


# ============================================================
# VALIDADORES (lanzan excepción si no tiene permiso)
# ============================================================


async def require_permission(
    session: AsyncSession,
    user_id: uuid.UUID,
    permission_code: str,
) -> None:
    """Valida permiso. Lanza PermissionDenied si no lo tiene."""
    if not await has_permission(session, user_id, permission_code):
        raise PermissionDenied(action=f"la operación requerida (permiso '{permission_code}')")


async def require_task(
    session: AsyncSession,
    user_id: uuid.UUID,
    task_code: str,
) -> None:
    """Valida tarea. Lanza PermissionDenied si no la tiene."""
    if not await has_task(session, user_id, task_code):
        raise PermissionDenied(action=f"la tarea '{task_code}'")


async def require_any_permission(
    session: AsyncSession,
    user_id: uuid.UUID,
    permission_codes: Sequence[str],
) -> None:
    """Valida que tenga AL MENOS UNO de los permisos indicados."""
    perms = await get_user_permissions(session, user_id)
    if not any(p in perms for p in permission_codes):
        raise PermissionDenied(action=f"la operación (requiere uno de: {', '.join(permission_codes)})")


async def require_all_permissions(
    session: AsyncSession,
    user_id: uuid.UUID,
    permission_codes: Sequence[str],
) -> None:
    """Valida que tenga TODOS los permisos indicados."""
    perms = await get_user_permissions(session, user_id)
    missing = [p for p in permission_codes if p not in perms]
    if missing:
        raise PermissionDenied(action=f"la operación (faltan permisos: {', '.join(missing)})")


async def ensure_active_employee(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> Empleado:
    """
    Verifica que el usuario esté vinculado a un empleado ACTIVO.
    Lanza EmployeeInactive si no lo está.
    """
    stmt = select(Empleado).join(Usuario, Usuario.empleado_id == Empleado.id).where(Usuario.id == user_id)
    result = await session.execute(stmt)
    empleado = result.scalar_one_or_none()

    if empleado is None:
        raise PermissionDenied(action="operaciones que requieren empleado asociado")

    if empleado.estado != "ACTIVO":
        raise EmployeeInactive(f"El empleado está en estado '{empleado.estado}' y no puede recibir nuevas tareas")

    return empleado


# ============================================================
# SEPARACIÓN DE FUNCIONES
# ============================================================


async def check_separation_of_duties(
    session: AsyncSession,
    performer_user_id: uuid.UUID,
    reviewer_task_code: str,
    performer_task_code: str,
    cylinder_id: uuid.UUID,
) -> None:
    """
    Verifica que quien revisa/aprueba NO sea quien ejecutó el trabajo.
    Regla RN28: técnico que reparó/llenó no puede aprobar su CC.
    """
    stmt = (
        select(TareaAsignada)
        .join(Tarea, Tarea.id == TareaAsignada.tarea_id)
        .join(Empleado, Empleado.id == TareaAsignada.responsable_id)
        .join(Usuario, Usuario.empleado_id == Empleado.id)
        .where(
            TareaAsignada.cilindro_id == cylinder_id,
            Tarea.codigo.in_([performer_task_code]),
            TareaAsignada.estado == "COMPLETADA",
            Usuario.id == performer_user_id,
        )
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise SeparationOfDutiesError


# ============================================================
# CACHE SIMPLE EN MEMORIA (opcional, para requests cortos)
# ============================================================

_permissions_cache: dict = {}


def invalidate_user_cache(user_id: uuid.UUID) -> None:
    """Invalida caché de permisos de un usuario (llamar tras cambios)."""
    _permissions_cache.pop(str(user_id), None)


def invalidate_all_cache() -> None:
    """Invalida todo el caché de permisos."""
    _permissions_cache.clear()
