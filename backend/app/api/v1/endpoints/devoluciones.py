"""
Endpoints de devoluciones de cilindros (ETAPA 5.6).

Colección `/devoluciones` (dominio RBAC TAREA_19 «Registrar devoluciones»):

    | acción                          | RBAC                  |
    |---------------------------------|-----------------------|
    | leer (listar/detalle)           | TAREA_19 + PERM_01    |
    | crear (REGISTRADA)              | TAREA_19 + PERM_02    |
    | editar campos descriptivos      | TAREA_19 + PERM_03    |
    | → ANULADA                       | TAREA_19 + PERM_07    |

Ciclo de vida (solo renta, misma/inválida → 409 con `allowed_states`):

    REGISTRADA → ANULADA   (terminal)

Cada cilindro debe estar `ENTREGADO` (retorna a AGAS de una entrega), no
repetirse y no figurar en otra devolución activa (409 `DUPLICATE_VALUE`). Al
registrar la devolución se emite un `Movimiento` por cilindro **en la misma
transacción** (D31) que lo deja en `RECIBIDO` (con `usuario_recibe_id`) y le
cambia la ubicación si se indica `ubicacion_destino_id`. Anular **no**
revierte la traza: el registro se invalida administrativamente, pero el
cilindro ya regresó físicamente a AGAS.

El `DELETE` de la cabecera no se expone (405): una devolución se anula por
estado. `documento_id`, la valorización y los cargos por daño son de ETAPA
posterior.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

# noqa en TC001: FastAPI y las firmas resuelven estos nombres en runtime.
from app.api.deps import (  # noqa: TC001
    CurrentUser,
    RequireTaskPermission,
    SessionDep,
)
from app.core.exceptions import (
    DuplicateValue,
    InvalidStateTransition,
    NotFound,
    ValidationError,
)
from app.core.numeracion import siguiente_numero
from app.core.permissions import require_permission, require_task
from app.models import (
    Cilindro,
    Cliente,
    Devolucion,
    DevolucionDetalle,
    Entrega,
    Movimiento,
    Ubicacion,
)
from app.schemas.common import Pagina
from app.schemas.devoluciones import (
    DevolucionCreate,
    DevolucionEstadoUpdate,
    DevolucionResponse,
    DevolucionUpdate,
    EstadoDevolucion,
)

router = APIRouter(tags=["Operaciones — devoluciones"])

# TAREA_19 «Registrar devoluciones» (matriz sembrada [0,1,2,7] =
# PERM_01/02/03/07): ni aprobar ni cerrar, solo registrar y anular.
_LEER = RequireTaskPermission("TAREA_19", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_19", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_19", "PERM_03")

# Estados de la devolución (solo un camino terminal).
_ESTADOS_DEVOLUCION = ("REGISTRADA", "ANULADA")

# Devueltos (activas): cilindros ligados a un registro de devolución vigente.
_ESTADOS_DEVOLUCION_ACTIVA = ("REGISTRADA",)

# Prefijo del correlativo (D30).
_PREFIJO_NUMERO = "DEV"

# Carga eager de la cabecera + detalles + cilindros (evita lazy loads async).
_CARGA_DEVOLUCION = (
    selectinload(Devolucion.detalles)
    .selectinload(DevolucionDetalle.cilindro)
    .selectinload(Cilindro.tipo_gas),
    selectinload(Devolucion.cliente_devuelve),
    selectinload(Devolucion.entrega),
    selectinload(Devolucion.ubicacion_destino),
)


def _respuesta(devolucion: Devolucion) -> DevolucionResponse:
    return DevolucionResponse.model_validate(devolucion, from_attributes=True)


async def _obtener_devolucion(session: SessionDep, devolucion_id: uuid.UUID) -> Devolucion:
    """
    Devolución con sus relaciones eager (si no existe → 404).

    `populate_existing` re-lee del registro actual aunque la instancia ya esté
    en el identity map (la sesión es `expire_on_commit=False`).
    """
    stmt = (
        select(Devolucion)
        .execution_options(populate_existing=True)
        .options(*_CARGA_DEVOLUCION)
        .where(Devolucion.id == devolucion_id)
    )
    devolucion = (await session.execute(stmt)).scalar_one_or_none()
    if devolucion is None:
        raise NotFound("Devolución", devolucion_id)
    return devolucion


async def _validar_cliente_devuelve(session: SessionDep, cliente_id: uuid.UUID) -> Cliente:
    cliente = await session.get(Cliente, cliente_id)
    if cliente is None:
        raise NotFound("Cliente", cliente_id)
    if cliente.estado != "ACTIVO":
        raise ValidationError(f"El cliente '{cliente.razon_social}' no está ACTIVO")
    return cliente


async def _validar_ubicacion_destino(session: SessionDep, ubicacion_id: uuid.UUID | None) -> None:
    if ubicacion_id is None:
        return
    ubicacion = await session.get(Ubicacion, ubicacion_id)
    if ubicacion is None:
        raise NotFound("Ubicación", ubicacion_id)


async def _validar_detalles(session: SessionDep, detalles) -> list:
    """
    Valida cada cilindro: existe (404), está `ENTREGADO` (400) y no está en
    otra devolución activa (409). Devuelve los `Cilindro` en el mismo orden.
    """
    vistos: set[uuid.UUID] = set()
    validados: list = []
    for detalle in detalles:
        if detalle.cilindro_id in vistos:
            raise DuplicateValue("cilindro_id", str(detalle.cilindro_id))
        vistos.add(detalle.cilindro_id)

        cilindro = await session.get(Cilindro, detalle.cilindro_id)
        if cilindro is None:
            raise NotFound("Cilindro", detalle.cilindro_id)

        if cilindro.estado_operativo != "ENTREGADO":
            raise ValidationError(
                f"El cilindro '{cilindro.codigo_interno}' está '{cilindro.estado_operativo}': "
                "solo se devuelven cilindros en estado ENTREGADO"
            )

        stmt = (
            select(DevolucionDetalle.id)
            .join(Devolucion, Devolucion.id == DevolucionDetalle.devolucion_id)
            .where(
                DevolucionDetalle.cilindro_id == cilindro.id,
                Devolucion.estado.in_(_ESTADOS_DEVOLUCION_ACTIVA),
            )
            .limit(1)
        )
        ocupado = (await session.execute(stmt)).scalar_one_or_none()
        if ocupado is not None:
            raise DuplicateValue("cilindro_id", str(cilindro.id))

        validados.append(cilindro)
    return validados


# ============================================================
# DEVOLUCIONES (cabecera)
# ============================================================


@router.get("", response_model=Pagina[DevolucionResponse], summary="Listar devoluciones")
async def listar_devoluciones(
    session: SessionDep,
    user=Depends(_LEER),
    estado: EstadoDevolucion | None = Query(None, description="Filtro exacto por estado."),
    cliente_devuelve_id: uuid.UUID | None = Query(None),
    motivo: str | None = Query(None, description="Filtro exacto por motivo."),
    desde: datetime | None = Query(None, description="Fecha de la devolución desde (inclusive)."),
    hasta: datetime | None = Query(None, description="Fecha de la devolución hasta (inclusive)."),
    q: str | None = Query(None, max_length=100, description="Contiene en el número."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
):
    filtros = []
    if estado:
        filtros.append(Devolucion.estado == estado)
    if cliente_devuelve_id:
        filtros.append(Devolucion.cliente_devuelve_id == cliente_devuelve_id)
    if motivo:
        filtros.append(Devolucion.motivo == motivo)
    if desde:
        filtros.append(Devolucion.fecha_hora >= desde)
    if hasta:
        filtros.append(Devolucion.fecha_hora <= hasta)
    if q:
        filtros.append(Devolucion.numero.ilike(f"%{q}%"))

    total = (
        await session.execute(select(func.count()).select_from(Devolucion).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Devolucion)
            .options(*_CARGA_DEVOLUCION)
            .where(*filtros)
            .order_by(Devolucion.fecha_hora.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[DevolucionResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{devolucion_id}", response_model=DevolucionResponse, summary="Detalle de devolución")
async def obtener_devolucion(
    devolucion_id: uuid.UUID,
    session: SessionDep,
    user=Depends(_LEER),
) -> DevolucionResponse:
    return _respuesta(await _obtener_devolucion(session, devolucion_id))


@router.post(
    "",
    response_model=DevolucionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar devolución con sus cilindros (emite movimientos atómicos)",
)
async def crear_devolucion(
    body: DevolucionCreate,
    session: SessionDep,
    user=Depends(_CREAR),
) -> DevolucionResponse:
    cliente = await _validar_cliente_devuelve(session, body.cliente_devuelve_id)
    if body.entrega_id is not None:
        entrega = await session.get(Entrega, body.entrega_id)
        if entrega is None:
            raise NotFound("Entrega", body.entrega_id)
    await _validar_ubicacion_destino(session, body.ubicacion_destino_id)

    cilindros = await _validar_detalles(session, body.detalles)

    devolucion = Devolucion(
        numero=await siguiente_numero(session, Devolucion, "numero", _PREFIJO_NUMERO),
        estado="REGISTRADA",
        usuario_responsable_id=user.id,
        cliente_devuelve_id=cliente.id,
        entrega_id=body.entrega_id,
        motivo=body.motivo,
        documento_referencia=body.documento_referencia,
        observaciones=body.observaciones,
        ubicacion_destino_id=body.ubicacion_destino_id,
    )
    session.add(devolucion)
    await session.flush()

    # D31: cada cilindro regresa a AGAS vía un Movimiento en la misma
    # transacción (ENTREGADO → RECIBIDO); con destino, además se mueve a él.
    for detalle, cilindro in zip(body.detalles, cilindros, strict=False):
        destino = body.ubicacion_destino_id or cilindro.ubicacion_actual_id
        session.add(
            Movimiento(
                cilindro_id=cilindro.id,
                ubicacion_origen_id=cilindro.ubicacion_actual_id,
                ubicacion_destino_id=destino,
                estado_anterior=cilindro.estado_operativo,
                estado_nuevo="RECIBIDO",
                usuario_recibe_id=user.id,
                motivo=f"Devolución {devolucion.numero}",
            )
        )
        cilindro.estado_operativo = "RECIBIDO"
        cilindro.ubicacion_actual_id = destino

        session.add(
            DevolucionDetalle(
                devolucion_id=devolucion.id,
                cilindro_id=detalle.cilindro_id,
                estado_fisico=detalle.estado_fisico,
                accesorios=detalle.accesorios,
                observaciones=detalle.observaciones,
            )
        )

    await session.commit()
    return _respuesta(await _obtener_devolucion(session, devolucion.id))


@router.patch(
    "/{devolucion_id}",
    response_model=DevolucionResponse,
    summary="Actualizar campos descriptivos de la devolución (solo en REGISTRADA)",
)
async def actualizar_devolucion(
    devolucion_id: uuid.UUID,
    body: DevolucionUpdate,
    session: SessionDep,
    user=Depends(_MODIFICAR),
) -> DevolucionResponse:
    devolucion = await _obtener_devolucion(session, devolucion_id)

    if devolucion.estado != "REGISTRADA":
        raise ValidationError(
            f"La devolución '{devolucion.numero}' está '{devolucion.estado}': "
            "solo se edita en 'REGISTRADA'"
        )

    # `null` = sin cambio (contrato de DevolucionUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    for campo, valor in datos.items():
        setattr(devolucion, campo, valor)
    await session.commit()
    return _respuesta(await _obtener_devolucion(session, devolucion.id))


@router.patch(
    "/{devolucion_id}/estado",
    response_model=DevolucionResponse,
    summary="Anular devolución (no revierte la traza)",
)
async def cambiar_estado(
    devolucion_id: uuid.UUID,
    body: DevolucionEstadoUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> DevolucionResponse:
    devolucion = await _obtener_devolucion(session, devolucion_id)

    if devolucion.estado == body.estado:
        raise InvalidStateTransition(
            "Devolución",
            devolucion.estado,
            body.estado,
            allowed=[e for e in _ESTADOS_DEVOLUCION if e != devolucion.estado],
        )
    if body.estado != "ANULADA":
        raise InvalidStateTransition(
            "Devolución", devolucion.estado, body.estado, allowed=["ANULADA"]
        )

    # La matriz TAREA_19 = [0,1,2,7] deja la anulación en PERM_07 (no en PERM_03).
    await require_task(session, user.id, "TAREA_19")
    await require_permission(session, user.id, "PERM_07")

    devolucion.estado = "ANULADA"
    await session.commit()
    return _respuesta(await _obtener_devolucion(session, devolucion.id))
