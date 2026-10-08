"""
Endpoints del catálogo de formas de pago (ETAPA 3.1).

Dominio RBAC: **TAREA_29** (administrar catálogos). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular.

DELETE /formas-pago/{id} solo elimina físicamente una forma de pago sin
referencias (pagos, documentos comerciales); con historial → 409
HAS_HISTORY (y en su lugar se inactiva con PATCH /formas-pago/{id}/estado).
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
from app.models import DocumentoComercial, FormaPago, Pago, Usuario
from app.schemas.catalogos import (
    FormaPagoCreate,
    FormaPagoEstadoUpdate,
    FormaPagoResponse,
    FormaPagoUpdate,
)
from app.schemas.common import Pagina

router = APIRouter(tags=["Catálogos — formas de pago"])

# Guard RBAC por acción (dominio TAREA_29: catálogos).
_LEER = RequireTaskPermission("TAREA_29", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_29", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_29", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_29", "PERM_07")

_ESTADOS = ("ACTIVA", "INACTIVA")


def _respuesta(forma_pago: FormaPago) -> FormaPagoResponse:
    return FormaPagoResponse.model_validate(forma_pago, from_attributes=True)


@router.get("", response_model=Pagina[FormaPagoResponse], summary="Listar formas de pago")
async def listar_formas_pago(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    estado: str | None = Query(None, description="Filtro exacto por estado."),
    q: str | None = Query(None, max_length=100, description="Contiene en código o nombre."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[FormaPagoResponse]:
    filtros = []
    if estado:
        filtros.append(FormaPago.estado == estado)
    if q:
        patron = f"%{q}%"
        filtros.append(or_(FormaPago.codigo.ilike(patron), FormaPago.nombre.ilike(patron)))

    total = (
        await session.execute(select(func.count()).select_from(FormaPago).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(FormaPago)
            .where(*filtros)
            .order_by(FormaPago.codigo)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[FormaPagoResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{forma_pago_id}", response_model=FormaPagoResponse, summary="Detalle de forma de pago")
async def obtener_forma_pago(
    forma_pago_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> FormaPagoResponse:
    return _respuesta(await obtener_o_404(session, FormaPago, forma_pago_id, "Forma de pago"))


@router.post(
    "",
    response_model=FormaPagoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear forma de pago",
)
async def crear_forma_pago(
    body: FormaPagoCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> FormaPagoResponse:
    await verificar_unico(session, FormaPago, "codigo", body.codigo)
    forma_pago = FormaPago(**body.model_dump())
    session.add(forma_pago)
    await session.commit()
    await session.refresh(forma_pago)
    return _respuesta(forma_pago)


@router.patch(
    "/{forma_pago_id}", response_model=FormaPagoResponse, summary="Actualizar forma de pago"
)
async def actualizar_forma_pago(
    forma_pago_id: uuid.UUID,
    body: FormaPagoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> FormaPagoResponse:
    forma_pago = await obtener_o_404(session, FormaPago, forma_pago_id, "Forma de pago")

    # `null` = sin cambio (contrato de FormaPagoUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    for campo, valor in datos.items():
        setattr(forma_pago, campo, valor)

    await session.commit()
    await session.refresh(forma_pago)
    return _respuesta(forma_pago)


@router.patch(
    "/{forma_pago_id}/estado",
    response_model=FormaPagoResponse,
    summary="Cambiar estado de forma de pago",
)
async def cambiar_estado(
    forma_pago_id: uuid.UUID,
    body: FormaPagoEstadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> FormaPagoResponse:
    forma_pago = await obtener_o_404(session, FormaPago, forma_pago_id, "Forma de pago")
    if forma_pago.estado == body.estado:
        raise InvalidStateTransition(
            "Forma de pago",
            forma_pago.estado,
            body.estado,
            allowed=[e for e in _ESTADOS if e != forma_pago.estado],
        )
    forma_pago.estado = body.estado
    await session.commit()
    await session.refresh(forma_pago)
    return _respuesta(forma_pago)


@router.delete("/{forma_pago_id}", summary="Eliminar forma de pago (solo sin historial)")
async def eliminar_forma_pago(
    forma_pago_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
):
    """Borrado físico condicionado a cero referencias; con historial → 409."""
    forma_pago = await obtener_o_404(session, FormaPago, forma_pago_id, "Forma de pago")

    for model in (Pago, DocumentoComercial):
        enlaces = (
            await session.execute(
                select(func.count())
                .select_from(model)
                .where(model.forma_pago_id == forma_pago.id)
            )
        ).scalar_one()
        if enlaces:
            raise HasHistoryError(
                "Forma de pago",
                f"No se puede eliminar la forma de pago '{forma_pago.codigo}': tiene "
                f"{enlaces} registro(s) asociados en '{model.__tablename__}'. "
                "Inactívela con PATCH /formas-pago/{id}/estado.",
            )

    await session.delete(forma_pago)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
