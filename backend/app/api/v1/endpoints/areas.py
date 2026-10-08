"""
Endpoints del catálogo de áreas operativas (ETAPA 3.1).

Dominio RBAC: **TAREA_29** (administrar catálogos). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular.

DELETE /areas/{id} solo elimina físicamente un área sin referencias
(empleados, órdenes de trabajo); con historial → 409 HAS_HISTORY (y en su
lugar se inactiva con PATCH /areas/{id}/estado).
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
from app.core.exceptions import HasHistoryError, InvalidStateTransition, ValidationError
from app.models import Area, Empleado, OrdenTrabajo, Usuario
from app.schemas.catalogos import (
    AreaCreate,
    AreaEstadoUpdate,
    AreaResponse,
    AreaUpdate,
)
from app.schemas.common import Pagina

router = APIRouter(tags=["Catálogos — áreas"])

# Guard RBAC por acción (dominio TAREA_29: catálogos).
_LEER = RequireTaskPermission("TAREA_29", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_29", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_29", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_29", "PERM_07")

_ESTADOS = ("ACTIVA", "INACTIVA")


def _respuesta(area: Area) -> AreaResponse:
    return AreaResponse.model_validate(area, from_attributes=True)


@router.get("", response_model=Pagina[AreaResponse], summary="Listar áreas")
async def listar_areas(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    estado: str | None = Query(None, description="Filtro exacto por estado."),
    q: str | None = Query(None, max_length=100, description="Contiene en código o nombre."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[AreaResponse]:
    filtros = []
    if estado:
        filtros.append(Area.estado == estado)
    if q:
        patron = f"%{q}%"
        filtros.append(or_(Area.codigo.ilike(patron), Area.nombre.ilike(patron)))

    total = (
        await session.execute(select(func.count()).select_from(Area).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Area)
            .where(*filtros)
            .order_by(Area.codigo)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[AreaResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{area_id}", response_model=AreaResponse, summary="Detalle de área")
async def obtener_area(
    area_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> AreaResponse:
    return _respuesta(await obtener_o_404(session, Area, area_id, "Área"))


@router.post(
    "",
    response_model=AreaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear área",
)
async def crear_area(
    body: AreaCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> AreaResponse:
    await verificar_unico(session, Area, "codigo", body.codigo)
    area = Area(**body.model_dump())
    session.add(area)
    await session.commit()
    await session.refresh(area)
    return _respuesta(area)


@router.patch("/{area_id}", response_model=AreaResponse, summary="Actualizar área")
async def actualizar_area(
    area_id: uuid.UUID,
    body: AreaUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> AreaResponse:
    area = await obtener_o_404(session, Area, area_id, "Área")

    # `null` = sin cambio (contrato de AreaUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    for campo, valor in datos.items():
        setattr(area, campo, valor)

    await session.commit()
    await session.refresh(area)
    return _respuesta(area)


@router.patch("/{area_id}/estado", response_model=AreaResponse, summary="Cambiar estado de área")
async def cambiar_estado(
    area_id: uuid.UUID,
    body: AreaEstadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> AreaResponse:
    area = await obtener_o_404(session, Area, area_id, "Área")
    if area.estado == body.estado:
        raise InvalidStateTransition(
            "Área",
            area.estado,
            body.estado,
            allowed=[e for e in _ESTADOS if e != area.estado],
        )
    area.estado = body.estado
    await session.commit()
    await session.refresh(area)
    return _respuesta(area)


@router.delete("/{area_id}", summary="Eliminar área (solo sin historial)")
async def eliminar_area(
    area_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
):
    """Borrado físico condicionado a cero referencias; con historial → 409."""
    area = await obtener_o_404(session, Area, area_id, "Área")

    referencias = (
        (Empleado, Empleado.area_id),
        (OrdenTrabajo, OrdenTrabajo.area_responsable_id),
    )
    for model, columna in referencias:
        enlaces = (
            await session.execute(
                select(func.count()).select_from(model).where(columna == area.id)
            )
        ).scalar_one()
        if enlaces:
            raise HasHistoryError(
                "Área",
                f"No se puede eliminar el área '{area.codigo}': tiene {enlaces} registro(s) "
                f"asociados en '{model.__tablename__}'. Inactívela con PATCH /areas/{{id}}/estado.",
            )

    await session.delete(area)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
