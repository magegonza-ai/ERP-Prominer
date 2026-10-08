"""
Endpoints de movimientos de cilindros (ETAPA 4.2).

Dominio RBAC en **alternativa**: **TAREA_15** (cambiar ubicación) ∨
**TAREA_16** (registrar movimientos) — la semilla asigna ambas para la
misma operación (matriz `[0,1,2]` y `[0,1,2,7]`). Acciones: PERM_01
consultar, PERM_02 crear.

`POST /movimientos` es la **única** forma de cambiar la ubicación y el
`estado_operativo` de un cilindro: opera **atómicamente** (inserta el
movimiento con `estado_anterior` derivado del servidor + `fecha_hora` de
ahora y actualiza el cilindro). Una vez creado, el registro es
**inmutable**: el router no expone PATCH ni DELETE (trazabilidad pura).

Reglas → 400: no-op (mismo destino y mismo estado); destino `INACTIVA`;
`permite_entrada=false` en destino o `permite_salida=false` en origen
(solo cuando hay cambio real de ubicación). `estado_nuevo` fuera de los
20 del `ck_cilindro_estado` → 422; referencias inexistentes → 404.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select

# noqa en TC001: FastAPI y las firmas resuelven estos nombres en runtime.
from app.api.deps import (  # noqa: TC001
    RequireAnyTaskPermission,
    SessionDep,
    obtener_o_404,
)
from app.core.exceptions import ValidationError
from app.models import Cilindro, Movimiento, Ubicacion, Usuario
from app.schemas.common import Pagina
from app.schemas.movimientos import MovimientoCreate, MovimientoResponse

router = APIRouter(tags=["Cilindros — movimientos"])

# Guard RBAC por acción (dominio alternativo: TAREA_15 o TAREA_16).
_TAREAS = ("TAREA_15", "TAREA_16")
_LEER = RequireAnyTaskPermission(_TAREAS, "PERM_01")
_CREAR = RequireAnyTaskPermission(_TAREAS, "PERM_02")


def _respuesta(movimiento: Movimiento) -> MovimientoResponse:
    return MovimientoResponse.model_validate(movimiento, from_attributes=True)


@router.get("", response_model=Pagina[MovimientoResponse], summary="Listar movimientos")
async def listar_movimientos(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    cilindro_id: uuid.UUID | None = Query(None),
    ubicacion_origen_id: uuid.UUID | None = Query(None),
    ubicacion_destino_id: uuid.UUID | None = Query(None),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[MovimientoResponse]:
    filtros = []
    if cilindro_id:
        filtros.append(Movimiento.cilindro_id == cilindro_id)
    if ubicacion_origen_id:
        filtros.append(Movimiento.ubicacion_origen_id == ubicacion_origen_id)
    if ubicacion_destino_id:
        filtros.append(Movimiento.ubicacion_destino_id == ubicacion_destino_id)

    total = (
        await session.execute(select(func.count()).select_from(Movimiento).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Movimiento)
            .where(*filtros)
            .order_by(Movimiento.fecha_hora.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[MovimientoResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{movimiento_id}", response_model=MovimientoResponse, summary="Detalle de movimiento")
async def obtener_movimiento(
    movimiento_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> MovimientoResponse:
    return _respuesta(await obtener_o_404(session, Movimiento, movimiento_id, "Movimiento"))


@router.post(
    "",
    response_model=MovimientoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar movimiento de cilindro (atómico: ubicación y estado)",
)
async def crear_movimiento(
    body: MovimientoCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> MovimientoResponse:
    cilindro = await obtener_o_404(session, Cilindro, body.cilindro_id, "Cilindro")
    destino = await obtener_o_404(session, Ubicacion, body.ubicacion_destino_id, "Ubicación")
    origen = await obtener_o_404(
        session, Ubicacion, cilindro.ubicacion_actual_id, "Ubicación"
    )

    # `estado_nuevo: null` = sin cambio de estado (solo se mueve).
    estado_nuevo = body.estado_nuevo or cilindro.estado_operativo

    if destino.id == origen.id and estado_nuevo == cilindro.estado_operativo:
        raise ValidationError(
            "El movimiento no cambia ni la ubicación ni el estado del cilindro "
            "(mismo destino y mismo estado)"
        )

    # Las reglas de la ubicación solo aplican si hay cambio real de ubicación:
    # un cambio de estado puro (p. ej. DADO_DE_BAJA) no exige entrada/salida.
    if destino.id != origen.id:
        if destino.estado != "ACTIVA":
            raise ValidationError(
                f"La ubicación destino '{destino.codigo}' está {destino.estado}; "
                "solo se puede mover a una ubicación ACTIVA"
            )
        if not destino.permite_entrada:
            raise ValidationError(f"La ubicación destino '{destino.codigo}' no permite entrada")
        if not origen.permite_salida:
            raise ValidationError(f"La ubicación origen '{origen.codigo}' no permite salida")

    for uid in (body.usuario_entrega_id, body.usuario_recibe_id):
        if uid is not None:
            await obtener_o_404(session, Usuario, uid, "Usuario")

    movimiento = Movimiento(
        cilindro_id=cilindro.id,
        ubicacion_origen_id=origen.id,
        ubicacion_destino_id=destino.id,
        estado_anterior=cilindro.estado_operativo,
        estado_nuevo=estado_nuevo,
        usuario_entrega_id=body.usuario_entrega_id,
        usuario_recibe_id=body.usuario_recibe_id,
        motivo=body.motivo,
        observaciones=body.observaciones,
    )
    session.add(movimiento)

    # Atómico: el cilindro queda en su nueva ubicación con su nuevo estado.
    cilindro.ubicacion_actual_id = destino.id
    cilindro.estado_operativo = estado_nuevo

    await session.commit()
    await session.refresh(movimiento)
    return _respuesta(movimiento)
