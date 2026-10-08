"""
Endpoints de tasas de impuesto con vigencia (ETAPA 3.2).

Dominio RBAC: **TAREA_29** (administrar catálogos). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular.

Reglas: `codigo` único e inmutable; `valor` acotado a 0–100 (422);
`vigencia_desde <= vigencia_hasta` cuando hay cierre (400); máximo **una**
tasa `es_default` global (al marcarla se revoca la de las demás en la misma
transacción); `cerrar_vigencia` cierra hoy / abre la vigencia y no se
combina con `vigencia_hasta` explícito. DELETE /tasas-impuesto/{id} solo
elimina físicamente una tasa sin referencias (productos, servicios); con
historial → 409 HAS_HISTORY (y en su lugar se inactiva con
PATCH /tasas-impuesto/{id}/estado).
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select, update

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
    ValidationError,
)
from app.models import Producto, Servicio, TasaImpuesto, Usuario
from app.schemas.catalogos import (
    TasaImpuestoCreate,
    TasaImpuestoEstadoUpdate,
    TasaImpuestoResponse,
    TasaImpuestoUpdate,
)
from app.schemas.common import Pagina

router = APIRouter(tags=["Catálogos — tasas de impuesto"])

# Guard RBAC por acción (dominio TAREA_29: catálogos).
_LEER = RequireTaskPermission("TAREA_29", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_29", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_29", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_29", "PERM_07")

_ESTADOS = ("ACTIVA", "INACTIVA")


def _respuesta(tasa: TasaImpuesto) -> TasaImpuestoResponse:
    return TasaImpuestoResponse.model_validate(tasa, from_attributes=True)


def _validar_vigencias(desde: date, hasta: date | None) -> None:
    if hasta is not None and desde > hasta:
        raise ValidationError(
            f"Vigencia inválida: desde ({desde}) no puede ser posterior a hasta ({hasta})"
        )


async def _revocar_otros_defaults(session: SessionDep, excluido_id: uuid.UUID | None) -> None:
    """Máximo una tasa `es_default` global: revoca el de las demás."""
    stmt = update(TasaImpuesto).where(TasaImpuesto.es_default.is_(True))
    if excluido_id is not None:
        stmt = stmt.where(TasaImpuesto.id != excluido_id)
    await session.execute(stmt.values(es_default=False))


@router.get("", response_model=Pagina[TasaImpuestoResponse], summary="Listar tasas de impuesto")
async def listar_tasas_impuesto(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    estado: str | None = Query(None, description="Filtro exacto por estado."),
    q: str | None = Query(None, max_length=100, description="Contiene en código o nombre."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[TasaImpuestoResponse]:
    filtros = []
    if estado:
        filtros.append(TasaImpuesto.estado == estado)
    if q:
        patron = f"%{q}%"
        filtros.append(or_(TasaImpuesto.codigo.ilike(patron), TasaImpuesto.nombre.ilike(patron)))

    total = (
        await session.execute(select(func.count()).select_from(TasaImpuesto).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(TasaImpuesto)
            .where(*filtros)
            .order_by(TasaImpuesto.codigo)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[TasaImpuestoResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get(
    "/{tasa_id}",
    response_model=TasaImpuestoResponse,
    summary="Detalle de tasa de impuesto",
)
async def obtener_tasa_impuesto(
    tasa_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> TasaImpuestoResponse:
    return _respuesta(await obtener_o_404(session, TasaImpuesto, tasa_id, "Tasa de impuesto"))


@router.post(
    "",
    response_model=TasaImpuestoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear tasa de impuesto",
)
async def crear_tasa_impuesto(
    body: TasaImpuestoCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> TasaImpuestoResponse:
    await verificar_unico(session, TasaImpuesto, "codigo", body.codigo)
    datos = body.model_dump()
    _validar_vigencias(datos["vigencia_desde"], datos["vigencia_hasta"])

    tasa = TasaImpuesto(**datos)
    session.add(tasa)
    if datos["es_default"]:
        await _revocar_otros_defaults(session, None)
    await session.commit()
    await session.refresh(tasa)
    return _respuesta(tasa)


@router.patch(
    "/{tasa_id}",
    response_model=TasaImpuestoResponse,
    summary="Actualizar tasa de impuesto",
)
async def actualizar_tasa_impuesto(
    tasa_id: uuid.UUID,
    body: TasaImpuestoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> TasaImpuestoResponse:
    tasa = await obtener_o_404(session, TasaImpuesto, tasa_id, "Tasa de impuesto")

    # `null` = sin cambio (contrato de TasaImpuestoUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    # `cerrar_vigencia` es el interruptor del cierre: true = hoy, false = sin cierre.
    cerrar = datos.pop("cerrar_vigencia", None)
    if cerrar is not None:
        if "vigencia_hasta" in datos:
            raise ValidationError(
                "Indique 'vigencia_hasta' o 'cerrar_vigencia', no ambos"
            )
        datos["vigencia_hasta"] = date.today() if cerrar else None

    desde = datos.get("vigencia_desde", tasa.vigencia_desde)
    hasta = datos.get("vigencia_hasta", tasa.vigencia_hasta)
    _validar_vigencias(desde, hasta)

    for campo, valor in datos.items():
        setattr(tasa, campo, valor)
    if datos.get("es_default") is True:
        await _revocar_otros_defaults(session, tasa.id)

    await session.commit()
    await session.refresh(tasa)
    return _respuesta(tasa)


@router.patch(
    "/{tasa_id}/estado",
    response_model=TasaImpuestoResponse,
    summary="Cambiar estado de tasa de impuesto",
)
async def cambiar_estado(
    tasa_id: uuid.UUID,
    body: TasaImpuestoEstadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> TasaImpuestoResponse:
    tasa = await obtener_o_404(session, TasaImpuesto, tasa_id, "Tasa de impuesto")
    if tasa.estado == body.estado:
        raise InvalidStateTransition(
            "Tasa de impuesto",
            tasa.estado,
            body.estado,
            allowed=[e for e in _ESTADOS if e != tasa.estado],
        )
    tasa.estado = body.estado
    await session.commit()
    await session.refresh(tasa)
    return _respuesta(tasa)


@router.delete("/{tasa_id}", summary="Eliminar tasa de impuesto (solo sin historial)")
async def eliminar_tasa_impuesto(
    tasa_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
):
    """Borrado físico condicionado a cero referencias; con historial → 409."""
    tasa = await obtener_o_404(session, TasaImpuesto, tasa_id, "Tasa de impuesto")

    for model in (Producto, Servicio):
        enlaces = (
            await session.execute(
                select(func.count())
                .select_from(model)
                .where(model.tasa_impuesto_id == tasa.id)
            )
        ).scalar_one()
        if enlaces:
            raise HasHistoryError(
                "Tasa de impuesto",
                f"No se puede eliminar la tasa '{tasa.codigo}': tiene {enlaces} registro(s) "
                f"asociados en '{model.__tablename__}'. Inactívela con PATCH "
                "/tasas-impuesto/{id}/estado.",
            )

    await session.delete(tasa)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
