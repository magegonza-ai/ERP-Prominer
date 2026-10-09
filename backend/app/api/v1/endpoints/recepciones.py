"""
Endpoints de recepción de cilindros (ETAPA 5.1).

Dominio RBAC: **TAREA_04** (recibir cilindros). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar y PERM_07 anular.

`Recepcion` es la cabecera del ingreso: `numero` lo genera el servidor
(correlativo ``REC-<AÑO>-######``, D30), `usuario_responsable_id` es el
usuario autenticado y `fecha_hora` la fija el servidor. Nace `COMPLETADA`;
el único cambio de estado es `COMPLETADA ⇄ ANULADA` vía
`PATCH /recepciones/{id}/estado` (misma transición → 409).

Los cilindros entran por el sub-recurso anidado
`/recepciones/{id}/detalles` (acotado a su recepción: detalle de otra
recepción → 404). Cada alta de detalle **emite un `Movimiento`** en la
misma transacción (D31: el estado del cilindro solo cambia vía
`Movimiento`): nace `RECIBIDO`, o `PENDIENTE_INSPECCION` si
`motivo_servicio = INSPECCION`; el origen es la ubicación actual del
cilindro (la recepción no la cambia, el modelo no tiene ubicación de
recepción). Un cilindro no puede repetirse en la misma recepción → 409
`DUPLICATE_VALUE`. Borrar un detalle es una corrección documental: no
revierte el movimiento ya registrado (traza inmutable).
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
    InvalidStateTransition,
    NotFound,
    ValidationError,
)
from app.core.numeracion import siguiente_numero
from app.models import (
    Cilindro,
    Cliente,
    DetalleRecepcion,
    Movimiento,
    Propietario,
    Recepcion,
    Usuario,
)
from app.schemas.common import Pagina
from app.schemas.recepciones import (
    DetalleRecepcionCreate,
    DetalleRecepcionResponse,
    EstadoRecepcion,
    MotivoServicio,
    RecepcionCreate,
    RecepcionEstadoUpdate,
    RecepcionResponse,
    RecepcionUpdate,
)

router = APIRouter(tags=["Operaciones — recepciones"])

# Guard RBAC por acción (dominio TAREA_04: recibir cilindros).
_LEER = RequireTaskPermission("TAREA_04", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_04", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_04", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_04", "PERM_07")

_ESTADOS_RECEPCION = ("COMPLETADA", "ANULADA")

# Estado del cilindro al ingresar según el motivo de la recepción.
_ESTADO_POR_MOTIVO = {
    "LLENADO": "RECIBIDO",
    "REPARACION": "RECIBIDO",
    "INSPECCION": "PENDIENTE_INSPECCION",
    "OTRO": "RECIBIDO",
}


def _respuesta(recepcion: Recepcion) -> RecepcionResponse:
    return RecepcionResponse.model_validate(recepcion, from_attributes=True)


def _respuesta_detalle(detalle: DetalleRecepcion) -> DetalleRecepcionResponse:
    return DetalleRecepcionResponse.model_validate(detalle, from_attributes=True)


async def _buscar_detalle(
    session: SessionDep, recepcion_id: uuid.UUID, detalle_id: uuid.UUID
) -> DetalleRecepcion:
    """Detalle acotado a su recepción: de otra recepción → 404 (no 403)."""
    detalle = (
        await session.execute(
            select(DetalleRecepcion).where(
                DetalleRecepcion.id == detalle_id,
                DetalleRecepcion.recepcion_id == recepcion_id,
            )
        )
    ).scalar_one_or_none()
    if detalle is None:
        raise NotFound("Detalle de recepción", detalle_id)
    return detalle


# ============================================================
# RECEPCIONES
# ============================================================


@router.get("", response_model=Pagina[RecepcionResponse], summary="Listar recepciones")
async def listar_recepciones(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    estado: EstadoRecepcion | None = Query(None, description="Filtro exacto por estado."),
    motivo_servicio: MotivoServicio | None = Query(None, description="Filtro exacto por motivo."),
    cliente_entrega_id: uuid.UUID | None = Query(None),
    propietario_id: uuid.UUID | None = Query(None),
    q: str | None = Query(None, max_length=100, description="Contiene en el número o referencia."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[RecepcionResponse]:
    filtros = []
    if estado:
        filtros.append(Recepcion.estado == estado)
    if motivo_servicio:
        filtros.append(Recepcion.motivo_servicio == motivo_servicio)
    if cliente_entrega_id:
        filtros.append(Recepcion.cliente_entrega_id == cliente_entrega_id)
    if propietario_id:
        filtros.append(Recepcion.propietario_id == propietario_id)
    if q:
        patron = f"%{q}%"
        filtros.append(
            or_(Recepcion.numero.ilike(patron), Recepcion.documento_referencia.ilike(patron))
        )

    total = (
        await session.execute(select(func.count()).select_from(Recepcion).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Recepcion)
            .where(*filtros)
            .order_by(Recepcion.fecha_hora.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[RecepcionResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{recepcion_id}", response_model=RecepcionResponse, summary="Detalle de recepción")
async def obtener_recepcion(
    recepcion_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> RecepcionResponse:
    return _respuesta(await obtener_o_404(session, Recepcion, recepcion_id, "Recepción"))


@router.post(
    "",
    response_model=RecepcionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear recepción (numero y fecha del servidor)",
)
async def crear_recepcion(
    body: RecepcionCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> RecepcionResponse:
    # FKs obligatorias/opcionales: 404 si alguna referencia no existe.
    await obtener_o_404(session, Cliente, body.cliente_entrega_id, "Cliente que entrega")
    await obtener_o_404(session, Propietario, body.propietario_id, "Propietario")
    if body.cliente_solicita_id is not None:
        await obtener_o_404(session, Cliente, body.cliente_solicita_id, "Cliente que solicita")

    recepcion = Recepcion(
        numero=await siguiente_numero(session, Recepcion, "numero", "REC"),
        usuario_responsable_id=user.id,
        **body.model_dump(),
    )
    session.add(recepcion)
    await session.commit()
    await session.refresh(recepcion)
    return _respuesta(recepcion)


@router.patch("/{recepcion_id}", response_model=RecepcionResponse, summary="Actualizar recepción")
async def actualizar_recepcion(
    recepcion_id: uuid.UUID,
    body: RecepcionUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> RecepcionResponse:
    recepcion = await obtener_o_404(session, Recepcion, recepcion_id, "Recepción")

    # `null` = sin cambio (contrato de RecepcionUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    if "cliente_solicita_id" in datos:
        await obtener_o_404(session, Cliente, datos["cliente_solicita_id"], "Cliente que solicita")

    for campo, valor in datos.items():
        setattr(recepcion, campo, valor)
    await session.commit()
    await session.refresh(recepcion)
    return _respuesta(recepcion)


@router.patch(
    "/{recepcion_id}/estado",
    response_model=RecepcionResponse,
    summary="Cambiar estado de recepción",
)
async def cambiar_estado(
    recepcion_id: uuid.UUID,
    body: RecepcionEstadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
) -> RecepcionResponse:
    recepcion = await obtener_o_404(session, Recepcion, recepcion_id, "Recepción")
    if recepcion.estado == body.estado:
        raise InvalidStateTransition(
            "Recepción",
            recepcion.estado,
            body.estado,
            allowed=[e for e in _ESTADOS_RECEPCION if e != recepcion.estado],
        )
    recepcion.estado = body.estado
    await session.commit()
    await session.refresh(recepcion)
    return _respuesta(recepcion)


# ============================================================
# DETALLES (sub-recurso anidado)
# ============================================================


@router.get(
    "/{recepcion_id}/detalles",
    response_model=Pagina[DetalleRecepcionResponse],
    summary="Listar cilindros de la recepción",
)
async def listar_detalles(
    recepcion_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    estado_fisico: str | None = Query(None, description="Filtro exacto por estado físico."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[DetalleRecepcionResponse]:
    await obtener_o_404(session, Recepcion, recepcion_id, "Recepción")
    filtros = [DetalleRecepcion.recepcion_id == recepcion_id]
    if estado_fisico:
        filtros.append(DetalleRecepcion.estado_fisico == estado_fisico)

    total = (
        await session.execute(select(func.count()).select_from(DetalleRecepcion).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(DetalleRecepcion)
            .where(*filtros)
            .order_by(DetalleRecepcion.fecha_creacion)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[DetalleRecepcionResponse](
        items=[_respuesta_detalle(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get(
    "/{recepcion_id}/detalles/{detalle_id}",
    response_model=DetalleRecepcionResponse,
    summary="Detalle de un cilindro recibido",
)
async def obtener_detalle(
    recepcion_id: uuid.UUID,
    detalle_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> DetalleRecepcionResponse:
    return _respuesta_detalle(await _buscar_detalle(session, recepcion_id, detalle_id))


@router.post(
    "/{recepcion_id}/detalles",
    response_model=DetalleRecepcionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Recibir un cilindro en la recepción (emite movimiento atómico)",
)
async def crear_detalle(
    recepcion_id: uuid.UUID,
    body: DetalleRecepcionCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> DetalleRecepcionResponse:
    recepcion = await obtener_o_404(session, Recepcion, recepcion_id, "Recepción")
    if recepcion.estado != "COMPLETADA":
        raise ValidationError(
            f"No se pueden recibir cilindros en la recepción '{recepcion.numero}': "
            f"está {recepcion.estado}"
        )

    cilindro = await obtener_o_404(session, Cilindro, body.cilindro_id, "Cilindro")

    # Un cilindro no puede repetirse dentro de la misma recepción.
    existe = (
        await session.execute(
            select(DetalleRecepcion.id)
            .where(
                DetalleRecepcion.recepcion_id == recepcion_id,
                DetalleRecepcion.cilindro_id == cilindro.id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existe is not None:
        raise DuplicateValue("cilindro_id", str(cilindro.id))

    detalle = DetalleRecepcion(
        recepcion_id=recepcion.id,
        **body.model_dump(),
    )
    session.add(detalle)

    # D31: el estado del cilindro solo cambia vía Movimiento (misma transacción).
    estado_nuevo = _ESTADO_POR_MOTIVO[recepcion.motivo_servicio]
    session.add(
        Movimiento(
            cilindro_id=cilindro.id,
            ubicacion_origen_id=cilindro.ubicacion_actual_id,
            ubicacion_destino_id=cilindro.ubicacion_actual_id,
            estado_anterior=cilindro.estado_operativo,
            estado_nuevo=estado_nuevo,
            usuario_recibe_id=user.id,
            motivo=f"Recepción {recepcion.numero}",
        )
    )
    cilindro.estado_operativo = estado_nuevo

    await session.commit()
    await session.refresh(detalle)
    return _respuesta_detalle(detalle)


@router.delete(
    "/{recepcion_id}/detalles/{detalle_id}",
    summary="Quitar un cilindro de la recepción (no revierte su movimiento)",
)
async def eliminar_detalle(
    recepcion_id: uuid.UUID,
    detalle_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
):
    """Corrección documental: el `Movimiento` ya registrado no se revierte."""
    detalle = await _buscar_detalle(session, recepcion_id, detalle_id)

    await session.delete(detalle)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
