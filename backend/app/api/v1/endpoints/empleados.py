"""
Endpoints de empleados (ETAPA 2.1).

Dominio RBAC: **TAREA_28** (gestión de personas). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular/baja,
PERM_09 asignar tareas, PERM_10 reasignar (revocar asignaciones).

DELETE /empleados/{id} es la **baja lógica** (estado := RETIRADO, el valor
del ciclo `ck_empleado_estado`) y además revoca las asignaciones VIGENTES.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select, update

# noqa en TC001: FastAPI y las firmas resuelven estos nombres en runtime.
from app.api.deps import (  # noqa: TC001
    RequireTaskPermission,
    SessionDep,
    obtener_o_404,
    verificar_unico,
)
from app.core.exceptions import (
    DuplicateValue,
    EmployeeInactive,
    InvalidStateTransition,
    NotFound,
    ValidationError,
)
from app.models import Area, Empleado, EmpleadoTarea, Tarea, Usuario
from app.schemas.common import Pagina
from app.schemas.empleados import (
    TODOS_ESTADOS_EMPLEADO,
    AsignacionTareaCreate,
    AsignacionTareaResponse,
    EmpleadoCreate,
    EmpleadoEstadoUpdate,
    EmpleadoResponse,
    EmpleadoUpdate,
)

router = APIRouter(tags=["Empleados"])

# Guard RBAC por acción (dominio TAREA_28).
_LEER = RequireTaskPermission("TAREA_28", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_28", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_28", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_28", "PERM_07")
_ASIGNAR = RequireTaskPermission("TAREA_28", "PERM_09")
_REVOCAR = RequireTaskPermission("TAREA_28", "PERM_10")


def _respuesta(empleado: Empleado) -> EmpleadoResponse:
    return EmpleadoResponse.model_validate(empleado, from_attributes=True)


def _respuesta_asignacion(asignacion: EmpleadoTarea) -> AsignacionTareaResponse:
    return AsignacionTareaResponse.model_validate(asignacion, from_attributes=True)


async def _revocar_asignaciones_vigentes(session, empleado_id: uuid.UUID) -> int:
    """Revoca todas las asignaciones VIGENTE de un empleado (baja)."""
    result = await session.execute(
        update(EmpleadoTarea)
        .where(EmpleadoTarea.empleado_id == empleado_id, EmpleadoTarea.estado == "VIGENTE")
        .values(estado="REVOCADA", fecha_termino=date.today())
    )
    return result.rowcount or 0


@router.get("", response_model=Pagina[EmpleadoResponse], summary="Listar empleados")
async def listar_empleados(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    estado: str | None = Query(None, description="Filtro exacto por estado laboral."),
    area_id: uuid.UUID | None = Query(None, description="Filtro por área."),
    q: str | None = Query(
        None, max_length=100, description="Contiene en RUT, nombres, apellidos o correo."
    ),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[EmpleadoResponse]:
    filtros = []
    if estado:
        filtros.append(Empleado.estado == estado)
    if area_id is not None:
        filtros.append(Empleado.area_id == area_id)
    if q:
        patron = f"%{q}%"
        filtros.append(
            or_(
                Empleado.rut.ilike(patron),
                Empleado.nombres.ilike(patron),
                Empleado.apellidos.ilike(patron),
                Empleado.correo.ilike(patron),
            )
        )

    total = (
        await session.execute(select(func.count()).select_from(Empleado).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Empleado)
            .where(*filtros)
            .order_by(Empleado.apellidos, Empleado.nombres)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[EmpleadoResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{empleado_id}", response_model=EmpleadoResponse, summary="Detalle de empleado")
async def obtener_empleado(
    empleado_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> EmpleadoResponse:
    return _respuesta(await obtener_o_404(session, Empleado, empleado_id, "Empleado"))


@router.post(
    "",
    response_model=EmpleadoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear empleado",
)
async def crear_empleado(
    body: EmpleadoCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> EmpleadoResponse:
    await obtener_o_404(session, Area, body.area_id, "Área")
    await verificar_unico(session, Empleado, "rut", body.rut)
    await verificar_unico(session, Empleado, "correo", body.correo)

    empleado = Empleado(**body.model_dump())
    session.add(empleado)
    await session.commit()
    await session.refresh(empleado)
    return _respuesta(empleado)


@router.patch("/{empleado_id}", response_model=EmpleadoResponse, summary="Actualizar empleado")
async def actualizar_empleado(
    empleado_id: uuid.UUID,
    body: EmpleadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> EmpleadoResponse:
    empleado = await obtener_o_404(session, Empleado, empleado_id, "Empleado")

    # `null` = sin cambio (contrato de EmpleadoUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    if "correo" in datos:
        await verificar_unico(session, Empleado, "correo", datos["correo"], exclude_id=empleado_id)
    if datos.get("area_id") is not None:
        await obtener_o_404(session, Area, datos["area_id"], "Área")

    for campo, valor in datos.items():
        setattr(empleado, campo, valor)

    await session.commit()
    await session.refresh(empleado)
    return _respuesta(empleado)


@router.patch("/{empleado_id}/estado", response_model=EmpleadoResponse, summary="Cambiar estado laboral")
async def cambiar_estado(
    empleado_id: uuid.UUID,
    body: EmpleadoEstadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> EmpleadoResponse:
    empleado = await obtener_o_404(session, Empleado, empleado_id, "Empleado")

    if empleado.estado == body.estado:
        raise InvalidStateTransition(
            "Empleado",
            empleado.estado,
            body.estado,
            allowed=[e for e in TODOS_ESTADOS_EMPLEADO if e != empleado.estado],
        )

    empleado.estado = body.estado
    if body.estado == "RETIRADO":
        # La baja definitiva cierra las asignaciones VIGENTES.
        await _revocar_asignaciones_vigentes(session, empleado.id)

    await session.commit()
    await session.refresh(empleado)
    return _respuesta(empleado)


@router.delete("/{empleado_id}", response_model=EmpleadoResponse, summary="Dar de baja empleado")
async def dar_de_baja_empleado(
    empleado_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
) -> EmpleadoResponse:
    """Baja lógica: estado := RETIRADO + revocación de asignaciones VIGENTES."""
    empleado = await obtener_o_404(session, Empleado, empleado_id, "Empleado")
    empleado.estado = "RETIRADO"
    await _revocar_asignaciones_vigentes(session, empleado.id)
    await session.commit()
    await session.refresh(empleado)
    return _respuesta(empleado)


# ============================================================
# ASIGNACIÓN DE TAREAS AL EMPLEADO
# ============================================================


@router.get(
    "/{empleado_id}/tareas",
    response_model=list[AsignacionTareaResponse],
    summary="Tareas asignadas al empleado",
)
async def listar_asignaciones(
    empleado_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    estado: str | None = Query(None, description="Filtro por estado de la asignación."),
) -> list[AsignacionTareaResponse]:
    await obtener_o_404(session, Empleado, empleado_id, "Empleado")
    filtros = [EmpleadoTarea.empleado_id == empleado_id]
    if estado:
        filtros.append(EmpleadoTarea.estado == estado)
    filas = (
        await session.execute(
            select(EmpleadoTarea).where(*filtros).order_by(EmpleadoTarea.fecha_asignacion.desc())
        )
    ).scalars().all()
    return [_respuesta_asignacion(f) for f in filas]


@router.post(
    "/{empleado_id}/tareas",
    response_model=AsignacionTareaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Asignar tarea al empleado",
)
async def asignar_tarea(
    empleado_id: uuid.UUID,
    body: AsignacionTareaCreate,
    session: SessionDep,
    user: Usuario = Depends(_ASIGNAR),
) -> AsignacionTareaResponse:
    empleado = await obtener_o_404(session, Empleado, empleado_id, "Empleado")
    if empleado.estado != "ACTIVO":
        raise EmployeeInactive(
            f"El empleado {empleado.rut} está en estado {empleado.estado} "
            "y no puede recibir nuevas tareas"
        )
    if body.fecha_inicio and body.fecha_termino and body.fecha_termino < body.fecha_inicio:
        raise ValidationError("La fecha de término no puede ser anterior a la fecha de inicio")

    tarea = await obtener_o_404(session, Tarea, body.tarea_id, "Tarea")

    duplicada = (
        await session.execute(
            select(EmpleadoTarea.id)
            .where(
                EmpleadoTarea.empleado_id == empleado.id,
                EmpleadoTarea.tarea_id == tarea.id,
                EmpleadoTarea.estado == "VIGENTE",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if duplicada is not None:
        raise DuplicateValue("tarea_id", str(tarea.id))

    asignacion = EmpleadoTarea(
        empleado_id=empleado.id,
        tarea_id=tarea.id,
        usuario_asigno_id=user.id,
        fecha_inicio=body.fecha_inicio,
        fecha_termino=body.fecha_termino,
        observaciones=body.observaciones,
    )
    session.add(asignacion)
    await session.commit()
    await session.refresh(asignacion)
    return _respuesta_asignacion(asignacion)


@router.delete(
    "/{empleado_id}/tareas/{tarea_id}",
    response_model=AsignacionTareaResponse,
    summary="Revocar asignación de tarea",
)
async def revocar_asignacion(
    empleado_id: uuid.UUID,
    tarea_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_REVOCAR),
) -> AsignacionTareaResponse:
    """Revoca la asignación VIGENTE (estado := REVOCADA, fecha_termino := hoy)."""
    await obtener_o_404(session, Empleado, empleado_id, "Empleado")
    asignacion = (
        await session.execute(
            select(EmpleadoTarea)
            .where(
                EmpleadoTarea.empleado_id == empleado_id,
                EmpleadoTarea.tarea_id == tarea_id,
                EmpleadoTarea.estado == "VIGENTE",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if asignacion is None:
        raise NotFound("Asignación", tarea_id)

    asignacion.estado = "REVOCADA"
    asignacion.fecha_termino = date.today()
    await session.commit()
    await session.refresh(asignacion)
    return _respuesta_asignacion(asignacion)
