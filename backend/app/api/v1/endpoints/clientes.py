"""
Endpoints de clientes y receptores autorizados (ETAPA 4.1).

Dominio RBAC: **TAREA_01** (registrar clientes). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular.

`rut` es único e inmutable. Estados `ACTIVO/INACTIVO/BLOQUEADO` (misma
transición → 409; fuera de `Literal` → 422). DELETE físico solo con cero
referencias externas (propietario, recepciones, entregas, presupuestos)
→ si no 409 HAS_HISTORY; los receptores autorizados —sub-recurso
anidado— se eliminan en cascada con su cliente (relación
`delete-orphan` del modelo). El receptor queda acotado a su cliente
(detalle de otro cliente → 404), registra `autorizado_por` = usuario
autenticado y no admite `vigente_hasta` anterior a `fecha_autorizacion`.
"""

from __future__ import annotations

import uuid
from datetime import date

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
    HasHistoryError,
    InvalidStateTransition,
    NotFound,
    ValidationError,
)
from app.models import (
    Cliente,
    ClienteReceptorAutorizado,
    Entrega,
    Presupuesto,
    Propietario,
    Recepcion,
    Usuario,
)
from app.schemas.clientes import (
    ClienteCreate,
    ClienteEstadoUpdate,
    ClienteResponse,
    ClienteUpdate,
    ReceptorAutorizadoCreate,
    ReceptorAutorizadoEstadoUpdate,
    ReceptorAutorizadoResponse,
    ReceptorAutorizadoUpdate,
)
from app.schemas.common import Pagina

router = APIRouter(tags=["Maestros — clientes"])

