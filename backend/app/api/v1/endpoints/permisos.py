"""
Endpoints del catálogo de permisos (ETAPA 2.1).

Dominio RBAC: **TAREA_29** (administrar catálogos). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular.

`codigo` es inmutable tras la creación (lo referencian las configuraciones
de seguridad de los endpoints). DELETE solo elimina permisos sin matriz;
con matriz → 409 HAS_HISTORY.
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
from app.core.exceptions import HasHistoryError, ValidationError
from app.models import Permiso, TareaPermiso, Usuario
from app.schemas.common import Pagina
from app.schemas.permisos import PermisoCreate, PermisoResponse, PermisoUpdate

router = APIRouter(tags=["Permisos"])

# Guard RBAC por acción (dominio TAREA_29: catálogos).
_LEER = RequireTaskPermission("TAREA_29", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_29", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_29", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_29", "PERM_07")


def _respuesta(permiso: Permiso) -> PermisoResponse:
    return PermisoResponse.model_validate(permiso, from_attributes=True)


@router.get("", response_model=Pagina[PermisoResponse], summary="Listar permisos")
async def listar_permisos(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    q: str | None = Query(None, max_length=100, description="Contiene en código o nombre."),
    es_critico: bool | None = Query(None, description="Filtra permisos críticos."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[PermisoResponse]:
    filtros = []
    if q:
        patron = f"%{q}%"
        filtros.append(or_(Permiso.codigo.ilike(patron), Permiso.nombre.ilike(patron)))
    if es_critico is not None:
        filtros.append(Permiso.es_critico.is_(es_critico))

    total = (
        await session.execute(select(func.count()).select_from(Permiso).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Permiso)
            .where(*filtros)
            .order_by(Permiso.codigo)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[PermisoResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{permiso_id}", response_model=PermisoResponse, summary="Detalle de permiso")
async def obtener_permiso(
    permiso_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> PermisoResponse:
    return _respuesta(await obtener_o_404(session, Permiso, permiso_id, "Permiso"))


@router.post(
    "",
    response_model=PermisoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear permiso",
)
async def crear_permiso(
    body: PermisoCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> PermisoResponse:
    await verificar_unico(session, Permiso, "codigo", body.codigo)
    permiso = Permiso(**body.model_dump())
    session.add(permiso)
    await session.commit()
    await session.refresh(permiso)
    return _respuesta(permiso)


@router.patch("/{permiso_id}", response_model=PermisoResponse, summary="Actualizar permiso")
async def actualizar_permiso(
    permiso_id: uuid.UUID,
    body: PermisoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> PermisoResponse:
    permiso = await obtener_o_404(session, Permiso, permiso_id, "Permiso")

    # `null` = sin cambio (contrato de PermisoUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    for campo, valor in datos.items():
        setattr(permiso, campo, valor)

    await session.commit()
    await session.refresh(permiso)
    return _respuesta(permiso)


@router.delete("/{permiso_id}", summary="Eliminar permiso (solo sin matriz)")
async def eliminar_permiso(
    permiso_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
):
    permiso = await obtener_o_404(session, Permiso, permiso_id, "Permiso")

    enlaces = (
        await session.execute(
            select(func.count())
            .select_from(TareaPermiso)
            .where(TareaPermiso.permiso_id == permiso.id)
        )
    ).scalar_one()
    if enlaces:
        raise HasHistoryError(
            "Permiso",
            f"No se puede eliminar el permiso '{permiso.codigo}': está concedido en {enlaces} "
            "tarea(s) de la matriz.",
        )

    await session.delete(permiso)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
