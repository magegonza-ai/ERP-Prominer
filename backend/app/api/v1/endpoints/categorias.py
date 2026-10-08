"""
Endpoints del catálogo de categorías jerárquicas (ETAPA 3.1).

Dominio RBAC: **TAREA_29** (administrar catálogos). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular.

`padre_id` debe existir (404), no ser la propia categoría ni crear ciclos
(422). DELETE /categorias/{id} solo elimina físicamente una categoría sin
referencias (hijas, productos, servicios); con historial → 409 HAS_HISTORY
(y en su lugar se inactiva con PATCH /categorias/{id}/estado).
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
from app.models import Categoria, Producto, Servicio, Usuario
from app.schemas.catalogos import (
    CategoriaCreate,
    CategoriaEstadoUpdate,
    CategoriaResponse,
    CategoriaUpdate,
)
from app.schemas.common import Pagina

router = APIRouter(tags=["Catálogos — categorías"])

# Guard RBAC por acción (dominio TAREA_29: catálogos).
_LEER = RequireTaskPermission("TAREA_29", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_29", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_29", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_29", "PERM_07")

_ESTADOS = ("ACTIVA", "INACTIVA")


def _respuesta(categoria: Categoria) -> CategoriaResponse:
    return CategoriaResponse.model_validate(categoria, from_attributes=True)


async def _validar_padre(
    session: SessionDep,
    categoria: Categoria | None,
    padre_id: uuid.UUID,
) -> None:
    """Valida la jerarquía: padre existente, sin auto-referencia ni ciclos.

    `categoria=None` en el alta (el registro aún no tiene id).
    """
    if categoria is not None and padre_id == categoria.id:
        raise ValidationError("Una categoría no puede ser su propio padre")

    padre = await obtener_o_404(session, Categoria, padre_id, "Categoría")

    # Sin ciclos: subir por la cadena de madres; si aparece la categoría
    # actual, el propuesto padre es en realidad su descendiente.
    if categoria is not None:
        actual: Categoria | None = padre
        while actual is not None and actual.padre_id is not None:
            if actual.padre_id == categoria.id:
                raise ValidationError(
                    f"Jerarquía inválida: '{padre.codigo}' es descendiente de "
                    f"'{categoria.codigo}' y no puede ser su padre"
                )
            actual = await session.get(Categoria, actual.padre_id)


@router.get("", response_model=Pagina[CategoriaResponse], summary="Listar categorías")
async def listar_categorias(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    estado: str | None = Query(None, description="Filtro exacto por estado."),
    tipo: str | None = Query(None, description="Filtro exacto por tipo."),
    padre_id: uuid.UUID | None = Query(None, description="Categorías hijas de una madre."),
    q: str | None = Query(None, max_length=100, description="Contiene en código o nombre."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[CategoriaResponse]:
    filtros = []
    if estado:
        filtros.append(Categoria.estado == estado)
    if tipo:
        filtros.append(Categoria.tipo == tipo)
    if padre_id is not None:
        filtros.append(Categoria.padre_id == padre_id)
    if q:
        patron = f"%{q}%"
        filtros.append(or_(Categoria.codigo.ilike(patron), Categoria.nombre.ilike(patron)))

    total = (
        await session.execute(select(func.count()).select_from(Categoria).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Categoria)
            .where(*filtros)
            .order_by(Categoria.codigo)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[CategoriaResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{categoria_id}", response_model=CategoriaResponse, summary="Detalle de categoría")
async def obtener_categoria(
    categoria_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> CategoriaResponse:
    return _respuesta(await obtener_o_404(session, Categoria, categoria_id, "Categoría"))


@router.post(
    "",
    response_model=CategoriaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear categoría",
)
async def crear_categoria(
    body: CategoriaCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> CategoriaResponse:
    await verificar_unico(session, Categoria, "codigo", body.codigo)
    if body.padre_id is not None:
        await _validar_padre(session, None, body.padre_id)

    categoria = Categoria(**body.model_dump())
    session.add(categoria)
    await session.commit()
    await session.refresh(categoria)
    return _respuesta(categoria)


@router.patch("/{categoria_id}", response_model=CategoriaResponse, summary="Actualizar categoría")
async def actualizar_categoria(
    categoria_id: uuid.UUID,
    body: CategoriaUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> CategoriaResponse:
    categoria = await obtener_o_404(session, Categoria, categoria_id, "Categoría")

    # `null` = sin cambio (contrato de CategoriaUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    if "padre_id" in datos:
        await _validar_padre(session, categoria, datos["padre_id"])

    for campo, valor in datos.items():
        setattr(categoria, campo, valor)

    await session.commit()
    await session.refresh(categoria)
    return _respuesta(categoria)


@router.patch(
    "/{categoria_id}/estado",
    response_model=CategoriaResponse,
    summary="Cambiar estado de categoría",
)
async def cambiar_estado(
    categoria_id: uuid.UUID,
    body: CategoriaEstadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> CategoriaResponse:
    categoria = await obtener_o_404(session, Categoria, categoria_id, "Categoría")
    if categoria.estado == body.estado:
        raise InvalidStateTransition(
            "Categoría",
            categoria.estado,
            body.estado,
            allowed=[e for e in _ESTADOS if e != categoria.estado],
        )
    categoria.estado = body.estado
    await session.commit()
    await session.refresh(categoria)
    return _respuesta(categoria)


@router.delete("/{categoria_id}", summary="Eliminar categoría (solo sin historial)")
async def eliminar_categoria(
    categoria_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
):
    """Borrado físico condicionado a cero referencias; con historial → 409."""
    categoria = await obtener_o_404(session, Categoria, categoria_id, "Categoría")

    referencias = (
        (Categoria, Categoria.padre_id),
        (Producto, Producto.categoria_id),
        (Servicio, Servicio.categoria_id),
    )
    for model, columna in referencias:
        enlaces = (
            await session.execute(
                select(func.count()).select_from(model).where(columna == categoria.id)
            )
        ).scalar_one()
        if enlaces:
            raise HasHistoryError(
                "Categoría",
                f"No se puede eliminar la categoría '{categoria.codigo}': tiene {enlaces} "
                f"registro(s) asociados en '{model.__tablename__}'. "
                "Inactívela con PATCH /categorias/{id}/estado.",
            )

    await session.delete(categoria)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
