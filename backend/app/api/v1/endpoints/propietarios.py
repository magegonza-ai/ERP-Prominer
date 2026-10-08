"""
Endpoints de propietarios de cilindros (ETAPA 4.1).

Dominio RBAC: **TAREA_02** (registrar propietarios). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular.

Reglas: `tipo` (`CLIENTE/AGAS/EMPRESA_EXTERNA`) y `rut` inmutables;
unicidad parcial `(rut, tipo)` solo para `tipo ≠ CLIENTE` (índice
`uk_propietario_rut_tipo`); `tipo=CLIENTE` exige `cliente_id` con cliente
existente y libre (índice `uk_propietario_cliente` → 409), mientras los
otros tipos no admiten vínculo. Estados `ACTIVO/INACTIVO/BLOQUEADO`.
DELETE físico solo con cero referencias (cilindros, recepciones,
entregas, cambios de propietario, presupuestos) → si no 409 HAS_HISTORY.
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
)
from app.core.exceptions import (
    DuplicateValue,
    HasHistoryError,
    InvalidStateTransition,
    NotFound,
    ValidationError,
)
from app.models import (
    CambioPropietario,
    Cilindro,
    Cliente,
    Entrega,
    Presupuesto,
    Propietario,
    Recepcion,
    Usuario,
)
from app.schemas.common import Pagina
from app.schemas.propietarios import (
    PropietarioCreate,
    PropietarioEstadoUpdate,
    PropietarioResponse,
    PropietarioUpdate,
)

router = APIRouter(tags=["Maestros — propietarios"])

# Guard RBAC por acción (dominio TAREA_02: registrar propietarios).
_LEER = RequireTaskPermission("TAREA_02", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_02", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_02", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_02", "PERM_07")

_ESTADOS = ("ACTIVO", "INACTIVO", "BLOQUEADO")

# (modelo, columna) → FKs entrantes hacia `propietario` que impiden el borrado.
_REFERENCIAS_PROPIETARIO = (
    (Cilindro, "propietario_id"),
    (Recepcion, "propietario_id"),
    (Entrega, "propietario_id"),
    (CambioPropietario, "propietario_anterior_id"),
    (CambioPropietario, "propietario_nuevo_id"),
    (Presupuesto, "propietario_id"),
)


def _respuesta(propietario: Propietario) -> PropietarioResponse:
    return PropietarioResponse.model_validate(propietario, from_attributes=True)


async def _verificar_rut_unico(session: SessionDep, rut: str, tipo: str) -> None:
    """Unicidad parcial `(rut, tipo)` — el índice solo aplica para `tipo ≠ CLIENTE`."""
    if tipo == "CLIENTE":
        return
    existente = (
        await session.execute(
            select(Propietario.id)
            .where(Propietario.rut == rut, Propietario.tipo == tipo)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existente is not None:
        raise DuplicateValue("rut", rut)


async def _validar_vinculo(
    session: SessionDep,
    tipo: str,
    cliente_id: uuid.UUID | None,
    propietario_id: uuid.UUID | None = None,
) -> None:
    """Reglas del vínculo `cliente_id` según `tipo` (con exclusión propio en PATCH)."""
    if tipo == "CLIENTE":
        if cliente_id is None:
            raise ValidationError(
                "Los propietarios de tipo CLIENTE deben indicar el cliente_id a vincular"
            )
        if await session.get(Cliente, cliente_id) is None:
            raise NotFound("Cliente", cliente_id)
        stmt = select(Propietario.id).where(Propietario.cliente_id == cliente_id)
        if propietario_id is not None:
            stmt = stmt.where(Propietario.id != propietario_id)
        if (await session.execute(stmt.limit(1))).scalar_one_or_none() is not None:
            raise DuplicateValue("cliente_id", str(cliente_id))
    elif cliente_id is not None:
        raise ValidationError(
            f"Los propietarios de tipo {tipo} no pueden vincular un cliente "
            "(cliente_id debe quedar vacío)"
        )


@router.get("", response_model=Pagina[PropietarioResponse], summary="Listar propietarios")
async def listar_propietarios(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    tipo: str | None = Query(None, description="Filtro exacto por tipo."),
    estado: str | None = Query(None, description="Filtro exacto por estado."),
    q: str | None = Query(None, max_length=100, description="Contiene en RUT o razón social."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[PropietarioResponse]:
    filtros = []
    if tipo:
        filtros.append(Propietario.tipo == tipo)
    if estado:
        filtros.append(Propietario.estado == estado)
    if q:
        patron = f"%{q}%"
        filtros.append(or_(Propietario.rut.ilike(patron), Propietario.razon_social.ilike(patron)))

    total = (
        await session.execute(select(func.count()).select_from(Propietario).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Propietario)
            .where(*filtros)
            .order_by(Propietario.razon_social)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[PropietarioResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{propietario_id}", response_model=PropietarioResponse, summary="Detalle de propietario")
async def obtener_propietario(
    propietario_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> PropietarioResponse:
    return _respuesta(await obtener_o_404(session, Propietario, propietario_id, "Propietario"))


@router.post(
    "",
    response_model=PropietarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear propietario",
)
async def crear_propietario(
    body: PropietarioCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> PropietarioResponse:
    await _verificar_rut_unico(session, body.rut, body.tipo)
    await _validar_vinculo(session, body.tipo, body.cliente_id)

    propietario = Propietario(**body.model_dump())
    session.add(propietario)
    await session.commit()
    await session.refresh(propietario)
    return _respuesta(propietario)


@router.patch("/{propietario_id}", response_model=PropietarioResponse, summary="Actualizar propietario")
async def actualizar_propietario(
    propietario_id: uuid.UUID,
    body: PropietarioUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> PropietarioResponse:
    propietario = await obtener_o_404(session, Propietario, propietario_id, "Propietario")

    # `null` = sin cambio (contrato de PropietarioUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    # El vínculo solo se valida cuando se intenta cambiar (la creación ya lo validó).
    if "cliente_id" in datos:
        await _validar_vinculo(session, propietario.tipo, datos["cliente_id"], propietario.id)

    for campo, valor in datos.items():
        setattr(propietario, campo, valor)
    await session.commit()
    await session.refresh(propietario)
    return _respuesta(propietario)


@router.patch(
    "/{propietario_id}/estado",
    response_model=PropietarioResponse,
    summary="Cambiar estado de propietario",
)
async def cambiar_estado(
    propietario_id: uuid.UUID,
    body: PropietarioEstadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> PropietarioResponse:
    propietario = await obtener_o_404(session, Propietario, propietario_id, "Propietario")
    if propietario.estado == body.estado:
        raise InvalidStateTransition(
            "Propietario",
            propietario.estado,
            body.estado,
            allowed=[e for e in _ESTADOS if e != propietario.estado],
        )
    propietario.estado = body.estado
    await session.commit()
    await session.refresh(propietario)
    return _respuesta(propietario)


@router.delete("/{propietario_id}", summary="Eliminar propietario (solo sin historial)")
async def eliminar_propietario(
    propietario_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
):
    """Borrado físico condicionado a cero referencias; con historial → 409."""
    propietario = await obtener_o_404(session, Propietario, propietario_id, "Propietario")

    for model, campo in _REFERENCIAS_PROPIETARIO:
        enlaces = (
            await session.execute(
                select(func.count())
                .select_from(model)
                .where(getattr(model, campo) == propietario.id)
            )
        ).scalar_one()
        if enlaces:
            raise HasHistoryError(
                "Propietario",
                f"No se puede eliminar el propietario '{propietario.rut}': tiene {enlaces} "
                f"registro(s) asociados en '{model.__tablename__}'. Inactívelo con PATCH "
                f"/propietarios/{propietario_id}/estado.",
            )

    await session.delete(propietario)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
