"""
Endpoints de tareas y su matriz de permisos (ETAPA 2.1).

Dominio RBAC: **TAREA_29** (administrar catálogos). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular.

La matriz `tarea_permiso` se administra bajo `/tareas/{id}/permisos`.
DELETE /tareas/{id} solo elimina físicamente una tarea sin referencias
(asignaciones, matriz, tareas asignadas); con historial → 409 HAS_HISTORY
(y en su lugar se inactiva con PATCH /tareas/{id}/estado).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select

# noqa en TC001: FastAPI y las firmas resuelven estos nombres en runtime.
from app.api.deps import (  # noqa: TC001
    RequireTaskPermission,
    SessionDep,
    obtener_o_404,
    verificar_unico,
)
from app.core.exceptions import (
    DuplicateValue,
    HasHistoryError,
    InvalidStateTransition,
    NotFound,
    ValidationError,
)
from app.models import EmpleadoTarea, Permiso, Tarea, TareaAsignada, TareaPermiso, Usuario
from app.schemas.common import Pagina
from app.schemas.tareas import (
    TareaCreate,
    TareaEstadoUpdate,
    TareaPermisoCreate,
    TareaPermisoResponse,
    TareaResponse,
    TareaUpdate,
)

router = APIRouter(tags=["Tareas"])

# Guard RBAC por acción (dominio TAREA_29: catálogos).
_LEER = RequireTaskPermission("TAREA_29", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_29", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_29", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_29", "PERM_07")


def _respuesta(tarea: Tarea) -> TareaResponse:
    return TareaResponse.model_validate(tarea, from_attributes=True)


@router.get("", response_model=Pagina[TareaResponse], summary="Listar tareas")
async def listar_tareas(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    categoria: str | None = Query(None, description="Filtro exacto por categoría."),
    estado: str | None = Query(None, description="Filtro exacto por estado."),
    q: str | None = Query(None, max_length=100, description="Contiene en código o nombre."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[TareaResponse]:
    filtros = []
    if categoria:
        filtros.append(Tarea.categoria == categoria)
    if estado:
        filtros.append(Tarea.estado == estado)
    if q:
        patron = f"%{q}%"
        filtros.append(or_(Tarea.codigo.ilike(patron), Tarea.nombre.ilike(patron)))

    total = (
        await session.execute(select(func.count()).select_from(Tarea).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Tarea)
            .where(*filtros)
            .order_by(Tarea.codigo)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[TareaResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{tarea_id}", response_model=TareaResponse, summary="Detalle de tarea")
async def obtener_tarea(
    tarea_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> TareaResponse:
    return _respuesta(await obtener_o_404(session, Tarea, tarea_id, "Tarea"))


@router.post(
    "",
    response_model=TareaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear tarea",
)
async def crear_tarea(
    body: TareaCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> TareaResponse:
    await verificar_unico(session, Tarea, "codigo", body.codigo)
    tarea = Tarea(**body.model_dump())
    session.add(tarea)
    await session.commit()
    await session.refresh(tarea)
    return _respuesta(tarea)


@router.patch("/{tarea_id}", response_model=TareaResponse, summary="Actualizar tarea")
async def actualizar_tarea(
    tarea_id: uuid.UUID,
    body: TareaUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> TareaResponse:
    tarea = await obtener_o_404(session, Tarea, tarea_id, "Tarea")

    # `null` = sin cambio (contrato de TareaUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    for campo, valor in datos.items():
        setattr(tarea, campo, valor)

    await session.commit()
    await session.refresh(tarea)
    return _respuesta(tarea)


@router.patch("/{tarea_id}/estado", response_model=TareaResponse, summary="Cambiar estado de tarea")
async def cambiar_estado(
    tarea_id: uuid.UUID,
    body: TareaEstadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> TareaResponse:
    tarea = await obtener_o_404(session, Tarea, tarea_id, "Tarea")
    if tarea.estado == body.estado:
        raise InvalidStateTransition(
            "Tarea",
            tarea.estado,
            body.estado,
            allowed=[e for e in ("ACTIVA", "INACTIVA") if e != tarea.estado],
        )
    tarea.estado = body.estado
    await session.commit()
    await session.refresh(tarea)
    return _respuesta(tarea)


@router.delete("/{tarea_id}", summary="Eliminar tarea (solo sin historial)")
async def eliminar_tarea(
    tarea_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
):
    """Borrado físico condicionado a cero referencias; con historial → 409."""
    tarea = await obtener_o_404(session, Tarea, tarea_id, "Tarea")

    for model in (EmpleadoTarea, TareaPermiso, TareaAsignada):
        enlaces = (
            await session.execute(
                select(func.count()).select_from(model).where(model.tarea_id == tarea.id)
            )
        ).scalar_one()
        if enlaces:
            raise HasHistoryError(
                "Tarea",
                f"No se puede eliminar la tarea '{tarea.codigo}': tiene {enlaces} registro(s) "
                f"asociados en '{model.__tablename__}'. Inactívela con PATCH /tareas/{{id}}/estado.",
            )

    await session.delete(tarea)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# MATRIZ TAREA ↔ PERMISO
# ============================================================


@router.get(
    "/{tarea_id}/permisos",
    response_model=list[TareaPermisoResponse],
    summary="Permisos de la tarea (matriz)",
)
async def listar_permisos_de_tarea(
    tarea_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> list[TareaPermisoResponse]:
    await obtener_o_404(session, Tarea, tarea_id, "Tarea")
    filas = await session.execute(
        select(TareaPermiso, Permiso.codigo, Permiso.nombre)
        .join(Permiso, Permiso.id == TareaPermiso.permiso_id)
        .where(TareaPermiso.tarea_id == tarea_id)
        .order_by(Permiso.codigo)
    )
    return [
        TareaPermisoResponse(
            tarea_id=tp.tarea_id,
            permiso_id=tp.permiso_id,
            permiso_codigo=codigo,
            permiso_nombre=nombre,
            concedido=tp.concedido,
        )
        for tp, codigo, nombre in filas
    ]


@router.post(
    "/{tarea_id}/permisos",
    response_model=TareaPermisoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Conceder permiso a la tarea",
)
async def conceder_permiso(
    tarea_id: uuid.UUID,
    body: TareaPermisoCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> TareaPermisoResponse:
    tarea = await obtener_o_404(session, Tarea, tarea_id, "Tarea")
    permiso = await obtener_o_404(session, Permiso, body.permiso_id, "Permiso")

    if (await session.get(TareaPermiso, (tarea.id, permiso.id))) is not None:
        raise DuplicateValue("permiso_id", str(permiso.id))

    fila = TareaPermiso(tarea_id=tarea.id, permiso_id=permiso.id, concedido=body.concedido)
    session.add(fila)
    await session.commit()
    return TareaPermisoResponse(
        tarea_id=fila.tarea_id,
        permiso_id=fila.permiso_id,
        permiso_codigo=permiso.codigo,
        permiso_nombre=permiso.nombre,
        concedido=fila.concedido,
    )


@router.delete(
    "/{tarea_id}/permisos/{permiso_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quitar permiso de la tarea",
)
async def quitar_permiso(
    tarea_id: uuid.UUID,
    permiso_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
):
    await obtener_o_404(session, Tarea, tarea_id, "Tarea")
    fila = await session.get(TareaPermiso, (tarea_id, permiso_id))
    if fila is None:
        raise NotFound("Permiso de la tarea", permiso_id)

    await session.delete(fila)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
