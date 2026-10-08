"""
Endpoints de ubicaciones (ETAPA 4.2, subetapa de cilindros).

Dominio RBAC: **TAREA_29** (administrar catálogos — la unidad de negocio
es «Catálogo de ubicaciones físicas/lógicas»). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular.

`codigo` único e inmutable (409 al crear, fuera del Update → 400);
`tipo` (`INTERNA/CLIENTE/EXTERNA/FUERA`) mutable; estados
`ACTIVA/INACTIVA`. DELETE /ubicaciones/{id} solo elimina físicamente una
ubicación sin referencias (cilindro.ubicacion_actual_id,
movimiento.ubicacion_origen_id/destino_id); con historial → 409
HAS_HISTORY (y en su lugar se inactiva con PATCH /ubicaciones/{id}/estado).
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
from app.models import Cilindro, Movimiento, Ubicacion, Usuario
from app.schemas.common import Pagina
from app.schemas.ubicaciones import (
    TipoUbicacion,
    UbicacionCreate,
    UbicacionEstadoUpdate,
    UbicacionResponse,
    UbicacionUpdate,
)

router = APIRouter(tags=["Cilindros — ubicaciones"])

# Guard RBAC por acción (dominio TAREA_29: catálogos).
_LEER = RequireTaskPermission("TAREA_29", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_29", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_29", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_29", "PERM_07")

_ESTADOS = ("ACTIVA", "INACTIVA")

# Las 3 tablas con FK entrante a ubicación (todas las del metadata).
_REFERENCIAS_UBICACION = (
    (Cilindro, Cilindro.ubicacion_actual_id),
    (Movimiento, Movimiento.ubicacion_origen_id),
    (Movimiento, Movimiento.ubicacion_destino_id),
)


def _respuesta(ubicacion: Ubicacion) -> UbicacionResponse:
    return UbicacionResponse.model_validate(ubicacion, from_attributes=True)


@router.get("", response_model=Pagina[UbicacionResponse], summary="Listar ubicaciones")
async def listar_ubicaciones(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    q: str | None = Query(None, max_length=100, description="Contiene en código o nombre."),
    tipo: TipoUbicacion | None = Query(None, description="Filtro exacto por tipo."),
    estado: str | None = Query(None, description="Filtro exacto por estado."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[UbicacionResponse]:
    filtros = []
    if tipo:
        filtros.append(Ubicacion.tipo == tipo)
    if estado:
        filtros.append(Ubicacion.estado == estado)
    if q:
        patron = f"%{q}%"
        filtros.append(or_(Ubicacion.codigo.ilike(patron), Ubicacion.nombre.ilike(patron)))

    total = (
        await session.execute(select(func.count()).select_from(Ubicacion).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Ubicacion)
            .where(*filtros)
            .order_by(Ubicacion.orden_visual, Ubicacion.codigo)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[UbicacionResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{ubicacion_id}", response_model=UbicacionResponse, summary="Detalle de ubicación")
async def obtener_ubicacion(
    ubicacion_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> UbicacionResponse:
    return _respuesta(await obtener_o_404(session, Ubicacion, ubicacion_id, "Ubicación"))


@router.post(
    "",
    response_model=UbicacionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear ubicación",
)
async def crear_ubicacion(
    body: UbicacionCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> UbicacionResponse:
    await verificar_unico(session, Ubicacion, "codigo", body.codigo)
    ubicacion = Ubicacion(**body.model_dump())
    session.add(ubicacion)
    await session.commit()
    await session.refresh(ubicacion)
    return _respuesta(ubicacion)


@router.patch("/{ubicacion_id}", response_model=UbicacionResponse, summary="Actualizar ubicación")
async def actualizar_ubicacion(
    ubicacion_id: uuid.UUID,
    body: UbicacionUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> UbicacionResponse:
    ubicacion = await obtener_o_404(session, Ubicacion, ubicacion_id, "Ubicación")

    # `null` = sin cambio (contrato de UbicacionUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    for campo, valor in datos.items():
        setattr(ubicacion, campo, valor)

    await session.commit()
    await session.refresh(ubicacion)
    return _respuesta(ubicacion)


@router.patch(
    "/{ubicacion_id}/estado",
    response_model=UbicacionResponse,
    summary="Cambiar estado de ubicación",
)
async def cambiar_estado(
    ubicacion_id: uuid.UUID,
    body: UbicacionEstadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> UbicacionResponse:
    ubicacion = await obtener_o_404(session, Ubicacion, ubicacion_id, "Ubicación")
    if ubicacion.estado == body.estado:
        raise InvalidStateTransition(
            "Ubicación",
            ubicacion.estado,
            body.estado,
            allowed=[e for e in _ESTADOS if e != ubicacion.estado],
        )
    ubicacion.estado = body.estado
    await session.commit()
    await session.refresh(ubicacion)
    return _respuesta(ubicacion)


@router.delete("/{ubicacion_id}", summary="Eliminar ubicación (solo sin historial)")
async def eliminar_ubicacion(
    ubicacion_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
):
    """Borrado físico condicionado a cero referencias; con historial → 409."""
    ubicacion = await obtener_o_404(session, Ubicacion, ubicacion_id, "Ubicación")

    for model, columna in _REFERENCIAS_UBICACION:
        enlaces = (
            await session.execute(
                select(func.count()).select_from(model).where(columna == ubicacion.id)
            )
        ).scalar_one()
        if enlaces:
            raise HasHistoryError(
                "Ubicación",
                f"No se puede eliminar la ubicación '{ubicacion.codigo}': tiene {enlaces} "
                f"registro(s) asociados en '{model.__tablename__}'. Inactívela con "
                "PATCH /ubicaciones/{id}/estado.",
            )

    await session.delete(ubicacion)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
