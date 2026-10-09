"""
Endpoints de cambios de propietario de cilindros (ETAPA 5.7).

Colección `/cambios-propietario` (dominio RBAC TAREA_20 «Autorizar cambio de
propietario»):

    | acción                    | RBAC                |
    |---------------------------|---------------------|
    | leer (listar/detalle)     | TAREA_20 + PERM_01  |
    | crear (= autorizar, POST) | TAREA_20 + PERM_04  |

`CambioPropietario` es un historial **append-only** (sin columna `estado`
desde la ETAPA 1): el registro nace autorizado. `propietario_anterior_id`,
`fecha` y `usuario_autoriza_id` los deriva el servidor; en la misma
transacción el cilindro pasa a `propietario_nuevo_id`. No hay edición ni
anulación (PATCH/DELETE → 405) y PERM_05 (rechazar) queda sembrado sin
endpoint: no crear el registro es la negativa. Revertir un traspaso = un
nuevo registro con el propietario inverso (queda el rastro).

No emite `Movimiento` (D31 no aplica): el traspaso no cambia ubicación ni
`estado_operativo` del cilindro, y su trazabilidad es el propio historial.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import (  # noqa: TC001
    RequireTaskPermission,
    SessionDep,
)
from app.core.exceptions import NotFound, ValidationError
from app.models import CambioPropietario, Cilindro, Propietario
from app.schemas.cambios_propietario import (
    CambioPropietarioCreate,
    CambioPropietarioResponse,
)
from app.schemas.common import Pagina

router = APIRouter(tags=["Operaciones — cambios de propietario"])

# TAREA_20 «Autorizar cambio de propietario» (matriz sembrada [0,3,4] =
# PERM_01 leer / PERM_04 aprobar / PERM_05 rechazar): el POST usa PERM_04
# porque crear un traspaso ES autorizarlo (no existe PERM_02 en la matriz).
_LEER = RequireTaskPermission("TAREA_20", "PERM_01")
_AUTORIZAR = RequireTaskPermission("TAREA_20", "PERM_04")

# Carga eager del traspaso + cilindro + propietarios + autorizador.
_CARGA_CAMBIO = (
    selectinload(CambioPropietario.cilindro).selectinload(Cilindro.tipo_gas),
    selectinload(CambioPropietario.propietario_anterior),
    selectinload(CambioPropietario.propietario_nuevo),
    selectinload(CambioPropietario.usuario_autoriza),
)


def _respuesta(cambio: CambioPropietario) -> CambioPropietarioResponse:
    return CambioPropietarioResponse.model_validate(cambio, from_attributes=True)


async def _obtener_cambio(session: SessionDep, cambio_id: uuid.UUID) -> CambioPropietario:
    """Registro del historial con sus relaciones eager (si no existe → 404)."""
    stmt = (
        select(CambioPropietario)
        .execution_options(populate_existing=True)
        .options(*_CARGA_CAMBIO)
        .where(CambioPropietario.id == cambio_id)
    )
    cambio = (await session.execute(stmt)).scalar_one_or_none()
    if cambio is None:
        raise NotFound("Cambio de propietario", cambio_id)
    return cambio


# ============================================================
# CAMBIOS DE PROPIETARIO (historial append-only)
# ============================================================


@router.get(
    "",
    response_model=Pagina[CambioPropietarioResponse],
    summary="Listar cambios de propietario",
)
async def listar_cambios(
    session: SessionDep,
    user=Depends(_LEER),
    cilindro_id: uuid.UUID | None = Query(None),
    propietario_anterior_id: uuid.UUID | None = Query(None),
    propietario_nuevo_id: uuid.UUID | None = Query(None),
    usuario_autoriza_id: uuid.UUID | None = Query(None),
    desde: datetime | None = Query(None, description="Fecha del traspaso desde (inclusive)."),
    hasta: datetime | None = Query(None, description="Fecha del traspaso hasta (inclusive)."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
):
    filtros = []
    if cilindro_id:
        filtros.append(CambioPropietario.cilindro_id == cilindro_id)
    if propietario_anterior_id:
        filtros.append(CambioPropietario.propietario_anterior_id == propietario_anterior_id)
    if propietario_nuevo_id:
        filtros.append(CambioPropietario.propietario_nuevo_id == propietario_nuevo_id)
    if usuario_autoriza_id:
        filtros.append(CambioPropietario.usuario_autoriza_id == usuario_autoriza_id)
    if desde:
        filtros.append(CambioPropietario.fecha >= desde)
    if hasta:
        filtros.append(CambioPropietario.fecha <= hasta)

    total = (
        await session.execute(
            select(func.count()).select_from(CambioPropietario).where(*filtros)
        )
    ).scalar_one()
    filas = (
        await session.execute(
            select(CambioPropietario)
            .options(*_CARGA_CAMBIO)
            .where(*filtros)
            .order_by(CambioPropietario.fecha.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[CambioPropietarioResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get(
    "/{cambio_id}",
    response_model=CambioPropietarioResponse,
    summary="Detalle de cambio de propietario",
)
async def obtener_cambio(
    cambio_id: uuid.UUID,
    session: SessionDep,
    user=Depends(_LEER),
) -> CambioPropietarioResponse:
    return _respuesta(await _obtener_cambio(session, cambio_id))


@router.post(
    "",
    response_model=CambioPropietarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Autorizar cambio de propietario (crea el traspaso y lo aplica al cilindro)",
)
async def autorizar_cambio(
    body: CambioPropietarioCreate,
    session: SessionDep,
    user=Depends(_AUTORIZAR),
) -> CambioPropietarioResponse:
    cilindro = await session.get(Cilindro, body.cilindro_id)
    if cilindro is None:
        raise NotFound("Cilindro", body.cilindro_id)

    propietario_nuevo = await session.get(Propietario, body.propietario_nuevo_id)
    if propietario_nuevo is None:
        raise NotFound("Propietario", body.propietario_nuevo_id)
    if propietario_nuevo.estado != "ACTIVO":
        raise ValidationError(
            f"El propietario '{propietario_nuevo.razon_social}' no está ACTIVO"
        )

    # No-op: el cilindro ya pertenece al propietario indicado.
    if propietario_nuevo.id == cilindro.propietario_id:
        raise ValidationError(
            f"El cilindro '{cilindro.codigo_interno}' ya pertenece a "
            f"'{propietario_nuevo.razon_social}'"
        )

    cambio = CambioPropietario(
        cilindro_id=cilindro.id,
        propietario_anterior_id=cilindro.propietario_id,
        propietario_nuevo_id=propietario_nuevo.id,
        usuario_autoriza_id=user.id,
        motivo=body.motivo,
        documento_respaldo_url=body.documento_respaldo_url,
        observaciones=body.observaciones,
    )
    session.add(cambio)

    # Aplicación atómica: el cilindro pasa al nuevo propietario en la misma
    # transacción (la única vía de cambiar propietario_id, D29).
    cilindro.propietario_id = propietario_nuevo.id

    await session.commit()
    return _respuesta(await _obtener_cambio(session, cambio.id))
