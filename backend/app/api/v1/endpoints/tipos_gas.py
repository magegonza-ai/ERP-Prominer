"""
Endpoints del catálogo de tipos de gas (ETAPA 3.1).

Dominio RBAC: **TAREA_29** (administrar catálogos). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular.

DELETE /tipos-gas/{id} solo elimina físicamente un tipo de gas sin
referencias (cilindros, órdenes/detalles de trabajo); con historial → 409
HAS_HISTORY (y en su lugar se inactiva con PATCH /tipos-gas/{id}/estado).
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
from app.models import Cilindro, DetalleOrden, OrdenTrabajo, TipoGas, Usuario
from app.schemas.catalogos import (
    TipoGasCreate,
    TipoGasEstadoUpdate,
    TipoGasResponse,
    TipoGasUpdate,
)
from app.schemas.common import Pagina

router = APIRouter(tags=["Catálogos — tipos de gas"])

# Guard RBAC por acción (dominio TAREA_29: catálogos).
_LEER = RequireTaskPermission("TAREA_29", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_29", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_29", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_29", "PERM_07")

_ESTADOS = ("ACTIVO", "INACTIVO")


def _respuesta(tipo_gas: TipoGas) -> TipoGasResponse:
    return TipoGasResponse.model_validate(tipo_gas, from_attributes=True)


@router.get("", response_model=Pagina[TipoGasResponse], summary="Listar tipos de gas")
async def listar_tipos_gas(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    estado: str | None = Query(None, description="Filtro exacto por estado."),
    q: str | None = Query(None, max_length=100, description="Contiene en código o nombre."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[TipoGasResponse]:
    filtros = []
    if estado:
        filtros.append(TipoGas.estado == estado)
    if q:
        patron = f"%{q}%"
        filtros.append(or_(TipoGas.codigo.ilike(patron), TipoGas.nombre.ilike(patron)))

    total = (
        await session.execute(select(func.count()).select_from(TipoGas).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(TipoGas)
            .where(*filtros)
            .order_by(TipoGas.codigo)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[TipoGasResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{tipo_gas_id}", response_model=TipoGasResponse, summary="Detalle de tipo de gas")
async def obtener_tipo_gas(
    tipo_gas_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> TipoGasResponse:
    return _respuesta(await obtener_o_404(session, TipoGas, tipo_gas_id, "Tipo de gas"))


@router.post(
    "",
    response_model=TipoGasResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear tipo de gas",
)
async def crear_tipo_gas(
    body: TipoGasCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> TipoGasResponse:
    await verificar_unico(session, TipoGas, "codigo", body.codigo)
    tipo_gas = TipoGas(**body.model_dump())
    session.add(tipo_gas)
    await session.commit()
    await session.refresh(tipo_gas)
    return _respuesta(tipo_gas)


@router.patch("/{tipo_gas_id}", response_model=TipoGasResponse, summary="Actualizar tipo de gas")
async def actualizar_tipo_gas(
    tipo_gas_id: uuid.UUID,
    body: TipoGasUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> TipoGasResponse:
    tipo_gas = await obtener_o_404(session, TipoGas, tipo_gas_id, "Tipo de gas")

    # `null` = sin cambio (contrato de TipoGasUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    for campo, valor in datos.items():
        setattr(tipo_gas, campo, valor)

    await session.commit()
    await session.refresh(tipo_gas)
    return _respuesta(tipo_gas)


@router.patch(
    "/{tipo_gas_id}/estado",
    response_model=TipoGasResponse,
    summary="Cambiar estado de tipo de gas",
)
async def cambiar_estado(
    tipo_gas_id: uuid.UUID,
    body: TipoGasEstadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> TipoGasResponse:
    tipo_gas = await obtener_o_404(session, TipoGas, tipo_gas_id, "Tipo de gas")
    if tipo_gas.estado == body.estado:
        raise InvalidStateTransition(
            "Tipo de gas",
            tipo_gas.estado,
            body.estado,
            allowed=[e for e in _ESTADOS if e != tipo_gas.estado],
        )
    tipo_gas.estado = body.estado
    await session.commit()
    await session.refresh(tipo_gas)
    return _respuesta(tipo_gas)


@router.delete("/{tipo_gas_id}", summary="Eliminar tipo de gas (solo sin historial)")
async def eliminar_tipo_gas(
    tipo_gas_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
):
    """Borrado físico condicionado a cero referencias; con historial → 409."""
    tipo_gas = await obtener_o_404(session, TipoGas, tipo_gas_id, "Tipo de gas")

    for model in (Cilindro, OrdenTrabajo, DetalleOrden):
        enlaces = (
            await session.execute(
                select(func.count()).select_from(model).where(model.tipo_gas_id == tipo_gas.id)
            )
        ).scalar_one()
        if enlaces:
            raise HasHistoryError(
                "Tipo de gas",
                f"No se puede eliminar el tipo de gas '{tipo_gas.codigo}': tiene {enlaces} "
                f"registro(s) asociados en '{model.__tablename__}'. "
                "Inactívelo con PATCH /tipos-gas/{id}/estado.",
            )

    await session.delete(tipo_gas)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
