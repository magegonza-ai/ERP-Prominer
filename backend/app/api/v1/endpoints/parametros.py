"""
Endpoints de parámetros de configuración global (ETAPA 3.2).

Dominio RBAC: **TAREA_29** (administrar catálogos). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular.

`clave` es la PK natural (ruta `/parametros/{clave}`) e inmutable, igual
que `tipo`; el `valor` debe coaccionar al `tipo` declarado (400 si no).
Un parámetro con `editable=false` rechaza PATCH y DELETE → 409 READONLY
(solo se cambia por seed/migración). DELETE es físico: `parametro` no
tiene FKs entrantes.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, DecimalException

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select

# noqa en TC001: FastAPI y las firmas resuelven estos nombres en runtime.
from app.api.deps import (  # noqa: TC001
    RequireTaskPermission,
    SessionDep,
    verificar_unico,
)
from app.core.exceptions import NotFound, ReadOnlyError, ValidationError
from app.models import Parametro, Usuario
from app.schemas.catalogos import (
    ParametroCreate,
    ParametroResponse,
    ParametroUpdate,
)
from app.schemas.common import Pagina

router = APIRouter(tags=["Catálogos — parámetros"])

# Guard RBAC por acción (dominio TAREA_29: catálogos).
_LEER = RequireTaskPermission("TAREA_29", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_29", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_29", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_29", "PERM_07")


def _respuesta(parametro: Parametro) -> ParametroResponse:
    return ParametroResponse.model_validate(parametro, from_attributes=True)


async def _buscar(session: SessionDep, clave: str) -> Parametro:
    parametro = await session.get(Parametro, clave)
    if parametro is None:
        raise NotFound("Parámetro", clave)
    return parametro


def _validar_valor(tipo: str, valor: str) -> None:
    """400 si `valor` no coacciona al `tipo` declarado del parámetro."""
    error: str | None = None
    try:
        if tipo == "INTEGER":
            int(valor)
        elif tipo == "DECIMAL":
            if not Decimal(valor).is_finite():
                error = valor
        elif tipo == "BOOLEAN":
            if valor.lower() not in ("true", "false", "1", "0"):
                error = valor
        elif tipo == "JSON":
            json.loads(valor)
        elif tipo == "DATE":
            date.fromisoformat(valor)
        # STRING: cualquier valor es válido.
    except (ValueError, DecimalException):
        error = valor
    if error is not None:
        raise ValidationError(
            f"El valor '{valor}' no corresponde al tipo '{tipo}' del parámetro"
        )


@router.get("", response_model=Pagina[ParametroResponse], summary="Listar parámetros")
async def listar_parametros(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    tipo: str | None = Query(None, description="Filtro exacto por tipo."),
    q: str | None = Query(None, max_length=100, description="Contiene en clave o descripción."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[ParametroResponse]:
    filtros = []
    if tipo:
        filtros.append(Parametro.tipo == tipo)
    if q:
        patron = f"%{q}%"
        filtros.append(or_(Parametro.clave.ilike(patron), Parametro.descripcion.ilike(patron)))

    total = (
        await session.execute(select(func.count()).select_from(Parametro).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Parametro)
            .where(*filtros)
            .order_by(Parametro.clave)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[ParametroResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{clave}", response_model=ParametroResponse, summary="Detalle de parámetro")
async def obtener_parametro(
    clave: str,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> ParametroResponse:
    return _respuesta(await _buscar(session, clave))


@router.post(
    "",
    response_model=ParametroResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear parámetro",
)
async def crear_parametro(
    body: ParametroCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> ParametroResponse:
    await verificar_unico(session, Parametro, "clave", body.clave)
    _validar_valor(body.tipo, body.valor)

    parametro = Parametro(**body.model_dump())
    session.add(parametro)
    await session.commit()
    await session.refresh(parametro)
    return _respuesta(parametro)


@router.patch("/{clave}", response_model=ParametroResponse, summary="Actualizar parámetro")
async def actualizar_parametro(
    clave: str,
    body: ParametroUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> ParametroResponse:
    parametro = await _buscar(session, clave)
    if not parametro.editable:
        raise ReadOnlyError(
            "Parámetro",
            f"El parámetro '{clave}' no es editable: solo puede cambiarse por seed o migración.",
        )

    # `null` = sin cambio (contrato de ParametroUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    if "valor" in datos:
        _validar_valor(parametro.tipo, datos["valor"])

    for campo, valor in datos.items():
        setattr(parametro, campo, valor)
    parametro.actualizada_por = user.id

    await session.commit()
    await session.refresh(parametro)
    return _respuesta(parametro)


@router.delete("/{clave}", summary="Eliminar parámetro (solo editable)")
async def eliminar_parametro(
    clave: str,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
):
    """Borrado físico: `parametro` no tiene referencias entrantes (FK)."""
    parametro = await _buscar(session, clave)
    if not parametro.editable:
        raise ReadOnlyError(
            "Parámetro",
            f"El parámetro '{clave}' no es editable: solo puede eliminarse por seed o migración.",
        )

    await session.delete(parametro)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
