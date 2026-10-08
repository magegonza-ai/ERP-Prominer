"""
Endpoints del catálogo de tipos de documento comercial (ETAPA 3.1).

Dominio RBAC: **TAREA_29** (administrar catálogos). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular.

DELETE /tipos-documento/{id} solo elimina físicamente un tipo de documento
sin referencias (documentos comerciales); con historial → 409 HAS_HISTORY
(y en su lugar se inactiva con PATCH /tipos-documento/{id}/estado).
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
from app.core.exceptions import HasHistoryError, InvalidStateTransition, ValidationError
from app.models import DocumentoComercial, TipoDocumento, Usuario
from app.schemas.catalogos import (
    TipoDocumentoCreate,
    TipoDocumentoEstadoUpdate,
    TipoDocumentoResponse,
    TipoDocumentoUpdate,
)
from app.schemas.common import Pagina

router = APIRouter(tags=["Catálogos — tipos de documento"])

# Guard RBAC por acción (dominio TAREA_29: catálogos).
_LEER = RequireTaskPermission("TAREA_29", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_29", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_29", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_29", "PERM_07")

_ESTADOS = ("ACTIVO", "INACTIVO")


def _respuesta(tipo_documento: TipoDocumento) -> TipoDocumentoResponse:
    return TipoDocumentoResponse.model_validate(tipo_documento, from_attributes=True)


@router.get("", response_model=Pagina[TipoDocumentoResponse], summary="Listar tipos de documento")
async def listar_tipos_documento(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    estado: str | None = Query(None, description="Filtro exacto por estado."),
    q: str | None = Query(None, max_length=100, description="Contiene en código o nombre."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[TipoDocumentoResponse]:
    filtros = []
    if estado:
        filtros.append(TipoDocumento.estado == estado)
    if q:
        patron = f"%{q}%"
        filtros.append(or_(TipoDocumento.codigo.ilike(patron), TipoDocumento.nombre.ilike(patron)))

    total = (
        await session.execute(select(func.count()).select_from(TipoDocumento).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(TipoDocumento)
            .where(*filtros)
            .order_by(TipoDocumento.codigo)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[TipoDocumentoResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get(
    "/{tipo_documento_id}",
    response_model=TipoDocumentoResponse,
    summary="Detalle de tipo de documento",
)
async def obtener_tipo_documento(
    tipo_documento_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> TipoDocumentoResponse:
    return _respuesta(
        await obtener_o_404(session, TipoDocumento, tipo_documento_id, "Tipo de documento")
    )


@router.post(
    "",
    response_model=TipoDocumentoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear tipo de documento",
)
async def crear_tipo_documento(
    body: TipoDocumentoCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> TipoDocumentoResponse:
    await verificar_unico(session, TipoDocumento, "codigo", body.codigo)
    tipo_documento = TipoDocumento(**body.model_dump())
    session.add(tipo_documento)
    await session.commit()
    await session.refresh(tipo_documento)
    return _respuesta(tipo_documento)


@router.patch(
    "/{tipo_documento_id}",
    response_model=TipoDocumentoResponse,
    summary="Actualizar tipo de documento",
)
async def actualizar_tipo_documento(
    tipo_documento_id: uuid.UUID,
    body: TipoDocumentoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> TipoDocumentoResponse:
    tipo_documento = await obtener_o_404(session, TipoDocumento, tipo_documento_id, "Tipo de documento")

    # `null` = sin cambio (contrato de TipoDocumentoUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    for campo, valor in datos.items():
        setattr(tipo_documento, campo, valor)

    await session.commit()
    await session.refresh(tipo_documento)
    return _respuesta(tipo_documento)


@router.patch(
    "/{tipo_documento_id}/estado",
    response_model=TipoDocumentoResponse,
    summary="Cambiar estado de tipo de documento",
)
async def cambiar_estado(
    tipo_documento_id: uuid.UUID,
    body: TipoDocumentoEstadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> TipoDocumentoResponse:
    tipo_documento = await obtener_o_404(session, TipoDocumento, tipo_documento_id, "Tipo de documento")
    if tipo_documento.estado == body.estado:
        raise InvalidStateTransition(
            "Tipo de documento",
            tipo_documento.estado,
            body.estado,
            allowed=[e for e in _ESTADOS if e != tipo_documento.estado],
        )
    tipo_documento.estado = body.estado
    await session.commit()
    await session.refresh(tipo_documento)
    return _respuesta(tipo_documento)


@router.delete("/{tipo_documento_id}", summary="Eliminar tipo de documento (solo sin historial)")
async def eliminar_tipo_documento(
    tipo_documento_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
):
    """Borrado físico condicionado a cero referencias; con historial → 409."""
    tipo_documento = await obtener_o_404(
        session, TipoDocumento, tipo_documento_id, "Tipo de documento"
    )

    enlaces = (
        await session.execute(
            select(func.count())
            .select_from(DocumentoComercial)
            .where(DocumentoComercial.tipo_id == tipo_documento.id)
        )
    ).scalar_one()
    if enlaces:
        raise HasHistoryError(
            "Tipo de documento",
            f"No se puede eliminar el tipo de documento '{tipo_documento.codigo}': tiene "
            f"{enlaces} documento(s) comercial(es) asociados. "
            "Inactívelo con PATCH /tipos-documento/{id}/estado.",
        )

    await session.delete(tipo_documento)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
