"""
Endpoints de inspección de cilindros (ETAPA 5.2).

Dominio RBAC: **TAREA_05** (inspeccionar cilindros). Al ser **append-only**
(D33) solo se exponen **PERM_01** (consultar) y **PERM_02** (crear);
PERM_03/04/05/07 quedan sembrados pero sin endpoint. El router **no**
expone PATCH ni DELETE (405): la inspección es traza pura.

`POST /inspecciones` crea la inspección y **emite un `Movimiento` en la
misma transacción** (D31: el estado del cilindro solo cambia vía
`Movimiento`): el `resultado` de la inspección mapea al `estado_nuevo` del
cilindro (`APTO_LLENADO`→`APTO_LLENADO`, `REQUIERE_REPARACION`→
`APTO_REPARACION`, `REQUIERE_INSPECCION_TECNICA`→`PENDIENTE_INSPECCION`,
`RECHAZADO`→`RECHAZADO`, `FUERA_SERVICIO`→`FUERA_SERVICIO`). El origen y el
destino del movimiento son la ubicación actual (cambio **puro de estado**:
la inspección no mueve físicamente el cilindro). `usuario_id` es el usuario
autenticado y `fecha_hora` la fija el servidor.

TAREA_06 «Aprobar cilindros para llenado» no se usa en esta subetapa (la
aprobación se ejerce al crear/autorizar la orden de llenado en 5.3). No hay
restricción de estado de origen: se registra la inspección física siempre y
el `Movimiento` deja la traza. `recepcion_id` es un vínculo informativo
opcional (solo se valida que exista → 404).
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
from app.models import Cilindro, Inspeccion, Movimiento, Recepcion, Usuario
from app.schemas.common import Pagina
from app.schemas.inspecciones import (
    InspeccionCreate,
    InspeccionResponse,
    ResultadoInspeccion,
)

router = APIRouter(tags=["Operaciones — inspecciones"])

# Guard RBAC por acción (dominio TAREA_05: inspeccionar cilindros).
_LEER = RequireTaskPermission("TAREA_05", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_05", "PERM_02")

# Mapeo resultado de la inspección → estado_operativo del cilindro.
_ESTADO_POR_RESULTADO = {
    "APTO_LLENADO": "APTO_LLENADO",
    "REQUIERE_REPARACION": "APTO_REPARACION",
    "REQUIERE_INSPECCION_TECNICA": "PENDIENTE_INSPECCION",
    "RECHAZADO": "RECHAZADO",
    "FUERA_SERVICIO": "FUERA_SERVICIO",
}


def _respuesta(inspeccion: Inspeccion) -> InspeccionResponse:
    return InspeccionResponse.model_validate(inspeccion, from_attributes=True)


@router.get("", response_model=Pagina[InspeccionResponse], summary="Listar inspecciones")
async def listar_inspecciones(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    cilindro_id: uuid.UUID | None = Query(None),
    recepcion_id: uuid.UUID | None = Query(None),
    usuario_id: uuid.UUID | None = Query(None),
    resultado: ResultadoInspeccion | None = Query(None, description="Filtro exacto por resultado."),
    desde: datetime | None = Query(None, description="Fecha/hora desde (inclusive)."),
    hasta: datetime | None = Query(None, description="Fecha/hora hasta (inclusive)."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[InspeccionResponse]:
    filtros = []
    if cilindro_id:
        filtros.append(Inspeccion.cilindro_id == cilindro_id)
    if recepcion_id:
        filtros.append(Inspeccion.recepcion_id == recepcion_id)
    if usuario_id:
        filtros.append(Inspeccion.usuario_id == usuario_id)
    if resultado:
        filtros.append(Inspeccion.resultado == resultado)
    if desde:
        filtros.append(Inspeccion.fecha_hora >= desde)
    if hasta:
        filtros.append(Inspeccion.fecha_hora <= hasta)

    total = (
        await session.execute(select(func.count()).select_from(Inspeccion).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Inspeccion)
            .where(*filtros)
            .order_by(Inspeccion.fecha_hora.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[InspeccionResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{inspeccion_id}", response_model=InspeccionResponse, summary="Detalle de inspección")
async def obtener_inspeccion(
    inspeccion_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> InspeccionResponse:
    return _respuesta(await obtener_o_404(session, Inspeccion, inspeccion_id, "Inspección"))


@router.post(
    "",
    response_model=InspeccionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear inspección (emite movimiento atómico)",
)
async def crear_inspeccion(
    body: InspeccionCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> InspeccionResponse:
    cilindro = await obtener_o_404(session, Cilindro, body.cilindro_id, "Cilindro")
    if body.recepcion_id is not None:
        await obtener_o_404(session, Recepcion, body.recepcion_id, "Recepción")

    inspeccion = Inspeccion(usuario_id=user.id, **body.model_dump())
    session.add(inspeccion)

    # D31: el estado del cilindro solo cambia vía Movimiento (misma transacción).
    estado_nuevo = _ESTADO_POR_RESULTADO[inspeccion.resultado]
    session.add(
        Movimiento(
            cilindro_id=cilindro.id,
            ubicacion_origen_id=cilindro.ubicacion_actual_id,
            ubicacion_destino_id=cilindro.ubicacion_actual_id,
            estado_anterior=cilindro.estado_operativo,
            estado_nuevo=estado_nuevo,
            usuario_recibe_id=user.id,
            motivo=f"Inspección: {inspeccion.resultado}",
        )
    )
    cilindro.estado_operativo = estado_nuevo

    await session.commit()
    await session.refresh(inspeccion)
    return _respuesta(inspeccion)
