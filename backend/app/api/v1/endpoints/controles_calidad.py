"""
Endpoints de control de calidad (ETAPA 5.4).

Dominio RBAC: **TAREA_14** (realizar control de calidad). Al ser **append-only**
(D33) solo se exponen **PERM_01** (consultar) y **PERM_02** (crear); el router
**no** expone PATCH ni DELETE (405): el control es traza pura. Además de
PERM_02, el resultado exige el permiso de la acción: **PERM_04** (aprobar) para
`APROBADO`/`APROBADO_OBSERVACIONES` y **PERM_05** (rechazar) para
`REQUIERE_NUEVA_REPARACION`/`RECHAZADO`.

`POST /controles-calidad` registra el control de un cilindro de una orden
`PENDIENTE_CALIDAD` (cilindro `PENDIENTE_CONTROL_CALIDAD`) y **emite un
`Movimiento` en la misma transacción** (D31): `APROBADO`→`APROBADO` (o
`LISTO_PARA_ENTREGAR` si `autoriza_entrega`), `APROBADO_OBSERVACIONES`→
`APROBADO_OBSERVACIONES`, `REQUIERE_NUEVA_REPARACION`→`APTO_REPARACION`,
`RECHAZADO`→`RECHAZADO`, `PENDIENTE_REVISION`→sin cambio. Origen = destino =
ubicación actual (cambio **puro de estado**).

**Segregación de funciones (RN28)**: quien ejecutó el trabajo del cilindro
(TAREA_08 llenado / TAREA_12 reparación, tarea `COMPLETADA`) no puede aprobar
su propio control → 403 `SEPARATION_OF_DUTIES`.

**Cierre de la orden**: cuando **todos** los cilindros de la orden tienen un
control y ninguno queda en `PENDIENTE_REVISION`, la orden pasa de
`PENDIENTE_CALIDAD` a `RECHAZADA` (algún `RECHAZADO`) ›
`REQUIERE_NUEVA_REPARACION` (alguno) › `APROBADA` (todos aprobados/observados).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select

# noqa en TC001: FastAPI y las firmas resuelven estos nombres en runtime.
from app.api.deps import (  # noqa: TC001
    RequireTaskPermission,
    SessionDep,
    obtener_o_404,
)
from app.core.exceptions import ValidationError
from app.core.permissions import check_separation_of_duties, require_permission
from app.models import (
    Cilindro,
    ControlCalidad,
    DetalleOrden,
    Movimiento,
    OrdenTrabajo,
    Usuario,
)
from app.schemas.common import Pagina
from app.schemas.controles_calidad import (
    ControlCalidadCreate,
    ControlCalidadResponse,
    ResultadoControlCalidad,
)

router = APIRouter(tags=["Operaciones — control de calidad"])

# Guard RBAC por acción (dominio TAREA_14: realizar control de calidad).
_LEER = RequireTaskPermission("TAREA_14", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_14", "PERM_02")

# Permiso adicional exigido por el resultado (aprobar/rechazar).
_PERMISO_POR_RESULTADO = {
    "APROBADO": "PERM_04",
    "APROBADO_OBSERVACIONES": "PERM_04",
    "REQUIERE_NUEVA_REPARACION": "PERM_05",
    "RECHAZADO": "PERM_05",
}

# Mapeo resultado → estado_operativo del cilindro (APROBADO depende de autoriza_entrega).
_ESTADO_POR_RESULTADO = {
    "APROBADO": "APROBADO",
    "APROBADO_OBSERVACIONES": "APROBADO_OBSERVACIONES",
    "REQUIERE_NUEVA_REPARACION": "APTO_REPARACION",
    "RECHAZADO": "RECHAZADO",
}

# Tarea ejecutora del trabajo (RN28) según el tipo de orden.
_TAREA_EJECUTORA = {"LLENADO": "TAREA_08", "REPARACION": "TAREA_12"}

_ESTADO_ELEGIBLE = "PENDIENTE_CONTROL_CALIDAD"
_ESTADO_ORDEN = "PENDIENTE_CALIDAD"


def _respuesta(control: ControlCalidad) -> ControlCalidadResponse:
    return ControlCalidadResponse.model_validate(control, from_attributes=True)


async def _cerrar_orden_si_corresponde(session, orden: OrdenTrabajo) -> None:
    """Fija el estado final de la orden cuando todos sus cilindros están controlados."""
    detalles = (
        await session.execute(select(DetalleOrden).where(DetalleOrden.orden_id == orden.id))
    ).scalars().all()
    controles = (
        await session.execute(
            select(ControlCalidad)
            .where(ControlCalidad.orden_relacionada_id == orden.id)
            .order_by(ControlCalidad.fecha_hora)
        )
    ).scalars().all()

    ultimo: dict[uuid.UUID, str] = {}
    for control in controles:  # el último control por cilindro es el vigente
        ultimo[control.cilindro_id] = control.resultado

    if len(ultimo) < len(detalles):
        return  # aún hay cilindros sin controlar
    resultados = set(ultimo.values())
    if "PENDIENTE_REVISION" in resultados:
        return  # requiere revisión: la orden sigue abierta
    if "RECHAZADO" in resultados:
        orden.estado = "RECHAZADA"
    elif "REQUIERE_NUEVA_REPARACION" in resultados:
        orden.estado = "REQUIERE_NUEVA_REPARACION"
    else:
        orden.estado = "APROBADA"


@router.get("", response_model=Pagina[ControlCalidadResponse], summary="Listar controles de calidad")
async def listar_controles(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    cilindro_id: uuid.UUID | None = Query(None),
    orden_relacionada_id: uuid.UUID | None = Query(None),
    usuario_id: uuid.UUID | None = Query(None),
    resultado: ResultadoControlCalidad | None = Query(None, description="Filtro exacto por resultado."),
    desde: datetime | None = Query(None, description="Fecha/hora desde (inclusive)."),
    hasta: datetime | None = Query(None, description="Fecha/hora hasta (inclusive)."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[ControlCalidadResponse]:
    filtros = []
    if cilindro_id:
        filtros.append(ControlCalidad.cilindro_id == cilindro_id)
    if orden_relacionada_id:
        filtros.append(ControlCalidad.orden_relacionada_id == orden_relacionada_id)
    if usuario_id:
        filtros.append(ControlCalidad.usuario_id == usuario_id)
    if resultado:
        filtros.append(ControlCalidad.resultado == resultado)
    if desde:
        filtros.append(ControlCalidad.fecha_hora >= desde)
    if hasta:
        filtros.append(ControlCalidad.fecha_hora <= hasta)

    total = (
        await session.execute(select(func.count()).select_from(ControlCalidad).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(ControlCalidad)
            .where(*filtros)
            .order_by(ControlCalidad.fecha_hora.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[ControlCalidadResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{control_id}", response_model=ControlCalidadResponse, summary="Detalle de control de calidad")
async def obtener_control(
    control_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> ControlCalidadResponse:
    return _respuesta(await obtener_o_404(session, ControlCalidad, control_id, "Control de calidad"))


@router.post(
    "",
    response_model=ControlCalidadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar control de calidad (emite movimiento atómico)",
)
async def crear_control(
    body: ControlCalidadCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> ControlCalidadResponse:
    cilindro = await obtener_o_404(session, Cilindro, body.cilindro_id, "Cilindro")
    orden = await obtener_o_404(session, OrdenTrabajo, body.orden_relacionada_id, "Orden de trabajo")

    if orden.estado != _ESTADO_ORDEN:
        raise ValidationError(
            f"La orden '{orden.numero}' está '{orden.estado}': "
            f"solo se controla una orden '{_ESTADO_ORDEN}'"
        )

    detalle = (
        await session.execute(
            select(DetalleOrden).where(
                DetalleOrden.orden_id == orden.id,
                DetalleOrden.cilindro_id == cilindro.id,
            )
        )
    ).scalar_one_or_none()
    if detalle is None:
        raise ValidationError(
            f"El cilindro '{cilindro.codigo_interno}' no pertenece a la orden '{orden.numero}'"
        )

    if cilindro.estado_operativo != _ESTADO_ELEGIBLE:
        raise ValidationError(
            f"El cilindro '{cilindro.codigo_interno}' está '{cilindro.estado_operativo}': "
            f"para el control de calidad debe estar '{_ESTADO_ELEGIBLE}'"
        )

    permiso = _PERMISO_POR_RESULTADO.get(body.resultado)
    if permiso is not None:
        await require_permission(session, user.id, permiso)

    # RN28: quien ejecutó el trabajo del cilindro no puede aprobar su control.
    tarea_ejecutora = _TAREA_EJECUTORA.get(orden.tipo)
    if tarea_ejecutora is not None:
        await check_separation_of_duties(session, user.id, "TAREA_14", tarea_ejecutora, cilindro.id)

    control = ControlCalidad(usuario_id=user.id, **body.model_dump())
    session.add(control)

    # D31: el estado del cilindro solo cambia vía Movimiento (misma transacción).
    if body.resultado == "APROBADO" and body.autoriza_entrega:
        estado_nuevo = "LISTO_PARA_ENTREGAR"
    else:
        estado_nuevo = _ESTADO_POR_RESULTADO.get(body.resultado, cilindro.estado_operativo)
    session.add(
        Movimiento(
            cilindro_id=cilindro.id,
            ubicacion_origen_id=cilindro.ubicacion_actual_id,
            ubicacion_destino_id=cilindro.ubicacion_actual_id,
            estado_anterior=cilindro.estado_operativo,
            estado_nuevo=estado_nuevo,
            usuario_recibe_id=user.id,
            motivo=f"Control de calidad: {body.resultado}",
        )
    )
    cilindro.estado_operativo = estado_nuevo

    await session.flush()
    await _cerrar_orden_si_corresponde(session, orden)

    await session.commit()
    await session.refresh(control)
    return _respuesta(control)
