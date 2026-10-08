"""
Endpoints de cilindros (ETAPA 4.2, entidad central).

Dominio RBAC: **TAREA_03** (registrar cilindros). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular.

Identidad única e inmutable: `codigo_interno`, `numero_serie` y
`codigo_qr` (409 al crear; fuera del Update → 400) y `codigo_barras`
único pero editable (revalidado → 409). El alta valida FKs → 404 y el
cilindro **nace `REGISTRADO`**: `estado_operativo` no es editable (ni en
Create ni en Update — los cambios de estado y de ubicación solo vía
POST /movimientos, para no romper la trazabilidad); `propietario_id` y
`tipo_gas_id` tampoco (el cambio de propietario es TAREA_20 con
CambioPropietario, etapa posterior).

DELETE /cilindros/{id} solo elimina físicamente un cilindro con cero
historial (8 tablas con FK RESTRICT); con historial → 409 HAS_HISTORY (y
la baja de negocio se hace con estado DADO_DE_BAJA vía POST /movimientos).
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
    verificar_unico,
)
from app.core.exceptions import HasHistoryError, ValidationError
from app.models import (
    CambioPropietario,
    Cilindro,
    ControlCalidad,
    DetalleEntrega,
    DetalleOrden,
    DetalleRecepcion,
    Inspeccion,
    Movimiento,
    Propietario,
    TareaAsignada,
    TipoGas,
    Ubicacion,
    Usuario,
)
from app.schemas.cilindros import (
    CilindroCreate,
    CilindroResponse,
    CilindroUpdate,
    EstadoOperativoCilindro,
)
from app.schemas.common import Pagina

router = APIRouter(tags=["Cilindros — cilindros"])

# Guard RBAC por acción (dominio TAREA_03: registrar cilindros).
_LEER = RequireTaskPermission("TAREA_03", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_03", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_03", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_03", "PERM_07")

# Las 8 tablas con FK RESTRICT entrante a cilindro.
_REFERENCIAS_CILINDRO = (
    (Movimiento, Movimiento.cilindro_id),
    (DetalleRecepcion, DetalleRecepcion.cilindro_id),
    (Inspeccion, Inspeccion.cilindro_id),
    (ControlCalidad, ControlCalidad.cilindro_id),
    (DetalleOrden, DetalleOrden.cilindro_id),
    (TareaAsignada, TareaAsignada.cilindro_id),
    (DetalleEntrega, DetalleEntrega.cilindro_id),
    (CambioPropietario, CambioPropietario.cilindro_id),
)


def _respuesta(cilindro: Cilindro) -> CilindroResponse:
    return CilindroResponse.model_validate(cilindro, from_attributes=True)


@router.get("", response_model=Pagina[CilindroResponse], summary="Listar cilindros")
async def listar_cilindros(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    q: str | None = Query(
        None, max_length=100, description="Contiene en código interno, serie, QR o barras."
    ),
    estado_operativo: EstadoOperativoCilindro | None = Query(
        None, description="Filtro exacto por estado operativo."
    ),
    tipo_gas_id: uuid.UUID | None = Query(None),
    propietario_id: uuid.UUID | None = Query(None),
    ubicacion_actual_id: uuid.UUID | None = Query(None),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[CilindroResponse]:
    filtros = []
    if estado_operativo:
        filtros.append(Cilindro.estado_operativo == estado_operativo)
    if tipo_gas_id:
        filtros.append(Cilindro.tipo_gas_id == tipo_gas_id)
    if propietario_id:
        filtros.append(Cilindro.propietario_id == propietario_id)
    if ubicacion_actual_id:
        filtros.append(Cilindro.ubicacion_actual_id == ubicacion_actual_id)
    if q:
        patron = f"%{q}%"
        filtros.append(
            or_(
                Cilindro.codigo_interno.ilike(patron),
                Cilindro.numero_serie.ilike(patron),
                Cilindro.codigo_qr.ilike(patron),
                Cilindro.codigo_barras.ilike(patron),
            )
        )

    total = (
        await session.execute(select(func.count()).select_from(Cilindro).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Cilindro)
            .where(*filtros)
            .order_by(Cilindro.codigo_interno)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[CilindroResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{cilindro_id}", response_model=CilindroResponse, summary="Detalle de cilindro")
async def obtener_cilindro(
    cilindro_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> CilindroResponse:
    return _respuesta(await obtener_o_404(session, Cilindro, cilindro_id, "Cilindro"))


@router.post(
    "",
    response_model=CilindroResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear cilindro (nace REGISTRADO)",
)
async def crear_cilindro(
    body: CilindroCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> CilindroResponse:
    # FKs obligatorias: 404 si alguna referencia no existe.
    await obtener_o_404(session, Propietario, body.propietario_id, "Propietario")
    await obtener_o_404(session, TipoGas, body.tipo_gas_id, "Tipo de gas")
    await obtener_o_404(session, Ubicacion, body.ubicacion_actual_id, "Ubicación")

    # Identidad única (409 antes de tocar la BD).
    await verificar_unico(session, Cilindro, "codigo_interno", body.codigo_interno)
    await verificar_unico(session, Cilindro, "numero_serie", body.numero_serie)
    await verificar_unico(session, Cilindro, "codigo_qr", body.codigo_qr)
    if body.codigo_barras is not None:
        await verificar_unico(session, Cilindro, "codigo_barras", body.codigo_barras)

    cilindro = Cilindro(**body.model_dump())
    session.add(cilindro)
    await session.commit()
    await session.refresh(cilindro)
    return _respuesta(cilindro)


@router.patch("/{cilindro_id}", response_model=CilindroResponse, summary="Actualizar cilindro")
async def actualizar_cilindro(
    cilindro_id: uuid.UUID,
    body: CilindroUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> CilindroResponse:
    cilindro = await obtener_o_404(session, Cilindro, cilindro_id, "Cilindro")

    # `null` = sin cambio (contrato de CilindroUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    # `codigo_barras` es editable pero único: revalidar excluyendo este registro.
    if "codigo_barras" in datos and datos["codigo_barras"] is not None:
        await verificar_unico(
            session,
            Cilindro,
            "codigo_barras",
            datos["codigo_barras"],
            exclude_id=cilindro.id,
        )

    for campo, valor in datos.items():
        setattr(cilindro, campo, valor)

    await session.commit()
    await session.refresh(cilindro)
    return _respuesta(cilindro)


@router.delete("/{cilindro_id}", summary="Eliminar cilindro (solo sin historial)")
async def eliminar_cilindro(
    cilindro_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
):
    """Borrado físico condicionado a cero historial; con historial → 409."""
    cilindro = await obtener_o_404(session, Cilindro, cilindro_id, "Cilindro")

    for model, columna in _REFERENCIAS_CILINDRO:
        enlaces = (
            await session.execute(
                select(func.count()).select_from(model).where(columna == cilindro.id)
            )
        ).scalar_one()
        if enlaces:
            raise HasHistoryError(
                "Cilindro",
                f"No se puede eliminar el cilindro '{cilindro.codigo_interno}': tiene "
                f"{enlaces} registro(s) asociados en '{model.__tablename__}'. Si el cilindro "
                "debe retirarse, délo de baja con POST /movimientos "
                "(estado_nuevo: DADO_DE_BAJA).",
            )

    await session.delete(cilindro)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
