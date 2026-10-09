"""
Endpoints de órdenes de trabajo (ETAPA 5.3.a: cabecera, detalles y ciclo de vida).

Una única colección `/ordenes-trabajo` sirve a llenado y reparación; el
**dominio RBAC depende del `tipo`** (D32), así que además de la lectura (que
usa `RequireAnyTaskPermission`) las acciones resuelven tarea y permiso en el
*handler* con `require_task` / `require_permission`:

    | acción                 | LLENADO            | REPARACION          |
    |------------------------|--------------------|---------------------|
    | crear                  | TAREA_07 + PERM_02 | TAREA_10 + PERM_02  |
    | modificar cabecera     | TAREA_07 + PERM_03 | TAREA_10 + PERM_03  |
    | ejecutar (EN_PROCESO/FINALIZADA) | TAREA_08 + PERM_03 | TAREA_12 + PERM_03 |
    | cerrar (PENDIENTE_CALIDAD)       | TAREA_09 + PERM_06 | TAREA_13 + PERM_06 |
    | anular (CANCELADA)     | TAREA_07 + PERM_07 | TAREA_10 + PERM_07  |

Ciclo de vida (una transición por endpoint, misma transición → 409 con
`allowed_states`): `PENDIENTE → EN_PROCESO → FINALIZADA → PENDIENTE_CALIDAD`,
más `PENDIENTE → CANCELADA`. Cada transición que cambia el estado del
cilindro **emite un `Movimiento` por cilindro** en la misma transacción (D31:
el estado del cilindro solo cambia vía `Movimiento`; origen = destino =
ubicación actual, cambio puro de estado). `APROBADA` / `RECHAZADA` /
`REQUIERE_NUEVA_REPARACION` las fijará el control de calidad (5.4).

El `DELETE` de la cabecera no se expone (405): la orden se anula por estado
(`CANCELADA`). Los cilindros se gestionan por el sub-recurso anidado
`/ordenes-trabajo/{id}/detalles` (solo mientras la orden está `PENDIENTE`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select

# noqa en TC001: FastAPI y las firmas resuelven estos nombres en runtime.
from app.api.deps import (  # noqa: TC001
    CurrentUser,
    RequireAnyTaskPermission,
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
from app.core.permissions import require_permission, require_task
from app.models import (
    Area,
    Cilindro,
    DetalleOrden,
    Movimiento,
    OrdenTrabajo,
    TipoGas,
    Usuario,
)
from app.schemas.common import Pagina
from app.schemas.ordenes_trabajo import (
    DetalleOrdenCreate,
    DetalleOrdenEjecucionUpdate,
    DetalleOrdenResponse,
    EstadoOrden,
    OrdenTrabajoCreate,
    OrdenTrabajoEstadoUpdate,
    OrdenTrabajoResponse,
    OrdenTrabajoUpdate,
    Prioridad,
    TipoOrden,
)

router = APIRouter(tags=["Operaciones — órdenes de trabajo"])

# Lectura: cualquiera de las tareas del dominio de órdenes (o el admin RBAC).
_LEER = RequireAnyTaskPermission(
    (
        "TAREA_07",
        "TAREA_08",
        "TAREA_09",
        "TAREA_10",
        "TAREA_11",
        "TAREA_12",
        "TAREA_13",
        "TAREA_28",
    ),
    "PERM_01",
)

# Prefijo del correlativo por tipo (D30).
_PREFIJO = {"LLENADO": "OTL", "REPARACION": "OTR"}

# Estado de cilindro exigido al incorporarlo a la orden.
_ESTADO_ELEGIBLE = {"LLENADO": "APTO_LLENADO", "REPARACION": "APTO_REPARACION"}

# (tarea, permiso) por acción de negocio según el tipo de orden.
_ACCION = {
    "crear": {"LLENADO": ("TAREA_07", "PERM_02"), "REPARACION": ("TAREA_10", "PERM_02")},
    "modificar": {"LLENADO": ("TAREA_07", "PERM_03"), "REPARACION": ("TAREA_10", "PERM_03")},
    "ejecutar": {"LLENADO": ("TAREA_08", "PERM_03"), "REPARACION": ("TAREA_12", "PERM_03")},
}

# Transiciones válidas por estado de origen.
_TRANSICIONES_VALIDAS = {
    "PENDIENTE": ("EN_PROCESO", "CANCELADA"),
    "EN_PROCESO": ("FINALIZADA",),
    "FINALIZADA": ("PENDIENTE_CALIDAD",),
}

# (tarea, permiso) exigidos para alcanzar cada estado, según el tipo.
_GUARD_TRANSICION = {
    "EN_PROCESO": {"LLENADO": ("TAREA_08", "PERM_03"), "REPARACION": ("TAREA_12", "PERM_03")},
    "FINALIZADA": {"LLENADO": ("TAREA_08", "PERM_03"), "REPARACION": ("TAREA_12", "PERM_03")},
    "PENDIENTE_CALIDAD": {"LLENADO": ("TAREA_09", "PERM_06"), "REPARACION": ("TAREA_13", "PERM_06")},
    "CANCELADA": {"LLENADO": ("TAREA_07", "PERM_07"), "REPARACION": ("TAREA_10", "PERM_07")},
}

# Estado del cilindro que provoca cada transición (ausente = sin cambio).
_ESTADO_CILINDRO = {
    ("LLENADO", "EN_PROCESO"): "EN_PROCESO_LLENADO",
    ("LLENADO", "FINALIZADA"): "FINALIZADO_LLENADO",
    ("LLENADO", "PENDIENTE_CALIDAD"): "PENDIENTE_CONTROL_CALIDAD",
    ("REPARACION", "EN_PROCESO"): "EN_REPARACION",
    ("REPARACION", "FINALIZADA"): "REPARADO",
    ("REPARACION", "PENDIENTE_CALIDAD"): "PENDIENTE_CONTROL_CALIDAD",
}


def _respuesta(orden: OrdenTrabajo) -> OrdenTrabajoResponse:
    return OrdenTrabajoResponse.model_validate(orden, from_attributes=True)


def _respuesta_detalle(detalle: DetalleOrden) -> DetalleOrdenResponse:
    return DetalleOrdenResponse.model_validate(detalle, from_attributes=True)


async def _exigir(session, user: Usuario, tarea: str, permiso: str) -> None:
    """RBAC condicionado por tipo (D32): tarea (dominio) + permiso (acción)."""
    await require_task(session, user.id, tarea)
    await require_permission(session, user.id, permiso)


async def _detalles_de(session, orden_id: uuid.UUID) -> list[DetalleOrden]:
    return list(
        (
            await session.execute(select(DetalleOrden).where(DetalleOrden.orden_id == orden_id))
        )
        .scalars()
        .all()
    )


async def _buscar_detalle(session, orden_id: uuid.UUID, detalle_id: uuid.UUID) -> DetalleOrden:
    """Detalle acotado a su orden: de otra orden → 404 (no 403)."""
    detalle = (
        await session.execute(
            select(DetalleOrden).where(
                DetalleOrden.id == detalle_id,
                DetalleOrden.orden_id == orden_id,
            )
        )
    ).scalar_one_or_none()
    if detalle is None:
        raise NotFound("Detalle de orden", detalle_id)
    return detalle


async def _validar_cilindro_elegible(session, tipo: str, cilindro_id: uuid.UUID) -> None:
    cilindro = await obtener_o_404(session, Cilindro, cilindro_id, "Cilindro")
    esperado = _ESTADO_ELEGIBLE[tipo]
    if cilindro.estado_operativo != esperado:
        raise ValidationError(
            f"El cilindro '{cilindro.codigo_interno}' está '{cilindro.estado_operativo}': "
            f"para una orden de {tipo.lower()} debe estar '{esperado}'"
        )


# ============================================================
# ÓRDENES (cabecera)
# ============================================================


@router.get("", response_model=Pagina[OrdenTrabajoResponse], summary="Listar órdenes de trabajo")
async def listar_ordenes(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    tipo: TipoOrden | None = Query(None, description="Filtro exacto por tipo."),
    estado: EstadoOrden | None = Query(None, description="Filtro exacto por estado."),
    prioridad: Prioridad | None = Query(None, description="Filtro exacto por prioridad."),
    area_responsable_id: uuid.UUID | None = Query(None),
    usuario_asignado_id: uuid.UUID | None = Query(None),
    desde: datetime | None = Query(None, description="Fecha de creación desde (inclusive)."),
    hasta: datetime | None = Query(None, description="Fecha de creación hasta (inclusive)."),
    q: str | None = Query(None, max_length=100, description="Contiene en el número."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[OrdenTrabajoResponse]:
    filtros = []
    if tipo:
        filtros.append(OrdenTrabajo.tipo == tipo)
    if estado:
        filtros.append(OrdenTrabajo.estado == estado)
    if prioridad:
        filtros.append(OrdenTrabajo.prioridad == prioridad)
    if area_responsable_id:
        filtros.append(OrdenTrabajo.area_responsable_id == area_responsable_id)
    if usuario_asignado_id:
        filtros.append(OrdenTrabajo.usuario_asignado_id == usuario_asignado_id)
    if desde:
        filtros.append(OrdenTrabajo.fecha_creacion >= desde)
    if hasta:
        filtros.append(OrdenTrabajo.fecha_creacion <= hasta)
    if q:
        filtros.append(OrdenTrabajo.numero.ilike(f"%{q}%"))

    total = (
        await session.execute(select(func.count()).select_from(OrdenTrabajo).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(OrdenTrabajo)
            .where(*filtros)
            .order_by(OrdenTrabajo.fecha_creacion.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[OrdenTrabajoResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{orden_id}", response_model=OrdenTrabajoResponse, summary="Detalle de orden")
async def obtener_orden(
    orden_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> OrdenTrabajoResponse:
    return _respuesta(await obtener_o_404(session, OrdenTrabajo, orden_id, "Orden de trabajo"))


@router.post(
    "",
    response_model=OrdenTrabajoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear orden de trabajo con sus cilindros (numero del servidor)",
)
async def crear_orden(
    body: OrdenTrabajoCreate,
    session: SessionDep,
    user: CurrentUser,
) -> OrdenTrabajoResponse:
    tarea, permiso = _ACCION["crear"][body.tipo]
    await _exigir(session, user, tarea, permiso)

    await obtener_o_404(session, Area, body.area_responsable_id, "Área responsable")
    if body.usuario_asignado_id is not None:
        await obtener_o_404(session, Usuario, body.usuario_asignado_id, "Usuario asignado")
    if body.tipo_gas_id is not None:
        await obtener_o_404(session, TipoGas, body.tipo_gas_id, "Tipo de gas")

    vistos: set[uuid.UUID] = set()
    for detalle in body.detalles:
        if detalle.cilindro_id in vistos:
            raise DuplicateValue("cilindro_id", str(detalle.cilindro_id))
        vistos.add(detalle.cilindro_id)
        await _validar_cilindro_elegible(session, body.tipo, detalle.cilindro_id)
        if detalle.tipo_gas_id is not None:
            await obtener_o_404(session, TipoGas, detalle.tipo_gas_id, "Tipo de gas")

    orden = OrdenTrabajo(
        numero=await siguiente_numero(session, OrdenTrabajo, "numero", _PREFIJO[body.tipo]),
        tipo=body.tipo,
        estado="PENDIENTE",
        usuario_creador_id=user.id,
        area_responsable_id=body.area_responsable_id,
        usuario_asignado_id=body.usuario_asignado_id,
        prioridad=body.prioridad,
        fecha_estimada_termino=body.fecha_estimada_termino,
        tipo_gas_id=body.tipo_gas_id,
        tipo_falla=body.tipo_falla,
        diagnostico=body.diagnostico,
        trabajo_solicitado=body.trabajo_solicitado,
        observaciones=body.observaciones,
    )
    session.add(orden)
    await session.flush()

    for detalle in body.detalles:
        session.add(DetalleOrden(orden_id=orden.id, **detalle.model_dump()))

    await session.commit()
    await session.refresh(orden)
    return _respuesta(orden)


@router.patch("/{orden_id}", response_model=OrdenTrabajoResponse, summary="Actualizar orden")
async def actualizar_orden(
    orden_id: uuid.UUID,
    body: OrdenTrabajoUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> OrdenTrabajoResponse:
    orden = await obtener_o_404(session, OrdenTrabajo, orden_id, "Orden de trabajo")
    tarea, permiso = _ACCION["modificar"][orden.tipo]
    await _exigir(session, user, tarea, permiso)

    if orden.estado != "PENDIENTE":
        raise ValidationError(
            f"La orden '{orden.numero}' está '{orden.estado}': solo se edita en 'PENDIENTE'"
        )

    # `null` = sin cambio (contrato de OrdenTrabajoUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    if "area_responsable_id" in datos:
        await obtener_o_404(session, Area, datos["area_responsable_id"], "Área responsable")
    if "usuario_asignado_id" in datos:
        await obtener_o_404(session, Usuario, datos["usuario_asignado_id"], "Usuario asignado")
    if "tipo_gas_id" in datos:
        await obtener_o_404(session, TipoGas, datos["tipo_gas_id"], "Tipo de gas")

    for campo, valor in datos.items():
        setattr(orden, campo, valor)
    await session.commit()
    await session.refresh(orden)
    return _respuesta(orden)


@router.patch(
    "/{orden_id}/estado",
    response_model=OrdenTrabajoResponse,
    summary="Cambiar estado de la orden (emite movimientos atómicos)",
)
async def cambiar_estado(
    orden_id: uuid.UUID,
    body: OrdenTrabajoEstadoUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> OrdenTrabajoResponse:
    orden = await obtener_o_404(session, OrdenTrabajo, orden_id, "Orden de trabajo")

    permitidas = _TRANSICIONES_VALIDAS.get(orden.estado, ())
    if body.estado not in permitidas:
        raise InvalidStateTransition(
            "Orden de trabajo", orden.estado, body.estado, allowed=list(permitidas)
        )

    tarea, permiso = _GUARD_TRANSICION[body.estado][orden.tipo]
    await _exigir(session, user, tarea, permiso)

    # D31: el estado del cilindro solo cambia vía Movimiento (misma transacción).
    estado_cilindro = _ESTADO_CILINDRO.get((orden.tipo, body.estado))
    if estado_cilindro is not None:
        for detalle in await _detalles_de(session, orden.id):
            cilindro = await obtener_o_404(session, Cilindro, detalle.cilindro_id, "Cilindro")
            session.add(
                Movimiento(
                    cilindro_id=cilindro.id,
                    ubicacion_origen_id=cilindro.ubicacion_actual_id,
                    ubicacion_destino_id=cilindro.ubicacion_actual_id,
                    estado_anterior=cilindro.estado_operativo,
                    estado_nuevo=estado_cilindro,
                    usuario_recibe_id=user.id,
                    motivo=body.motivo or f"Orden {orden.numero}: {body.estado}",
                )
            )
            cilindro.estado_operativo = estado_cilindro

    orden.estado = body.estado
    if body.estado == "EN_PROCESO" and orden.fecha_inicio is None:
        orden.fecha_inicio = datetime.now(UTC)
    if body.estado == "FINALIZADA":
        orden.fecha_termino_real = datetime.now(UTC)

    await session.commit()
    await session.refresh(orden)
    return _respuesta(orden)


# ============================================================
# DETALLES (sub-recurso anidado)
# ============================================================


@router.get(
    "/{orden_id}/detalles",
    response_model=Pagina[DetalleOrdenResponse],
    summary="Listar cilindros de la orden",
)
async def listar_detalles(
    orden_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[DetalleOrdenResponse]:
    await obtener_o_404(session, OrdenTrabajo, orden_id, "Orden de trabajo")
    filtros = [DetalleOrden.orden_id == orden_id]

    total = (
        await session.execute(select(func.count()).select_from(DetalleOrden).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(DetalleOrden)
            .where(*filtros)
            .order_by(DetalleOrden.fecha_creacion)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[DetalleOrdenResponse](
        items=[_respuesta_detalle(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get(
    "/{orden_id}/detalles/{detalle_id}",
    response_model=DetalleOrdenResponse,
    summary="Detalle de un cilindro de la orden",
)
async def obtener_detalle(
    orden_id: uuid.UUID,
    detalle_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> DetalleOrdenResponse:
    return _respuesta_detalle(await _buscar_detalle(session, orden_id, detalle_id))


@router.post(
    "/{orden_id}/detalles",
    response_model=DetalleOrdenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar un cilindro a la orden (solo en PENDIENTE)",
)
async def agregar_detalle(
    orden_id: uuid.UUID,
    body: DetalleOrdenCreate,
    session: SessionDep,
    user: CurrentUser,
) -> DetalleOrdenResponse:
    orden = await obtener_o_404(session, OrdenTrabajo, orden_id, "Orden de trabajo")
    tarea, permiso = _ACCION["modificar"][orden.tipo]
    await _exigir(session, user, tarea, permiso)

    if orden.estado != "PENDIENTE":
        raise ValidationError(
            f"La orden '{orden.numero}' está '{orden.estado}': "
            "solo admite cilindros mientras está 'PENDIENTE'"
        )

    await _validar_cilindro_elegible(session, orden.tipo, body.cilindro_id)
    if body.tipo_gas_id is not None:
        await obtener_o_404(session, TipoGas, body.tipo_gas_id, "Tipo de gas")

    existe = (
        await session.execute(
            select(DetalleOrden.id)
            .where(
                DetalleOrden.orden_id == orden_id,
                DetalleOrden.cilindro_id == body.cilindro_id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existe is not None:
        raise DuplicateValue("cilindro_id", str(body.cilindro_id))

    detalle = DetalleOrden(orden_id=orden.id, **body.model_dump())
    session.add(detalle)
    await session.commit()
    await session.refresh(detalle)
    return _respuesta_detalle(detalle)


@router.patch(
    "/{orden_id}/detalles/{detalle_id}",
    response_model=DetalleOrdenResponse,
    summary="Registrar resultados de ejecución del cilindro",
)
async def actualizar_detalle(
    orden_id: uuid.UUID,
    detalle_id: uuid.UUID,
    body: DetalleOrdenEjecucionUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> DetalleOrdenResponse:
    orden = await obtener_o_404(session, OrdenTrabajo, orden_id, "Orden de trabajo")
    tarea, permiso = _ACCION["ejecutar"][orden.tipo]
    await _exigir(session, user, tarea, permiso)

    if orden.estado not in ("EN_PROCESO", "FINALIZADA"):
        raise ValidationError(
            "Los resultados de ejecución se registran con la orden 'EN_PROCESO' o "
            f"'FINALIZADA' (actual: '{orden.estado}')"
        )

    detalle = await _buscar_detalle(session, orden_id, detalle_id)
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    for campo, valor in datos.items():
        setattr(detalle, campo, valor)
    await session.commit()
    await session.refresh(detalle)
    return _respuesta_detalle(detalle)


@router.delete(
    "/{orden_id}/detalles/{detalle_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quitar un cilindro de la orden (solo en PENDIENTE)",
)
async def eliminar_detalle(
    orden_id: uuid.UUID,
    detalle_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
) -> Response:
    orden = await obtener_o_404(session, OrdenTrabajo, orden_id, "Orden de trabajo")
    tarea, permiso = _ACCION["modificar"][orden.tipo]
    await _exigir(session, user, tarea, permiso)

    if orden.estado != "PENDIENTE":
        raise ValidationError(
            f"La orden '{orden.numero}' está '{orden.estado}': "
            "solo se quitan cilindros mientras está 'PENDIENTE'"
        )

    detalle = await _buscar_detalle(session, orden_id, detalle_id)
    await session.delete(detalle)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