# Guard RBAC por acción (dominio TAREA_01: registrar clientes).
_LEER = RequireTaskPermission("TAREA_01", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_01", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_01", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_01", "PERM_07")

_ESTADOS = ("ACTIVO", "INACTIVO", "BLOQUEADO")
_ESTADOS_RECEPTOR = ("VIGENTE", "VENCIDO", "REVOCADO")

# (modelo, columna) → FKs entrantes hacia `cliente` que impiden el borrado.
_REFERENCIAS_CLIENTE = (
    (Propietario, "cliente_id"),
    (Recepcion, "cliente_entrega_id"),
    (Recepcion, "cliente_solicita_id"),
    (Entrega, "cliente_recibe_id"),
    (Presupuesto, "cliente_id"),
)


def _respuesta_cliente(cliente: Cliente) -> ClienteResponse:
    return ClienteResponse.model_validate(cliente, from_attributes=True)


def _respuesta_receptor(receptor: ClienteReceptorAutorizado) -> ReceptorAutorizadoResponse:
    return ReceptorAutorizadoResponse.model_validate(receptor, from_attributes=True)


def _validar_vigencia(vigente_hasta: date | None, fecha_autorizacion: date) -> None:
    if vigente_hasta is not None and vigente_hasta < fecha_autorizacion:
        raise ValidationError(
            f"Vigencia inválida: 'vigente_hasta' ({vigente_hasta}) no puede ser "
            f"anterior a la fecha de autorización ({fecha_autorizacion})"
        )


async def _buscar_receptor(
    session: SessionDep, cliente_id: uuid.UUID, receptor_id: uuid.UUID
) -> ClienteReceptorAutorizado:
    """Detalle acotado al cliente: de otro cliente → 404 (no 403)."""
    receptor = (
        await session.execute(
            select(ClienteReceptorAutorizado).where(
                ClienteReceptorAutorizado.id == receptor_id,
                ClienteReceptorAutorizado.cliente_id == cliente_id,
            )
        )
    ).scalar_one_or_none()
    if receptor is None:
        raise NotFound("Receptor autorizado", receptor_id)
    return receptor


# ============================================================
# CLIENTES
# ============================================================


@router.get("", response_model=Pagina[ClienteResponse], summary="Listar clientes")
async def listar_clientes(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    estado: str | None = Query(None, description="Filtro exacto por estado."),
    q: str | None = Query(None, max_length=100, description="Contiene en RUT o razón social."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[ClienteResponse]:
    filtros = []
    if estado:
        filtros.append(Cliente.estado == estado)
    if q:
        patron = f"%{q}%"
        filtros.append(or_(Cliente.rut.ilike(patron), Cliente.razon_social.ilike(patron)))

    total = (
        await session.execute(select(func.count()).select_from(Cliente).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Cliente)
            .where(*filtros)
            .order_by(Cliente.razon_social)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[ClienteResponse](
        items=[_respuesta_cliente(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{cliente_id}", response_model=ClienteResponse, summary="Detalle de cliente")
async def obtener_cliente(
    cliente_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> ClienteResponse:
    return _respuesta_cliente(await obtener_o_404(session, Cliente, cliente_id, "Cliente"))


@router.post(
    "",
    response_model=ClienteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear cliente",
)
async def crear_cliente(
    body: ClienteCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> ClienteResponse:
    await verificar_unico(session, Cliente, "rut", body.rut)

    cliente = Cliente(**body.model_dump())
    session.add(cliente)
    await session.commit()
    await session.refresh(cliente)
    return _respuesta_cliente(cliente)


@router.patch("/{cliente_id}", response_model=ClienteResponse, summary="Actualizar cliente")
async def actualizar_cliente(
    cliente_id: uuid.UUID,
    body: ClienteUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> ClienteResponse:
    cliente = await obtener_o_404(session, Cliente, cliente_id, "Cliente")

    # `null` = sin cambio (contrato de ClienteUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    for campo, valor in datos.items():
        setattr(cliente, campo, valor)
    await session.commit()
    await session.refresh(cliente)
    return _respuesta_cliente(cliente)


@router.patch("/{cliente_id}/estado", response_model=ClienteResponse, summary="Cambiar estado de cliente")
async def cambiar_estado(
    cliente_id: uuid.UUID,
    body: ClienteEstadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> ClienteResponse:
    cliente = await obtener_o_404(session, Cliente, cliente_id, "Cliente")
    if cliente.estado == body.estado:
        raise InvalidStateTransition(
            "Cliente",
            cliente.estado,
            body.estado,
            allowed=[e for e in _ESTADOS if e != cliente.estado],
        )
    cliente.estado = body.estado
    await session.commit()
    await session.refresh(cliente)
    return _respuesta_cliente(cliente)


@router.delete("/{cliente_id}", summary="Eliminar cliente (solo sin historial)")
async def eliminar_cliente(
    cliente_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
):
    """Borrado físico condicionado; los receptores autorizados se van en cascada."""
    cliente = await obtener_o_404(session, Cliente, cliente_id, "Cliente")

    for model, campo in _REFERENCIAS_CLIENTE:
        enlaces = (
            await session.execute(
                select(func.count()).select_from(model).where(getattr(model, campo) == cliente.id)
            )
        ).scalar_one()
        if enlaces:
            raise HasHistoryError(
                "Cliente",
                f"No se puede eliminar el cliente '{cliente.rut}': tiene {enlaces} registro(s) "
                f"asociados en '{model.__tablename__}'. Inactívelo con PATCH "
                f"/clientes/{cliente_id}/estado.",
            )

    await session.delete(cliente)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# RECEPTORES AUTORIZADOS (sub-recurso anidado)
# ============================================================


@router.get(
    "/{cliente_id}/receptores-autorizados",
    response_model=Pagina[ReceptorAutorizadoResponse],
    summary="Listar receptores autorizados del cliente",
)
async def listar_receptores(
    cliente_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    estado: str | None = Query(None, description="Filtro exacto por estado."),
    q: str | None = Query(None, max_length=100, description="Contiene en nombre o RUT."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[ReceptorAutorizadoResponse]:
    await obtener_o_404(session, Cliente, cliente_id, "Cliente")
    filtros = [ClienteReceptorAutorizado.cliente_id == cliente_id]
    if estado:
        filtros.append(ClienteReceptorAutorizado.estado == estado)
    if q:
        patron = f"%{q}%"
        filtros.append(
            or_(ClienteReceptorAutorizado.nombre.ilike(patron), ClienteReceptorAutorizado.rut.ilike(patron))
        )

    total = (
        await session.execute(
            select(func.count()).select_from(ClienteReceptorAutorizado).where(*filtros)
        )
    ).scalar_one()
    filas = (
        await session.execute(
            select(ClienteReceptorAutorizado)
            .where(*filtros)
            .order_by(ClienteReceptorAutorizado.nombre)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[ReceptorAutorizadoResponse](
        items=[_respuesta_receptor(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get(
    "/{cliente_id}/receptores-autorizados/{receptor_id}",
    response_model=ReceptorAutorizadoResponse,
    summary="Detalle de receptor autorizado",
)
async def obtener_receptor(
    cliente_id: uuid.UUID,
    receptor_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> ReceptorAutorizadoResponse:
    return _respuesta_receptor(await _buscar_receptor(session, cliente_id, receptor_id))


@router.post(
    "/{cliente_id}/receptores-autorizados",
    response_model=ReceptorAutorizadoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear receptor autorizado",
)
async def crear_receptor(
    cliente_id: uuid.UUID,
    body: ReceptorAutorizadoCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> ReceptorAutorizadoResponse:
    await obtener_o_404(session, Cliente, cliente_id, "Cliente")
    hoy = date.today()
    _validar_vigencia(body.vigente_hasta, hoy)

    receptor = ClienteReceptorAutorizado(
        **body.model_dump(),
        cliente_id=cliente_id,
        autorizado_por=user.id,
    )
    session.add(receptor)
    await session.commit()
    await session.refresh(receptor)
    return _respuesta_receptor(receptor)


@router.patch(
    "/{cliente_id}/receptores-autorizados/{receptor_id}",
    response_model=ReceptorAutorizadoResponse,
    summary="Actualizar receptor autorizado",
)
async def actualizar_receptor(
    cliente_id: uuid.UUID,
    receptor_id: uuid.UUID,
    body: ReceptorAutorizadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> ReceptorAutorizadoResponse:
    receptor = await _buscar_receptor(session, cliente_id, receptor_id)

    # `null` = sin cambio (contrato de ReceptorAutorizadoUpdate).
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    if "vigente_hasta" in datos:
        _validar_vigencia(datos["vigente_hasta"], receptor.fecha_autorizacion)

    for campo, valor in datos.items():
        setattr(receptor, campo, valor)
    await session.commit()
    await session.refresh(receptor)
    return _respuesta_receptor(receptor)


@router.patch(
    "/{cliente_id}/receptores-autorizados/{receptor_id}/estado",
    response_model=ReceptorAutorizadoResponse,
    summary="Cambiar estado de receptor autorizado",
)
async def cambiar_estado_receptor(
    cliente_id: uuid.UUID,
    receptor_id: uuid.UUID,
    body: ReceptorAutorizadoEstadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> ReceptorAutorizadoResponse:
    receptor = await _buscar_receptor(session, cliente_id, receptor_id)
    if receptor.estado == body.estado:
        raise InvalidStateTransition(
            "Receptor autorizado",
            receptor.estado,
            body.estado,
            allowed=[e for e in _ESTADOS_RECEPTOR if e != receptor.estado],
        )
    receptor.estado = body.estado
    await session.commit()
    await session.refresh(receptor)
    return _respuesta_receptor(receptor)


@router.delete(
    "/{cliente_id}/receptores-autorizados/{receptor_id}",
    summary="Eliminar receptor autorizado",
)
async def eliminar_receptor(
    cliente_id: uuid.UUID,
    receptor_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
):
    """Borrado físico: nada referencia a los receptores (FKs solo salientes)."""
    receptor = await _buscar_receptor(session, cliente_id, receptor_id)

    await session.delete(receptor)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
